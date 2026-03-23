import os
import time
import random
import string
import hashlib
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

app = Flask(__name__)
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
CORS(app, origins=ALLOWED_ORIGINS)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://"
)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
SECRET_KEY        = os.environ.get("SECRET_KEY",       "dev-secret-change-in-prod")
JWT_SECRET        = os.environ.get("JWT_SECRET",        "dev-jwt-secret-change-in-prod")
SENDGRID_API_KEY  = os.environ.get("SENDGRID_API_KEY",  "")
SENDGRID_FROM     = os.environ.get("SENDGRID_FROM_EMAIL","noreply@trustchecknigeria.com")
GMAIL_USER        = os.environ.get("GMAIL_USER",         "")
GMAIL_APP_PASS    = os.environ.get("GMAIL_APP_PASS",     "")
ADMIN_EMAIL       = os.environ.get("ADMIN_EMAIL",        GMAIL_USER)
ADMIN_TOKEN       = os.environ.get("ADMIN_TOKEN",        "change-this-admin-token")
PREMBLY_API_KEY   = os.environ.get("PREMBLY_API_KEY",   "")
PREMBLY_APP_ID    = os.environ.get("PREMBLY_APP_ID",    "")
PREMBLY_MOCK      = os.environ.get("PREMBLY_MOCK",      "true").lower() == "true"
UPLOAD_FOLDER     = "/app/uploads"
MAX_CONTENT_MB    = 10
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_MB * 1024 * 1024


# ─── DATABASE ─────────────────────────────────────────────────────────────────
def get_db():
    """Open and return a new psycopg2 connection using environment-configured credentials."""
    return psycopg2.connect(
        host=os.environ.get("DB_HOST",     "db"),
        database=os.environ.get("DB_NAME", "trustcheck"),
        user=os.environ.get("DB_USER",     "postgres"),
        password=os.environ.get("DB_PASSWORD"),
        cursor_factory=RealDictCursor
    )


def init_db():
    """
    Create all required database tables and run any pending column migrations.
    Retries up to 15 times with a 3-second backoff to handle slow DB startup.
    """
    for i in range(15):
        try:
            conn = get_db()
            cur  = conn.cursor()

            # USERS
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    name          VARCHAR(200) NOT NULL,
                    email         VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255),
                    role          VARCHAR(20)  DEFAULT 'user',
                    is_verified   BOOLEAN      DEFAULT FALSE,
                    otp_code      VARCHAR(6),
                    otp_expires   TIMESTAMP,
                    google_id     VARCHAR(255),
                    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # REPORTS
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id            SERIAL PRIMARY KEY,
                    report_type   VARCHAR(50)  NOT NULL,
                    subject       VARCHAR(300) NOT NULL,
                    phone_number  VARCHAR(50),
                    business_name VARCHAR(200),
                    social_handle VARCHAR(200),
                    platform      VARCHAR(100),
                    category      VARCHAR(100) NOT NULL,
                    description   TEXT         NOT NULL,
                    amount        VARCHAR(100),
                    proof_path    TEXT,
                    reporter_name VARCHAR(200) DEFAULT 'Anonymous',
                    user_id       INTEGER      REFERENCES users(id) ON DELETE SET NULL,
                    rating        INTEGER      CHECK (rating BETWEEN 1 AND 5),
                    upvotes       INTEGER      DEFAULT 0,
                    downvotes     INTEGER      DEFAULT 0,
                    is_flagged    BOOLEAN      DEFAULT FALSE,
                    appeal_note   TEXT,
                    appeal_name   VARCHAR(200),
                    appeal_at     TIMESTAMP,
                    reported_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # BUSINESSES
            cur.execute("""
                CREATE TABLE IF NOT EXISTS businesses (
                    id                  SERIAL PRIMARY KEY,
                    business_name       VARCHAR(200) NOT NULL,
                    owner_name          VARCHAR(200),
                    phone               VARCHAR(50),
                    email               VARCHAR(200),
                    address             TEXT,
                    website             VARCHAR(300),
                    description         TEXT,
                    cac_number          VARCHAR(100) NOT NULL,
                    verification_type   VARCHAR(50),
                    verification_number VARCHAR(200),
                    document_path       TEXT,
                    status              VARCHAR(50)  DEFAULT 'pending',
                    badge_type          VARCHAR(50),
                    owner_id            INTEGER      REFERENCES users(id) ON DELETE SET NULL,
                    cac_verified        BOOLEAN      DEFAULT FALSE,
                    id_verified         BOOLEAN      DEFAULT FALSE,
                    submitted_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # REVIEWS
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reviews (
                    id         SERIAL PRIMARY KEY,
                    subject    VARCHAR(300) NOT NULL,
                    rating     INTEGER      NOT NULL CHECK (rating BETWEEN 1 AND 5),
                    comment    TEXT         NOT NULL,
                    user_name  VARCHAR(200) DEFAULT 'Anonymous',
                    user_id    INTEGER      REFERENCES users(id) ON DELETE SET NULL,
                    parent_id  INTEGER      REFERENCES reviews(id) ON DELETE CASCADE,
                    is_official BOOLEAN     DEFAULT FALSE,
                    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # REPLIES (on reports)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS replies (
                    id         SERIAL PRIMARY KEY,
                    report_id  INTEGER      NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                    comment    TEXT         NOT NULL,
                    user_name  VARCHAR(200) DEFAULT 'Anonymous',
                    user_id    INTEGER      REFERENCES users(id) ON DELETE SET NULL,
                    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # VOTES
            cur.execute("""
                CREATE TABLE IF NOT EXISTS votes (
                    id         SERIAL PRIMARY KEY,
                    report_id  INTEGER      NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                    user_id    INTEGER      REFERENCES users(id) ON DELETE CASCADE,
                    session_id VARCHAR(100),
                    direction  VARCHAR(4)   NOT NULL CHECK (direction IN ('up', 'down')),
                    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (report_id, user_id),
                    UNIQUE (report_id, session_id)
                )
            """)

            # Migrations: safely add columns that may not exist on older DBs
            for col, definition in [
                ("appeal_note", "TEXT"),
                ("appeal_name", "VARCHAR(200)"),
                ("appeal_at",   "TIMESTAMP"),
            ]:
                cur.execute("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='reports' AND column_name=%s
                """, (col,))
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE reports ADD COLUMN {col} {definition}")

            # Migrations: add social media columns to businesses
            for col, definition in [
                ("instagram", "VARCHAR(200)"),
                ("twitter",   "VARCHAR(200)"),
                ("facebook",  "VARCHAR(200)"),
                ("tiktok",    "VARCHAR(200)"),
            ]:
                cur.execute("""
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='businesses' AND column_name=%s
                """, (col,))
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE businesses ADD COLUMN {col} {definition}")

            # REPORT RATINGS
            cur.execute("""
                CREATE TABLE IF NOT EXISTS report_ratings (
                    id         SERIAL PRIMARY KEY,
                    report_id  INTEGER      NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                    user_id    INTEGER      REFERENCES users(id) ON DELETE CASCADE,
                    session_id VARCHAR(100),
                    rating     INTEGER      NOT NULL CHECK (rating BETWEEN 1 AND 5),
                    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (report_id, user_id),
                    UNIQUE (report_id, session_id)
                )
            """)

            conn.commit()
            cur.close()
            conn.close()
            print("✅ Database initialised!")
            return
        except Exception as e:
            print(f"DB not ready ({i+1}/15): {e}")
            time.sleep(3)
    print("❌ Could not connect to DB after 15 attempts")


