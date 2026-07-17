# 🚀 Quick Start Commands

## First Time Setup

### 1. Backend Setup
```bash
cd Backend
python3 -m venv venv
source venv/bin/activate
pip install -r ../requirements.txt
cp .env.example .env
# Edit .env with your API keys (Weaviate + Gemini)
```

### 2. Frontend Setup
```bash
cd Frontend
npm install
# .env already configured
```

---

## Daily Usage

### Option 1: One-Command Start (Recommended)
```bash
./start.sh
```
This starts both backend and frontend automatically!

### Option 2: Manual Start (Two Terminals)

**Terminal 1 - Backend:**
```bash
cd Backend
source venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd Frontend
npm run dev
```

---

## URLs

- 🌐 **Frontend**: http://localhost:8080
- 🔗 **Backend API**: http://localhost:8000
- 📚 **API Docs**: http://localhost:8000/docs

---

## Quick Tests

### Test Backend Health
```bash
curl http://localhost:8000/
```
Expected: `{"status":"ok","message":"VIT Chennai AI Assistant API is running"}`

### Test RAG Query
```bash
curl -X POST http://localhost:8000/retrieve/ \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the hostel facilities?"}'
```

### Test Frontend
1. Open http://localhost:8080
2. Click a suggested prompt or type: "Tell me about VIT Chennai"
3. You should see an AI response with sources

---

## Stop Servers

**If using start.sh:** Press `Ctrl+C`

**If manual:** Press `Ctrl+C` in each terminal

---

## Troubleshooting One-Liners

```bash
# Kill process on port 8000 (backend)
lsof -ti:8000 | xargs kill -9

# Kill process on port 8080 (frontend)
lsof -ti:8080 | xargs kill -9

# Reinstall backend dependencies
cd Backend && source venv/bin/activate && pip install -r ../requirements.txt --force-reinstall

# Reinstall frontend dependencies
cd Frontend && rm -rf node_modules package-lock.json && npm install

# View backend logs (if using start.sh)
tail -f backend.log

# View frontend logs (if using start.sh)
tail -f frontend.log
```

---

## Environment Variables Checklist

### Backend/.env
- [ ] `WEAVIATE_URL` - Your Weaviate cluster URL
- [ ] `WEAVIATE_API_KEY` - Your Weaviate API key
- [ ] `GEMINI_API_KEY` - Your Google Gemini API key
- [ ] `GEMINI_MODEL` - Model name (default: gemini-1.5-flash)

### Frontend/.env
- [ ] `VITE_API_URL` - Backend URL (default: http://localhost:8000)

---

## Common Issues & Fixes

| Issue | Solution |
|-------|----------|
| Backend won't start | Check Backend/.env has all keys |
| Frontend can't connect | Ensure backend is running on port 8000 |
| "Module not found" errors | Reinstall dependencies (see above) |
| CORS errors | Already fixed in main.py, restart backend |
| Port already in use | Kill process (see above) or change port |

---

## Development Workflow

1. **Start both servers** using `./start.sh`
2. **Make changes** to frontend/backend
3. **Auto-reload** happens automatically
4. **Test** in browser (http://localhost:8080)
5. **Stop servers** with Ctrl+C

---

## Production Deployment

### Backend
```bash
cd Backend/app
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Frontend
```bash
cd Frontend
npm run build
# Deploy dist/ folder to Vercel/Netlify
```

Don't forget to:
- Set production environment variables
- Update CORS origins in `Backend/app/main.py`
- Use HTTPS
- Set `VITE_API_URL` to production backend URL

---

**Need more help?** See [SETUP_GUIDE.md](./SETUP_GUIDE.md) for detailed instructions!
