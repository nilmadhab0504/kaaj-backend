# Lender Match API

FastAPI backend for loan underwriting and lender matching.

## Setup

1. **Python 3.11+**

2. Create a virtual environment and install dependencies (recommended):
   ```bash
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate   # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Copy env and configure the database:
   ```bash
   cp .env.example .env
   ```

4. **Database** – switch via `DATABASE_URL` in `.env`:
   - **SQLite** (default): No extra setup. Uses `./lender_match.db`.
   - **PostgreSQL**: Set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/lender_match`, create the DB with `createdb lender_match`, then start the server.

5. Run the server (port 3005) — with venv activated:
   ```bash
   python3 run.py
   ```
   Or: `python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 3005`

6. Seed lender policies (from normalized PDF guidelines):
   ```bash
   python -m scripts.seed_lenders
   ```

## PDF guideline ingestion

PDF parsing uses **LLM extraction** (Groq or Google Gemini free tier) when API keys are set, otherwise falls back to regex-based parsing. LLM extraction is more accurate, especially for multi-tier documents.

**Optional – enable LLM parsing** (recommended):
1. **Groq** (free): Sign up at https://console.groq.com → API Keys. Add to `.env`:
   ```
   GROQ_API_KEY=gsk_...
   ```
2. **Google Gemini** (free): Get key at https://aistudio.google.com/apikey. Add to `.env`:
   ```
   GEMINI_API_KEY=...
   ```
If both are set, Groq is tried first.

The following PDFs are referenced for lender policies:

- **Advantage++ Broker 2025.pdf** → Advantage+ Financing (non-trucking up to $75K)
- **Apex EF Broker Guidelines_082725.pdf** → Apex Commercial Capital
- **112025 Rates - STANDARD.pdf** → Falcon Equipment Finance
- **2025 Program Guidelines UPDATED.pdf** → Citizens Bank

To add or update a lender from a new PDF:

1. Place the PDF in `backend/data/pdfs/` (or set path in script).
2. Extract text: `python -c "from pdf_ingestion.parser import extract_text; print(extract_text('data/pdfs/YourFile.pdf'))"`
3. Use `suggest_criteria_from_text(text)` for heuristic hints, then normalize criteria into the schema (FICO, PayNet, loan amount, time in business, geographic, industry, equipment).
4. Add a new entry to `scripts/seed_lenders.py` and run `python -m scripts.seed_lenders`, or call the API to create/update lenders.

## API

- `GET /health` – health check
- `GET /api/applications` – list applications
- `POST /api/applications` – create application (body: camelCase OK)
- `GET /api/applications/{id}` – get application
- `POST /api/applications/{id}/submit` – submit application
- `POST /api/applications/{id}/underwrite` – run underwriting (match against all lenders)
- `GET /api/applications/{id}/runs` – list underwriting runs (latest run has `results`)
- `GET /api/lenders` – list lender policies
- `GET /api/lenders/{id}` – get lender policy
- `PATCH /api/lenders/{id}` – update lender (name, description, etc.)

Responses use **camelCase** for frontend compatibility.
# kaaj-backend
