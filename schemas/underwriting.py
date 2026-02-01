from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel

from schemas.lender import LenderMatchResultSchema


class UnderwritingRunResponse(BaseModel):
    id: str
    application_id: str
    status: Literal["pending", "running", "completed", "failed"]
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    results: Optional[list[dict[str, Any]]] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