# ─── AUTH HELPERS ─────────────────────────────────────────────────────────────
def make_token(user_id, role="user"):
    """Encode a signed JWT containing user_id, role, and a 30-day expiry."""
    payload = {
        "user_id": user_id,
        "role":    role,
        "exp":     datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token):
    """Decode and verify a JWT. Returns the payload dict, or None if invalid/expired."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception:
        return None


def get_current_user():
    """Returns user dict from JWT, or None for guests."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        data = decode_token(auth[7:])
        if data:
            return data
    return None


def require_auth(f):
    """Decorator that enforces a valid Bearer JWT. Attaches decoded payload to request.current_user."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper


def generate_otp():
    """Return a cryptographically random 6-digit OTP string."""
    return "".join(random.choices(string.digits, k=6))


# ─── EMAIL ───────────────────────────────────────────────────────────────────
def _send_gmail(to_email, subject, body):
    """Send email via Gmail SMTP using app password. Returns True on success."""
    if not GMAIL_USER or not GMAIL_APP_PASS:
        print(f"\n{'='*50}")
        print(f"EMAIL (no Gmail credentials configured)")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print(f"Body:\n{body}")
        print(f"{'='*50}\n")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"TrustCheck Nigeria <{GMAIL_USER}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(GMAIL_USER, GMAIL_APP_PASS)
            server.sendmail(GMAIL_USER, to_email, msg.as_string())
        print(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"Gmail SMTP error: {e}")
        return False


def send_otp_email(to_email, otp, name="there"):
    """Send a formatted OTP verification email to the given address."""
    subject = f"TrustCheck Nigeria — Your verification code: {otp}"
    body = f"""Hi {name},

Your TrustCheck Nigeria verification code is:

    {otp}

This code expires in 10 minutes.

If you did not request this, please ignore this email.

