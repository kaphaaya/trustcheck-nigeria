# 🛡️ TrustCheck Nigeria
### Nigeria's Community-Powered Scam & Trust Database

**🔗 Live Site:** http://130.107.145.125  
**🐳 Docker Hub:** https://hub.docker.com/u/kaphaaya

---

## What Is This?

TrustCheck Nigeria is a community-powered scam reporting and business verification platform I built to protect Nigerians from online fraud. Think Truecaller meets a business trust registry — but built specifically for Nigeria's digital landscape.

The problem is real. Nigeria loses billions of naira every year to online scams — fake vendors on Instagram, investment fraud on WhatsApp, romance scams on Telegram, fake job offers, Ponzi schemes. There was no single place where Nigerians could search a phone number, business name, or social media handle and instantly see if others had reported it as a scam. TrustCheck Nigeria fills that gap.

---

## What It Does

**For the public (no login needed):**
- Search any phone number, business name, or social media handle
- See a trust score (0–100) based on community reports
- View all reports filed against a number or account with proof
- Read descriptions of how specific scams work
- Submit a scam report with screenshot proof uploaded

**For businesses:**
- Submit for verification using NIN, BVN, CAC, or Driver's License
- Get a Verified ✅ badge visible in search results
- Build trust with customers before they transact

**The dashboard shows:**
- Total reports in the database
- Reports filed today
- Number of verified businesses
- A live feed of the most recent community reports

---

## Why I Built It This Way

This is a three-tier application — frontend, backend, and database — each running in its own Docker container. I chose this architecture because it mirrors how real production applications are built and deployed. Each tier is independent, can be scaled separately, and can be updated without taking down the whole system.

For the backend I used Python Flask because it's clean, fast to build with, and pairs perfectly with PostgreSQL. The database stores all reports, business verification submissions, and search data. The frontend is served by Nginx — lightweight and fast.

Everything runs in Docker containers orchestrated with Docker Compose, deployed on a Linux VM on Microsoft Azure.

---

## The Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Frontend | HTML, CSS, JavaScript | User interface served by Nginx |
| Backend | Python Flask | REST API handling all business logic |
| Database | PostgreSQL | Stores reports and business records |
| Containerization | Docker + Docker Compose | Runs all three tiers together |
| VM | Azure Ubuntu 22.04 (Canada Central) | Hosts the live deployment |
| CI/CD | GitHub Actions | Auto-deploys on every push |
| Image Registry | Docker Hub | Stores versioned container images |

---

## Architecture

```
USER'S BROWSER
      │
      │  HTTP Request
      ▼
NGINX (Frontend Container) — Port 80
      │
      │  API calls to backend
      ▼
FLASK API (Backend Container) — Port 5001
      │
      │  SQL queries
      ▼
POSTGRESQL (Database Container) — Port 5432

─────────────────────────────────────────

All three containers connected via
Docker internal network: trustcheck-network

─────────────────────────────────────────

GITHUB (source code)
      │
      │  Push to main branch
      ▼
GITHUB ACTIONS
      │
      ├── Build & push images to Docker Hub
      │
      └── SSH into Azure VM → git pull → docker-compose up
```

---

## Project Structure

```
trustcheck-nigeria/
│
├── frontend/
│   ├── index.html          # Complete frontend — HTML, CSS, JavaScript
│   └── Dockerfile          # Nginx container
│
├── backend/
│   ├── app.py              # Flask API — all endpoints
│   ├── requirements.txt    # Python dependencies
│   └── Dockerfile          # Python/Gunicorn container
│
├── docker-compose.yml      # Orchestrates all three containers
├── README.md               # This file
│
└── .github/
    └── workflows/
        └── deploy.yml      # GitHub Actions CI/CD pipeline
```

---

## API Endpoints

| Method | Endpoint | What it does |
|--------|----------|-------------|
| GET | `/api/health` | Check if API is running |
| GET | `/api/search?q=query` | Search reports and businesses |
| GET | `/api/reports` | Get all recent reports |
| POST | `/api/reports` | Submit a new scam report |
| GET | `/api/stats` | Get dashboard statistics |
| POST | `/api/verify-business` | Submit business for verification |

---

## How the Deployment Works

I deployed this entirely from the terminal — no clicking around in portals.

