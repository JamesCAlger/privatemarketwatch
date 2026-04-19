"""LLM extraction of structured fields from BDC investment identifiers.

Uses GPT-4o-mini to decompose raw BDC ``investment_identifier`` strings into
structured fields (company name, instrument type, industry, reference rate,
basis spread, maturity date).  Results are cached in a CSV lookup table for
resumability and applied to unified holdings via DuckDB LEFT JOIN.

Usage::

    python -m pipeline.main --unified --extract

Requires ``OPENAI_API_KEY`` in ``.env`` (or environment variable).
"""

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import duckdb
import pandas as pd

from pipeline.config import (
    IDENTIFIER_EXTRACTION_LOOKUP_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load .env for OPENAI_API_KEY
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; key must be in env already

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATCH_SIZE = 50
MAX_TOKENS = 16384
API_DELAY_SECONDS = 0.5
MAX_WORKERS = 10  # concurrent API calls
CACHE_SAVE_INTERVAL = 50  # save cache every N batches

_SYSTEM_PROMPT = """\
You extract structured data from BDC (Business Development Company) investment \
identifier strings found in SEC XBRL filings.

These identifiers come in several format families:

1. Pipe-delimited: "Senior Secured Loans | First Lien | Acme Corp | Technology"
   Structure: Type | Industry | Company | optional extra segments

2. Structured comma: "Non-Control/Non-Affiliate, Senior Secured Loan, First Lien \
Term Loan, Acme Corp, Inc., Technology"
   Structure: Affiliation, Instrument Category, Instrument Detail, Company, Industry

3. Unstructured/concatenated: "Acme Corp Inc First Lien Senior Secured Term Loan \
SOFR + 5.25% 12/15/2028"
   Everything concatenated with spaces, no clear delimiters.

4. Short/clean: "Acme Corp, Inc. - First Lien Term Loan"
   Company - Instrument, simple dash-separated.

For each identifier, extract a JSON object with these fields:
{
  "company_name": "...",
  "instrument_description": "...",
  "industry": "...",
  "reference_rate": "...",
  "basis_spread_pct": ...,
  "maturity_date": "...",
  "is_aggregate": false
}

Rules:
- company_name: The operating company name ONLY. Exclude affiliation labels \
(Non-Control, Affiliate), instrument types (First Lien, Term Loan), industry \
labels (Technology, Healthcare), and financial terms (SOFR + 5.25%).
  Include suffixes like Inc., LLC, Corp., Ltd., L.P.
- instrument_description: The instrument type/description (e.g., "First Lien \
Senior Secured Term Loan", "Revolving Credit Facility", "Common Equity").
  Null if not discernible.
- industry: The industry/sector if present in the identifier (e.g., "Technology", \
"Healthcare", "Aerospace & Defense"). Null if not present.
- reference_rate: SOFR, PRIME, LIBOR, or similar reference rate name. Null if absent.
- basis_spread_pct: Numeric spread in percentage points (e.g., 5.25 for \
"SOFR + 5.25%"). Null if absent.
- maturity_date: In YYYY-MM-DD format if a date is present. Null if absent.
- is_aggregate: True ONLY if this is a subtotal line, section header, or \
category label -- not an actual holding. Examples: "Total Senior Secured First Lien", \
"Debt Investments", "Total Investments at Fair Value".

Respond with a JSON object containing a single key "results" whose value is an \
array of objects. Each object must include an "id" field matching the number in \
the input list.\
"""

# Lookup CSV columns
_LOOKUP_COLUMNS = [
    "bdc_investment_identifier",
    "extracted_company_name",
    "extracted_instrument_description",
    "extracted_industry",
    "extracted_reference_rate",
    "extracted_basis_spread",
    "extracted_maturity_date",
    "extracted_is_aggregate",
    "extraction_timestamp",
]


# ---------------------------------------------------------------------------
# 1. Identify candidates
# ---------------------------------------------------------------------------

_JUNK_ID_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}(\s*\(.\))?|.{0,3})$"
)


def _get_candidates(unified_df: pd.DataFrame) -> pd.Series:
    """Return all distinct non-empty BDC investment identifiers.

    Runs on ALL BDC rows (not just parser-failed ones) so the LLM can
    extract industry, reference rate, basis spread, and maturity date
    that are embedded in the raw identifier string but not captured by
    the rule-based parser.

    Filters out junk identifiers (bare dates, <=3-char strings) that
    carry no extractable information.
    """
    bdc_mask = unified_df["source"] == "bdc"
    id_col = unified_df["bdc_investment_identifier"].fillna("")
    has_id = bdc_mask & (id_col != "")

    candidates = unified_df.loc[has_id, "bdc_investment_identifier"].unique()
    # Filter junk: bare dates (MM/DD/YYYY) and very short strings
    candidates = [c for c in candidates if not _JUNK_ID_RE.match(c)]
    return pd.Series(sorted(candidates))


