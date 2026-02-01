from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import LoanApplication, UnderwritingRun
from schemas.application import ApplicationCreate
from utils.case import dict_keys_to_camel

router = APIRouter(prefix="/api/applications", tags=["applications"])


def _app_to_response(app: LoanApplication) -> dict[str, Any]:
    """Serialize application to dict with camelCase for frontend."""
    return {
        "id": app.id,
        "status": app.status,
        "business": dict_keys_to_camel(app.business) if app.business else {},
        "guarantor": dict_keys_to_camel(app.guarantor) if app.guarantor else {},
        "businessCredit": dict_keys_to_camel(app.business_credit) if app.business_credit else None,
        "loanRequest": dict_keys_to_camel(app.loan_request) if app.loan_request else {},
        "createdAt": app.created_at.isoformat() if app.created_at else None,
        "updatedAt": app.updated_at.isoformat() if app.updated_at else None,
        "submittedAt": app.submitted_at.isoformat() if app.submitted_at else None,
    }


@router.get("")
async def list_applications(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LoanApplication).order_by(LoanApplication.updated_at.desc()))
    apps = result.scalars().all()
    return [_app_to_response(a) for a in apps]


@router.get("/{application_id}")
async def get_application(application_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LoanApplication).where(LoanApplication.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    return _app_to_response(app)


@router.post("", status_code=201)
async def create_application(body: ApplicationCreate, db: AsyncSession = Depends(get_db)):
    app_id = f"app-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    app = LoanApplication(
        id=app_id,
        status="draft",
        business=body.business.model_dump(by_alias=False),
        guarantor=body.guarantor.model_dump(by_alias=False),
        business_credit=body.business_credit.model_dump(by_alias=False) if body.business_credit else None,
        loan_request=body.loan_request.model_dump(by_alias=False),
        created_at=now,
        updated_at=now,
    )
    db.add(app)
    await db.flush()
    return _app_to_response(app)


@router.post("/{application_id}/submit")
async def submit_application(application_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LoanApplication).where(LoanApplication.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    app.status = "submitted"
    app.submitted_at = datetime.now(timezone.utc)
    app.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return _app_to_response(app)


@router.get("/{application_id}/runs", response_model=list[dict])
async def list_runs(application_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UnderwritingRun)
        .where(UnderwritingRun.application_id == application_id)
        .order_by(UnderwritingRun.created_at.desc())
    )
    runs = result.scalars().all()
    out = []
    for r in runs:
        out.append({
            "id": r.id,
            "applicationId": r.application_id,
            "status": r.status,
            "startedAt": r.started_at.isoformat() if r.started_at else None,
            "completedAt": r.completed_at.isoformat() if r.completed_at else None,
            "error": r.error_message,
            "results": r.results,
        })
    return out
