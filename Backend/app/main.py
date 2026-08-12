import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .routers import admin, retrieve, stream

# Centralized logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Rate limiter setup
from contextlib import asynccontextmanager

from app.limiter import limiter
from app.services.rag_service import RAGService


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up: Initializing RAGService...")
    app.state.rag_service = RAGService()
    yield
    logger.info("Shutting down: Closing RAGService...")
    app.state.rag_service.close()

app = FastAPI(title="VIT Chennai AI Assistant API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Prometheus metrics — exposes /metrics endpoint (no auth, standard Prometheus scrape)
Instrumentator().instrument(app).expose(app)

# Enable CORS for frontend connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",  # Frontend dev server
        "http://127.0.0.1:8080",
        "http://localhost:5173",  # Alternative Vite port
        "http://127.0.0.1:5173",
        "http://localhost",       # Docker nginx (port 80)
        "http://127.0.0.1",
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
app.include_router(admin.router)
