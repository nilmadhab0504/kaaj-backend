from sqlalchemy import Column, DateTime, String, Text, func
from sqlalchemy import JSON

from database import Base


class LoanApplication(Base):
    __tablename__ = "loan_applications"

    id = Column(String(64), primary_key=True, index=True)
    status = Column(String(32), nullable=False, default="draft", index=True)
    # Normalized payloads (aligned with frontend types)
    business = Column(JSON, nullable=False)
    guarantor = Column(JSON, nullable=False)
    business_credit = Column(JSON, nullable=True)
    loan_request = Column(JSON, nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