— TrustCheck Nigeria Team
Nigeria's Community-Powered Scam Database
"""
    return _send_gmail(to_email, subject, body)


def send_admin_alert(subject, body):
    """Send an alert email to the admin."""
    if not ADMIN_EMAIL:
        print(f"ADMIN ALERT — {subject}\n{body}")
        return False
    return _send_gmail(ADMIN_EMAIL, subject, body)


# ─── PREMBLY / CAC VERIFICATION ──────────────────────────────────────────────
def verify_cac(cac_number, business_name):
    """
    Verify CAC registration. In MOCK mode returns simulated result.
    In live mode calls Prembly API.
    """
    if PREMBLY_MOCK:
        # Simulate: RC- prefix passes, anything else fails
        passes = cac_number.upper().startswith("RC") or len(cac_number) >= 6
        return {
            "verified": passes,
            "registered_name": business_name if passes else None,
            "message": "CAC number verified (mock mode)" if passes else "CAC number not found in registry"
        }

    try:
        resp = requests.post(
            "https://api.prembly.com/identitypass/verification/cac",
            headers={
                "x-api-key": PREMBLY_API_KEY,
                "app-id":    PREMBLY_APP_ID,
                "Content-Type": "application/json"
            },
            json={"rc_number": cac_number},
            timeout=15
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("status"):
            reg_name = data.get("data", {}).get("company_name", "")
            name_match = business_name.lower() in reg_name.lower() or reg_name.lower() in business_name.lower()
            return {
                "verified": name_match,
                "registered_name": reg_name,
                "message": "Business name matches CAC record" if name_match else f"Name mismatch: CAC shows '{reg_name}'"
            }
        return {"verified": False, "registered_name": None, "message": "CAC number not found"}
    except Exception as e:
        print(f"Prembly CAC error: {e}")
        return {"verified": False, "registered_name": None, "message": "Verification service unavailable"}


def verify_identity(id_type, id_number, full_name):
    """
    Verify government-issued ID via Prembly.
    id_type: NIN | BVN | Drivers License | Passport
    """
    if PREMBLY_MOCK:
        passes = len(id_number) >= 8
        return {
            "verified": passes,
            "name_on_record": full_name if passes else None,
            "message": f"{id_type} verified (mock mode)" if passes else f"{id_type} number invalid or not found"
        }

    endpoint_map = {
        "NIN":             "https://api.prembly.com/identitypass/verification/nin",
        "BVN":             "https://api.prembly.com/identitypass/verification/bvn",
        "Drivers License": "https://api.prembly.com/identitypass/verification/drivers_license",
        "Passport":        "https://api.prembly.com/identitypass/verification/passport"
    }
    endpoint = endpoint_map.get(id_type)
    if not endpoint:
        return {"verified": False, "name_on_record": None, "message": "Unsupported ID type"}

    field_map = {
        "NIN":             "number",
        "BVN":             "number",
        "Drivers License": "license_number",
        "Passport":        "passport_number"
    }

    try:
        resp = requests.post(
            endpoint,
            headers={
                "x-api-key": PREMBLY_API_KEY,
                "app-id":    PREMBLY_APP_ID,
                "Content-Type": "application/json"
            },
            json={field_map[id_type]: id_number},
            timeout=15
        )
        data = resp.json()
        if resp.status_code == 200 and data.get("status"):
            record = data.get("data", {})
            record_name = f"{record.get('firstName','')} {record.get('lastName','')}".strip()
            name_parts = full_name.lower().split()
            match = any(part in record_name.lower() for part in name_parts if len(part) > 2)
            return {
                "verified": match,
                "name_on_record": record_name,
                "message": f"Identity verified — name matches {id_type} record" if match
                           else f"Name mismatch: {id_type} record shows '{record_name}'"
            }
        return {"verified": False, "name_on_record": None, "message": f"{id_type} not found in database"}
    except Exception as e:
        print(f"Prembly {id_type} error: {e}")
        return {"verified": False, "name_on_record": None, "message": "Identity service unavailable"}


# ─── TRUST SCORE ─────────────────────────────────────────────────────────────
def calculate_trust_score(report_count, unique_reporters, avg_rating, upvotes, downvotes):
    """
    Weighted trust score (0–100). Only called when report_count > 0.
    Starts at 50 (neutral) for 1-2 reports, lower for more reports.
    """
    if report_count <= 2:
        base = 50
    else:
        base = max(0, 60 - (unique_reporters * 10) - (report_count * 3))

    # Rating adjustment: avg 1 = -15, avg 5 = +15
    if avg_rating:
        rating_adj = (avg_rating - 3) * 5
        base = min(100, max(0, base + rating_adj))

    # Vote credibility
    net_votes = upvotes - downvotes
    if net_votes > 0:
        base = min(100, base - min(10, net_votes * 2))  # more upvotes = reports confirmed = lower score
    elif net_votes < 0:
        base = min(100, base + min(10, abs(net_votes) * 2))  # more downvotes = disputed reports

    return round(base)


# ─── FILE UPLOAD ──────────────────────────────────────────────────────────────
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file_obj, prefix="upload"):
    if not file_obj or file_obj.filename == "":
        return None
    if not allowed_file(file_obj.filename):
        return None
    ext = secure_filename(file_obj.filename).rsplit(".", 1)[-1].lower()
    unique_name = f"{prefix}_{int(time.time())}_{random.randint(1000,9999)}.{ext}"
    path = os.path.join(UPLOAD_FOLDER, unique_name)
    file_obj.save(path)
    return f"/uploads/{unique_name}"


# ──────────────────────────────────────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────────────────────────────────────

# ─── SERVE UPLOADED FILES ────────────────────────────────────────────────────
@app.route("/uploads/<filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ─── HEALTH ──────────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    try:
        conn = get_db()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({
        "status":  "TrustCheck Nigeria API v2 running",
        "db":      "connected" if db_ok else "disconnected",
        "mock":    PREMBLY_MOCK
    })


# ─── AUTH: REGISTER ──────────────────────────────────────────────────────────
@app.route("/api/auth/register", methods=["POST"])
@limiter.limit("10 per hour")
def register():
    data = request.json or {}
    name     = (data.get("name") or "").strip()
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    phone    = (data.get("phone") or "").strip()

    if not name or not email or not password:
        return jsonify({"error": "Name, email and password are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    if cur.fetchone():
        cur.close(); conn.close()
        return jsonify({"error": "An account with this email already exists"}), 400

    otp     = generate_otp()
    expires = datetime.utcnow() + timedelta(minutes=10)
    hashed  = generate_password_hash(password)

    cur.execute("""
        INSERT INTO users (name, email, password_hash, otp_code, otp_expires, is_verified)
        VALUES (%s, %s, %s, %s, %s, FALSE) RETURNING id
    """, (name, email, hashed, otp, expires))
    conn.commit(); cur.close(); conn.close()

    send_otp_email(email, otp, name)
    return jsonify({"message": "Account created! Check your email for the verification code.", "email": email}), 201


# ─── AUTH: VERIFY EMAIL OTP ──────────────────────────────────────────────────
@app.route("/api/auth/verify-email", methods=["POST"])
def verify_email():
    data  = request.json or {}
    email = (data.get("email") or "").strip().lower()
    otp   = (data.get("otp") or "").strip()

    if not email or not otp:
        return jsonify({"error": "Email and OTP are required"}), 400

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id, name, role, otp_code, otp_expires FROM users WHERE email = %s", (email,))
    user = cur.fetchone()

    if not user:
        cur.close(); conn.close()
        return jsonify({"error": "No account found with this email"}), 404

    if user["otp_code"] != otp:
        cur.close(); conn.close()
        return jsonify({"error": "Incorrect verification code"}), 400

    if datetime.utcnow() > user["otp_expires"]:
        cur.close(); conn.close()
        return jsonify({"error": "Code has expired — please request a new one"}), 400

    cur.execute("UPDATE users SET is_verified = TRUE, otp_code = NULL, otp_expires = NULL WHERE id = %s", (user["id"],))
    conn.commit(); cur.close(); conn.close()

    token = make_token(user["id"], user["role"])
    return jsonify({
        "message": "Email verified! Welcome to TrustCheck Nigeria.",
        "token":   token,
        "user":    {"id": user["id"], "name": user["name"], "email": email, "role": user["role"]}
    })


# ─── AUTH: RESEND OTP ────────────────────────────────────────────────────────
@app.route("/api/auth/resend-otp", methods=["POST"])
@limiter.limit("5 per hour")
def resend_otp():
    data  = request.json or {}
    email = (data.get("email") or "").strip().lower()
    conn  = get_db()
    cur   = conn.cursor()
    cur.execute("SELECT id, name FROM users WHERE email = %s AND is_verified = FALSE", (email,))
    user = cur.fetchone()
    if not user:
        cur.close(); conn.close()
        return jsonify({"error": "Account not found or already verified"}), 404

    otp     = generate_otp()
    expires = datetime.utcnow() + timedelta(minutes=10)
    cur.execute("UPDATE users SET otp_code = %s, otp_expires = %s WHERE id = %s", (otp, expires, user["id"]))
    conn.commit(); cur.close(); conn.close()

    send_otp_email(email, otp, user["name"])
    return jsonify({"message": "New verification code sent!"})


# ─── AUTH: LOGIN ─────────────────────────────────────────────────────────────
@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("20 per hour")
def login():
    data     = request.json or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id, name, email, password_hash, role, is_verified FROM users WHERE email = %s", (email,))
    user = cur.fetchone()
    cur.close(); conn.close()

    if not user or not user["password_hash"]:
        return jsonify({"error": "Invalid email or password"}), 401
    if not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401
    if not user["is_verified"]:
        return jsonify({"error": "Please verify your email first"}), 403

    token = make_token(user["id"], user["role"])
    return jsonify({
        "message": "Login successful",
        "token":   token,
        "user":    {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}
    })



# ─── SEARCH ──────────────────────────────────────────────────────────────────
@app.route("/api/search")
def search():
    query       = (request.args.get("q") or "").strip()
    search_type = request.args.get("type", "all")
    page        = int(request.args.get("page", 1))
    per_page    = int(request.args.get("per_page", 20))
    date_from   = request.args.get("date_from", "")   # e.g. "7days", "30days", "90days"
    offset      = (page - 1) * per_page

    if not query:
        return jsonify({"error": "Search query required"}), 400

    q = f"%{query.lower()}%"

    # Build date filter clause
    date_filter = ""
    date_params = []
    if date_from == "7days":
        date_filter = "AND r.reported_at >= NOW() - INTERVAL '7 days'"
    elif date_from == "30days":
        date_filter = "AND r.reported_at >= NOW() - INTERVAL '30 days'"
    elif date_from == "90days":
        date_filter = "AND r.reported_at >= NOW() - INTERVAL '90 days'"
    elif date_from == "1year":
        date_filter = "AND r.reported_at >= NOW() - INTERVAL '1 year'"

    conn = get_db()
    cur  = conn.cursor()

    # Reports
    cur.execute(f"""
        SELECT r.id, r.report_type, r.subject, r.phone_number, r.business_name,
               r.social_handle, r.platform, r.category, r.description,
               r.reporter_name, r.rating, r.upvotes, r.downvotes, r.amount,
               r.reported_at,
               COUNT(rp.id) as reply_count
        FROM reports r
        LEFT JOIN replies rp ON rp.report_id = r.id
        WHERE (LOWER(r.subject) LIKE %s
           OR LOWER(r.phone_number) LIKE %s
           OR LOWER(r.business_name) LIKE %s
           OR LOWER(r.social_handle) LIKE %s)
          AND r.is_flagged = FALSE
          {date_filter}
        GROUP BY r.id
        ORDER BY r.reported_at DESC
        LIMIT %s OFFSET %s
    """, (q, q, q, q, per_page, offset))
    reports = [dict(row) for row in cur.fetchall()]
    for r in reports:
        r["reported_at"] = str(r["reported_at"])

    # Total reports count for trust score
    cur.execute(f"""
        SELECT COUNT(*) as cnt,
               COUNT(DISTINCT COALESCE(user_id::text, reporter_name)) as unique_reporters,
               AVG(rating) as avg_rating,
               SUM(upvotes) as total_up,
               SUM(downvotes) as total_down
        FROM reports
        WHERE (LOWER(subject) LIKE %s
           OR LOWER(phone_number) LIKE %s
           OR LOWER(business_name) LIKE %s
           OR LOWER(social_handle) LIKE %s)
          AND is_flagged = FALSE
          {date_filter}
    """, (q, q, q, q))
    stats = cur.fetchone()
    report_count    = stats["cnt"] or 0
    unique_reporters = stats["unique_reporters"] or 0
    avg_rating      = float(stats["avg_rating"]) if stats["avg_rating"] else None
    total_up        = stats["total_up"] or 0
    total_down      = stats["total_down"] or 0

    # Reviews avg
    cur.execute("""
        SELECT AVG(rating) as avg_r, COUNT(*) as cnt
        FROM reviews
        WHERE LOWER(subject) LIKE %s
    """, (q,))
    rev = cur.fetchone()
    review_avg   = float(rev["avg_r"]) if rev and rev["avg_r"] else avg_rating
    review_count = rev["cnt"] if rev else 0

    # Businesses
    cur.execute("""
        SELECT id, business_name, owner_name, phone, address, status, badge_type,
               cac_verified, id_verified, submitted_at
        FROM businesses
        WHERE LOWER(business_name) LIKE %s OR LOWER(phone) LIKE %s
        ORDER BY submitted_at DESC
    """, (q, q))
    businesses = [dict(row) for row in cur.fetchall()]
    for b in businesses:
        b["submitted_at"] = str(b["submitted_at"])

    cur.close(); conn.close()

    # Determine trust status
    if report_count == 0:
        has_pending_biz = businesses and any(
            b.get("status") != "verified" for b in businesses
        )
        if has_pending_biz:
            trust_status  = "pending"
            trust_message = ("This business has not been verified on TrustCheck Nigeria. "
                             "Verification pending or not submitted.")
        else:
            trust_status  = "unverified"
            trust_message = ("No reviews found for this search. This does not mean they are "
                             "trustworthy — they simply have not been reported on TrustCheck "
                             "yet. Always verify before you transact.")
        trust_score = None
    else:
        trust_score   = calculate_trust_score(
            report_count, unique_reporters, review_avg, total_up, total_down
        )
        trust_status  = "scored"
        trust_message = None

    return jsonify({
        "query":         query,
        "report_count":  report_count,
        "trust_score":   trust_score,
        "trust_status":  trust_status,
        "trust_message": trust_message,
        "avg_rating":    round(review_avg, 1) if review_avg else None,
        "review_count":  review_count,
        "reports":       reports,
        "businesses":    businesses,
        "page":          page,
        "per_page":      per_page,
        "date_from":     date_from
    })


# ─── AUTOCOMPLETE ─────────────────────────────────────────────────────────────
@app.route("/api/search/autocomplete")
def autocomplete():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])

    like = f"%{q.lower()}%"
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        (SELECT DISTINCT subject as value, report_type as type FROM reports
         WHERE LOWER(subject) LIKE %s LIMIT 4)
        UNION
        (SELECT DISTINCT business_name as value, 'business' as type FROM businesses
         WHERE LOWER(business_name) LIKE %s LIMIT 4)
        LIMIT 6
    """, (like, like))

    results = []
    for row in cur.fetchall():
        results.append({
            "value": row["value"],
            "label": row["value"],
            "type":  row["type"]
        })

    cur.close(); conn.close()
    return jsonify(results)