# ---------------------------------------------------------------------------
# 2. Cache management
# ---------------------------------------------------------------------------

def _load_cache() -> pd.DataFrame:
    """Load existing lookup CSV, or return empty DataFrame."""
    if IDENTIFIER_EXTRACTION_LOOKUP_FILE.exists():
        df = pd.read_csv(
            IDENTIFIER_EXTRACTION_LOOKUP_FILE, dtype=str,
        )
        logger.info("  Loaded %d cached extractions from %s",
                     len(df), IDENTIFIER_EXTRACTION_LOOKUP_FILE.name)
        return df
    return pd.DataFrame(columns=_LOOKUP_COLUMNS)


def _save_cache(cache_df: pd.DataFrame) -> None:
    """Save lookup DataFrame to CSV."""
    cache_df.to_csv(IDENTIFIER_EXTRACTION_LOOKUP_FILE, index=False)


# ---------------------------------------------------------------------------
# 3. API batching
# ---------------------------------------------------------------------------

def _build_batch_prompt(identifiers: list[str]) -> str:
    """Build a numbered-list prompt for a batch of identifiers."""
    lines = []
    for i, ident in enumerate(identifiers, start=1):
        lines.append(f"{i}. {ident}")
    return (
        "Extract structured fields from each identifier below. "
        "Respond with a JSON object: {\"results\": [...]}.\n\n"
        + "\n".join(lines)
    )


def _call_openai_batch(
    identifiers: list[str],
    client: object,
) -> list[dict]:
    """Call GPT-4o-mini for a single batch, return parsed results.

    Returns a list of dicts (one per identifier, keyed by 1-based ``id``).
    On failure, returns an empty list.
    """
    prompt = _build_batch_prompt(identifiers)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=MAX_TOKENS,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        parsed = json.loads(text)
        results = parsed.get("results", parsed if isinstance(parsed, list) else [])
        if not isinstance(results, list):
            results = [results]
        return results
    except Exception as exc:
        logger.error("  OpenAI API call failed: %s", exc)
        return []


def _parse_batch_results(
    identifiers: list[str],
    results: list[dict],
) -> list[dict]:
    """Convert API results into lookup rows, one per identifier."""
    # Build id -> result map
    result_map = {}
    for item in results:
        rid = item.get("id")
        if rid is not None:
            result_map[int(rid)] = item

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for i, ident in enumerate(identifiers, start=1):
        item = result_map.get(i, {})
        rows.append({
            "bdc_investment_identifier": ident,
            "extracted_company_name": str(item.get("company_name") or ""),
            "extracted_instrument_description": str(
                item.get("instrument_description") or ""
            ),
            "extracted_industry": str(item.get("industry") or ""),
            "extracted_reference_rate": str(item.get("reference_rate") or ""),
            "extracted_basis_spread": str(item.get("basis_spread_pct") or ""),
            "extracted_maturity_date": str(item.get("maturity_date") or ""),
            "extracted_is_aggregate": str(
                bool(item.get("is_aggregate", False))
            ),
            "extraction_timestamp": now,
        })
    return rows


# ---------------------------------------------------------------------------
# 4. Apply enrichment via DuckDB
# ---------------------------------------------------------------------------

