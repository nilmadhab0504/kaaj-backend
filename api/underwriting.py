from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import LoanApplication, UnderwritingRun
from services.underwriting import run_underwriting

router = APIRouter(prefix="/api", tags=["underwriting"])


def _validate_application_completeness(app: LoanApplication) -> None:
    """Raise 400 if critical fields for matching are missing."""
    missing = []
    if not (app.guarantor and app.guarantor.get("fico_score") is not None):
        missing.append("guarantor.ficoScore")
    if not (app.loan_request and app.loan_request.get("amount") is not None):
        missing.append("loanRequest.amount")
    if not (app.business and app.business.get("state")):
        missing.append("business.state")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Application incomplete for underwriting. Missing or invalid: {', '.join(missing)}",
        )


@router.post("/applications/{application_id}/underwrite", response_model=dict)
async def start_underwriting(application_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LoanApplication).where(LoanApplication.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    _validate_application_completeness(app)
    run = await run_underwriting(db, application_id)
    return {
        "id": run.id,
        "applicationId": run.application_id,
        "status": run.status,
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "completedAt": run.completed_at.isoformat() if run.completed_at else None,
        "error": run.error_message,
        "results": run.results,
    }


@router.get("/underwriting/{run_id}", response_model=dict)
async def get_underwriting_run(run_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UnderwritingRun).where(UnderwritingRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "id": run.id,
        "applicationId": run.application_id,
        "status": run.status,
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "completedAt": run.completed_at.isoformat() if run.completed_at else None,
        "error": run.error_message,
        "results": run.results,
    }
