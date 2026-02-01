"""
Normalized schema for lender credit policy criteria.
Supports: FICO, PayNet, time in business, loan amount, equipment, geographic, industry, min revenue, custom rules.
"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class FicoCriteriaSchema(BaseModel):
    """FICO score limits (min/max or tiered by program)."""
    min_score: Optional[int] = Field(None, ge=300, le=850, description="Minimum FICO score")
    max_score: Optional[int] = Field(None, ge=300, le=850, description="Maximum FICO score")
    tiered: Optional[list[dict[str, Any]]] = Field(
        None,
        description="Tiered minimums: [{min_score, program_name}, ...]",
    )


class PayNetCriteriaSchema(BaseModel):
    """PayNet score limits."""
    min_score: Optional[int] = Field(None, ge=0, le=100)
    max_score: Optional[int] = Field(None, ge=0, le=100)


class LoanAmountCriteriaSchema(BaseModel):
    """Min/max loan amount (required for every program)."""
    min_amount: int = Field(..., ge=0, description="Minimum loan amount in USD")
    max_amount: int = Field(..., ge=0, description="Maximum loan amount in USD")


class TimeInBusinessCriteriaSchema(BaseModel):
    """Minimum time in business (years)."""
    min_years: int = Field(..., ge=0, le=100)


class GeographicRestrictionSchema(BaseModel):
    """State-level geographic restrictions."""
    allowed_states: Optional[list[str]] = Field(None, description="Only these states (e.g. ['CA','TX'])")
    excluded_states: Optional[list[str]] = Field(None, description="Exclude these states")


class IndustryRestrictionSchema(BaseModel):
    """Industry inclusions/exclusions."""
    allowed_industries: Optional[list[str]] = Field(None, description="Only these industries")
    excluded_industries: Optional[list[str]] = Field(None, description="Exclude these industries (e.g. Trucking)")


class EquipmentRestrictionSchema(BaseModel):
    """Equipment type and age restrictions."""
    allowed_types: Optional[list[str]] = Field(None, description="Only these equipment types")
    excluded_types: Optional[list[str]] = Field(None, description="Exclude these equipment types")
    max_equipment_age_years: Optional[int] = Field(None, ge=0, le=50, description="Max age of equipment in years")


class CustomRuleSchema(BaseModel):
    """Custom rule (name, description, optional expression for future use)."""
    name: str
    description: str
    expression: Optional[str] = None


class LenderPolicyCriteriaSchema(BaseModel):
    """
    Normalized lender credit policy criteria.
    loan_amount is required; all other criteria are optional.
    """
    fico: Optional[FicoCriteriaSchema] = None
    paynet: Optional[PayNetCriteriaSchema] = None
    loan_amount: LoanAmountCriteriaSchema = Field(..., description="Min/max loan amount (required)")
    time_in_business: Optional[TimeInBusinessCriteriaSchema] = None
    geographic: Optional[GeographicRestrictionSchema] = None
    industry: Optional[IndustryRestrictionSchema] = None
    equipment: Optional[EquipmentRestrictionSchema] = None
    min_revenue: Optional[int] = Field(None, ge=0, description="Minimum annual revenue in USD")
    custom_rules: Optional[list[CustomRuleSchema]] = Field(None, description="Additional named rules")

    def to_storage_dict(self) -> dict[str, Any]:
        """Convert to dict for JSONB storage (snake_case)."""
        return self.model_dump(exclude_none=True, by_alias=False)

    @classmethod
    def from_camel_dict(cls, d: dict[str, Any]) -> "LenderPolicyCriteriaSchema":
        """Build from frontend camelCase dict."""
        return cls.model_validate(snake_case_dict(d))


def snake_case_dict(obj: Any) -> Any:
    """Recursively convert dict keys from camelCase to snake_case. For API input normalization."""
    import re
    def to_snake(s: str) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()
    if isinstance(obj, dict):
        return {to_snake(k): snake_case_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [snake_case_dict(x) for x in obj]
    return obj
