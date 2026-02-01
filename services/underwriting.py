from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import Lender, LoanApplication, UnderwritingRun
from schemas.lender import LenderMatchResultSchema
from services.matching_engine import evaluate_application
from utils.case import dict_keys_to_camel


async def run_underwriting(session: AsyncSession, application_id: str) -> UnderwritingRun:
    """Load application and all lenders; evaluate each lender; persist run and results."""
    now_start = datetime.now(timezone.utc)
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    run = UnderwritingRun(
        id=run_id,
        application_id=application_id,
        status="running",
        started_at=now_start,
        results=None,
    )
    session.add(run)
    await session.flush()

    try:
        app_result = await session.execute(select(LoanApplication).where(LoanApplication.id == application_id))
        app = app_result.scalar_one_or_none()
        if not app:
            run.status = "failed"
            run.error_message = "Application not found"
            run.completed_at = now_start
            return run

        business = app.business or {}
        guarantor = app.guarantor or {}
        business_credit = app.business_credit
        loan_request = app.loan_request or {}

        lenders_result = await session.execute(
            select(Lender).options(selectinload(Lender.programs))
        )
        lenders = lenders_result.scalars().all()
        if not lenders:
            run.status = "completed"
            run.results = []
            run.completed_at = now_start
            return run

        lenders_with_programs = [l for l in lenders if l.programs]
        results: list[dict] = []
        for lender in lenders_with_programs:
            programs_data = [
                {"id": p.id, "name": p.name, "tier": p.tier, "criteria": p.criteria or {}}
                for p in lender.programs
            ]
            match = evaluate_application(
                business=business,
                guarantor=guarantor,
                business_credit=business_credit,
                loan_request=loan_request,
                lender_id=lender.id,
                lender_name=lender.name,
                programs=programs_data,
            )
            results.append(dict_keys_to_camel(match.model_dump()))

        results.sort(key=lambda r: (-r["eligible"], -r["fitScore"]))

        now = datetime.now(timezone.utc)
        run.status = "completed"
        run.results = results
        run.completed_at = now
    except Exception as e:
        run.status = "failed"
        run.error_message = str(e)
        run.completed_at = datetime.now(timezone.utc)
        raise

    return run