**Creating the VM:**
```bash
az vm create \
  --resource-group afritech-pulse-rg \
  --name trustcheck-vm \
  --image Ubuntu2204 \
  --size Standard_B2ats_v2 \
  --location canadacentral \
  --zone 2 \
  --admin-username azureuser \
  --generate-ssh-keys \
  --public-ip-sku Standard
```

**Installing Docker on the VM:**
```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker azureuser
```

**Deploying the app:**
```bash
git clone https://github.com/kaphaaya/trustcheck-nigeria.git
cd trustcheck-nigeria
docker-compose up --build -d
```

---

## CI/CD with GitHub Actions

Every time I push to the `main` branch, GitHub Actions automatically:

1. Builds the latest frontend and backend Docker images
2. Pushes them to Docker Hub with the `latest` tag
3. SSHs into the Azure VM
4. Pulls the latest code
5. Rebuilds and restarts the containers

The pipeline uses four GitHub Secrets:

| Secret | Purpose |
|--------|---------|
| `DOCKER_USERNAME` | Docker Hub login |
| `DOCKER_PASSWORD` | Docker Hub password |
| `VM_HOST` | Public IP of the Azure VM |
| `VM_SSH_KEY` | Private SSH key for VM access |

---

## Docker Hub Images

Both images are publicly available on Docker Hub:

```bash
# Pull and run yourself
docker pull kaphaaya/trustcheck-frontend:v1
docker pull kaphaaya/trustcheck-backend:v1
```

---

## Challenges I Ran Into

**Azure VM size availability** — The Standard_B1s and B2s sizes were unavailable across West Europe and North Europe on the free tier. I found that `Standard_B2ats_v2` in Canada Central Zone 2 was available and worked perfectly.

**Port conflicts on Mac** — Port 5000 was being used by AirPlay Receiver on macOS. I remapped the backend to port 5001 in Docker Compose to resolve this.

**Database tables not initializing** — Gunicorn doesn't execute the `if __name__ == '__main__'` block, so `init_db()` wasn't being called on startup. I moved the `init_db()` call outside that block so it runs regardless of how the app starts.

**GitHub Actions workflow permissions** — My GitHub Personal Access Token didn't have the `workflow` scope enabled, which blocked pushing the Actions YAML file. I updated the token permissions and re-pushed.

**Frontend pointing to localhost on VM** — After deployment the frontend was still calling `localhost:5001` instead of the VM's public IP. I updated the API URL to dynamically detect whether it's running locally or on the VM using `window.location.hostname`.

---

## Screenshots

### Live Site — http://130.107.145.125
*[Screenshot of TrustCheck Nigeria homepage]*

### Scam Report Submission
*[Screenshot of report modal and success message]*

### Search Results with Trust Score
*[Screenshot of search results showing trust score]*

### Docker Hub — Both Images
*[Screenshot of hub.docker.com/u/kaphaaya]*

### GitHub Actions — Successful Deployment
*[Screenshot of green workflow]*

### Docker Containers Running on VM
*[Screenshot of docker ps output]*

### Azure VM in Portal
*[Screenshot of Azure portal showing VM]*

---

## Does It Meet the Brief?

| Requirement | Status |
|-------------|--------|
| Three-tier app (frontend + backend + database) | ✅ |
| Dockerfile for frontend | ✅ |
| Dockerfile for backend | ✅ |
| Docker Compose running all three services | ✅ |
| Images pushed to Docker Hub with tags | ✅ `v1` and `latest` |
| Linux VM created and containers deployed | ✅ Azure Ubuntu 22.04 |
| App accessible on public IP port 80 | ✅ http://130.107.145.125 |
| GitHub Actions CI/CD pipeline | ✅ Builds, pushes, and deploys |
| README and documentation | ✅ |
| Screenshots of deployment | ✅ |

---

## The Bigger Picture

TrustCheck Nigeria is more than a capstone project. Nigeria needs this. The infrastructure for digital trust — a searchable, community-powered database of scam reports tied to phone numbers, businesses, and social handles — doesn't exist in any meaningful way right now. This is the foundation of what that could look like.

Future versions would integrate with NIMC for NIN verification, NIBSS for BVN, and CAC's API for business registration checks. The verification pipeline is already designed for those integrations — it's just pending API access approval from the relevant government agencies.

---

## About

Built by **Brown** — Cloud Engineering Student, AWS Solutions Architect candidate, and Web3 developer in training. Based in Nigeria. Building things that matter for Africa.

*TrustCheck Nigeria — Protecting Nigerians, one report at a time.*