from fastapi import APIRouter, status, File, UploadFile, Form, HTTPException, Request
from ..import schemas, database
from typing import Optional
import logging


logger = logging.getLogger(__name__)

from fastapi import APIRouter, status, File, UploadFile, Form, HTTPException, Request, Depends
from app.auth import get_api_key

router = APIRouter(
    prefix = '/retrieve',
    tags = ["Retrieval"],
    dependencies=[Depends(get_api_key)]
)


from app.limiter import limiter

from app.services.rag_service import RAGService, get_rag_service

@router.post("/", response_model=schemas.RetrieveResponse)
@limiter.limit("10/minute")
def retrieve(req: schemas.RetrieveRequest, request: Request, rag_service: RAGService = Depends(get_rag_service)):
    try:
        result = rag_service.query(req.query)
        return schemas.RetrieveResponse(
            answer=result["answer"],
            sources=result.get("sources", []),
            confidence=result.get("confidence", "low"),
        )
    except Exception as e:
        logger.exception("RAG query failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error, please try again."
        )