from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy import JSON

from database import Base


class UnderwritingRun(Base):
    __tablename__ = "underwriting_runs"

    id = Column(String(64), primary_key=True, index=True)
    application_id = Column(String(64), ForeignKey("loan_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    # Cached match results (list of LenderMatchResult dicts, aligned with frontend)
    results = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
