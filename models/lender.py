from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import relationship

from database import Base


class Lender(Base):
    __tablename__ = "lenders"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(256), nullable=False)
    slug = Column(String(128), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    source_document = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    programs = relationship("LenderProgram", back_populates="lender", cascade="all, delete-orphan")


class LenderProgram(Base):
    __tablename__ = "lender_programs"

    id = Column(String(64), primary_key=True, index=True)
    lender_id = Column(String(64), ForeignKey("lenders.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    tier = Column(String(32), nullable=True)
    description = Column(Text, nullable=True)
    # Normalized criteria (FICO, PayNet, loan amount, time in business, geographic, industry, equipment, etc.)
    criteria = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    lender = relationship("Lender", back_populates="programs")
