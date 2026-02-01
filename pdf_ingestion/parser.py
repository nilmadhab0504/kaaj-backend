"""
Extract lender guideline details from PDFs and map to normalized credit policy criteria.

Extracts: FICO limits, PayNet limits, time in business, min/max loan amounts,
equipment types/age, geographic restrictions, industry exclusions, min revenue.

Usage:
  1. text = extract_text(pdf_path)
  2. criteria = parse_lender_criteria_from_text(text)
  3. Use criteria to create/update LenderProgram via API or seed script.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore

# US state codes for geographic extraction
US_STATE_CODES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia",
    "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt",
    "va", "wa", "wv", "wi", "wy", "dc",
}

#
# --- Optional LLM extraction (Gemini first, Groq fallback) ---
#

LLM_MAX_INPUT_CHARS = 24_000
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")

# Simple in-process cache so repeated parses of same PDF text
# don't re-bill / re-hit provider rate limits.
_LLM_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_LLM_CACHE_MAX = 32
_LLM_CACHE_TTL_SECONDS = 60 * 30  # 30 minutes

LLM_EXTRACTION_PROMPT = """You are extracting lender underwriting criteria from equipment finance guideline PDFs.

The input text may include multiple *programs/tiers* and often uses tables + headings. Common patterns:
- Tier tables with columns like: "Tier 1  Tier 2  Tier 3" and rows like "FICO", "TIB", "PayNet".
- Credit grade sections like: "A Rates", "A+ Rates", "B Rates", "C Rates" with ticket-size ranges,
  plus separate "A Rate Guidelines" / "B Rate Guidelines" bullets containing FICO/PayNet/TIB.
- Caps written as: "App-only up to $200,000", "ALL IN $75,000", "Net Financed $15,000 to $50,000".
- Geography written as: "does not lend in CA, NV, ND, VT" or "will no longer provide financing in California".
- Restrictions lists under headings like "Restrictions" or "Excluded Industry/Equipment List".

TASK
Extract **all lender programs/tiers** and normalize into a JSON object with this exact shape:

{
  "programs": [
    {
      "name": "A+" | "A" | "B" | "C" | "Tier 1" | "Tier 2" | "Standard Program" | "<use doc label>",
      "tier": "A+" | "A" | "B" | "C" | "1" | "2" | "3" | null,
      "criteria": {
        "fico": { "min_score": 680, "max_score": null } | null,
        "paynet": { "min_score": 60, "max_score": null } | null,
        "loan_amount": { "min_amount": 10000, "max_amount": 250000 },
        "time_in_business": { "min_years": 2 } | null,
        "geographic": { "allowed_states": ["TX"], "excluded_states": ["CA"] } | null,
        "industry": { "allowed_industries": null, "excluded_industries": ["Trucking", "Oil & Gas"] } | null,
        "equipment": { "allowed_types": null, "excluded_types": ["Aircrafts/Boats"], "max_equipment_age_years": 15 } | null,
        "min_revenue": 3000000 | null,
        "custom_rules": [
          { "name": "US Citizen", "description": "US Citizen only" }
        ] | null
      }
    }
  ]
}

IMPORTANT NORMALIZATION RULES (based on these lender PDFs)
- **Programs**:
  - If the PDF has multiple credit grades (A+, A, B, C, etc.), create one program per grade.
  - If the PDF has a Tier 1/2/3 table, create one program per tier.
  - If the PDF has *conditional tables* (e.g. "If no PayNet", "Corp only"), create separate programs
    with names like "Tier 1 (No PayNet)" / "Corp Only" and capture the condition in `custom_rules`.
- **Loan amount**:
  - Always output `loan_amount` with BOTH `min_amount` and `max_amount` as integers.
  - Use ticket-size ranges like "$10,000 - $49,999" as min/max.
  - Interpret "up to $X" / "≤$X" as max_amount = X. If no min is stated, set min_amount = 0.
  - Interpret "$X - $Y" as min_amount = X, max_amount = Y.
  - If the program truly has no loan amount, set {"min_amount": 0, "max_amount": 500000} and add a `custom_rules`
    note: "Loan amount not specified in document section".
- **Time in business**:
  - "TIB" means time in business in years. If expressed in months, convert to years by rounding up (e.g. 18 months -> 2).
  - If there are multiple TIB numbers for a program, use the strictest (highest minimum).
