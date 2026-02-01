"""
Seed lender policies from normalized data (aligned with the 5 PDF guidelines).
Run: python -m scripts.seed_lenders (from backend dir, with DB running).
"""
import asyncio
import os
import sys

# Add parent so we can import from backend
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, init_db
from models import Lender, LenderProgram


LENDERS_DATA = [
    {
        "id": "stearns",
        "name": "Stearns Bank - Equipment Finance",
        "slug": "stearns-bank",
        "description": "Equipment finance credit box",
        "source_document": "Stearns Bank - Equipment Finance Credit Box.pdf",
        "programs": [
            {
                "id": "stearns-standard",
                "name": "Standard Program",
                "tier": "A",
                "criteria": {
                    "fico": {"min_score": 700},
                    "paynet": {"min_score": 60},
                    "loan_amount": {"min_amount": 25_000, "max_amount": 500_000},
                    "time_in_business": {"min_years": 2},
                    "geographic": {"excluded_states": []},
                    "equipment": {"max_equipment_age_years": 10},
                },
            },
        ],
    },
    {
        "id": "apex",
        "name": "Apex Commercial Capital",
        "slug": "apex-commercial",
        "description": "Broker guidelines (Apex EF Broker Guidelines)",
        "source_document": "Apex EF Broker Guidelines_082725.pdf",
        "programs": [
            {
                "id": "apex-tier1",
                "name": "Tier 1",
                "criteria": {
                    "fico": {"min_score": 680},
                    "loan_amount": {"min_amount": 10_000, "max_amount": 250_000},
                    "time_in_business": {"min_years": 1},
                },
            },
        ],
    },
    {
        "id": "advantage",
        "name": "Advantage+ Financing",
        "slug": "advantage-plus",
        "description": "Broker ICP ($75K non-trucking) - Advantage+ Broker 2025",
        "source_document": "Advantage++ Broker 2025.pdf",
        "programs": [
            {
                "id": "adv-75k",
                "name": "Non-Trucking up to $75K",
                "criteria": {
                    "fico": {"min_score": 650},
                    "loan_amount": {"min_amount": 5_000, "max_amount": 75_000},
                    "time_in_business": {"min_years": 1},
                    "industry": {"excluded_industries": ["Trucking"]},
                },
            },
        ],
    },
    {
        "id": "citizens",
        "name": "Citizens Bank",
        "slug": "citizens-bank",
        "description": "2025 Equipment Finance Program",
        "source_document": "2025 Program Guidelines UPDATED.pdf",
        "programs": [
            {
                "id": "citizens-standard",
                "name": "Standard",
                "criteria": {
                    "fico": {"min_score": 680},
                    "loan_amount": {"min_amount": 25_000, "max_amount": 1_000_000},
                    "time_in_business": {"min_years": 3},
                },
            },
        ],
    },
    {
        "id": "falcon",
        "name": "Falcon Equipment Finance",
        "slug": "falcon-equipment",
        "description": "Rates & Programs (STANDARD)",
        "source_document": "112025 Rates - STANDARD.pdf",
        "programs": [
            {
                "id": "falcon-standard",
                "name": "Standard Program",
                "criteria": {
                    "fico": {"min_score": 660},
                    "loan_amount": {"min_amount": 15_000, "max_amount": 350_000},
                    "time_in_business": {"min_years": 2},
                },
            },
        ],
    },
]


async def seed():
    await init_db()
    async with AsyncSessionLocal() as session:
        for data in LENDERS_DATA:
            existing = await session.execute(select(Lender).where(Lender.id == data["id"]))
            if existing.scalar_one_or_none():
                print(f"Lender {data['id']} already exists, skipping")
                continue
            lender = Lender(
                id=data["id"],
                name=data["name"],
                slug=data["slug"],
                description=data["description"],
                source_document=data["source_document"],
            )
            session.add(lender)
            await session.flush()
            for p in data["programs"]:
                prog = LenderProgram(
                    id=p["id"],
                    lender_id=lender.id,
                    name=p["name"],
                    tier=p.get("tier"),
                    criteria=p["criteria"],
                )
                session.add(prog)
            print(f"Seeded lender: {data['name']}")
        await session.commit()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