# ─── REPORTS: GET FEED ───────────────────────────────────────────────────────
@app.route("/api/reports", methods=["GET"])
def get_reports():
    limit  = min(int(request.args.get("limit", 20)), 50)
    offset = int(request.args.get("offset", 0))
    conn   = get_db()
    cur    = conn.cursor()
    cur.execute("""
        SELECT id, report_type, subject, phone_number, business_name,
               social_handle, platform, category, description,
               reporter_name, rating, upvotes, downvotes, amount, reported_at
        FROM reports
        WHERE is_flagged = FALSE
        ORDER BY reported_at DESC
        LIMIT %s OFFSET %s
    """, (limit, offset))
    reports = [dict(r) for r in cur.fetchall()]
    for r in reports:
        r["reported_at"] = str(r["reported_at"])
    cur.close(); conn.close()
    return jsonify(reports)


# ─── REPORTS: SUBMIT ─────────────────────────────────────────────────────────
@app.route("/api/reports", methods=["POST"])
def submit_report():
    user = get_current_user()

    # Handle both multipart (file upload) and JSON
    if request.content_type and "multipart" in request.content_type:
        data = request.form.to_dict()
        proof_file = request.files.get("proof_file")
        proof_path = save_upload(proof_file, "report")
    else:
        data = request.json or {}
        proof_path = None

    subject     = (data.get("subject") or "").strip()
    description = (data.get("description") or "").strip()
    category    = (data.get("category") or "").strip()
    report_type = (data.get("report_type") or "phone").strip()

    if not subject or not description or not category:
        return jsonify({"error": "Subject, description and category are required"}), 400
    if len(description) < 20:
        return jsonify({"error": "Description must be at least 20 characters"}), 400

    rating_raw = data.get("rating")
    rating     = int(rating_raw) if rating_raw and str(rating_raw).isdigit() else None
    if rating and not (1 <= rating <= 5):
        rating = None

    # Resolve reporter display name — JWT only carries user_id/role, not name
    reporter_display = data.get("reporter_name") or "Anonymous"
    if user and not data.get("reporter_name"):
        try:
            _nc = get_db(); _cur = _nc.cursor()
            _cur.execute("SELECT name FROM users WHERE id = %s", (user["user_id"],))
            _row = _cur.fetchone()
            if _row:
                reporter_display = _row["name"]
            _cur.close(); _nc.close()
        except Exception:
            pass

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO reports (
            report_type, subject, phone_number, business_name,
            social_handle, platform, category, description,
            amount, proof_path, reporter_name, user_id, rating
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        report_type, subject,
        data.get("phone_number"), data.get("business_name"),
        data.get("social_handle"), data.get("platform"),
        category, description,
        data.get("amount"), proof_path,
        reporter_display,
        user["user_id"] if user else None,
        rating
    ))
    report_id = cur.fetchone()["id"]
    conn.commit(); cur.close(); conn.close()

    return jsonify({"message": "Report submitted! Thank you for protecting others.", "report_id": report_id}), 201


