from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import retrieve, user
import logging

# Centralized logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="VIT Chennai AI Assistant API", version="1.0.0")

# Enable CORS for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",  # Frontend dev server
        "http://127.0.0.1:8080",
        "http://localhost:5173",  # Alternative Vite port
        "http://127.0.0.1:5173",
        "https://vitc-chat-bot-frontend.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get('/')
def test_server():
    logger.info("Health check endpoint called")
    return {"status": "ok", "message": "VIT Chennai AI Assistant API is running"}

app.include_router(retrieve.router)