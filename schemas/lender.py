from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class CriterionResultSchema(BaseModel):
    name: str
    met: bool
    reason: str
    expected: Optional[str] = None
    actual: Optional[str] = None


class BestProgramSchema(BaseModel):
    id: str
    name: str
    tier: Optional[str] = None


class LenderMatchResultSchema(BaseModel):
    lender_id: str
    lender_name: str
    eligible: bool
    fit_score: int
    best_program: Optional[BestProgramSchema] = None
    rejection_reasons: list[str] = Field(default_factory=list)
    criteria_results: list[CriterionResultSchema] = Field(default_factory=list)


class LenderProgramResponse(BaseModel):
    id: str
    name: str
    tier: Optional[str] = None
    description: Optional[str] = None
    criteria: dict[str, Any]


class LenderProgramUpdate(BaseModel):
    name: Optional[str] = None
    tier: Optional[str] = None
    description: Optional[str] = None
    criteria: Optional[dict[str, Any]] = None


class LenderResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    source_document: Optional[str] = None
    programs: list[LenderProgramResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LenderPolicyResponse(LenderResponse):
    """Alias for frontend compatibility."""

    pass


class LenderUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    source_document: Optional[str] = None


class ProgramCreate(BaseModel):
    """Create a new program under a lender."""
    name: str
    tier: Optional[str] = None
    description: Optional[str] = None
    criteria: dict[str, Any] = Field(..., description="Normalized criteria; must include loan_amount (min_amount, max_amount)")


class LenderCreate(BaseModel):
    """Create a new lender (with optional programs)."""
    name: str
    slug: str
    description: Optional[str] = None
    source_document: Optional[str] = Field(None, alias="sourceDocument")
    programs: Optional[list[ProgramCreate]] = Field(None, description="Optional initial programs")

    model_config = {"populate_by_name": True}