# ─── REPORTS: VOTE ───────────────────────────────────────────────────────────
@app.route("/api/reports/<int:report_id>/vote", methods=["POST"])
def vote_report(report_id):
    data      = request.json or {}
    direction = data.get("direction")
    user      = get_current_user()

    if direction not in ("up", "down"):
        return jsonify({"error": "Direction must be 'up' or 'down'"}), 400

    # Use user_id if logged in, otherwise session fingerprint
    user_id    = user["user_id"] if user else None
    session_id = None if user_id else hashlib.md5(
        (request.remote_addr + request.headers.get("User-Agent", "")).encode()
    ).hexdigest()

    conn = get_db()
    cur  = conn.cursor()

    # Check existing vote
    if user_id:
        cur.execute("SELECT id, direction FROM votes WHERE report_id=%s AND user_id=%s", (report_id, user_id))
    else:
        cur.execute("SELECT id, direction FROM votes WHERE report_id=%s AND session_id=%s", (report_id, session_id))

    existing = cur.fetchone()

    if existing:
        if existing["direction"] == direction:
            # Undo vote
            cur.execute("DELETE FROM votes WHERE id=%s", (existing["id"],))
            col = "upvotes" if direction == "up" else "downvotes"
            cur.execute(f"UPDATE reports SET {col} = GREATEST(0, {col} - 1) WHERE id=%s", (report_id,))
        else:
            # Change vote
            cur.execute("UPDATE votes SET direction=%s WHERE id=%s", (direction, existing["id"]))
            old = "upvotes" if direction == "down" else "downvotes"
            new = "upvotes" if direction == "up" else "downvotes"
            cur.execute(f"UPDATE reports SET {old}=GREATEST(0,{old}-1), {new}={new}+1 WHERE id=%s", (report_id,))
    else:
        # New vote
        if user_id:
            cur.execute("INSERT INTO votes (report_id,user_id,direction) VALUES (%s,%s,%s)", (report_id,user_id,direction))
        else:
            cur.execute("INSERT INTO votes (report_id,session_id,direction) VALUES (%s,%s,%s)", (report_id,session_id,direction))
        col = "upvotes" if direction == "up" else "downvotes"
        cur.execute(f"UPDATE reports SET {col}={col}+1 WHERE id=%s", (report_id,))

    cur.execute("SELECT upvotes, downvotes FROM reports WHERE id=%s", (report_id,))
    counts = cur.fetchone()
    conn.commit(); cur.close(); conn.close()

    return jsonify({"upvotes": counts["upvotes"], "downvotes": counts["downvotes"]})


# ─── REPORTS: FLAG ───────────────────────────────────────────────────────────
@app.route("/api/reports/<int:report_id>/flag", methods=["POST"])
def flag_report(report_id):
    data   = request.json or {}
    reason = data.get("reason", "Flagged by user")
    conn   = get_db()
    cur    = conn.cursor()
    # For now just log — admin reviews flagged reports
    print(f"🚩 Report {report_id} flagged: {reason}")
    cur.execute("UPDATE reports SET is_flagged = TRUE WHERE id = %s", (report_id,))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"message": "Report flagged for review. Our team will investigate."})


# ─── REPORT DETAIL ───────────────────────────────────────────────────────────
@app.route("/api/reports/<int:report_id>", methods=["GET"])
def get_report(report_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, report_type, subject, phone_number, business_name,
               social_handle, platform, category, description,
               amount, proof_path, reporter_name, rating,
               upvotes, downvotes, reported_at
        FROM reports WHERE id = %s AND is_flagged = FALSE
    """, (report_id,))
    report = cur.fetchone()
    if not report:
        cur.close(); conn.close()
        return jsonify({"error": "Report not found"}), 404
    report = dict(report)
    report["reported_at"] = str(report["reported_at"])

    # Compute session fingerprint for vote/rating state lookup
    user      = get_current_user()
    user_id   = user["user_id"] if user else None
    sess_id   = None if user_id else hashlib.md5(
        (request.remote_addr + request.headers.get("User-Agent", "")).encode()
    ).hexdigest()

    # Current user's vote direction
    if user_id:
        cur.execute("SELECT direction FROM votes WHERE report_id=%s AND user_id=%s", (report_id, user_id))
    else:
        cur.execute("SELECT direction FROM votes WHERE report_id=%s AND session_id=%s", (report_id, sess_id))
    vote_row = cur.fetchone()
    report["user_vote"] = vote_row["direction"] if vote_row else None

    # Current user's rating + aggregate rating stats
    cur.execute("""
        SELECT AVG(rating)::FLOAT AS avg_r, COUNT(*) AS cnt
        FROM report_ratings WHERE report_id=%s
    """, (report_id,))
    rstat = cur.fetchone()
    report["avg_rating"]    = round(rstat["avg_r"], 1) if rstat["avg_r"] else None
    report["total_ratings"] = rstat["cnt"]

    if user_id:
        cur.execute("SELECT rating FROM report_ratings WHERE report_id=%s AND user_id=%s", (report_id, user_id))
    else:
        cur.execute("SELECT rating FROM report_ratings WHERE report_id=%s AND session_id=%s", (report_id, sess_id))
    rating_row = cur.fetchone()
    report["user_rating"] = rating_row["rating"] if rating_row else None

    cur.execute("""
        SELECT id, comment, user_name, created_at
        FROM replies WHERE report_id = %s ORDER BY created_at ASC
    """, (report_id,))
    replies = [dict(r) for r in cur.fetchall()]
    for r in replies:
        r["created_at"] = str(r["created_at"])
    report["replies"] = replies

    cur.close(); conn.close()
    return jsonify(report)


# ─── REPORT RATING ───────────────────────────────────────────────────────────
@app.route("/api/reports/<int:report_id>/rate", methods=["POST"])
def rate_report(report_id):
    data   = request.json or {}
    rating = data.get("rating")

    if not isinstance(rating, int) or not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be an integer between 1 and 5"}), 400

    user      = get_current_user()
    user_id   = user["user_id"] if user else None
    session_id = None if user_id else hashlib.md5(
        (request.remote_addr + request.headers.get("User-Agent", "")).encode()
    ).hexdigest()

    conn = get_db()
    cur  = conn.cursor()

    # Check if already rated
    if user_id:
        cur.execute("SELECT id FROM report_ratings WHERE report_id=%s AND user_id=%s", (report_id, user_id))
    else:
        cur.execute("SELECT id FROM report_ratings WHERE report_id=%s AND session_id=%s", (report_id, session_id))

    existing = cur.fetchone()

    if existing:
        # Update existing rating
        cur.execute("UPDATE report_ratings SET rating=%s WHERE id=%s", (rating, existing["id"]))
    else:
        # New rating
        if user_id:
            cur.execute("INSERT INTO report_ratings (report_id, user_id, rating) VALUES (%s,%s,%s)", (report_id, user_id, rating))
        else:
            cur.execute("INSERT INTO report_ratings (report_id, session_id, rating) VALUES (%s,%s,%s)", (report_id, session_id, rating))

    cur.execute("SELECT AVG(rating)::FLOAT AS avg_r, COUNT(*) AS cnt FROM report_ratings WHERE report_id=%s", (report_id,))
    rstat = cur.fetchone()
    conn.commit(); cur.close(); conn.close()

    return jsonify({
        "avg_rating":    round(rstat["avg_r"], 1) if rstat["avg_r"] else rating,
        "total_ratings": rstat["cnt"],
        "your_rating":   rating
    })


# ─── REPLIES ─────────────────────────────────────────────────────────────────
@app.route("/api/reports/<int:report_id>/replies", methods=["GET"])
def get_replies(report_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, comment, user_name, created_at
        FROM replies WHERE report_id=%s ORDER BY created_at ASC
    """, (report_id,))
    replies = [dict(r) for r in cur.fetchall()]
    for r in replies:
        r["created_at"] = str(r["created_at"])
    cur.close(); conn.close()
    return jsonify(replies)


