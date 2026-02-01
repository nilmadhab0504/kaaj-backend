# Lender Match API

FastAPI backend for loan underwriting and lender matching.

## API documentation

When the server is running, **OpenAPI (Swagger) docs** are at [http://localhost:3005/docs](http://localhost:3005/docs). Request/response shapes and examples are available there.

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

6. Ensure database tables exist:
   ```bash
   python -m scripts.seed_lenders
   ```
   (Creates tables only. Lenders are added via the API or UI, e.g. from parsed PDFs.)

## PDF guideline ingestion

PDF parsing uses **LLM extraction** (OpenAI or Google Gemini) when API keys are set, otherwise falls back to regex-based parsing. LLM extraction is more accurate, especially for multi-tier documents.

**Optional – enable LLM parsing** (recommended):
1. **OpenAI**: Sign up at https://platform.openai.com/api-keys. Add to `.env`:
   ```
   OPENAI_API_KEY=sk-proj-...
   ```
2. **Google Gemini** (free): Get key at https://aistudio.google.com/apikey. Add to `.env`:
   ```
   GEMINI_API_KEY=...
   ```
If both are set, **Gemini is tried first**, then OpenAI.

The following PDFs are referenced for lender policies:

- **Advantage++ Broker 2025.pdf** → Advantage+ Financing (non-trucking up to $75K)
- **Apex EF Broker Guidelines_082725.pdf** → Apex Commercial Capital
- **112025 Rates - STANDARD.pdf** → Falcon Equipment Finance
- **2025 Program Guidelines UPDATED.pdf** → Citizens Bank

To add or update a lender from a new PDF:

1. **Via UI**: Lenders → Add lender → upload PDF. The app calls `POST /api/lenders/parse-pdf` and pre-fills name, slug, and criteria; edit and save.
2. **Via API**: `POST /api/lenders/parse-pdf` with the PDF file to get suggested name, slug, and programs. Then `POST /api/lenders` with the parsed data (and any edits) to create the lender.
3. Optionally extract text locally: `python -c "from pdf_ingestion.parser import extract_text; print(extract_text('path/to/file.pdf'))"` and use `suggest_criteria_from_text(text)` for heuristic hints.

## API

- `GET /health` – health check
- `GET /api/applications` – list applications
- `POST /api/applications` – create application (body: camelCase OK)
- `GET /api/applications/{id}` – get application
- `POST /api/applications/{id}/submit` – submit application
- `POST /api/applications/{id}/underwrite` – run underwriting (match against all lenders)
- `GET /api/applications/{id}/runs` – list underwriting runs (latest run has `results`)
- `GET /api/underwriting/{run_id}` – get a single underwriting run
- `GET /api/lenders` – list lender policies
- `GET /api/lenders/{id}` – get lender policy
- `POST /api/lenders` – create lender (optional programs in body)
- `PATCH /api/lenders/{id}` – update lender (name, slug, description, sourceDocument)
- `POST /api/lenders/parse-pdf` – upload PDF; returns suggested name, slug, programs (criteria)
- `POST /api/lenders/{id}/programs` – add program to lender
- `PATCH /api/lenders/{id}/programs/{programId}` – update program
- `DELETE /api/lenders/{id}/programs/{programId}` – delete program

Responses use **camelCase** for frontend compatibility. Full request/response schemas: [http://localhost:3005/docs](http://localhost:3005/docs).

## Tests

Run matching-engine tests (from `backend/`):

```bash
python -m unittest tests.test_matching_engine -v
```
