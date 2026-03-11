# PadhloAI 📚

AI-powered education platform for rural India. Upload your state-board textbooks, get instant curriculum-aligned answers, auto-generated notes, and practice tests — optimized for low bandwidth.

---

## Quick Start

### 1. Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r ../requirements.txt
cp .env.example .env          # then add your GEMINI_API_KEY
uvicorn main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 2. Frontend

```bash
cd frontend
python -m http.server 3000
# Open http://localhost:3000
```

> ⚠️ Open via HTTP (`http://localhost:...`), not `file://` — browsers block API calls from `file://`.

---

## Architecture

```
frontend/
  js/api.js        ← ALL backend calls + Auth (JWT) session management
  js/app.js        ← Theme, toasts, animations
  js/layout.js     ← Sidebar + navbar injection

backend/
  routers/auth.py      ← POST /api/auth/register  /login
  routers/documents.py ← POST /api/documents/upload  GET  DELETE
  routers/chat.py      ← POST /api/chat/message  (RAG pipeline)
  routers/tests.py     ← POST /api/tests/generate  /submit  GET /results
  routers/analytics.py ← GET /api/analytics/summary
  services/ai_service.py   ← Gemini 1.5 Flash + HuggingFace embeddings
  services/file_service.py ← PDF text extraction + chunking
```

## Environment Variables (backend/.env)

| Variable | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | ✅ | Free at aistudio.google.com |
| `SECRET_KEY` | ✅ | Change in production! |
| `SCALEDOWN_API_KEY` | No | Leave blank to skip compression |

See `backend/.env.example` for the full list.

## License

MIT