- **FICO vs PayNet sanity checks**:
  - Only set FICO values if clearly on the 300–850 scale.
  - PayNet (MasterScore) is typically 0–100. In some extracted PDF text, PayNet may appear as 3-digit values
    around 600–799 (e.g. 660, 685, 700) due to OCR/text-extraction artifacts.
    - If a 3-digit PayNet value appears consistently and dividing by 10 yields a plausible 0–100 score,
      convert it by dividing by 10 and rounding to the nearest integer (e.g. 660 → 66, 685 → 69, 700 → 70).
    - If conversion is not clearly supported by context, omit `paynet` and record the ambiguity in `custom_rules`.
- **Equipment age**:
  - Convert "Equipment over 15 years old" or "Max Age of Collateral = 5 years" to `max_equipment_age_years`.
- **Geography**:
  - Convert state lists to 2-letter codes and place them under excluded_states or allowed_states based on wording.
- **Industry vs equipment restrictions**:
  - Put clear business-type bans (e.g. "Gaming/Gambling", "Oil & Gas", "Adult Entertainment", "Restaurants") into `industry.excluded_industries`.
  - Put equipment bans (e.g. "Aircrafts/Boats", "Electric Vehicles", "Copiers") into `equipment.excluded_types`.
  - If ambiguous, prefer `custom_rules` rather than guessing.
- **Unmodeled rules**:
  - Add important constraints we don't model (e.g., "US Citizen only", "No BK in last 7 years", "No tax liens",
    "Trucking requires 5+ trucks", "Homeownership required") to `custom_rules` with short names + exact descriptions.

