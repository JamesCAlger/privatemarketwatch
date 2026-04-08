"""LLM-assisted classification of remaining UNCLASSIFIED holdings.

Extracts unique identifier tuples that could not be classified by heuristics,
batches them for LLM review, and applies the results back to the unified
holdings dataset.

Supports two modes:
  - Automated via OpenAI API (GPT-4o-mini)
  - Interactive via dry-run export (CSV for manual review)

Requires ``OPENAI_API_KEY`` in ``.env`` (or environment variable).
"""

import json
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

import pandas as pd

try:
    from pydantic import BaseModel
except ImportError:
    BaseModel = None  # type: ignore[assignment,misc]

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
# Structured output schema (Pydantic)
# ---------------------------------------------------------------------------

if BaseModel is not None:
    class Classification(BaseModel):
        id: int
        is_aggregate: bool
        asset_class: Literal[
            "LOAN", "EQUITY_COMMON", "EQUITY_PREFERRED", "FUND", "UNKNOWN"
        ]
        confidence: Literal["high", "medium", "low"]
        reasoning: str

    class ClassificationResponse(BaseModel):
        classifications: list[Classification]
else:
    Classification = None  # type: ignore[assignment,misc]
    ClassificationResponse = None  # type: ignore[assignment,misc]

from pipeline.config import (
    LLM_REVIEW_CANDIDATES_FILE,
    LLM_REVIEW_LOOKUP_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt for LLM classification
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial data classifier for SEC investment filings. You will \
classify investment identifiers from two sources:

1. BDC (Business Development Company) XBRL filings -- identifiers are \
structured strings like "Company Name | Instrument Type | Affiliation" or \
"Company Name, Instrument Type". BDCs invest in private middle-market \
companies via senior secured loans, mezzanine debt, and equity co-investments.

2. N-PORT filings from interval/tender offer funds -- identifiers are \
issuer names and instrument descriptions. These funds invest in private \
credit, PE/VC funds, hedge funds, real estate, and structured products.

For EACH identifier, provide a classification with: id (the number), \
is_aggregate (bool), asset_class (LOAN/EQUITY_COMMON/EQUITY_PREFERRED/FUND/UNKNOWN), \
confidence (high/medium/low), and reasoning (1 sentence).

Classification rules:
- LOAN: Senior secured loans, term loans, revolving credit, mezzanine debt, \
subordinated notes, unitranche, delayed draw, PIK notes to operating companies.
- EQUITY_COMMON: Common stock, membership interests, LLC units, warrants in \
operating companies (Inc., LLC, Corp., Holdings, LP operating entities).
- EQUITY_PREFERRED: Preferred stock, preferred units in operating companies.
- FUND: Fund vehicles -- names containing "Fund", "Partners", "L.P.", \
"Limited Partnership", "Capital" + Roman numerals (I-X), "Feeder", "SCSp", \
"Aggregator". Includes PE funds, credit funds, hedge funds, CLO vehicles.
- UNKNOWN: Only when genuinely insufficient information to classify.

Aggregate detection:
- is_aggregate=true for section headers ("Total Senior Secured First Lien"), \
subtotals ("Sub-total", "Grand Total"), industry/geography labels \
("Healthcare", "United States"), category summaries, or XBRL placeholders.
- is_aggregate=false for real investments. Key signals: non-zero interest_rate \
or basis_spread strongly indicates a real loan; non-zero shares_held indicates \
real equity; a specific company name with instrument description is almost \
always a real investment.

Each entry includes the current heuristic classification. Focus on cases where \
you disagree with the current classification or can provide higher confidence.
"""


# ---------------------------------------------------------------------------
# 1. Extract review candidates
# ---------------------------------------------------------------------------

def extract_review_candidates(
    unified_df: pd.DataFrame,
    aggregate_suspects: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Extract unique identifiers needing LLM classification.

    Deduplicates to unique (issuer_name, instrument_description,
    bdc_investment_identifier) tuples.  Includes:
    - All UNCLASSIFIED rows
    - Suspected aggregate rows from audit_aggregate_leaks()
    - Rows where asset_category == OTHER

    Returns DataFrame with review metadata and financial signal samples.
    """
    # Collect candidate rows
    masks = []

    # UNCLASSIFIED
    unclass_mask = unified_df["index_classification"] == "UNCLASSIFIED"
    masks.append(unclass_mask)

    # OTHER asset category
    other_mask = unified_df["asset_category"] == "OTHER"
    masks.append(other_mask)

    combined_mask = masks[0]
    for m in masks[1:]:
        combined_mask = combined_mask | m

    candidates = unified_df[combined_mask].copy()

    # Add suspected aggregates if provided
    if aggregate_suspects is not None and not aggregate_suspects.empty:
        # Match by bdc_investment_identifier
        suspect_ids = set(
            aggregate_suspects["bdc_investment_identifier"].dropna().unique()
        )
        if suspect_ids:
            suspect_mask = unified_df["bdc_investment_identifier"].isin(suspect_ids)
            extra = unified_df[suspect_mask & ~combined_mask]
            if not extra.empty:
                candidates = pd.concat([candidates, extra], ignore_index=True)

    if candidates.empty:
        return pd.DataFrame(columns=[
            "review_id", "issuer_name", "instrument_description",
            "bdc_investment_identifier", "source", "sample_fair_value",
            "sample_interest_rate", "sample_basis_spread",
            "sample_principal_amount", "sample_shares_held",
            "current_asset_category", "current_index_classification",
            "review_type", "occurrence_count",
        ])

    # Determine review type
    candidates["review_type"] = "unclassified"
    candidates.loc[
        candidates["asset_category"] == "OTHER", "review_type"
    ] = "other_asset"
    if aggregate_suspects is not None and not aggregate_suspects.empty:
        suspect_ids = set(
            aggregate_suspects["bdc_investment_identifier"].dropna().unique()
        )
        candidates.loc[
            candidates["bdc_investment_identifier"].isin(suspect_ids),
            "review_type",
        ] = "suspected_aggregate"

    # Dedup to unique identifier tuples
    group_cols = ["issuer_name", "instrument_description", "bdc_investment_identifier"]
    # Ensure group cols are strings
    for col in group_cols:
        candidates[col] = candidates[col].fillna("").astype(str)

    grouped = candidates.groupby(group_cols, sort=False)

    records = []
    for idx, (key, g) in enumerate(grouped):
        sample = g.iloc[0]
        records.append({
            "review_id": idx,
            "issuer_name": key[0],
            "instrument_description": key[1],
            "bdc_investment_identifier": key[2],
            "source": sample.get("source", ""),
            "sample_fair_value": sample.get("fair_value", ""),
            "sample_interest_rate": sample.get("interest_rate", ""),
            "sample_basis_spread": sample.get("basis_spread", ""),
            "sample_principal_amount": sample.get("principal_amount", ""),
            "sample_shares_held": sample.get("shares_held", ""),
            "current_asset_category": sample.get("asset_category", ""),
            "current_index_classification": sample.get("index_classification", ""),
            "review_type": g["review_type"].iloc[0],
            "occurrence_count": len(g),
        })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 2. Build LLM prompt batches
# ---------------------------------------------------------------------------

def _format_fv(val) -> str:
    """Format fair_value as human-readable string."""
    if pd.isna(val) or val == "" or val == "0":
        return ""
    try:
        fv = float(val)
    except (ValueError, TypeError):
        return ""
    if fv == 0:
        return ""
    abs_fv = abs(fv)
    sign = "-" if fv < 0 else ""
    if abs_fv >= 1_000_000_000:
        return f"{sign}${abs_fv / 1_000_000_000:.1f}B"
    if abs_fv >= 1_000_000:
        return f"{sign}${abs_fv / 1_000_000:.1f}M"
    if abs_fv >= 1_000:
        return f"{sign}${abs_fv / 1_000:.0f}K"
    return f"{sign}${abs_fv:.0f}"


def build_review_batches(
    candidates: pd.DataFrame,
    batch_size: int = 50,
) -> list:
    """Build structured prompts for LLM classification.

    Each batch contains up to ``batch_size`` identifiers formatted as a
    numbered list with financial signal context and current classification.

    Returns list of (prompt_string, review_ids) tuples.
    """
    batches = []
    total = len(candidates)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch = candidates.iloc[start:end]

        lines = []
        review_ids = []
        for _, row in batch.iterrows():
            rid = row["review_id"]
            review_ids.append(rid)

            parts = [f"{rid}."]

            # Identifier text (guard against "nan" strings)
            bdc_id = row.get("bdc_investment_identifier", "")
            issuer = row.get("issuer_name", "")
            instr = row.get("instrument_description", "")
            if bdc_id and str(bdc_id).lower() != "nan":
                parts.append(f'Identifier: "{bdc_id}"')
            elif issuer and str(issuer).lower() != "nan":
                parts.append(f'Issuer: "{issuer}"')
                if instr and str(instr).lower() != "nan":
                    parts.append(f'Instrument: "{instr}"')
            elif instr and str(instr).lower() != "nan":
                parts.append(f'Instrument: "{instr}"')
            else:
                parts.append('Identifier: (no name available)')

            # Current classification context
            cur_asset = row.get("current_asset_category", "")
            cur_index = row.get("current_index_classification", "")
            if cur_asset or cur_index:
                parts.append(f"Current: {cur_asset}/{cur_index}")

            # Financial signals
            signals = []
            fv_str = _format_fv(row.get("sample_fair_value", ""))
            if fv_str:
                signals.append(f"FV={fv_str}")
            for col, label in [
                ("sample_interest_rate", "rate"),
                ("sample_basis_spread", "spread"),
                ("sample_principal_amount", "principal"),
                ("sample_shares_held", "shares"),
            ]:
                val = row.get(col, "")
                if pd.notna(val) and val != "" and val != 0 and val != "0":
                    if col == "sample_principal_amount":
                        signals.append(f"{label}={_format_fv(val)}")
                    else:
                        signals.append(f"{label}={val}")
            if signals:
                parts.append(f"[{', '.join(signals)}]")

            parts.append(f"({row['occurrence_count']}x)")
            lines.append(" | ".join(parts))

        prompt = (
            "Classify the following investment identifiers.\n\n"
            + "\n".join(lines)
        )

        batches.append((prompt, review_ids))

    return batches


# ---------------------------------------------------------------------------
# 3. Parse LLM responses
# ---------------------------------------------------------------------------

def _parse_text_response(text: str) -> list:
    """Extract classification dicts from an unstructured text response.

    Handles raw JSON, markdown code fences, and single-object responses.
    Returns list of dicts with keys: id, is_aggregate, asset_class,
    confidence, reasoning.
    """
    text = text.strip()
    if not text:
        return []

    # Strip markdown code fences
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    items = json.loads(text)
    if not isinstance(items, list):
        items = [items]
    return items


def parse_review_responses(
    candidates: pd.DataFrame,
    responses: list,
    batch_size: int = 50,
) -> pd.DataFrame:
    """Parse LLM responses into a classification lookup table.

    Accepts mixed response types from ``_call_llm_api``:
      - ``list[dict]``: pre-parsed structured output (from ``.parse()``)
      - ``str``: raw text needing JSON extraction (fallback mode)

    Returns lookup DataFrame to be saved to LLM_REVIEW_LOOKUP_FILE.
    """
    all_classifications = {}

    for response in responses:
        try:
            if isinstance(response, list):
                # Structured output: already a list of dicts
                items = response
            elif isinstance(response, str):
                # Unstructured fallback: parse text
                items = _parse_text_response(response)
            else:
                continue

            for item in items:
                rid = item.get("id")
                if rid is None:
                    continue
                all_classifications[int(rid)] = {
                    "llm_is_aggregate": bool(item.get("is_aggregate", False)),
                    "llm_asset_class": str(item.get("asset_class", "UNKNOWN")).upper(),
                    "llm_confidence": str(item.get("confidence", "low")).lower(),
                    "llm_reasoning": str(item.get("reasoning", "")),
                }
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Failed to parse LLM response: %s", exc)
            continue

    # Build lookup table
    records = []
    now = datetime.now(timezone.utc).isoformat()
    for _, row in candidates.iterrows():
        rid = row["review_id"]
        cls = all_classifications.get(rid, {})
        records.append({
            "review_id": rid,
            "issuer_name": row["issuer_name"],
            "instrument_description": row["instrument_description"],
            "bdc_investment_identifier": row["bdc_investment_identifier"],
            "llm_is_aggregate": cls.get("llm_is_aggregate", False),
            "llm_asset_class": cls.get("llm_asset_class", "UNKNOWN"),
            "llm_confidence": cls.get("llm_confidence", "low"),
            "llm_reasoning": cls.get("llm_reasoning", ""),
            "occurrence_count": row["occurrence_count"],
            "review_timestamp": now,
        })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 4. Apply lookup table to unified holdings
# ---------------------------------------------------------------------------

def apply_llm_classifications(
    unified_df: pd.DataFrame,
    lookup_df: pd.DataFrame,
) -> pd.DataFrame:
    """Join LLM lookup table back into unified holdings (vectorized).

    - Rows where llm_is_aggregate == True: removed
    - Rows where llm_asset_class != UNKNOWN and confidence != low: reclassified
    - Adds 'llm_reviewed' column
    """
    from pipeline.unified_holdings import _classify_bdc_issuer, _classify_index

    df = unified_df.copy()
    df["llm_reviewed"] = False

    if lookup_df.empty:
        return df

    # Normalize join keys
    join_cols = ["issuer_name", "instrument_description", "bdc_investment_identifier"]
    lk = lookup_df.copy()
    for col in join_cols:
        lk[col] = lk[col].fillna("").astype(str)
        df[col] = df[col].fillna("").astype(str)

    # Deduplicate lookup to one row per key (keep first)
    lk = lk.drop_duplicates(subset=join_cols, keep="first")

    # Normalize boolean
    if "llm_is_aggregate" in lk.columns:
        lk["llm_is_aggregate"] = lk["llm_is_aggregate"].map(
            {"True": True, "False": False, "true": True, "false": False,
             True: True, False: False, "1": True, "0": False,
             "yes": True, "no": False}
        ).fillna(False).astype(bool)

    # Merge lookup onto unified
    lk_subset = lk[join_cols + ["llm_is_aggregate", "llm_asset_class", "llm_confidence"]].copy()
    lk_subset["llm_asset_class"] = lk_subset["llm_asset_class"].fillna("UNKNOWN").str.upper()
    lk_subset["llm_confidence"] = lk_subset["llm_confidence"].fillna("low").str.lower()

    df = df.merge(lk_subset, on=join_cols, how="left", suffixes=("", "_llm"))

    # Mark reviewed rows
    matched = df["llm_is_aggregate"].notna()
    df.loc[matched, "llm_reviewed"] = True

    # Remove aggregates
    is_agg = df["llm_is_aggregate"].infer_objects(copy=False).fillna(False).astype(bool)
    n_agg = is_agg.sum()
    if n_agg > 0:
        df = df[~is_agg].reset_index(drop=True)
        logger.info("  LLM review: removed %d aggregate rows", n_agg)

    # Reclassify confident non-UNKNOWN rows
    reclass_mask = (
        df["llm_reviewed"]
        & (df["llm_asset_class"] != "UNKNOWN")
        & (df["llm_confidence"] != "low")
    )

    if reclass_mask.any():
        df.loc[reclass_mask, "asset_category"] = df.loc[reclass_mask, "llm_asset_class"]

        # Re-derive issuer_category for BDC rows
        bdc_reclass = reclass_mask & (df["source"] == "bdc")
        if bdc_reclass.any():
            df.loc[bdc_reclass, "issuer_category"] = (
                df.loc[bdc_reclass, "llm_asset_class"]
                .map(lambda ac: _classify_bdc_issuer(ac))
            )

        # Re-derive index_classification
        df.loc[reclass_mask, "index_classification"] = df.loc[reclass_mask].apply(
            lambda r: _classify_index(
                r["asset_category"], r["issuer_category"],
                str(r["issuer_name"]), str(r["instrument_description"]),
            ),
            axis=1,
        )
        logger.info("  LLM review: reclassified %d rows", reclass_mask.sum())

    # Drop temporary merge columns
    for col in ["llm_is_aggregate", "llm_asset_class", "llm_confidence"]:
        if col in df.columns:
            df = df.drop(columns=[col])

    return df


# ---------------------------------------------------------------------------
# 5. Orchestrator
# ---------------------------------------------------------------------------

def run_llm_review(
    unified_df: Optional[pd.DataFrame] = None,
    aggregate_suspects: Optional[pd.DataFrame] = None,
    dry_run: bool = False,
) -> pd.DataFrame:
    """Run the full LLM review pipeline.

    Steps:
    1. Extract candidates (dedup to unique identifiers)
    2. Check for existing lookup table (resumable)
    3. Build prompt batches for uncovered candidates
    4. Invoke GPT-4o-mini via OpenAI SDK (if not dry_run)
    5. Parse responses, save lookup table
    6. Apply classifications to unified_df (if not dry_run)

    dry_run=True: exports candidates CSV only, no API calls.
    """
    # Load unified if not provided
    if unified_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            logger.error("Unified holdings file not found: %s", UNIFIED_HOLDINGS_FILE)
            return pd.DataFrame()
        logger.info("Loading unified holdings from %s", UNIFIED_HOLDINGS_FILE.name)
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
        logger.info("  Loaded %d rows", len(unified_df))

    # Step 1: Extract candidates
    logger.info("Extracting LLM review candidates...")
    candidates = extract_review_candidates(unified_df, aggregate_suspects)
    logger.info("  %d unique identifier tuples to review", len(candidates))

    if candidates.empty:
        logger.info("  No candidates to review -- all classified!")
        return unified_df

    # Save candidates CSV
    candidates.to_csv(LLM_REVIEW_CANDIDATES_FILE, index=False)
    logger.info("  Saved candidates to %s", LLM_REVIEW_CANDIDATES_FILE.name)

    if dry_run:
        logger.info("  Dry run -- skipping API calls and application")
        return unified_df

    # Step 2: Check for existing lookup table
    lookup_df = None
    if LLM_REVIEW_LOOKUP_FILE.exists():
        logger.info("  Loading existing lookup table from %s", LLM_REVIEW_LOOKUP_FILE.name)
        lookup_df = pd.read_csv(LLM_REVIEW_LOOKUP_FILE, dtype=str)
        # Check if all candidates are covered
        existing_ids = set(lookup_df["review_id"].astype(int))
        needed_ids = set(candidates["review_id"])
        uncovered = needed_ids - existing_ids
        if not uncovered:
            logger.info("  All %d candidates already in lookup table", len(candidates))
        else:
            logger.info("  %d of %d candidates need review", len(uncovered), len(candidates))
            candidates = candidates[candidates["review_id"].isin(uncovered)]
            lookup_df = None  # Will merge after new reviews

    if lookup_df is None:
        # Step 3: Build batches
        batches = build_review_batches(candidates)
        logger.info("  Built %d batches of prompts", len(batches))

        # Step 4: Call API
        responses = _call_llm_api(batches)

        # Step 5: Parse and save
        new_lookup = parse_review_responses(candidates, responses)

        # Merge with existing if any
        if LLM_REVIEW_LOOKUP_FILE.exists():
            existing = pd.read_csv(LLM_REVIEW_LOOKUP_FILE, dtype=str)
            lookup_df = pd.concat([existing, new_lookup], ignore_index=True)
        else:
            lookup_df = new_lookup

        lookup_df.to_csv(LLM_REVIEW_LOOKUP_FILE, index=False)
        logger.info("  Saved lookup table to %s (%d entries)",
                     LLM_REVIEW_LOOKUP_FILE.name, len(lookup_df))

    # Ensure boolean type
    if "llm_is_aggregate" in lookup_df.columns:
        lookup_df["llm_is_aggregate"] = lookup_df["llm_is_aggregate"].map(
            {"True": True, "False": False, True: True, False: False}
        ).fillna(False)

    # Step 6: Apply
    logger.info("Applying LLM classifications...")
    result = apply_llm_classifications(unified_df, lookup_df)

    # Save updated unified
    result.to_csv(UNIFIED_HOLDINGS_FILE, index=False)
    logger.info("  Saved updated unified holdings to %s", UNIFIED_HOLDINGS_FILE.name)

    # Log final stats
    total = len(result)
    unclass = (result["index_classification"] == "UNCLASSIFIED").sum()
    logger.info("  Final UNCLASSIFIED: %d / %d (%.1f%%)",
                unclass, total, 100 * unclass / total if total else 0)

    return result


def _call_llm_api(batches: list) -> list:
    """Call OpenAI API (GPT-4o-mini) with structured output for each batch.

    Uses ``client.beta.chat.completions.parse()`` with the
    ``ClassificationResponse`` Pydantic schema so the API guarantees
    well-formed JSON.  Falls back to unstructured ``create()`` + text
    parsing if the SDK version does not support ``.parse()``.

    Returns list of dicts, one per batch:
      - On structured success: list of Classification dicts
      - On fallback/failure: raw text string (parsed later by
        ``parse_review_responses``)
    """
    if OpenAI is None:
        logger.error(
            "openai SDK not installed. Install with: pip install openai"
        )
        logger.info("  Returning empty responses -- use --llm-review-dry-run instead")
        return []

    client = OpenAI()
    responses: list = []

    # Detect structured output support
    use_structured = ClassificationResponse is not None and hasattr(
        getattr(client, "beta", None), "chat"
    )
    if use_structured:
        logger.info("  Using structured output mode (Pydantic schema)")
    else:
        logger.info("  Using unstructured output mode (text + JSON parse)")

    for i, (prompt, review_ids) in enumerate(batches):
        logger.info("  Batch %d/%d (%d identifiers)...",
                     i + 1, len(batches), len(review_ids))
        try:
            if use_structured:
                response = client.beta.chat.completions.parse(
                    model="gpt-4o-mini",
                    max_tokens=16384,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    response_format=ClassificationResponse,
                )
                parsed = response.choices[0].message.parsed
                if parsed is not None:
                    responses.append([c.model_dump() for c in parsed.classifications])
                else:
                    # Refusal or content filter
                    logger.warning("  Batch %d: model returned no parsed content", i + 1)
                    responses.append(response.choices[0].message.content or "")
            else:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    max_tokens=16384,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                )
                responses.append(response.choices[0].message.content or "")
        except Exception as exc:
            logger.error("  API call failed for batch %d: %s", i + 1, exc)
            responses.append("")

        # Rate limit: small delay between batches
        if i < len(batches) - 1:
            time.sleep(0.5)

    return responses
