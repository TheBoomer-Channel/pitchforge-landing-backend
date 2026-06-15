# 🔧 PitchForge — Backend API

> FastAPI backend deployed on **Coolify** at [api.pitch-forge.com](https://api.pitch-forge.com)

## 📁 Structure

```
├── app/                   ← FastAPI application
│   ├── main.py            ← Entry point
│   ├── routes/            ← API endpoints (research, planning, generate, waitlist, ...)
│   ├── services/          ← Business logic (LLM, research runner, waitlist, ...)
│   ├── generator/         ← Asset generators (pitch deck, landing, pricing)
│   ├── planning/          ← Planning pipeline (PRD → Func → Fin → Tech)
│   ├── research/          ← Research engine (8 data sources)
│   ├── models/            ← Beanie/MongoDB models
│   └── middleware/         ← Security headers, auth
├── tests/                 ← pytest tests (63 tests)
├── requirements.txt       ← Python dependencies
├── Dockerfile             ← Docker image
├── docker-compose.yml     ← Full stack (API + Redis + MongoDB + Worker)
└── .github/workflows/
    └── deploy.yml         ← Coolify deploy trigger
```

## 🚀 Deploy on Coolify

### Prerequisites
- Coolify instance running on `dev.theboomer.dev`
- Domain `api.pitch-forge.com` pointing to Coolify

### Setup
1. In Coolify, create a **New Service** → **Docker Compose**
2. Connect to GitHub repo: `TheBoomerDev/pitchforge-landing-backend`
3. Set environment variables from `.env.example`
4. Deploy!

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/waitlist/subscribe` | Waitlist subscription (called by landing page) |
| POST | `/api/research/start` | Start market research |
| POST | `/api/plan/start` | Start planning pipeline |
| POST | `/api/generate` | Generate assets (pitch, landing, pricing) |
| GET | `/api/projects/{id}/state` | Project state |
| GET | `/docs` | Scalar API Reference |

### CORS

Make sure `ALLOWED_ORIGINS` includes:
```
https://pitchforge.ai
https://*.pages.dev
```

## 🧪 Local development

```bash
# Create venv
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Copy and edit .env
cp .env.example .env

# Run
uvicorn app.main:app --port 8086 --reload

# Tests
pytest tests/ -v
```

## 🌐 DNS
```
api.pitch-forge.com  →  A/AAAA  →  Coolify server IP
```