def _apply_enrichment(
    unified_df: pd.DataFrame,
    lookup_df: pd.DataFrame,
) -> pd.DataFrame:
    """LEFT JOIN lookup onto unified holdings, COALESCE to fill gaps.

    Only overwrites ``issuer_name`` when the current value equals the raw
    identifier (i.e., the rule-based parser failed).  Other fields use
    COALESCE to preserve existing non-empty values.
    """
    if lookup_df.empty:
        return unified_df

    con = duckdb.connect()
    con.register("holdings", unified_df)
    con.register("extraction_lookup", lookup_df)

    sql = """
    SELECT
        h.source, h.cik, h.entity_name, h.accession_number,
        h.filing_date, h.report_date,
        -- issuer_name: only overwrite when parser failed
        CASE
            WHEN h.source = 'bdc'
                 AND CAST(h.issuer_name AS VARCHAR) = CAST(h.bdc_investment_identifier AS VARCHAR)
                 AND e.extracted_company_name IS NOT NULL
                 AND e.extracted_company_name != ''
            THEN e.extracted_company_name
            ELSE h.issuer_name
        END AS issuer_name,
        -- instrument_description: fill if empty
        CASE
            WHEN (h.instrument_description IS NULL OR CAST(h.instrument_description AS VARCHAR) = '')
                 AND e.extracted_instrument_description IS NOT NULL
                 AND e.extracted_instrument_description != ''
            THEN e.extracted_instrument_description
            ELSE h.instrument_description
        END AS instrument_description,
        h.cusip, h.isin, h.lei, h.ticker,
        h.fair_value, h.cost, h.pct_of_net_assets,
        h.shares_held, h.principal_amount,
        h.asset_category, h.issuer_category, h.index_classification,
        h.fair_value_level,
        h.interest_rate,
        -- basis_spread: fill if null/empty/zero (cast both sides to VARCHAR)
        CASE
            WHEN (h.basis_spread IS NULL
                  OR CAST(h.basis_spread AS VARCHAR) = ''
                  OR TRY_CAST(h.basis_spread AS DOUBLE) = 0
                  OR TRY_CAST(h.basis_spread AS DOUBLE) IS NULL)
                 AND e.extracted_basis_spread IS NOT NULL
                 AND e.extracted_basis_spread != ''
                 AND e.extracted_basis_spread != 'None'
            THEN CAST(e.extracted_basis_spread AS VARCHAR)
            ELSE CAST(h.basis_spread AS VARCHAR)
        END AS basis_spread,
        -- reference_rate_type: fill if empty
        CASE
            WHEN (h.reference_rate_type IS NULL OR CAST(h.reference_rate_type AS VARCHAR) = '')
                 AND e.extracted_reference_rate IS NOT NULL
                 AND e.extracted_reference_rate != ''
                 AND e.extracted_reference_rate != 'None'
            THEN e.extracted_reference_rate
            ELSE h.reference_rate_type
        END AS reference_rate_type,
        h.coupon_type, h.pik_rate,
        -- maturity_date: fill if empty
        CASE
            WHEN (h.maturity_date IS NULL OR CAST(h.maturity_date AS VARCHAR) = '')
                 AND e.extracted_maturity_date IS NOT NULL
                 AND e.extracted_maturity_date != ''
                 AND e.extracted_maturity_date != 'None'
            THEN e.extracted_maturity_date
            ELSE h.maturity_date
        END AS maturity_date,
        h.bdc_investment_identifier, h.bdc_form_type, h.bdc_dimensions_raw,
        h.bdc_unrealized_gain_loss,
        h.nport_holding_id, h.nport_series_name, h.nport_series_id,
        h.nport_asset_cat, h.nport_issuer_type, h.nport_payoff_profile,
        h.nport_investment_country, h.nport_is_restricted, h.nport_quarter,
        h.nport_is_default, h.nport_are_interest_payments_in_arrears,
        h.nport_is_paid_in_kind, h.nport_currency_code,
        h.nport_liquidity_classification,
        h.entity_id, h.canonical_name,
        -- extracted_industry: fill from lookup
        CASE
            WHEN (h.extracted_industry IS NULL OR CAST(h.extracted_industry AS VARCHAR) = '')
                 AND e.extracted_industry IS NOT NULL
                 AND e.extracted_industry != ''
                 AND e.extracted_industry != 'None'
            THEN e.extracted_industry
            ELSE h.extracted_industry
        END AS extracted_industry,
        h.position_id
    FROM holdings h
    LEFT JOIN extraction_lookup e
      ON CAST(h.bdc_investment_identifier AS VARCHAR)
       = CAST(e.bdc_investment_identifier AS VARCHAR)
    """

    result = con.execute(sql).fetchdf()
    con.close()

    return result


# ---------------------------------------------------------------------------
# 5. Main entry point
# ---------------------------------------------------------------------------

