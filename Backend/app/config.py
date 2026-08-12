from pathlib import Path

from pydantic_settings import BaseSettings

# Compute the backend root directory (assumes config.py is inside Backend/app/)
BACKEND_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    # API Keys & Auth
    api_key: str

    # Gemini
    gemini_api_key: str
    gemini_model: str = "gemini-3.5-flash"

    # Weaviate
    weaviate_url: str
    weaviate_api_key: str

    # Constants
    collection_name: str = "VIT_docs"
    # Can be overridden by PDF_DIRECTORY env var (e.g. /app/data inside Docker)
    pdf_directory: str = str(BACKEND_DIR / "data")

    class Config:
        env_file = str(BACKEND_DIR / ".env")
        env_file_encoding = 'utf-8'
        extra = "ignore"  # Ignore extraneous env vars

settings = Settings()
