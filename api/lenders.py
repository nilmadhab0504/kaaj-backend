import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import Lender, LenderProgram
from schemas.lender import LenderCreate, LenderUpdate, ProgramCreate, LenderProgramUpdate
from schemas.lender_criteria import snake_case_dict
from utils.case import dict_keys_to_camel

router = APIRouter(prefix="/api/lenders", tags=["lenders"])

MSG_LENDER_NOT_FOUND = "Lender not found"
MSG_PROGRAM_NOT_FOUND = "Program not found"


def _program_to_response(p: LenderProgram) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "tier": p.tier,
        "description": p.description,
        "criteria": dict_keys_to_camel(p.criteria or {}),
    }


def _lender_to_response(l: Lender) -> dict[str, Any]:
    return {
        "id": l.id,
        "name": l.name,
        "slug": l.slug,
        "description": l.description,
        "sourceDocument": l.source_document,
        "programs": [_program_to_response(p) for p in l.programs],
        "createdAt": l.created_at.isoformat() if l.created_at else None,
        "updatedAt": l.updated_at.isoformat() if l.updated_at else None,
    }


def _normalize_criteria(criteria: dict[str, Any]) -> dict[str, Any]:
    """Normalize criteria keys to snake_case for storage; ensure loan_amount (min/max) exists."""
    out = snake_case_dict(criteria)
    la = out.get("loan_amount")
    if not isinstance(la, dict) or "min_amount" not in la or "max_amount" not in la:
        raise ValueError("criteria must include loan_amount with min_amount and max_amount")
    return out


def _slug_to_id(slug: str) -> str:
    """Generate a short id from slug (e.g. 'stearns-bank' -> 'stearns-bank' or unique)."""
    return re.sub(r"[^a-z0-9-]", "", slug.lower()) or f"lender-{uuid.uuid4().hex[:8]}"


def _suggest_from_filename(filename: str) -> tuple[str, str, str]:
    """From PDF filename suggest lender name, slug, and source document."""
    name = Path(filename).stem.strip()
    name = re.sub(r"\s+", " ", name.replace("+", " ").replace("++", " "))
    slug = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug) or "lender"
    return (name or "Lender", slug, filename)


@router.post("/parse-pdf", response_model=dict)
async def parse_lender_pdf(file: UploadFile = File(..., description="Lender guideline PDF")):
    """
    Upload a lender guideline PDF; parse and return suggested lender name, source document, and criteria.
    Frontend pre-fills the form with this data; user verifies/edits and submits.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")
    try:
        from pdf_ingestion.parser import parse_lender_programs_from_pdf
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"PDF parsing not available: {e}") from e
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty.")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        programs_snake = parse_lender_programs_from_pdf(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    suggested_name, suggested_slug, source_document = _suggest_from_filename(file.filename or "guidelines.pdf")
    programs_camel = [
        {
            "name": p["name"],
            "tier": p.get("tier"),
            "criteria": dict_keys_to_camel(p["criteria"]),
        }
        for p in programs_snake
    ]
    return {
        "suggestedName": suggested_name,
        "suggestedSlug": suggested_slug,
        "sourceDocument": source_document,
        "programs": programs_camel,
    }


@router.get("", response_model=list[dict])
async def list_lenders(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Lender).options(selectinload(Lender.programs)).order_by(Lender.name))
    lenders = result.scalars().all()
    return [_lender_to_response(l) for l in lenders]


@router.get("/{lender_id}", response_model=dict)
async def get_lender(lender_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Lender).options(selectinload(Lender.programs)).where(Lender.id == lender_id)
    )
    lender = result.scalar_one_or_none()
    if not lender:
        raise HTTPException(status_code=404, detail=MSG_LENDER_NOT_FOUND)
    return _lender_to_response(lender)


@router.post("", response_model=dict, status_code=201)
async def create_lender(body: LenderCreate, db: AsyncSession = Depends(get_db)):
    lender_id = _slug_to_id(body.slug)
    existing = await db.execute(
        select(Lender).where(or_(Lender.id == lender_id, Lender.slug == body.slug))
    )
    found = existing.scalar_one_or_none()
    if found:
        if found.slug == body.slug:
            raise HTTPException(status_code=400, detail="Slug already in use")
        lender_id = f"{lender_id}-{uuid.uuid4().hex[:6]}"
    lender = Lender(
        id=lender_id,
        name=body.name,
        slug=body.slug,
        description=body.description,
        source_document=body.source_document,
    )
    db.add(lender)
    await db.flush()
    if body.programs:
        for prog_in in body.programs:
            criteria = _normalize_criteria(prog_in.criteria)
            prog_id = f"{lender_id}-{uuid.uuid4().hex[:8]}"
            prog = LenderProgram(
                id=prog_id,
                lender_id=lender.id,
                name=prog_in.name,
                tier=prog_in.tier,
                description=prog_in.description,
                criteria=criteria,
            )
            db.add(prog)
    await db.flush()
    await db.refresh(lender, ["programs"])
    return _lender_to_response(lender)


@router.patch("/{lender_id}", response_model=dict)
async def update_lender(lender_id: str, body: LenderUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Lender).options(selectinload(Lender.programs)).where(Lender.id == lender_id)
    )
    lender = result.scalar_one_or_none()
    if not lender:
        raise HTTPException(status_code=404, detail=MSG_LENDER_NOT_FOUND)
    if body.name is not None:
        lender.name = body.name
    if body.slug is not None:
        lender.slug = body.slug
    if body.description is not None:
        lender.description = body.description
    if body.source_document is not None:
        lender.source_document = body.source_document
    await db.flush()
    return _lender_to_response(lender)


@router.post("/{lender_id}/programs", response_model=dict, status_code=201)
async def create_program(lender_id: str, body: ProgramCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Lender).options(selectinload(Lender.programs)).where(Lender.id == lender_id)
    )
    lender = result.scalar_one_or_none()
    if not lender:
        raise HTTPException(status_code=404, detail=MSG_LENDER_NOT_FOUND)
    try:
        criteria = _normalize_criteria(body.criteria)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    prog_id = f"{lender_id}-{uuid.uuid4().hex[:8]}"
    prog = LenderProgram(
        id=prog_id,
        lender_id=lender.id,
        name=body.name,
        tier=body.tier,
        description=body.description,
        criteria=criteria,
    )
    db.add(prog)
    await db.flush()
    return _program_to_response(prog)


@router.patch("/{lender_id}/programs/{program_id}", response_model=dict)
async def update_program(
    lender_id: str, program_id: str, body: LenderProgramUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(LenderProgram)
        .where(LenderProgram.id == program_id, LenderProgram.lender_id == lender_id)
    )
    prog = result.scalar_one_or_none()
    if not prog:
        raise HTTPException(status_code=404, detail=MSG_PROGRAM_NOT_FOUND)
    if body.name is not None:
        prog.name = body.name
    if body.tier is not None:
        prog.tier = body.tier
    if body.description is not None:
        prog.description = body.description
    if body.criteria is not None:
        try:
            prog.criteria = _normalize_criteria(body.criteria)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    await db.flush()
    await db.refresh(prog)
    return _program_to_response(prog)


@router.delete("/{lender_id}/programs/{program_id}", status_code=204)
async def delete_program(lender_id: str, program_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(LenderProgram)
        .where(LenderProgram.id == program_id, LenderProgram.lender_id == lender_id)
    )
    prog = result.scalar_one_or_none()
    if not prog:
        raise HTTPException(status_code=404, detail=MSG_PROGRAM_NOT_FOUND)
    await db.delete(prog)
    await db.flush()
    return None