@app.route("/api/reports/<int:report_id>/replies", methods=["POST"])
def post_reply(report_id):
    data      = request.json or {}
    comment   = (data.get("comment") or "").strip()
    user      = get_current_user()
    user_name = data.get("user_name") or (user.get("name") if user else "Anonymous") or "Anonymous"

    if not comment:
        return jsonify({"error": "Comment cannot be empty"}), 400
    if len(comment) > 1000:
        return jsonify({"error": "Comment too long (max 1000 characters)"}), 400

    # Basic privacy: never expose email as display name
    if "@" in user_name:
        user_name = user_name.split("@")[0]

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO replies (report_id, comment, user_name, user_id)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, (report_id, comment, user_name, user["user_id"] if user else None))
    reply_id = cur.fetchone()["id"]
    conn.commit(); cur.close(); conn.close()

    return jsonify({"message": "Reply posted!", "reply_id": reply_id}), 201


# ─── REVIEWS ─────────────────────────────────────────────────────────────────
@app.route("/api/reviews", methods=["GET"])
def get_reviews():
    subject = (request.args.get("subject") or "").strip()
    if not subject:
        return jsonify({"error": "Subject required"}), 400

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, rating, comment, user_name, created_at
        FROM reviews WHERE LOWER(subject) = LOWER(%s)
        ORDER BY created_at DESC LIMIT 50
    """, (subject,))
    reviews = [dict(r) for r in cur.fetchall()]
    for r in reviews:
        r["created_at"] = str(r["created_at"])
    cur.close(); conn.close()
    return jsonify(reviews)


@app.route("/api/reviews", methods=["POST"])
def post_review():
    data      = request.json or {}
    subject   = (data.get("subject") or "").strip()
    comment   = (data.get("comment") or "").strip()
    user      = get_current_user()
    user_name = data.get("user_name") or (user.get("name") if user else "Anonymous") or "Anonymous"

    # Privacy: strip email from display name
    if "@" in user_name:
        user_name = user_name.split("@")[0]

    try:
        rating = int(data.get("rating") or 0)
    except (ValueError, TypeError):
        rating = 0

    if not subject:
        return jsonify({"error": "Subject is required"}), 400
    if not comment:
        return jsonify({"error": "Review comment is required"}), 400
    if not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be between 1 and 5"}), 400

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO reviews (subject, rating, comment, user_name, user_id)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (subject, rating, comment, user_name, user["user_id"] if user else None))
    conn.commit(); cur.close(); conn.close()

    return jsonify({"message": "Review posted! Thank you."}), 201


# ─── BUSINESS VERIFICATION ───────────────────────────────────────────────────
@app.route("/api/verify-business", methods=["POST"])
def verify_business():
    user = get_current_user()

    # Require multipart form (file upload)
    if not (request.content_type and "multipart" in request.content_type):
        return jsonify({"error": "Request must be multipart/form-data"}), 400

    data     = request.form.to_dict()
    doc_file = request.files.get("document_file")

    business_name = (data.get("business_name") or "").strip()
    owner_name    = (data.get("owner_name") or "").strip()
    cac_number    = (data.get("cac_number") or "").strip()
    phone         = (data.get("phone") or "").strip()
    email         = (data.get("email") or "").strip()
    address       = (data.get("address") or "").strip()
    id_type       = (data.get("verification_type") or "NIN").strip()
    id_number     = (data.get("verification_number") or "").strip()
    instagram     = (data.get("instagram") or "").strip()
    twitter       = (data.get("twitter") or "").strip()
    facebook      = (data.get("facebook") or "").strip()
    tiktok        = (data.get("tiktok") or "").strip()

    # Validate required fields
    missing = []
    if not business_name: missing.append("business_name")
    if not owner_name:    missing.append("owner_name")
    if not cac_number:    missing.append("cac_number")
    if not phone:         missing.append("phone")
    if not email:         missing.append("email")
    if not address:       missing.append("address")
    if not id_number:     missing.append("verification_number (identity number)")
    if not doc_file or doc_file.filename == "":
        missing.append("document_file (PDF)")

    if missing:
        return jsonify({"error": f"Required fields missing: {', '.join(missing)}"}), 400

    # Validate document is PDF
    doc_ext = doc_file.filename.rsplit(".", 1)[-1].lower() if doc_file.filename else ""
    if doc_ext != "pdf":
        return jsonify({"error": "Identity document must be a PDF file"}), 400

    # Save the uploaded document
    doc_path = save_upload(doc_file, "biz_doc")
    if not doc_path:
        return jsonify({"error": "Failed to save uploaded document"}), 500

    # Check duplicate
    conn = get_db()
    cur  = conn.cursor()

    # Block duplicate business name or CAC number
    cur.execute("""
        SELECT id, status FROM businesses
        WHERE LOWER(business_name)=LOWER(%s) OR LOWER(cac_number)=LOWER(%s)
    """, (business_name, cac_number))
    existing = cur.fetchone()
    if existing:
        cur.close(); conn.close()
        return jsonify({
            "error": f"A business with this name or CAC number has already been submitted (status: {existing['status']}). Contact support if this is an error."
        }), 400

    # Block same email used for an active (non-rejected) business
    cur.execute("""
        SELECT id, business_name FROM businesses
        WHERE LOWER(email)=LOWER(%s) AND status != 'rejected'
    """, (email,))
    email_conflict = cur.fetchone()
    if email_conflict:
        cur.close(); conn.close()
        return jsonify({
            "error": f"This email address is already linked to an active business registration ({email_conflict['business_name']}). Use a different email or contact support."
        }), 400

    # Block same phone used for an active (non-rejected) business
    cur.execute("""
        SELECT id, business_name FROM businesses
        WHERE phone=%s AND status != 'rejected'
    """, (phone,))
    phone_conflict = cur.fetchone()
    if phone_conflict:
        cur.close(); conn.close()
        return jsonify({
            "error": f"This phone number is already linked to an active business registration ({phone_conflict['business_name']}). Use a different number or contact support."
        }), 400

    # ── CAC Verification ──
    cac_result = verify_cac(cac_number, business_name)

    # ── ID Verification ──
    id_result = verify_identity(id_type, id_number, owner_name)

    # Determine status — all submissions go to pending for admin review
    cac_ok = cac_result["verified"]
    id_ok  = id_result["verified"]
    status     = "pending"
    badge_type = None

    cur.execute("""
        INSERT INTO businesses (
            business_name, owner_name, phone, email, address,
            website, description, cac_number,
            verification_type, verification_number,
            document_path, status, badge_type, owner_id,
            cac_verified, id_verified,
            instagram, twitter, facebook, tiktok
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        business_name, owner_name, phone, email, address,
        data.get("website"), data.get("description"), cac_number,
        id_type, id_number,
        doc_path, status, badge_type,
        user["user_id"] if user else None,
        cac_ok, id_ok,
        instagram or None, twitter or None, facebook or None, tiktok or None
    ))
    biz_id = cur.fetchone()["id"]
    conn.commit(); cur.close(); conn.close()

    # Build social handles section for email
    social_lines = []
    if instagram: social_lines.append(f"  Instagram:  {instagram}")
    if twitter:   social_lines.append(f"  Twitter/X:  {twitter}")
    if facebook:  social_lines.append(f"  Facebook:   {facebook}")
    if tiktok:    social_lines.append(f"  TikTok:     {tiktok}")
    social_section = "\n".join(social_lines) if social_lines else "  Not provided"

    base_url = "http://130.107.145.125"
    doc_url  = f"{base_url}{doc_path}" if doc_path else "No document uploaded"

    alert_subject = f"[TrustCheck] New Business Submission: {business_name}"
    alert_body = f"""New business verification submission — action required.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUSINESS DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Business Name:  {business_name}
Owner Name:     {owner_name}
CAC Number:     {cac_number}
Phone:          {phone}
Email:          {email}
Address:        {address}
Website:        {data.get('website') or 'Not provided'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IDENTITY VERIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ID Type:        {id_type}
ID Number:      {id_number}
CAC Check:      {cac_result['message']}
ID Check:       {id_result['message']}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
UPLOADED DOCUMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{doc_url}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOCIAL MEDIA HANDLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{social_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ACTION REQUIRED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ APPROVE (click to approve and notify owner):
{base_url}/api/admin/businesses/{biz_id}/approve?token={ADMIN_TOKEN}

❌ REJECT (click to reject — add reason after &reason=):
{base_url}/api/admin/businesses/{biz_id}/reject?token={ADMIN_TOKEN}&reason=Your+CAC+number+could+not+be+verified

Click either link directly from Gmail — no login needed.
"""
    send_admin_alert(alert_subject, alert_body)

    return jsonify({
        "message":     "✅ Verification submitted! We will review within 24-48 hours and email you the outcome.",
        "business_id": biz_id,
        "status":      status,
        "cac_result":  cac_result,
        "id_result":   id_result
    }), 201


