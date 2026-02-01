from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def _camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


class BusinessSchema(BaseModel):
    industry: str
    industry_code: Optional[str] = Field(None, alias="industryCode")
    state: str
    years_in_business: int = Field(..., alias="yearsInBusiness")
    annual_revenue: int = Field(..., alias="annualRevenue")
    entity_type: Optional[str] = Field(None, alias="entityType")

    model_config = {"populate_by_name": True}


class GuarantorSchema(BaseModel):
    fico_score: int = Field(..., alias="ficoScore")
    has_bankruptcy: Optional[bool] = Field(False, alias="hasBankruptcy")
    has_tax_liens: Optional[bool] = Field(False, alias="hasTaxLiens")
    has_judgments: Optional[bool] = Field(False, alias="hasJudgments")
    years_at_address: Optional[int] = Field(None, alias="yearsAtAddress")

    model_config = {"populate_by_name": True}


class BusinessCreditSchema(BaseModel):
    paynet_score: Optional[int] = Field(None, alias="paynetScore")
    trade_lines_count: Optional[int] = Field(None, alias="tradeLinesCount")
    average_trade_age_months: Optional[int] = Field(None, alias="averageTradeAgeMonths")

    model_config = {"populate_by_name": True}


class EquipmentSchema(BaseModel):
    type: str
    category: Optional[str] = None
    age_years: Optional[int] = Field(None, alias="ageYears")
    cost: Optional[int] = None
    description: Optional[str] = None

    model_config = {"populate_by_name": True}


class LoanRequestSchema(BaseModel):
    amount: int
    term_months: int = Field(..., alias="termMonths")
    equipment: EquipmentSchema
    purpose: Optional[str] = None

    model_config = {"populate_by_name": True}


class ApplicationCreate(BaseModel):
    business: BusinessSchema
    guarantor: GuarantorSchema
    business_credit: Optional[BusinessCreditSchema] = Field(None, alias="businessCredit")
    loan_request: LoanRequestSchema = Field(..., alias="loanRequest")

    model_config = {"populate_by_name": True}


class ApplicationSubmit(BaseModel):
    pass  # no body; POST to submit


class ApplicationResponse(BaseModel):
    id: str
    status: Literal["draft", "submitted", "underwriting", "completed", "failed"]
    business: dict[str, Any]
    guarantor: dict[str, Any]
    business_credit: Optional[dict[str, Any]] = None
    loan_request: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    submitted_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_with_camel(cls, obj: Any) -> "ApplicationResponse":
        """Map DB snake_case to frontend camelCase."""
        def to_camel(d: dict | None) -> dict | None:
            if d is None:
                return None
            out: dict = {}
            for k, v in d.items():
                parts = k.split("_")
                new_k = parts[0] + "".join(p.capitalize() for p in parts[1:])
                out[new_k] = v
            return out

        return cls(
            id=obj.id,
            status=obj.status,
            business=to_camel(obj.business) or {},
            guarantor=to_camel(obj.guarantor) or {},
            business_credit=to_camel(obj.business_credit) if obj.business_credit else None,
            loan_request=to_camel(obj.loan_request) or {},
            created_at=obj.created_at,
            updated_at=obj.updated_at,
            submitted_at=obj.submitted_at,
        )
