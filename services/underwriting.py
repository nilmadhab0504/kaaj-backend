from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Lender, LenderProgram, LoanApplication, UnderwritingRun
from services.matching_engine import evaluate_application
from schemas.lender import LenderMatchResultSchema

if TYPE_CHECKING:
    # (reserved for typing-only imports to avoid runtime cycles)
    ...


async def run_underwriting(session: AsyncSession, application_id: str) -> UnderwritingRun:
    """
    Load application and all lenders; evaluate each lender; persist run and results.
    """
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    run = UnderwritingRun(
        id=run_id,
        application_id=application_id,
        status="running",
        started_at=datetime.now(timezone.utc),
        results=None,
    )
    session.add(run)
    await session.flush()

    try:
        # Load application
        app_result = await session.execute(select(LoanApplication).where(LoanApplication.id == application_id))
        app = app_result.scalar_one_or_none()
        if not app:
            run.status = "failed"
            run.error_message = "Application not found"
            run.completed_at = datetime.now(timezone.utc)
            return run

        business = app.business or {}
        guarantor = app.guarantor or {}
        business_credit = app.business_credit
        loan_request = app.loan_request or {}

        # Load all lenders with programs
        lenders_result = await session.execute(
            select(Lender).options(selectinload(Lender.programs))
        )
        lenders = lenders_result.scalars().all()
        if not lenders:
            run.status = "completed"
            run.results = []
            run.completed_at = datetime.now(timezone.utc)
            return run

        results: list[dict] = []
        for lender in lenders:
            programs_data = []
            for p in lender.programs:
                programs_data.append({
                    "id": p.id,
                    "name": p.name,
                    "tier": p.tier,
                    "criteria": p.criteria or {},
                })
            if not programs_data:
                continue
            match = evaluate_application(
                business=business,
                guarantor=guarantor,
                business_credit=business_credit,
                loan_request=loan_request,
                lender_id=lender.id,
                lender_name=lender.name,
                programs=programs_data,
            )
            # Serialize to dict for JSONB (camelCase for frontend)
            results.append(_match_to_dict(match))

        # Sort: eligible first, by fit_score desc
        results.sort(key=lambda r: (-r.get("eligible", False), -r.get("fitScore", 0)))

        run.status = "completed"
        run.results = results
        run.completed_at = datetime.now(timezone.utc)
    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)
        run.completed_at = datetime.now(timezone.utc)
        raise

    return run


def _match_to_dict(m: LenderMatchResultSchema) -> dict:
    """Convert match result to dict with camelCase keys for frontend."""
    d: dict = {
        "lenderId": m.lender_id,
        "lenderName": m.lender_name,
        "eligible": m.eligible,
        "fitScore": m.fit_score,
        "rejectionReasons": m.rejection_reasons,
        "criteriaResults": [
            {
                "name": c.name,
                "met": c.met,
                "reason": c.reason,
                "expected": c.expected,
                "actual": c.actual,
            }
            for c in m.criteria_results
        ],
    }
    if m.best_program:
        d["bestProgram"] = {
            "id": m.best_program.id,
            "name": m.best_program.name,
            "tier": m.best_program.tier,
        }
    return d
