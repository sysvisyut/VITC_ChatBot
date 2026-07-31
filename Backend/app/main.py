from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from .routers import retrieve, user, stream
import logging

# Centralized logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Rate limiter setup
from app.limiter import limiter

app = FastAPI(title="VIT Chennai AI Assistant API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

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
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

@app.get('/')
def test_server():
    logger.info("Health check endpoint called")
    return {"status": "ok", "message": "VIT Chennai AI Assistant API is running"}

app.include_router(retrieve.router)
app.include_router(stream.router)