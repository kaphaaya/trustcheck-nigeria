# 🛡️ TrustCheck Nigeria
### Nigeria's Community-Powered Scam & Trust Database

**🔗 Live Site:** http://130.107.145.125  
**🐳 Docker Hub:** https://hub.docker.com/u/kaphaaya  
**📦 GitHub:** https://github.com/kaphaaya/trustcheck-nigeria

---

## The Problem

Nigeria loses billions of naira every year to online scams — fake vendors on Instagram, investment fraud on WhatsApp, romance scams on Telegram, fake job offers, Ponzi schemes. There was no single place where Nigerians could search a phone number, business name, or social handle and instantly see if others had reported it as fraudulent.

**TrustCheck Nigeria fills that gap.**

---

## What It Does

**For the public (no login required):**
- Search any phone number, business name, or social media handle
- See a trust score (0–100) calculated from community reports
- View all scam reports filed against a number or business — with proof
- Submit a scam report with description, category, star rating, and screenshot

**For businesses:**
- Submit for verification using CAC number, NIN, BVN, or Driver's License
- Receive a Verified ✅ badge visible in all search results
- Build customer trust before they transact

**Dashboard shows:**
- Total reports in the database
- Reports filed today
- Number of verified businesses
- Live feed of most recent community reports

---

## Architecture

```
USER'S BROWSER
      │
      │  HTTP on Port 80
      ▼
┌─────────────────────────┐
│   NGINX (Frontend)      │  — Serves index.html, proxies /api/ calls
│   trustcheck-frontend   │
└───────────┬─────────────┘
            │  Internal Docker network
            ▼
┌─────────────────────────┐
│   FLASK API (Backend)   │  — All business logic, JWT auth, email, CAC verify
│   trustcheck-backend    │
└───────────┬─────────────┘
            │  SQL queries
            ▼
┌─────────────────────────┐
│   POSTGRESQL (Database) │  — Reports, users, businesses, votes, reviews
│   trustcheck-db         │
└─────────────────────────┘

All three containers run on a private Docker bridge network.
Only port 80 is exposed to the internet.
```

---

## CI/CD Pipeline

```
git push origin main
        │
        ▼
GitHub Actions triggered
        │
        ├── Build frontend Docker image → push to Docker Hub
        ├── Build backend Docker image  → push to Docker Hub
        ├── SSH into Azure VM
        ├── Write .env file with secrets
        └── docker-compose pull && docker-compose up -d --force-recreate
```

Every push to `main` deploys automatically. Zero manual steps.

---

## Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | HTML, CSS, JavaScript | UI served by Nginx |
| Backend | Python Flask + Gunicorn | REST API, business logic |
| Database | PostgreSQL 15 | Persistent data storage |
| Containerization | Docker + Docker Compose | 3-tier orchestration |
| VM | Azure Ubuntu 22.04 — Canada Central | Live deployment |
| CI/CD | GitHub Actions | Auto build & deploy |
| Image Registry | Docker Hub | Versioned container images |
| Email | Gmail SMTP | OTP verification + admin alerts |
| Identity Verification | Prembly API (mock mode) | CAC, NIN, BVN verification |

---

## Project Structure

```
trustcheck-nigeria/
│
├── frontend/
│   ├── index.html              # Complete UI — HTML, CSS, JavaScript
│   ├── nginx.conf              # Nginx reverse proxy config
│   └── Dockerfile              # Nginx container
│
├── backend/
│   ├── app.py                  # Flask API — 21 endpoints, all logic
│   ├── requirements.txt        # Python dependencies
│   └── Dockerfile              # Python + Gunicorn container
│
├── docker-compose.yml          # Orchestrates all 3 containers
├── .env.example                # Template — never commit real .env
├── .gitignore                  # Protects secrets
├── README.md                   # This file
│
└── .github/
    └── workflows/
        └── deploy.yml          # GitHub Actions CI/CD pipeline
```

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Health check — DB status |
| GET | `/api/stats` | Dashboard statistics |
| GET | `/api/search?q=query` | Search reports and businesses |
| GET | `/api/search/autocomplete?q=` | Live search suggestions |
| POST | `/api/auth/register` | Register new account |
| POST | `/api/auth/verify-email` | Verify OTP code |
| POST | `/api/auth/resend-otp` | Resend OTP email |
| POST | `/api/auth/login` | Login — returns JWT token |
| GET | `/api/reports` | Get recent reports |
| POST | `/api/reports` | Submit scam report |
| GET | `/api/reports/:id` | Get single report with replies |
| POST | `/api/reports/:id/vote` | Upvote or downvote a report |
| GET/POST | `/api/reports/:id/replies` | Get or post comments |
| POST | `/api/reports/:id/flag` | Flag a report |
| GET/POST | `/api/reviews` | Get or post reviews |
| POST | `/api/verify-business` | Submit business for verification |
| GET | `/api/businesses/:id` | Get full business profile |
| GET/POST | `/api/admin/businesses/:id/approve` | Approve business (requires ADMIN_TOKEN) |
| GET/POST | `/api/admin/businesses/:id/reject` | Reject business (requires ADMIN_TOKEN) |

