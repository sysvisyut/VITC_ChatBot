from fastapi import APIRouter, status, File, UploadFile, Form, HTTPException, Request
from ..import schemas, database
from typing import Optional
import logging
from app.utils.rag_adaptor import query_rag

logger = logging.getLogger(__name__)

from fastapi import APIRouter, status, File, UploadFile, Form, HTTPException, Request, Depends
from app.auth import get_api_key

router = APIRouter(
    prefix = '/retrieve',
    tags = ["Retrieval"],
    dependencies=[Depends(get_api_key)]
)


from app.limiter import limiter

@router.post("/", response_model=schemas.RetrieveResponse)
@limiter.limit("10/minute")
def retrieve(req: schemas.RetrieveRequest, request: Request):
    try:
        result = query_rag(req.query)
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