from fastapi import APIRouter, status, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from ..import schemas
import logging
from app.services.rag_service import RAGService, get_rag_service
from app.auth import get_api_key
from app.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix='/stream',
    tags=["Retrieval (Streaming)"],
    dependencies=[Depends(get_api_key)]
)

@router.post("/")
@limiter.limit("10/minute")
def stream_retrieve(req: schemas.RetrieveRequest, request: Request, rag_service: RAGService = Depends(get_rag_service)):
    try:
        # Returning a StreamingResponse tells FastAPI to iterate the generator
        # and send chunks back to the client immediately.
        return StreamingResponse(
            rag_service.query_stream(req.query),
            media_type="text/event-stream"
        )
    except Exception as e:
        logger.exception("RAG streaming request failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error, please try again."
        )
