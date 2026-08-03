import os
from pydantic_settings import BaseSettings
from pathlib import Path

# Compute the backend root directory (assumes config.py is inside Backend/app/)
BACKEND_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    # API Keys & Auth
    api_key: str
    
    # Gemini
    gemini_api_key: str
    gemini_model: str = "models/gemini-2.5-flash"
    
    # Weaviate
    weaviate_url: str
    weaviate_api_key: str
    
    # Constants
    collection_name: str = "VIT_docs"
    pdf_directory: str = str(BACKEND_DIR / "data")
    
    class Config:
        env_file = str(BACKEND_DIR / ".env")
        env_file_encoding = 'utf-8'
        extra = "ignore"  # Ignore extraneous env vars

settings = Settings()