def extract_identifiers(
    unified_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Run LLM extraction on BDC identifiers and enrich unified holdings.

    Steps:
    1. Identify BDC rows where the rule-based parser failed
    2. Load CSV cache, skip already-processed identifiers
    3. Batch remaining to GPT-4o-mini
    4. Parse responses, append to cache after each batch
    5. Apply enrichment via DuckDB LEFT JOIN
    6. Return enriched DataFrame

    If ``unified_df`` is None, reads from ``UNIFIED_HOLDINGS_FILE``.
    """
    # Load unified if not provided
    if unified_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            logger.error("Unified holdings file not found: %s",
                         UNIFIED_HOLDINGS_FILE)
            return pd.DataFrame()
        logger.info("Loading unified holdings from %s",
                     UNIFIED_HOLDINGS_FILE.name)
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
        logger.info("  Loaded %d rows", len(unified_df))

    # Step 1: Get candidates
    all_candidates = _get_candidates(unified_df)
    logger.info("Identifier extraction: %d distinct BDC identifiers where "
                "parser failed", len(all_candidates))

    if all_candidates.empty:
        logger.info("  No candidates to process -- all identifiers parsed")
        return unified_df

    # Step 2: Load cache
    cache_df = _load_cache()
    cached_ids = set(cache_df["bdc_investment_identifier"].values) if len(cache_df) else set()
    new_candidates = [c for c in all_candidates if c not in cached_ids]
    logger.info("  %d already cached, %d new to process",
                len(all_candidates) - len(new_candidates), len(new_candidates))

    # Step 3: Batch API calls
    if new_candidates and OpenAI is None:
        logger.error(
            "openai SDK not installed. Install with: pip install openai"
        )
        logger.info("  Skipping extraction -- applying cached results only")
        new_candidates = []

    if new_candidates:
        client = OpenAI()
        total_batches = (len(new_candidates) + BATCH_SIZE - 1) // BATCH_SIZE
        all_new_rows: list[dict] = []
        cache_lock = threading.Lock()
        completed_count = 0

        # Build list of (batch_idx, batch_items)
        batch_specs = []
        for batch_idx in range(total_batches):
            start = batch_idx * BATCH_SIZE
            end = min(start + BATCH_SIZE, len(new_candidates))
            batch_specs.append((batch_idx, new_candidates[start:end]))

        def _process_batch(spec: tuple) -> list[dict]:
            """Process a single batch (called from worker thread)."""
            idx, batch = spec
            results = _call_openai_batch(batch, client)
            return _parse_batch_results(batch, results)

        logger.info("  Processing %d batches with %d workers...",
                     total_batches, MAX_WORKERS)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(_process_batch, spec): spec[0]
                for spec in batch_specs
            }
            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    rows = future.result()
                except Exception as exc:
                    logger.error("  Batch %d failed: %s", batch_idx + 1, exc)
                    rows = []

                with cache_lock:
                    all_new_rows.extend(rows)
                    completed_count += 1

                    # Periodic cache save
                    if completed_count % CACHE_SAVE_INTERVAL == 0 or \
                       completed_count == total_batches:
                        new_df = pd.DataFrame(all_new_rows)
                        cache_df = pd.concat(
                            [cache_df, new_df], ignore_index=True,
                        ).drop_duplicates(
                            subset=["bdc_investment_identifier"], keep="last",
                        )
                        _save_cache(cache_df)
                        logger.info(
                            "  Progress: %d/%d batches (%.1f%%), "
                            "cache: %d identifiers",
                            completed_count, total_batches,
                            100 * completed_count / total_batches,
                            len(cache_df),
                        )

        # Final cache save
        if all_new_rows:
            new_df = pd.DataFrame(all_new_rows)
            cache_df = pd.concat(
                [cache_df, new_df], ignore_index=True,
            ).drop_duplicates(
                subset=["bdc_investment_identifier"], keep="last",
            )
            _save_cache(cache_df)

        logger.info("  Extraction complete: %d new rows added to cache",
                     len(all_new_rows))

    # Log coverage stats before enrichment
    _log_coverage("Before enrichment", unified_df)

    # Step 5: Apply enrichment
    logger.info("Applying identifier extraction enrichment...")
    result = _apply_enrichment(unified_df, cache_df)

    # Log coverage stats after enrichment
    _log_coverage("After enrichment", result)

    return result


def _log_coverage(label: str, df: pd.DataFrame) -> None:
    """Log field coverage statistics."""
    total = len(df)
    if total == 0:
        return

    bdc_mask = df["source"] == "bdc"
    bdc_total = bdc_mask.sum()
    if bdc_total == 0:
        return

    bdc = df[bdc_mask]
    stats = {}

    # issuer_name != bdc_investment_identifier (i.e., parser succeeded)
    id_col = bdc["bdc_investment_identifier"].fillna("")
    name_col = bdc["issuer_name"].fillna("")
    parsed = (id_col != name_col) | (id_col == "")
    stats["issuer_name parsed"] = parsed.sum()

    for col, lbl in [
        ("instrument_description", "instrument_description"),
        ("extracted_industry", "extracted_industry"),
        ("reference_rate_type", "reference_rate_type"),
        ("basis_spread", "basis_spread"),
        ("maturity_date", "maturity_date"),
    ]:
        if col in bdc.columns:
            filled = bdc[col].notna() & (bdc[col] != "") & (bdc[col] != 0)
            stats[lbl] = filled.sum()

    logger.info("  %s (BDC, n=%d):", label, bdc_total)
    for field, count in stats.items():
        logger.info("    %-30s %d (%.1f%%)",
                     field + ":", count, 100 * count / bdc_total)