---

## GitHub Secrets Required

| Secret | Purpose |
|---|---|
| `DOCKER_USERNAME` | Docker Hub username |
| `DOCKER_PASSWORD` | Docker Hub password |
| `VM_HOST` | Azure VM public IP |
| `VM_SSH_KEY` | SSH private key for VM access |
| `DB_PASSWORD` | PostgreSQL password |
| `SECRET_KEY` | Flask session secret |
| `JWT_SECRET` | JWT signing key |
| `GMAIL_USER` | Gmail address for sending emails |
| `GMAIL_APP_PASS` | Gmail App Password (16 chars) |
| `ADMIN_EMAIL` | Email for business verification alerts |
| `ADMIN_TOKEN` | Secret token for one-click approve/reject links in admin emails |

---

## Database Schema

```
users          — id, name, email, password_hash, role, otp_code, is_verified
reports        — id, subject, phone_number, business_name, category, 
                 description, amount, rating, upvotes, downvotes, reporter_name
businesses     — id, business_name, cac_number, owner_name, status, badge_type
reviews        — id, subject, rating, comment, user_name
replies        — id, report_id, comment, user_name
votes          — id, report_id, user_id, direction
```

---

## How to Run Locally

```bash
# Clone the repo
git clone https://github.com/kaphaaya/trustcheck-nigeria.git
cd trustcheck-nigeria

# Create your .env file
cp .env.example .env
# Fill in DB_PASSWORD, SECRET_KEY, JWT_SECRET, GMAIL_USER, GMAIL_APP_PASS

# Start all 3 containers
docker-compose up --build -d

# Visit the app
open http://localhost
```

---

## Challenges & How I Solved Them

**1. Azure VM size availability**  
Standard_B1s and B2s were unavailable across West Europe and North Europe on the free tier. Found that `Standard_B2ats_v2` in Canada Central Zone 2 was available.

**2. Port 5000 conflict on Mac**  
macOS AirPlay Receiver uses port 5000. Remapped backend to port 5001 in docker-compose.yml.

**3. Database tables not initialising under Gunicorn**  
Gunicorn doesn't execute `if __name__ == '__main__'` blocks. Moved `init_db()` to module level so it runs on every startup regardless of how Flask is launched.

**4. GitHub Actions workflow permissions**  
Personal Access Token was missing the `workflow` scope. Updated token permissions and re-pushed.

**5. PostgreSQL password mismatch after volume recreation**  
When DB_PASSWORD changed, the existing volume still held the old password. Fixed by running `docker-compose down -v` to wipe the volume and recreate fresh.

**6. .env indentation bug from CI/CD heredoc**  
The GitHub Actions heredoc was writing leading spaces into .env values, breaking env var parsing. Fixed by writing .env directly on the VM with clean formatting.

---

## Does It Meet the Brief?

| Requirement | Status |
|---|---|
| Three-tier app (frontend + backend + database) | ✅ |
| Dockerfile for frontend | ✅ |
| Dockerfile for backend | ✅ |
| Docker Compose running all three services | ✅ |
| Images pushed to Docker Hub | ✅ `kaphaaya/trustcheck-frontend` + `kaphaaya/trustcheck-backend` |
| Linux VM created and containers deployed | ✅ Azure Ubuntu 22.04 |
| App accessible on public IP port 80 | ✅ http://130.107.145.125 |
| GitHub Actions CI/CD pipeline | ✅ |
| README and documentation | ✅ |

---

## The Bigger Picture

TrustCheck Nigeria is more than a capstone project. The infrastructure for digital trust — a searchable, community-powered database of scam reports tied to phone numbers, businesses, and social handles — doesn't exist in any meaningful way in Nigeria right now.

Future versions would integrate directly with NIMC for NIN verification, NIBSS for BVN, and CAC's API for real-time business registration checks. The verification pipeline is already designed for those integrations — pending API access from the relevant government agencies.

---

## About

Built by **Kafayat Aziz (Brown)** — Cloud Engineering Student, AWS Solutions Architect candidate, Web3 developer in training. Based in Nigeria. Building things that matter for Africa.

> *TrustCheck Nigeria — Protecting Nigerians, one report at a time.*
