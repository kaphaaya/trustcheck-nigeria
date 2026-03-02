from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
import os
import time
import base64

app = Flask(__name__)
CORS(app)

# ─── DATABASE CONNECTION ───
def get_db():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        database=os.environ.get("DB_NAME", "trustcheck"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", "password")
    )

# ─── INIT DATABASE ───
def init_db():
    for i in range(10):
        try:
            conn = get_db()
            cur = conn.cursor()

            # Reports table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id SERIAL PRIMARY KEY,
                    report_type VARCHAR(50) NOT NULL,
                    subject VARCHAR(300) NOT NULL,
                    phone_number VARCHAR(50),
                    business_name VARCHAR(200),
                    social_handle VARCHAR(200),
                    platform VARCHAR(100),
                    category VARCHAR(100) NOT NULL,
                    description TEXT NOT NULL,
                    proof_image TEXT,
                    reporter_name VARCHAR(200),
                    reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Businesses table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS businesses (
                    id SERIAL PRIMARY KEY,
                    business_name VARCHAR(200) NOT NULL,
                    owner_name VARCHAR(200),
                    phone VARCHAR(50),
                    email VARCHAR(200),
                    address TEXT,
                    verification_type VARCHAR(50),
                    verification_number VARCHAR(200),
                    status VARCHAR(50) DEFAULT 'pending',
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            cur.close()
            conn.close()
            print("✅ Database initialized!")
            return
        except Exception as e:
            print(f"DB not ready, retrying... ({i+1}/10): {e}")
            time.sleep(3)

# ─── HEALTH CHECK ───
@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "TrustCheck Nigeria API is running!"})

# ─── SEARCH ───
@app.route('/api/search', methods=['GET'])
def search():
    query = request.args.get('q', '').strip().lower()
    search_type = request.args.get('type', 'all')

    if not query:
        return jsonify({"error": "Search query required"}), 400

    conn = get_db()
    cur = conn.cursor()

    # Search reports
    cur.execute("""
        SELECT id, report_type, subject, phone_number, business_name,
               social_handle, platform, category, description, reported_at
        FROM reports
        WHERE LOWER(subject) LIKE %s
           OR LOWER(phone_number) LIKE %s
           OR LOWER(business_name) LIKE %s
           OR LOWER(social_handle) LIKE %s
        ORDER BY reported_at DESC
    """, (f'%{query}%', f'%{query}%', f'%{query}%', f'%{query}%'))

    rows = cur.fetchall()
    reports = []
    for row in rows:
        reports.append({
            "id": row[0],
            "report_type": row[1],
            "subject": row[2],
            "phone_number": row[3],
            "business_name": row[4],
            "social_handle": row[5],
            "platform": row[6],
            "category": row[7],
            "description": row[8],
            "reported_at": str(row[9])
        })

    # Search verified businesses
    cur.execute("""
        SELECT id, business_name, owner_name, phone, email, address, status, submitted_at
        FROM businesses
        WHERE LOWER(business_name) LIKE %s
           OR LOWER(phone) LIKE %s
        ORDER BY submitted_at DESC
    """, (f'%{query}%', f'%{query}%'))

    biz_rows = cur.fetchall()
    businesses = []
    for row in biz_rows:
        businesses.append({
            "id": row[0],
            "business_name": row[1],
            "owner_name": row[2],
            "phone": row[3],
            "email": row[4],
            "address": row[5],
            "status": row[6],
            "submitted_at": str(row[7])
        })

    cur.close()
    conn.close()

    report_count = len(reports)
    trust_score = 100 if report_count == 0 else max(0, 100 - (report_count * 20))

    return jsonify({
        "query": query,
        "report_count": report_count,
        "trust_score": trust_score,
        "reports": reports,
        "businesses": businesses
    })

# ─── SUBMIT REPORT ───
@app.route('/api/reports', methods=['POST'])
def submit_report():
    data = request.json

    required = ['report_type', 'subject', 'category', 'description']
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Field '{field}' is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO reports (
            report_type, subject, phone_number, business_name,
            social_handle, platform, category, description,
            proof_image, reporter_name
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        data['report_type'],
        data['subject'],
        data.get('phone_number'),
        data.get('business_name'),
        data.get('social_handle'),
        data.get('platform'),
        data['category'],
        data['description'],
        data.get('proof_image'),
        data.get('reporter_name', 'Anonymous')
    ))
    report_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "message": "Report submitted successfully! Thank you for protecting others.",
        "report_id": report_id
    }), 201

# ─── GET ALL REPORTS (recent feed) ───
@app.route('/api/reports', methods=['GET'])
def get_reports():
    limit = request.args.get('limit', 20)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, report_type, subject, phone_number, business_name,
               social_handle, platform, category, description, reporter_name, reported_at
        FROM reports
        ORDER BY reported_at DESC
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    reports = []
    for row in rows:
        reports.append({
            "id": row[0],
            "report_type": row[1],
            "subject": row[2],
            "phone_number": row[3],
            "business_name": row[4],
            "social_handle": row[5],
            "platform": row[6],
            "category": row[7],
            "description": row[8],
            "reporter_name": row[9],
            "reported_at": str(row[10])
        })

    return jsonify(reports)

# ─── STATS ───
@app.route('/api/stats', methods=['GET'])
def get_stats():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM reports")
    total_reports = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM reports WHERE reported_at >= NOW() - INTERVAL '24 hours'")
    reports_today = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM businesses WHERE status = 'verified'")
    verified_businesses = cur.fetchone()[0]

    cur.execute("""
        SELECT category, COUNT(*) as count
        FROM reports
        GROUP BY category
        ORDER BY count DESC
        LIMIT 5
    """)
    top_categories = [{"category": row[0], "count": row[1]} for row in cur.fetchall()]

    cur.execute("""
        SELECT platform, COUNT(*) as count
        FROM reports
        WHERE platform IS NOT NULL
        GROUP BY platform
        ORDER BY count DESC
        LIMIT 5
    """)
    top_platforms = [{"platform": row[0], "count": row[1]} for row in cur.fetchall()]

    cur.close()
    conn.close()

    return jsonify({
        "total_reports": total_reports,
        "reports_today": reports_today,
        "verified_businesses": verified_businesses,
        "top_categories": top_categories,
        "top_platforms": top_platforms
    })

# ─── BUSINESS VERIFICATION ───
@app.route('/api/verify-business', methods=['POST'])
def verify_business():
    data = request.json

    required = ['business_name', 'owner_name', 'phone', 'verification_type', 'verification_number']
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Field '{field}' is required"}), 400

    conn = get_db()
    cur = conn.cursor()

    # Check if already submitted
    cur.execute("SELECT id, status FROM businesses WHERE LOWER(business_name) = LOWER(%s)", (data['business_name'],))
    existing = cur.fetchone()

    if existing:
        cur.close()
        conn.close()
        return jsonify({
            "message": f"This business has already been submitted. Current status: {existing[1]}",
            "status": existing[1]
        }), 200

    cur.execute("""
        INSERT INTO businesses (
            business_name, owner_name, phone, email,
            address, verification_type, verification_number, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
        RETURNING id
    """, (
        data['business_name'],
        data['owner_name'],
        data['phone'],
        data.get('email'),
        data.get('address'),
        data['verification_type'],
        data['verification_number']
    ))

    biz_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()

    return jsonify({
        "message": "Verification request submitted! We will review and verify your business within 24-48 hours.",
        "business_id": biz_id,
        "status": "pending"
    }), 201


init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)