OUTPUT REQUIREMENTS
- Return ONLY the JSON object. No markdown, no commentary, no trailing commas.
"""


def _now() -> float:
    return time.time()


def _cache_get(key: str) -> Optional[list[dict[str, Any]]]:
    item = _LLM_CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if _now() - ts > _LLM_CACHE_TTL_SECONDS:
        _LLM_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: list[dict[str, Any]]) -> None:
    # Evict oldest if needed
    if len(_LLM_CACHE) >= _LLM_CACHE_MAX:
        oldest_key = min(_LLM_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _LLM_CACHE.pop(oldest_key, None)
    _LLM_CACHE[key] = (_now(), value)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _prepare_text_for_llm(text: str) -> str:
    """
    Condense raw PDF text into a high-signal subset while preserving tables/structure.
    This improves extraction quality and reduces token use.
    """
    # Normalize newlines & collapse excessive whitespace but keep line boundaries
    raw_lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    # Drop obvious page markers often produced by pdf text extraction
    cleaned_lines: list[str] = []
    seen = set()
    for ln in raw_lines:
        s = ln.strip()
        if not s:
            cleaned_lines.append("")
            continue
        if re.fullmatch(r"--\s*\d+\s*of\s*\d+\s*--", s, flags=re.IGNORECASE):
            continue
        if s.lower().startswith("subject to credit approval"):
            # Usually boilerplate repeated verbatim
            continue
        # De-dupe exact repeated lines (common in some extracted PDFs)
        if s in seen:
            continue
        seen.add(s)
        cleaned_lines.append(s)

    # Keyword-focused selection (plus a small window around matches)
    kw = re.compile(
        r"(tier\s*\d+|a\+?\s*rates|b\s*rates|c\s*rates|rate guidelines|guidelines|"
        r"fico|credit score|paynet|tib|time in business|years in business|"
        r"\$|net financed|app-only|all in|"
        r"excluded|restriction|does not lend|california|state|industry|equipment|max age|collateral|"
        r"revenue|sales|citizen|bankruptcy|tax lien|homeownership|trucking)",
        re.IGNORECASE,
    )
    keep: list[str] = []
    window = 2
    for i, ln in enumerate(cleaned_lines):
        if kw.search(ln):
            start = max(0, i - window)
            end = min(len(cleaned_lines), i + window + 1)
            for j in range(start, end):
                keep.append(cleaned_lines[j])

    # Always include some header + tail context
    head = "\n".join([l for l in cleaned_lines[:120] if l is not None])
    tail = "\n".join([l for l in cleaned_lines[-120:] if l is not None])
    mid = "\n".join(keep)

    combined = "\n\n".join([head, mid, tail]).strip()
    if len(combined) > LLM_MAX_INPUT_CHARS:
        combined = combined[:LLM_MAX_INPUT_CHARS]
    return combined


def _llm_call_gemini(text: str) -> str | None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(GEMINI_MODEL)
        resp = model.generate_content(
            f"{LLM_EXTRACTION_PROMPT}\n\n---\n\nDocument text:\n\n{text}",
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=4096,
            ),
        )
        content = resp.text if resp and resp.text else None
        return content.strip() if content else None
    except Exception:
        return None


def _llm_call_groq(text: str) -> str | None:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None
    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You extract structured data from documents. Respond only with valid JSON."},
                {"role": "user", "content": f"{LLM_EXTRACTION_PROMPT}\n\n---\n\nDocument text:\n\n{text}"},
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        content = resp.choices[0].message.content
        return content.strip() if content else None
    except Exception:
        return None


def _llm_parse_response(raw: str) -> list[dict[str, Any]] | None:
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if m:
            cleaned = m.group(1).strip()
    # If model added any leading/trailing text, attempt to extract the JSON object
    if not cleaned.startswith("{"):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1].strip()
    try:
        data = json.loads(cleaned)
        programs = data.get("programs")
        if not isinstance(programs, list) or not programs:
            return None
        return programs
    except json.JSONDecodeError:
        return None


def _llm_clean_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _llm_clean_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_llm_clean_none(x) for x in obj]
    return obj


def _llm_normalize_programs(programs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    default_loan = {"min_amount": 5000, "max_amount": 500_000}
    for p in programs:
        criteria = dict(p.get("criteria") or {})
        loan_amt = criteria.get("loan_amount") or criteria.get("loanAmount") or {}
        if not isinstance(loan_amt, dict):
            loan_amt = {}
        min_a = loan_amt.get("min_amount") or loan_amt.get("minAmount")
        max_a = loan_amt.get("max_amount") or loan_amt.get("maxAmount")
        if min_a is None and max_a is None:
            criteria["loan_amount"] = default_loan
        else:
            criteria["loan_amount"] = {
                "min_amount": int(min_a) if min_a is not None else default_loan["min_amount"],
                "max_amount": int(max_a) if max_a is not None else default_loan["max_amount"],
            }
        criteria = _llm_clean_none(criteria)
        out.append(
            {
                "name": str(p.get("name") or "Standard Program"),
                "tier": str(p["tier"]) if p.get("tier") is not None else None,
                "criteria": criteria,
            }
        )
    return out


def _extract_programs_with_llm(text: str) -> list[dict[str, Any]] | None:
    """
    LLM path (Gemini first, Groq fallback) with caching and condensed context.
    Returns normalized list[{name,tier,criteria}] or None.
    """
    cache_key = _hash_text(text)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    prepared = _prepare_text_for_llm(text)

    # Per request: Gemini first, Groq fallback
    raw = _llm_call_gemini(prepared)
    if raw is None:
        raw = _llm_call_groq(prepared)
    if raw is None:
        return None
    programs = _llm_parse_response(raw)
    if programs is None:
        return None
    normalized = _llm_normalize_programs(programs)
    _cache_put(cache_key, normalized)
    return normalized


def extract_text(pdf_path: str | Path) -> str:
    """Extract all text from a PDF file."""
    if pdfplumber is None:
        raise ImportError("Install pdfplumber: pip install pdfplumber")
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    text_parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n\n".join(text_parts)


def _find_numbers_in_range(text: str, lo: int, hi: int) -> list[int]:
    """Find all integers in text that fall within [lo, hi]."""
    nums: list[int] = []
    for m in re.finditer(r"\b(\d{1,4})\b", text):
        try:
            n = int(m.group(1))
            if lo <= n <= hi:
                nums.append(n)
        except ValueError:
            pass
    return nums


def _extract_fico(text: str) -> dict[str, Any] | None:
    """
    Extract FICO min/max from text.

    Prefer numbers *near the token* \"FICO\" to avoid mixing with PayNet or other scores on the same line.
    Falls back to broader heuristics if no keyword-adjacent numbers are found.
    """
    lower = text.lower()
    if "fico" not in lower and "credit score" not in lower and "minimum score" not in lower:
        return None
    lines = text.split("\n")

    # First: extract numbers adjacent to "FICO" token
    near: list[int] = []
    for line in lines:
        ll = line.lower()
        if "fico" not in ll:
            continue
        for m in re.finditer(r"fico\D{0,20}(\d{3})", ll, flags=re.IGNORECASE):
            n = int(m.group(1))
            if 300 <= n <= 850:
                near.append(n)
        for m in re.finditer(r"(\d{3})\D{0,20}fico", ll, flags=re.IGNORECASE):
            n = int(m.group(1))
            if 300 <= n <= 850:
                near.append(n)
    if near:
        return {"min_score": min(near), "max_score": max(near) if len(near) > 1 else None}

    # Fallback: any score-like numbers in lines mentioning FICO/score
    fico_lines = " ".join(
        L for L in lines
        if "fico" in L.lower() or "credit score" in L.lower() or "min score" in L.lower() or "minimum score" in L.lower()
    )
    search = fico_lines or lower
    nums = _find_numbers_in_range(search, 300, 850) or _find_numbers_in_range(lower, 300, 850)
    if not nums:
        return None
    return {"min_score": min(nums), "max_score": max(nums) if len(nums) > 1 else None}


def _extract_paynet(text: str) -> dict[str, Any] | None:
    """
    Extract PayNet score min/max.

    Preferred scale is 0–100 (PayNet MasterScore). Some PDF text extractions/OCR can produce
    3-digit values around 600–799 for PayNet tables; when encountered, we attempt a safe
    conversion by dividing by 10 (e.g. 685 -> 69) if it yields plausible 0–100 values.
    """
    lower = text.lower()
    if "paynet" not in lower and "pay net" not in lower:
        return None
    lines = text.split("\n")
    paynet_lines = " ".join(L for L in lines if "paynet" in L.lower() or "pay net" in L.lower())
    search = paynet_lines or lower

    # Prefer numbers adjacent to "paynet"/"pay net" to avoid mixing with FICO on same line.
    # IMPORTANT: In many bullets the pattern is "650+ PayNet, 670+ FICO".
    # We therefore prioritize "number BEFORE paynet" matches; only use "after paynet"
    # matches when no "before" matches exist.
    before: list[int] = []
    after: list[int] = []
    for line in lines:
        ll = line.lower()
        if "paynet" not in ll and "pay net" not in ll:
            continue
        for m in re.finditer(r"(\d{1,4})\D{0,20}(?:paynet|pay\s+net)", ll, flags=re.IGNORECASE):
            before.append(int(m.group(1)))
        for m in re.finditer(r"(?:paynet|pay\s+net)\D{0,12}(\d{1,4})", ll, flags=re.IGNORECASE):
            after.append(int(m.group(1)))

    near_raw = before if before else after

    nums = [n for n in near_raw if 0 <= n <= 100]
    if nums:
        return {"min_score": min(nums), "max_score": max(nums) if len(nums) > 1 else None}

    # Fallback: sometimes PayNet appears as 660/685/700 in extracted text; try converting /10 (floor)
    nums_3 = [n for n in near_raw if 600 <= n <= 799]
    if not nums_3:
        nums_3 = _find_numbers_in_range(search, 600, 799)
    if not nums_3:
        return None
    converted = [int(n // 10) for n in nums_3 if 0 <= int(n // 10) <= 100]
    if not converted:
        return None
    return {"min_score": min(converted), "max_score": max(converted) if len(converted) > 1 else None}


def _extract_loan_amounts(text: str) -> dict[str, Any] | None:
    """Extract min/max loan amount. Look for $ amounts, 'loan size', 'ticket', 'min'/'max' with numbers/K/M."""
    lower = text.lower()
    # Dollar amounts: $75,000 or 75K or 1M
    dollar_pattern = r"\$?\s*([\d,]+(?:\.[\d]+)?)\s*(K|M|MM)?\b"
    matches = list(re.finditer(dollar_pattern, text, re.IGNORECASE))
    amounts: list[int] = []
    for m in matches:
        num_str = m.group(1).replace(",", "")
        suffix = (m.group(2) or "").upper()
        try:
            val = float(num_str)
            if suffix == "K":
                val *= 1000
            elif suffix in ("M", "MM"):
                val *= 1_000_000
            if 1000 <= val <= 100_000_000:
                amounts.append(int(val))
        except ValueError:
            pass
    # Also look for "min" / "max" with numbers on same or next line
    min_max_pattern = r"(?:min(?:imum)?|max(?:imum)?)\s*[:\s]*\$?\s*([\d,]+)\s*(K|M)?"
    for m in re.finditer(min_max_pattern, lower, re.IGNORECASE):
        try:
            val = float(m.group(1).replace(",", ""))
            if m.group(2):
                val *= 1000 if (m.group(2) or "").upper() == "K" else 1_000_000
            if 1000 <= val <= 100_000_000:
                amounts.append(int(val))
        except ValueError:
            pass
    if not amounts:
        return None
    # If phrasing suggests a cap ("up to"), treat as max-only
    if len(amounts) == 1 and ("up to" in lower or "≤" in text):
        return {"min_amount": 0, "max_amount": amounts[0]}
    return {"min_amount": min(amounts), "max_amount": max(amounts)}


def _extract_time_in_business(text: str) -> dict[str, Any] | None:
    """Extract minimum time in business (years). Look for TIB, 'time in business', 'years in business' + number."""
    lower = text.lower()
    triggers = ["time in business", "years in business", "tib", "min. years", "minimum years", "years in operation"]
    if not any(t in lower for t in triggers):
        return None
    lines = text.split("\n")
    for line in lines:
        line_lower = line.lower()
        if not any(t in line_lower for t in triggers):
            continue
        nums = _find_numbers_in_range(line, 0, 50)
        if nums:
            return {"min_years": min(nums)}
    nums = _find_numbers_in_range(lower, 1, 50)
    if nums:
        return {"min_years": min(nums)}
    return None


def _extract_geographic(text: str) -> dict[str, Any] | None:
    """Extract allowed/excluded states. Look for 2-letter state codes and context (excluded, approved, etc.)."""
    # Find phrases like "excluded states", "no [state]", "approved states", "states: CA, TX"
    excluded: list[str] = []
    allowed: list[str] = []
    # Two-letter state codes in text (standalone or in lists)
    for m in re.finditer(r"\b([A-Za-z]{2})\b", text):
        code = m.group(1).lower()
        if code in US_STATE_CODES:
            # Context: check surrounding words
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 80)
            context = text[start:end].lower()
            if "exclud" in context or "no " in context or "restrict" in context or "prohibit" in context:
                if code not in excluded:
                    excluded.append(code.upper())
            elif "allow" in context or "approv" in context or "only" in context or "state list" in context:
                if code not in allowed:
                    allowed.append(code.upper())
    if not excluded and not allowed:
        return None
    out: dict[str, Any] = {}
    if excluded:
        out["excluded_states"] = excluded
    if allowed:
        out["allowed_states"] = allowed
    return out if out else None


def _extract_industry(text: str) -> dict[str, Any] | None:
    """Extract industry exclusions/allowed. Look for 'trucking', 'excluded industries', SIC, NAICS, etc."""
    lower = text.lower()
    excluded: list[str] = []
    allowed: list[str] = []
    # Common exclusions in equipment finance
    if "trucking" in lower or "over-the-road" in lower:
        excluded.append("Trucking")
    if "truck" in lower and "equipment" not in lower and "Trucking" not in excluded:
        excluded.append("Trucking")
    # Phrases like "excluded industries", "restricted industries"
    excluded_phrases = ["excluded industr", "restricted industr", "ineligible industr", "no trucking"]
    for phrase in excluded_phrases:
        if phrase in lower:
            # Try to find industry names on same line
            for line in text.split("\n"):
                if phrase[:10] in line.lower():
                    # Simple: add known ones
                    if "trucking" in line.lower() and "Trucking" not in excluded:
                        excluded.append("Trucking")
    if "allowed industr" in lower or "approved industr" in lower:
        # Could parse list; for now leave allowed empty if we only found excluded
        pass
    if not excluded and not allowed:
        return None
    out: dict[str, Any] = {}
    if excluded:
        out["excluded_industries"] = excluded
    if allowed:
        out["allowed_industries"] = allowed
    return out if out else None


def _extract_equipment(text: str) -> dict[str, Any] | None:
    """Extract equipment restrictions: allowed/excluded types, max equipment age."""
    out: dict[str, Any] = {}
    lower = text.lower()
    # Max equipment age: "max age", "equipment age", "years old" + number
    age_patterns = [
        r"max(?:imum)?\s*(?:equipment)?\s*age\s*[:\s]*(\d+)\s*years?",
        r"equipment\s*(?:max)?\s*age\s*[:\s]*(\d+)",
        r"(\d+)\s*years?\s*(?:old|max|maximum)",
    ]
    for pat in age_patterns:
        m = re.search(pat, lower, re.IGNORECASE)
        if m:
            try:
                n = int(m.group(1))
                if 1 <= n <= 50:
                    out["max_equipment_age_years"] = n
                    break
            except (ValueError, IndexError):
                pass
    # Excluded equipment types: "no semi", "excluded: ...", "truck chassis"
    excluded_types: list[str] = []
    if "excluded equipment" in lower or "ineligible equipment" in lower:
        for line in text.split("\n"):
            if "excluded" in line.lower() or "ineligible" in line.lower():
                # Simple: split on comma and take capitalized words
                for part in re.split(r"[,;]", line):
                    word = part.strip()
                    if len(word) > 2 and word[0].isupper():
                        excluded_types.append(word)
    if "no semi" in lower or "no tractor" in lower:
        excluded_types.append("Semi/Tractor")
    if excluded_types:
        out["excluded_types"] = excluded_types[:10]  # limit
    if not out:
        return None
    return out


def _extract_min_revenue(text: str) -> int | None:
    """Extract minimum annual revenue if mentioned."""
    lower = text.lower()
    if "revenue" not in lower and "sales" not in lower:
        return None
    # Patterns: "min revenue $500,000", "annual revenue of at least..."
    patterns = [
        r"(?:min(?:imum)?|annual)\s*revenue\s*[:\s]*\$?\s*([\d,]+)\s*(K|M)?",
        r"revenue\s*(?:of\s*)?(?:at\s*least|minimum)\s*\$?\s*([\d,]+)\s*(K|M)?",
        r"\$([\d,]+)\s*(K|M)?\s*(?:min(?:imum)?\s*)?(?:annual\s*)?revenue",
    ]
    for pat in patterns:
        m = re.search(pat, lower, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1).replace(",", ""))
                suffix = (m.group(2) if m.lastindex >= 2 else "") or ""
                if suffix.upper() == "K":
                    val *= 1000
                elif suffix.upper() == "M":
                    val *= 1_000_000
                if val >= 1000:
                    return int(val)
            except (ValueError, IndexError):
                pass
    return None


def _extract_tier_table_programs(text: str) -> list[dict[str, Any]] | None:
    """
    Deterministically extract Tier 1/2/3-style *tables* like:
      Tier 1   Tier 2   Tier 3
      FICO     725      710      700
      TIB      3        3        2
      Paynet   685      675      665

    This is common in credit-box PDFs. Returns None if no usable table found.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None

    global_crit = _extract_criteria_from_section(text)

    def default_program(tier: str, suffix: str | None = None) -> dict[str, Any]:
        name = f"Tier {tier}" + (f" ({suffix})" if suffix else "")
        crit: dict[str, Any] = {"loan_amount": global_crit.get("loan_amount", {"min_amount": 5000, "max_amount": 500_000})}
        # Carry global restrictions if present
        for k in ("geographic", "industry", "equipment", "min_revenue"):
            if global_crit.get(k) is not None:
                crit[k] = global_crit[k]
        if suffix:
            crit["custom_rules"] = [{"name": "Condition", "description": suffix}]
        return {"name": name, "tier": tier, "criteria": crit}

    programs: dict[str, dict[str, Any]] = {}

    def parse_row_numbers(row: str, kind: str) -> list[int]:
        if kind == "fico":
            return _find_numbers_in_range(row, 300, 850)
        if kind == "tib":
            return _find_numbers_in_range(row, 0, 50)
        if kind == "paynet":
            n = _find_numbers_in_range(row, 0, 100)
            if n:
                return n
            n3 = _find_numbers_in_range(row, 600, 799)
            return [int(x // 10) for x in n3]
        return []

    for i, line in enumerate(lines):
        if not (re.search(r"\bTier\s*1\b", line, re.IGNORECASE) and re.search(r"\bTier\s*2\b", line, re.IGNORECASE)):
            continue

        tiers = []
        for t in re.findall(r"Tier\s*(\d+)", line, flags=re.IGNORECASE):
            if t not in tiers:
                tiers.append(t)
        if len(tiers) < 2:
            continue

        # Look back for conditional context ("If no Paynet", "Corp only")
        ctx = " ".join(lines[max(0, i - 3) : i]).lower()
        suffix = None
        if "no paynet" in ctx:
            suffix = "No PayNet"
        elif "corp only" in ctx or "corporation only" in ctx:
            suffix = "Corp Only"

        for t in tiers:
            programs.setdefault(t, default_program(t, suffix=suffix))

        # Parse a small window after the header for FICO/TIB/PayNet rows
        j = i + 1
        while j < len(lines) and j < i + 12:
            row = lines[j]
            if j != i and re.search(r"\bTier\s*1\b", row, re.IGNORECASE) and re.search(r"\bTier\s*2\b", row, re.IGNORECASE):
                break
            m = re.match(r"^(fico|tib|paynet)\b", row, flags=re.IGNORECASE)
            if m:
                kind = m.group(1).lower()
                nums = parse_row_numbers(row, kind)
                if len(nums) >= len(tiers):
                    nums = nums[: len(tiers)]
                    for idx, t in enumerate(tiers):
                        prog = programs[t]
                        crit = prog["criteria"]
                        if kind == "fico":
                            crit["fico"] = {"min_score": int(nums[idx])}
                        elif kind == "tib":
                            crit["time_in_business"] = {"min_years": int(nums[idx])}
                        elif kind == "paynet":
                            crit["paynet"] = {"min_score": int(nums[idx])}
            j += 1

    if len(programs) >= 2:
        # Only return if we actually extracted something besides loan_amount
        extracted_any = any(
            any(k in p["criteria"] for k in ("fico", "paynet", "time_in_business"))
            for p in programs.values()
        )
        if extracted_any:
            return list(programs.values())
    return None


def _extract_rate_guideline_programs(text: str) -> list[dict[str, Any]] | None:
    """
    Extract A/A+/B/C... programs from headings like:
      A Rate Guidelines - ...
      B Rate Guidelines - ...
      C Rate Guidelines - ...
    Returns None if not found.
    """
    # Use multiline anchors (text extraction usually preserves line breaks around headings)
    pattern = re.compile(r"(?im)^\s*([A-D](?:\+)?)\s*Rate Guidelines\b.*$", re.IGNORECASE)
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        return None

    global_crit = _extract_criteria_from_section(text)
    programs: list[dict[str, Any]] = []

    for idx, m in enumerate(matches):
        grade = (m.group(1) or "").upper()
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        section = text[start:end]

        crit = _extract_criteria_from_section(section)
        # Merge global restrictions into each grade program
        for k in ("geographic", "industry", "equipment", "min_revenue"):
            if crit.get(k) is None and global_crit.get(k) is not None:
                crit[k] = global_crit[k]

        programs.append({"name": grade, "tier": grade, "criteria": crit})

    return programs if programs else None


def _split_into_tier_sections(text: str) -> list[tuple[str, str]]:
    """
    Split text into (program_name, section_text) pairs by detecting tier/program headers.
    Returns list of (name, text) e.g. [("Tier 1", "FICO 680+ ..."), ("Tier 2", "FICO 650+ ...")].
    """
    # Find all tier/program header positions: "Tier 1", "Tier 2", "Program A", "Credit Box 1", "Level 1"
    header_pattern = re.compile(
        r"(?:^|\n)\s*"
        r"((?:Tier|TIER)\s*(\d+)|(?:Program|PROGRAM)\s+([A-Za-z])|(?:Credit\s+Box|CreditBox)\s*(\d+)|(?:Level|LEVEL)\s*(\d+))"
        r"[:\s\-]*",
        re.IGNORECASE,
    )
    matches = list(header_pattern.finditer(text))
    if not matches:
        return []

    result: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        tier_num = m.group(2)
        prog_letter = m.group(3)
        box_num = m.group(4)
        level_num = m.group(5)
        if tier_num:
            name = f"Tier {tier_num}"
        elif prog_letter:
            name = f"Program {prog_letter.upper()}"
        elif box_num:
            name = f"Credit Box {box_num}"
        elif level_num:
            name = f"Level {level_num}"
        else:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        result.append((name, body))
    return result


def _extract_criteria_from_section(section_text: str) -> dict[str, Any]:
    """Extract criteria from a single section of text."""
    criteria: dict[str, Any] = {}
    fico = _extract_fico(section_text)
    if fico:
        criteria["fico"] = fico
    paynet = _extract_paynet(section_text)
    if paynet:
        criteria["paynet"] = paynet
    loan_amount = _extract_loan_amounts(section_text)
    if loan_amount:
        criteria["loan_amount"] = loan_amount
    else:
        criteria["loan_amount"] = {"min_amount": 5000, "max_amount": 500_000}
    tib = _extract_time_in_business(section_text)
    if tib:
        criteria["time_in_business"] = tib
    geo = _extract_geographic(section_text)
    if geo:
        criteria["geographic"] = geo
    ind = _extract_industry(section_text)
    if ind:
        criteria["industry"] = ind
    equip = _extract_equipment(section_text)
    if equip:
        criteria["equipment"] = equip
    min_rev = _extract_min_revenue(section_text)
    if min_rev is not None:
        criteria["min_revenue"] = min_rev
    return criteria


def parse_lender_programs_from_text(text: str, use_llm: bool = True) -> list[dict[str, Any]]:
    """
    Parse full text from a lender guideline PDF into a list of programs (tiers).
    Each program has: name, tier, criteria.
    When use_llm=True and GROQ_API_KEY or GEMINI_API_KEY is set, uses LLM for extraction (more accurate).
    Otherwise falls back to regex-based parsing.
    """
    if use_llm:
        try:
            programs = _extract_programs_with_llm(text)
            if programs:
                return programs
        except Exception:
            # Any LLM failure falls back to deterministic regex parsing
            pass

    # Deterministic (non-LLM) fast paths for common PDF structures
    tier_table_programs = _extract_tier_table_programs(text)
    if tier_table_programs:
        return tier_table_programs

    rate_programs = _extract_rate_guideline_programs(text)
    if rate_programs:
        return rate_programs

    sections = _split_into_tier_sections(text)
    if not sections:
        # No tier sections found: treat whole text as one program
        criteria = _extract_criteria_from_section(text)
        return [{"name": "Standard Program", "tier": None, "criteria": criteria}]

    # Extract tier-specific criteria from each section; merge with global defaults
    global_criteria = _extract_criteria_from_section(text)
    programs: list[dict[str, Any]] = []
    for name, section_text in sections:
        section_criteria = _extract_criteria_from_section(section_text)
        # Merge: section overrides, global fills gaps
        merged: dict[str, Any] = {}
        for key in ("geographic", "industry", "equipment", "min_revenue"):
            val = section_criteria.get(key) or global_criteria.get(key)
            if val is not None:
                merged[key] = val
        for key in ("fico", "paynet", "loan_amount", "time_in_business"):
            val = section_criteria.get(key) or global_criteria.get(key)
            if val is not None:
                merged[key] = val
        if "loan_amount" not in merged or not merged["loan_amount"].get("min_amount"):
            merged["loan_amount"] = global_criteria.get("loan_amount", {"min_amount": 5000, "max_amount": 500_000})
        # Extract tier label from name (e.g. "Tier 1" -> "1", "Program A" -> "A")
        tier_m = re.search(r"(?:Tier|Level)\s*(\d+)|(?:Program)\s+([A-Za-z])", name, re.IGNORECASE)
        tier_val = None
        if tier_m:
            tier_val = (tier_m.group(1) or tier_m.group(2) or "").upper() or None
        programs.append({"name": name, "tier": tier_val, "criteria": merged})
    return programs


def parse_lender_criteria_from_text(text: str) -> dict[str, Any]:
    """
    Parse full text from a lender guideline PDF into normalized criteria (snake_case).
    Returns a single criteria dict for backward compatibility.
    For multiple programs/tiers, use parse_lender_programs_from_text instead.
    """
    programs = parse_lender_programs_from_text(text)
    return programs[0]["criteria"]


def suggest_criteria_from_text(text: str) -> dict[str, Any]:
    """
    Alias for parse_lender_criteria_from_text for backward compatibility.
    Heuristic extraction of criteria from raw text; review output before use.
    """
    return parse_lender_criteria_from_text(text)


def parse_lender_criteria_from_pdf(pdf_path: str | Path) -> dict[str, Any]:
    """
    Extract text from PDF and parse into normalized lender criteria (single program).
    For multiple programs/tiers, use parse_lender_programs_from_pdf.
    """
    text = extract_text(pdf_path)
    return parse_lender_criteria_from_text(text)


def parse_lender_programs_from_pdf(
    pdf_path: str | Path, use_llm: bool = True
) -> list[dict[str, Any]]:
    """
    Extract text from PDF and parse into a list of programs (tiers).
    Each item: {"name": str, "tier": str|None, "criteria": dict}.
    Uses LLM (Groq/Gemini free tier) when API keys are set; otherwise regex parsing.
    """
    text = extract_text(pdf_path)
    return parse_lender_programs_from_text(text, use_llm=use_llm)
