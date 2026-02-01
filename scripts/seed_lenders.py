"""
Ensure database tables exist. Lenders are managed via the API (create/parse PDF).
Run: python -m scripts.seed_lenders (from backend dir).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import init_db


async def seed():
    await init_db()
    print("Database ready.")


if __name__ == "__main__":
    asyncio.run(seed())
