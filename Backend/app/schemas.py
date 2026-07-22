from pydantic import BaseModel
from typing import Optional, List, Literal


class RetrieveRequest(BaseModel):
    query: str


class SourceSchema(BaseModel):
    document_name: str
    page_number:   Optional[int] = None
    doc_type:      Optional[str] = None
    section_name:  Optional[str] = None


class RetrieveResponse(BaseModel):
    answer:     str
    sources:    List[SourceSchema]
    confidence: Literal["high", "medium", "low"] = "low"