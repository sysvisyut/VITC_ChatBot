import os
from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def get_api_key(api_key_header: str = Security(api_key_header)):
    expected_api_key = os.getenv("API_KEY")
    if not expected_api_key:
        # If no key is set in .env, we assume auth is disabled (or we could fail safe).
        # For security, let's fail safe if it's supposed to be secured.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server API key not configured"
        )
    
    if api_key_header == expected_api_key:
        return api_key_header
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Could not validate API key"
    )
