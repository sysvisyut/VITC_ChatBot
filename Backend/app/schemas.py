from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500, description="The user's query")

    @field_validator('query')
    @classmethod
    def check_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Query cannot be only whitespace')
        return v


class SourceSchema(BaseModel):
    document_name: str
    page_number:   Optional[int] = None
    doc_type:      Optional[str] = None
    section_name:  Optional[str] = None


class RetrieveResponse(BaseModel):
    answer:     str
    sources:    List[SourceSchema]
    confidence: Literal["high", "medium", "low"] = "low"