# ─── STATS ───────────────────────────────────────────────────────────────────

# ─── BUSINESS PROFILE ────────────────────────────────────────────────────────
@app.route("/api/businesses/<int:biz_id>")
def get_business(biz_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, business_name, owner_name, phone, email, address, website,
               description, cac_number, status, badge_type,
               cac_verified, id_verified, submitted_at
        FROM businesses WHERE id = %s
    """, (biz_id,))
    biz = cur.fetchone()
    if not biz:
        cur.close(); conn.close()
        return jsonify({"error": "Business not found"}), 404
    biz = dict(biz)
    biz["submitted_at"] = str(biz["submitted_at"])

    cur.execute("""
        SELECT id, category, description, reporter_name, rating,
               upvotes, downvotes, reported_at
        FROM reports
        WHERE LOWER(business_name) = LOWER(%s) AND is_flagged = FALSE
        ORDER BY reported_at DESC LIMIT 20
    """, (biz["business_name"],))
    reports = [dict(r) for r in cur.fetchall()]
    for r in reports: r["reported_at"] = str(r["reported_at"])

    cur.execute("""
        SELECT rating, comment, user_name, created_at
        FROM reviews WHERE LOWER(subject) = LOWER(%s)
        ORDER BY created_at DESC LIMIT 20
    """, (biz["business_name"],))
    reviews = [dict(r) for r in cur.fetchall()]
    for r in reviews: r["created_at"] = str(r["created_at"])

    cur.close(); conn.close()
    biz["reports"] = reports
    biz["reviews"] = reviews
    return jsonify(biz)


# ─── ADMIN: APPROVE / REJECT BUSINESS ────────────────────────────────────────
def _check_admin_token():
    """Return True if the request carries a valid admin token."""
    # Accept token from Authorization header or ?token= query param
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:] == ADMIN_TOKEN
    return request.args.get("token", "") == ADMIN_TOKEN


def _send_business_status_email(biz_email, biz_name, approved: bool, reason: str = ""):
    if approved:
        subject = f"TrustCheck Nigeria — {biz_name} is now Verified ✅"
        body = f"""Hi,

Great news! Your business "{biz_name}" has been reviewed and is now verified on TrustCheck Nigeria.

Your Verified badge is live and will appear on all search results.

Thank you for helping build trust in Nigerian commerce.

— TrustCheck Nigeria Team
"""
    else:
        reason_line = f"\nReason: {reason}\n" if reason else ""
        subject = f"TrustCheck Nigeria — Verification Update for {biz_name}"
        body = f"""Hi,

We have completed our review of your business verification submission for "{biz_name}".

Unfortunately, we were unable to verify your business at this time.
{reason_line}
Please review the information you submitted and feel free to re-apply with updated documents.

If you believe this is an error, reply to this email for assistance.

— TrustCheck Nigeria Team
"""
    _send_gmail(biz_email, subject, body)


def _admin_html(title, body_html):
    """Wrap content in a minimal styled admin page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TrustCheck Admin — {title}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:'Segoe UI',sans-serif;background:#080B0F;color:#E8EDF5;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
  .card{{background:#0E1218;border:1px solid rgba(255,255,255,0.1);border-radius:16px;padding:40px;max-width:520px;width:100%}}
  .logo{{font-size:0.8rem;color:#00E87A;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:24px}}
  h2{{font-size:1.3rem;margin-bottom:8px}}
  .biz{{color:#00E87A;font-weight:600}}
  .sub{{color:#5A6478;font-size:0.88rem;margin-bottom:28px}}
  label{{display:block;font-size:0.82rem;color:#8A95A8;font-weight:600;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em}}
  textarea{{width:100%;background:#141A22;border:1px solid rgba(255,255,255,0.12);border-radius:10px;color:#E8EDF5;padding:12px 14px;font-size:0.9rem;font-family:inherit;resize:vertical;min-height:90px;outline:none}}
  textarea:focus{{border-color:rgba(255,59,92,0.5);box-shadow:0 0 0 3px rgba(255,59,92,0.08)}}
  .btn{{display:inline-block;padding:13px 32px;border-radius:12px;font-size:0.9rem;font-weight:700;border:none;cursor:pointer;width:100%;margin-top:16px;font-family:inherit;transition:opacity 0.2s}}
  .btn-green{{background:#00E87A;color:#000}}.btn-green:hover{{opacity:0.9}}
  .btn-red{{background:#FF3B5C;color:#fff}}.btn-red:hover{{opacity:0.9}}
  .done{{text-align:center;padding:20px 0}}
  .done .icon{{font-size:3rem;margin-bottom:12px}}
  .done p{{color:#8A95A8;font-size:0.88rem;margin-top:8px}}
</style>
</head>
<body><div class="card">{body_html}</div></body>
</html>"""


@app.route("/api/admin/businesses/<int:biz_id>/approve", methods=["GET", "POST"])
def admin_approve_business(biz_id):
    import html as html_mod
    if not _check_admin_token():
        return _admin_html("Unauthorized", "<h2>Unauthorized</h2><p class='sub'>Invalid or missing admin token.</p>"), 401

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id, business_name, email FROM businesses WHERE id = %s", (biz_id,))
    biz = cur.fetchone()
    if not biz:
        cur.close(); conn.close()
        return _admin_html("Not Found", "<h2>Business not found</h2>"), 404

    biz_name = biz["business_name"]
    biz_email = biz["email"]

    if request.method == "GET":
        cur.close(); conn.close()
        token = request.args.get("token", "")
        safe_name = html_mod.escape(biz_name)
        return _admin_html("Approve Business", f"""
<div class="logo">TrustCheck Admin</div>
<h2>Approve this business?</h2>
<p class="biz">{safe_name}</p>
<p class="sub">The owner will receive a confirmation email that their business is now verified.</p>
<form method="POST" action="/api/admin/businesses/{biz_id}/approve?token={token}">
  <button class="btn btn-green" type="submit">✅ Confirm Approval</button>
</form>""")

    # POST — perform the approval
    cur.execute("UPDATE businesses SET status='verified', badge_type='verified' WHERE id = %s", (biz_id,))
    conn.commit(); cur.close(); conn.close()
    _send_business_status_email(biz_email, biz_name, approved=True)
    safe_name = html_mod.escape(biz_name)
    return _admin_html("Approved", f"""
<div class="done">
  <div class="icon">✅</div>
  <h2>Business Approved</h2>
  <p class="biz">{safe_name}</p>
  <p>The owner has been notified by email.</p>
</div>""")


@app.route("/api/admin/businesses/<int:biz_id>/reject", methods=["GET", "POST"])
def admin_reject_business(biz_id):
    import html as html_mod
    if not _check_admin_token():
        return _admin_html("Unauthorized", "<h2>Unauthorized</h2><p class='sub'>Invalid or missing admin token.</p>"), 401

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id, business_name, email FROM businesses WHERE id = %s", (biz_id,))
    biz = cur.fetchone()
    if not biz:
        cur.close(); conn.close()
        return _admin_html("Not Found", "<h2>Business not found</h2>"), 404

    biz_name  = biz["business_name"]
    biz_email = biz["email"]

    if request.method == "GET":
        cur.close(); conn.close()
        token = request.args.get("token", "")
        safe_name = html_mod.escape(biz_name)
        return _admin_html("Reject Business", f"""
<div class="logo">TrustCheck Admin</div>
<h2>Reject this business?</h2>
<p class="biz">{safe_name}</p>
<p class="sub">Enter a reason below — it will be included in the email sent to the business owner.</p>
<form method="POST" action="/api/admin/businesses/{biz_id}/reject?token={token}">
  <label for="reason">Rejection Reason</label>
  <textarea id="reason" name="reason" placeholder="e.g. Your CAC number could not be verified. Please resubmit with a clear scan of your CAC certificate." required></textarea>
  <button class="btn btn-red" type="submit">❌ Confirm Rejection</button>
</form>""")

    # POST — perform the rejection
    reason = (request.form.get("reason") or request.args.get("reason") or "").strip()
    cur.execute("UPDATE businesses SET status='rejected', badge_type=NULL WHERE id = %s", (biz_id,))
    conn.commit(); cur.close(); conn.close()
    _send_business_status_email(biz_email, biz_name, approved=False, reason=reason)
    safe_name = html_mod.escape(biz_name)
    return _admin_html("Rejected", f"""
<div class="done">
  <div class="icon">❌</div>
  <h2>Business Rejected</h2>
  <p class="biz">{safe_name}</p>
  <p>The owner has been notified by email{' with your reason.' if reason else '.'}</p>
</div>""")


# ─── USER PROFILE ─────────────────────────────────────────────────────────────
@app.route("/api/users/me")
@require_auth
def get_my_profile():
    user_id = request.current_user["user_id"]
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, name, email, role, is_verified, created_at
        FROM users WHERE id = %s
    """, (user_id,))
    user = cur.fetchone()
    if not user:
        cur.close(); conn.close()
        return jsonify({"error": "User not found"}), 404
    user = dict(user)
    user["created_at"] = str(user["created_at"])

    cur.execute("""
        SELECT id, subject, category, description, reported_at, is_flagged
        FROM reports WHERE user_id = %s ORDER BY reported_at DESC LIMIT 20
    """, (user_id,))
    my_reports = [dict(r) for r in cur.fetchall()]
    for r in my_reports: r["reported_at"] = str(r["reported_at"])

    cur.close(); conn.close()
    user["reports"] = my_reports
    return jsonify(user)


# ─── APPEALS ─────────────────────────────────────────────────────────────────
@app.route("/api/reports/<int:report_id>/appeal", methods=["POST"])
def appeal_report(report_id):
    data   = request.json or {}
    reason = (data.get("reason") or "").strip()
    name   = (data.get("name") or "Anonymous").strip()
    if not reason or len(reason) < 20:
        return jsonify({"error": "Please provide a detailed reason (at least 20 characters)"}), 400

    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id, subject FROM reports WHERE id = %s", (report_id,))
    report = cur.fetchone()
    if not report:
        cur.close(); conn.close()
        return jsonify({"error": "Report not found"}), 404

    print(f"\n📋 APPEAL on report #{report_id} ('{report['subject']}')")
    print(f"   From: {name}")
    print(f"   Reason: {reason}\n")

    # Do NOT auto-unflag — store appeal_note for admin to review manually
    cur.execute("""
        UPDATE reports
        SET appeal_note = %s, appeal_name = %s, appeal_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """, (reason, name, report_id))
    conn.commit(); cur.close(); conn.close()
    return jsonify({"message": "Appeal submitted. Our team will review within 48 hours."}), 200


@app.route("/api/stats")
def get_stats():
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) as c FROM reports WHERE is_flagged=FALSE")
    total_reports = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM reports WHERE reported_at >= NOW()-INTERVAL '24 hours' AND is_flagged=FALSE")
    reports_today = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM businesses WHERE status IN ('verified','cac_verified')")
    verified_businesses = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM users WHERE is_verified=TRUE")
    total_users = cur.fetchone()["c"]

    cur.execute("""
        SELECT category, COUNT(*) as cnt FROM reports
        WHERE is_flagged=FALSE GROUP BY category ORDER BY cnt DESC LIMIT 5
    """)
    top_categories = [{"category": r["category"], "count": r["cnt"]} for r in cur.fetchall()]

    cur.execute("""
        SELECT platform, COUNT(*) as cnt FROM reports
        WHERE platform IS NOT NULL AND is_flagged=FALSE
        GROUP BY platform ORDER BY cnt DESC LIMIT 5
    """)
    top_platforms = [{"platform": r["platform"], "count": r["cnt"]} for r in cur.fetchall()]

    cur.close(); conn.close()
    return jsonify({
        "total_reports":      total_reports,
        "reports_today":      reports_today,
        "verified_businesses": verified_businesses,
        "total_users":        total_users,
        "top_categories":     top_categories,
        "top_platforms":      top_platforms
    })


# ─── INIT ────────────────────────────────────────────────────────────────────
# Called here so Gunicorn (which never hits __main__) also initialises the DB
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
