import os
import time
import random
import string
import hashlib
import requests
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
GOOGLE_CLIENT_ID  = os.environ.get("GOOGLE_CLIENT_ID",  "")
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
    return psycopg2.connect(
        host=os.environ.get("DB_HOST",     "db"),
        database=os.environ.get("DB_NAME", "trustcheck"),
        user=os.environ.get("DB_USER",     "postgres"),
        password=os.environ.get("DB_PASSWORD", "password"),
        cursor_factory=RealDictCursor
    )


def init_db():
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
    payload = {
        "user_id": user_id,
        "role":    role,
        "exp":     datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token):
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
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return wrapper


def generate_otp():
    return "".join(random.choices(string.digits, k=6))


# ─── EMAIL ───────────────────────────────────────────────────────────────────
def send_otp_email(to_email, otp, name="there"):
    subject = f"TrustCheck Nigeria — Your verification code: {otp}"
    body = f"""Hi {name},

Your TrustCheck Nigeria verification code is:

    {otp}

This code expires in 10 minutes.

If you did not request this, please ignore this email.

— TrustCheck Nigeria Team
Nigeria's Community-Powered Scam Database
"""
    if not SENDGRID_API_KEY:
        # Print to logs for local testing — check with: docker logs trustcheck-backend -f
        print(f"\n{'='*50}")
        print(f"📧 OTP EMAIL (no SendGrid configured)")
        print(f"To: {to_email}")
        print(f"OTP: {otp}")
        print(f"{'='*50}\n")
        return True

    try:
        resp = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {SENDGRID_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": SENDGRID_FROM, "name": "TrustCheck Nigeria"},
                "subject": subject,
                "content": [{"type": "text/plain", "value": body}]
            },
            timeout=10
        )
        return resp.status_code in (200, 202)
    except Exception as e:
        print(f"SendGrid error: {e}")
        return False


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
    Weighted trust score (0–100).
    Starts at 100, deductions for reports, adjusted by ratings and votes.
    """
    if report_count == 0:
        base = 100
    else:
        # Diminishing penalty — first reports hurt more than later ones
        base = max(0, 100 - (unique_reporters * 15) - (report_count * 5))

    # Rating adjustment: avg 1 = -20, avg 5 = +10
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


# ─── AUTH: GOOGLE OAUTH ──────────────────────────────────────────────────────
@app.route("/api/auth/google", methods=["POST"])
def google_auth():
    data       = request.json or {}
    id_token   = data.get("id_token") or data.get("credential") or ""
    access_token = data.get("access_token") or ""

    if not id_token and not access_token:
        return jsonify({"error": "Google token required"}), 400

    # Verify token with Google
    try:
        if id_token:
            verify_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
        else:
            verify_url = f"https://www.googleapis.com/oauth2/v1/userinfo?access_token={access_token}"

        resp      = requests.get(verify_url, timeout=10)
        google_data = resp.json()

        if resp.status_code != 200 or google_data.get("error"):
            return jsonify({"error": "Invalid Google token"}), 401

        google_id = google_data.get("sub") or google_data.get("id")
        email     = google_data.get("email", "").lower()
        name      = google_data.get("name") or google_data.get("given_name") or email.split("@")[0]

        if not email:
            return jsonify({"error": "Google account must have an email"}), 400

        # Verify email belongs to expected client
        if GOOGLE_CLIENT_ID and id_token:
            if google_data.get("aud") != GOOGLE_CLIENT_ID:
                return jsonify({"error": "Token audience mismatch"}), 401

    except Exception as e:
        return jsonify({"error": f"Could not verify Google token: {str(e)}"}), 500

    # Upsert user
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id, name, role FROM users WHERE email = %s OR google_id = %s", (email, google_id))
    user = cur.fetchone()

    if user:
        cur.execute("UPDATE users SET google_id = %s, is_verified = TRUE WHERE id = %s", (google_id, user["id"]))
        user_id   = user["id"]
        user_name = user["name"]
        role      = user["role"]
    else:
        cur.execute("""
            INSERT INTO users (name, email, google_id, is_verified, role)
            VALUES (%s, %s, %s, TRUE, 'user') RETURNING id
        """, (name, email, google_id))
        user_id   = cur.fetchone()["id"]
        user_name = name
        role      = "user"

    conn.commit(); cur.close(); conn.close()

    token = make_token(user_id, role)
    return jsonify({
        "message": "Google sign-in successful",
        "token":   token,
        "user":    {"id": user_id, "name": user_name, "email": email, "role": role}
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

    trust_score = calculate_trust_score(
        report_count, unique_reporters, review_avg, total_up, total_down
    )

    return jsonify({
        "query":        query,
        "report_count": report_count,
        "trust_score":  trust_score,
        "avg_rating":   round(review_avg, 1) if review_avg else None,
        "review_count": review_count,
        "reports":      reports,
        "businesses":   businesses,
        "page":         page,
        "per_page":     per_page,
        "date_from":    date_from
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

    # Support both multipart and JSON
    if request.content_type and "multipart" in request.content_type:
        data = request.form.to_dict()
        doc_file    = request.files.get("document_file")
        doc_path    = save_upload(doc_file, "biz_doc")
    else:
        data = request.json or {}
        doc_path = None

    business_name = (data.get("business_name") or "").strip()
    owner_name    = (data.get("owner_name") or "").strip()
    cac_number    = (data.get("cac_number") or "").strip()
    phone         = (data.get("phone") or "").strip()
    email         = (data.get("email") or "").strip()
    address       = (data.get("address") or "").strip()
    id_type       = (data.get("verification_type") or "NIN").strip()
    id_number     = (data.get("verification_number") or "").strip()

    # Validate required fields
    missing = []
    if not business_name: missing.append("business_name")
    if not owner_name:    missing.append("owner_name")
    if not cac_number:    missing.append("cac_number")
    if not phone:         missing.append("phone")
    if not email:         missing.append("email")
    if not address:       missing.append("address")

    if missing:
        return jsonify({"error": f"Required fields missing: {', '.join(missing)}"}), 400

    # Check duplicate
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id, status FROM businesses WHERE LOWER(business_name)=LOWER(%s) OR LOWER(cac_number)=LOWER(%s)", (business_name, cac_number))
    existing = cur.fetchone()
    if existing:
        cur.close(); conn.close()
        return jsonify({
            "message": f"This business has already been submitted. Status: {existing['status']}",
            "status":  existing["status"]
        }), 200

    # ── CAC Verification ──
    cac_result = verify_cac(cac_number, business_name)

    # ── ID Verification (if number provided) ──
    id_result = {"verified": False, "message": "No ID number provided"}
    if id_number:
        id_result = verify_identity(id_type, id_number, owner_name)

    # Determine status
    cac_ok = cac_result["verified"]
    id_ok  = id_result["verified"] if id_number else True  # optional for now

    if cac_ok and id_ok:
        status     = "verified"
        badge_type = "verified"
    elif cac_ok:
        status     = "cac_verified"
        badge_type = "cac_verified"
    else:
        status     = "pending"
        badge_type = None

    cur.execute("""
        INSERT INTO businesses (
            business_name, owner_name, phone, email, address,
            website, description, cac_number,
            verification_type, verification_number,
            document_path, status, badge_type, owner_id,
            cac_verified, id_verified
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
    """, (
        business_name, owner_name, phone, email, address,
        data.get("website"), data.get("description"), cac_number,
        id_type, id_number or None,
        doc_path, status, badge_type,
        user["user_id"] if user else None,
        cac_ok, id_ok if id_number else False
    ))
    biz_id = cur.fetchone()["id"]
    conn.commit(); cur.close(); conn.close()

    # Build response message
    msgs = []
    msgs.append(f"CAC: {cac_result['message']}")
    if id_number:
        msgs.append(f"ID ({id_type}): {id_result['message']}")

    if status == "verified":
        msg = "✅ Business fully verified! Your verified badge is now live."
    elif status == "cac_verified":
        msg = "✅ CAC verified. ID verification pending review."
    else:
        msg = f"Submitted for manual review. {' | '.join(msgs)}"

    return jsonify({
        "message":     msg,
        "business_id": biz_id,
        "status":      status,
        "cac_result":  cac_result,
        "id_result":   id_result if id_number else None
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
