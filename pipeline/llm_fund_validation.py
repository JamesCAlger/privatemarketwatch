"""Blind validation of LLM fund classification accuracy.

Sends issuer_names from already-classified fund positions to GPT-4o-mini,
compares predictions against ground truth (majority-vote labels from
unified holdings), and computes a confusion matrix with per-class
precision/recall/F1.

Cache: ``data/output/llm_fund_validation_cache.csv`` -- keyed by
issuer_name so re-runs cost $0.

Entry point: ``run_fund_validation() -> dict``
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
import pandas as pd

try:
    from pydantic import BaseModel
except ImportError:
    BaseModel = None  # type: ignore[assignment,misc]

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]

from pipeline.config import (
    LLM_FUND_CLASSIFICATION_REVIEW_FILE,
    LLM_FUND_VALIDATION_CACHE_FILE,
    LLM_FUND_VALIDATION_RESULTS_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BATCH_SIZE = 50
_MAX_WORKERS = 10
_LLM_DELAY = 0.5

_LABELS = [
    "PRIVATE_EQUITY_FUND",
    "PRIVATE_CREDIT_FUND",
    "HEDGE_FUND",
    "REAL_ESTATE_FUND",
    "STRUCTURED_CREDIT",
    "OTHER_FUND",
]

_DISPLAY_LABELS = [
    "PE Fund",
    "Credit Fund",
    "Hedge Fund",
    "RE Fund",
    "Struct. Credit",
    "Other",
]

# ---------------------------------------------------------------------------
# Pydantic schema for structured output
# ---------------------------------------------------------------------------

if BaseModel is not None:
    from typing import Literal

    class FundClassification(BaseModel):
        id: int
        classification: Literal[
            "PRIVATE_EQUITY_FUND",
            "PRIVATE_CREDIT_FUND",
            "HEDGE_FUND",
            "REAL_ESTATE_FUND",
            "STRUCTURED_CREDIT",
            "OTHER_FUND",
        ]

    class FundClassificationResponse(BaseModel):
        classifications: list[FundClassification]
else:
    FundClassification = None  # type: ignore[assignment,misc]
    FundClassificationResponse = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial data classifier. Given a list of fund/vehicle names \
from SEC filings, classify each into exactly one category:

- PRIVATE_EQUITY_FUND: PE/VC/buyout/growth equity funds. Signals: \
"Partners", Roman numerals (I-X), "Capital", "Ventures", "Growth", \
"Buyout", "Equity Partners", "Co-Invest".
- PRIVATE_CREDIT_FUND: Private credit/direct lending/mezzanine fund \
vehicles. Signals: "Credit", "Lending", "Senior Loan", "Floating Rate", \
"Income", "Debt", "CLO" (managed CLO vehicles that are fund-like).
- HEDGE_FUND: Hedge funds, multi-strategy, macro, long/short. Signals: \
"Hedge", "Macro", "Absolute Return", "Multi-Strategy", "Long/Short", \
"Alpha", "Arbitrage".
- REAL_ESTATE_FUND: Real estate funds and REITs. Signals: "Real Estate", \
"Realty", "REIT", "Property", "Mortgage Fund".
- STRUCTURED_CREDIT: CLO tranches, ABS vehicles, CDOs, securitization \
trusts. Signals: "CLO", "CDO", "ABS", specific tranche designations \
(Class A, B, C notes), "Trust", "Securitization", numbered series.
- OTHER_FUND: Cannot confidently classify into any of the above.

For each numbered entry, return its id and classification. Classify by \
name only -- no other context is available. When in doubt between two \
categories, choose the more specific one. Only use OTHER_FUND if you \
genuinely cannot determine the type.
"""


# ---------------------------------------------------------------------------
# 1. Extract ground truth
# ---------------------------------------------------------------------------

def _extract_ground_truth() -> pd.DataFrame:
    """Extract unique fund names with known labels from unified holdings.

    Uses majority vote when a name appears under multiple classifications.
    Returns DataFrame with columns: issuer_name, actual_label.
    """
    if not UNIFIED_HOLDINGS_FILE.exists():
        logger.error("Unified holdings file not found: %s",
                     UNIFIED_HOLDINGS_FILE)
        return pd.DataFrame(columns=["issuer_name", "actual_label"])

    con = duckdb.connect()
    try:
        df = con.execute(f"""
            WITH fund_rows AS (
                SELECT
                    TRIM(issuer_name) AS issuer_name,
                    index_classification AS label
                FROM read_csv_auto(
                    '{UNIFIED_HOLDINGS_FILE.as_posix()}',
                    all_varchar=true
                )
                WHERE issuer_category = 'FUND'
                  AND index_classification IN (
                      'PRIVATE_CREDIT_FUND',
                      'PRIVATE_EQUITY_FUND',
                      'HEDGE_FUND',
                      'REAL_ESTATE_FUND',
                      'STRUCTURED_CREDIT'
                  )
                  AND TRIM(issuer_name) != ''
                  AND issuer_name IS NOT NULL
            ),
            -- Count occurrences per (issuer_name, label)
            name_label_counts AS (
                SELECT issuer_name, label, COUNT(*) AS cnt
                FROM fund_rows
                GROUP BY issuer_name, label
            ),
            -- Pick majority label per issuer_name
            ranked AS (
                SELECT *,
                    ROW_NUMBER() OVER (
                        PARTITION BY issuer_name
                        ORDER BY cnt DESC, label
                    ) AS rn
                FROM name_label_counts
            )
            SELECT issuer_name, label AS actual_label
            FROM ranked
            WHERE rn = 1
        """).fetchdf()
    finally:
        con.close()

    logger.info("  Ground truth: %d unique fund names", len(df))
    for label in _LABELS[:5]:  # skip OTHER_FUND
        n = (df["actual_label"] == label).sum()
        if n:
            logger.info("    %s: %d", label, n)

    return df


# ---------------------------------------------------------------------------
# 2. LLM batch classification
# ---------------------------------------------------------------------------

def _build_batches(names: list[str]) -> list[tuple[str, list[int]]]:
    """Build numbered prompt batches from a list of fund names."""
    batches = []
    for start in range(0, len(names), _BATCH_SIZE):
        end = min(start + _BATCH_SIZE, len(names))
        batch_names = names[start:end]
        lines = [f"{start + i}. {name}" for i, name in enumerate(batch_names)]
        prompt = (
            "Classify the following fund/vehicle names.\n\n"
            + "\n".join(lines)
        )
        ids = list(range(start, end))
        batches.append((prompt, ids))
    return batches


def _call_batch(client: "OpenAI", prompt: str, batch_idx: int,
                total: int) -> list[dict]:
    """Call GPT-4o-mini for a single batch. Returns list of {id, classification}."""
    use_structured = (
        FundClassificationResponse is not None
        and hasattr(getattr(client, "beta", None), "chat")
    )

    try:
        if use_structured:
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format=FundClassificationResponse,
            )
            parsed = response.choices[0].message.parsed
            if parsed is not None:
                return [c.model_dump() for c in parsed.classifications]
            return []
        else:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
            import json
            text = response.choices[0].message.content or ""
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            items = json.loads(text)
            if not isinstance(items, list):
                items = [items]
            return items
    except Exception as exc:
        logger.warning("  Batch %d/%d failed: %s", batch_idx + 1, total, exc)
        return []


def _classify_names(names: list[str]) -> dict[str, str]:
    """Classify a list of fund names via GPT-4o-mini.

    Returns dict mapping issuer_name -> predicted_label.
    """
    if OpenAI is None:
        logger.error("openai SDK not installed. "
                     "Install with: pip install openai")
        return {}

    client = OpenAI()
    batches = _build_batches(names)
    logger.info("  Classifying %d names in %d batches (%d workers)...",
                len(names), len(batches), _MAX_WORKERS)

    # Map id -> classification
    results: dict[int, str] = {}

    def _process(args: tuple[int, str, list[int]]) -> list[dict]:
        idx, prompt, _ = args
        time.sleep(_LLM_DELAY * (idx % _MAX_WORKERS))
        return _call_batch(client, prompt, idx, len(batches))

    work = [(i, prompt, ids) for i, (prompt, ids) in enumerate(batches)]

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        futures = {executor.submit(_process, w): w for w in work}
        for future in as_completed(futures):
            batch_results = future.result()
            for item in batch_results:
                rid = item.get("id")
                cls = item.get("classification", "OTHER_FUND")
                if rid is not None and cls in _LABELS:
                    results[int(rid)] = cls
                elif rid is not None:
                    results[int(rid)] = "OTHER_FUND"

    # Map back to names
    name_to_pred: dict[str, str] = {}
    for i, name in enumerate(names):
        name_to_pred[name] = results.get(i, "OTHER_FUND")

    classified = sum(1 for v in name_to_pred.values() if v != "OTHER_FUND")
    logger.info("  Classified %d/%d names (%d OTHER_FUND)",
                classified, len(names), len(names) - classified)

    return name_to_pred


# ---------------------------------------------------------------------------
# 3. Cache management
# ---------------------------------------------------------------------------

def _load_cache() -> dict[str, str]:
    """Load existing cache. Returns dict: issuer_name -> predicted_label."""
    if not LLM_FUND_VALIDATION_CACHE_FILE.exists():
        return {}
    df = pd.read_csv(LLM_FUND_VALIDATION_CACHE_FILE, dtype=str)
    if df.empty:
        return {}
    return dict(zip(df["issuer_name"], df["predicted_label"]))


def _save_cache(cache: dict[str, str]) -> None:
    """Save cache to CSV."""
    df = pd.DataFrame([
        {"issuer_name": k, "predicted_label": v}
        for k, v in sorted(cache.items())
    ])
    df.to_csv(LLM_FUND_VALIDATION_CACHE_FILE, index=False)
    logger.info("  Cache saved: %d entries -> %s",
                len(df), LLM_FUND_VALIDATION_CACHE_FILE.name)


# ---------------------------------------------------------------------------
# 4. Confusion matrix computation
# ---------------------------------------------------------------------------

def _compute_confusion_matrix(
    ground_truth: pd.DataFrame,
    predictions: dict[str, str],
) -> dict:
    """Compute confusion matrix and per-class metrics.

    Returns dict with keys:
      overallAccuracy, totalSamples, labels, confusionMatrix, perClassMetrics
    """
    # Build aligned arrays
    actuals = []
    preds = []
    for _, row in ground_truth.iterrows():
        name = row["issuer_name"]
        if name in predictions:
            actuals.append(row["actual_label"])
            preds.append(predictions[name])

    total = len(actuals)
    if total == 0:
        return {
            "overallAccuracy": 0,
            "totalSamples": 0,
            "labels": _DISPLAY_LABELS,
            "confusionMatrix": [[0] * len(_LABELS) for _ in _LABELS],
            "perClassMetrics": [],
        }

    # Build confusion matrix (rows = actual, cols = predicted)
    label_to_idx = {label: i for i, label in enumerate(_LABELS)}
    n_classes = len(_LABELS)
    matrix = [[0] * n_classes for _ in range(n_classes)]

    for actual, pred in zip(actuals, preds):
        ai = label_to_idx.get(actual)
        pi = label_to_idx.get(pred)
        if ai is not None and pi is not None:
            matrix[ai][pi] += 1

    # Compute per-class metrics
    correct = sum(matrix[i][i] for i in range(n_classes))
    overall_accuracy = correct / total if total else 0

    per_class = []
    for i, label in enumerate(_LABELS):
        tp = matrix[i][i]
        # Support = actual count for this class
        support = sum(matrix[i])
        # Predicted count for this class
        predicted_count = sum(matrix[j][i] for j in range(n_classes))

        precision = tp / predicted_count if predicted_count > 0 else 0
        recall = tp / support if support > 0 else 0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) > 0 else 0)

        per_class.append({
            "label": _DISPLAY_LABELS[i],
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        })

    return {
        "overallAccuracy": round(overall_accuracy, 4),
        "totalSamples": total,
        "labels": _DISPLAY_LABELS,
        "confusionMatrix": matrix,
        "perClassMetrics": per_class,
    }


# ---------------------------------------------------------------------------
# 5. Save results
# ---------------------------------------------------------------------------

def _save_results(results: dict) -> None:
    """Save confusion matrix results to CSV for export_frontend pickup."""
    import json
    rows = []
    rows.append({
        "metric": "overall",
        "value": json.dumps({
            "overallAccuracy": results["overallAccuracy"],
            "totalSamples": results["totalSamples"],
            "labels": results["labels"],
            "confusionMatrix": results["confusionMatrix"],
        }),
    })
    for m in results["perClassMetrics"]:
        rows.append({
            "metric": f"class_{m['label']}",
            "value": json.dumps(m),
        })

    df = pd.DataFrame(rows)
    df.to_csv(LLM_FUND_VALIDATION_RESULTS_FILE, index=False)
    logger.info("  Results saved -> %s", LLM_FUND_VALIDATION_RESULTS_FILE.name)


# ---------------------------------------------------------------------------
# 6. Entry point
# ---------------------------------------------------------------------------

def run_fund_validation() -> dict:
    """Orchestrate the full validation experiment.

    Steps:
    1. Extract ground truth from unified holdings
    2. Check cache for existing predictions
    3. Call LLM for uncached names
    4. Compute confusion matrix
    5. Save results

    Returns the results dict (confusion matrix + metrics).
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("LLM FUND CLASSIFICATION VALIDATION")
    logger.info("=" * 60)

    # Step 1: Ground truth
    logger.info("Step 1: Extracting ground truth...")
    gt = _extract_ground_truth()
    if gt.empty:
        logger.warning("No ground truth data found -- aborting")
        return {}

    # Step 2: Load cache
    logger.info("Step 2: Checking cache...")
    cache = _load_cache()
    all_names = gt["issuer_name"].tolist()
    uncached = [n for n in all_names if n not in cache]
    logger.info("  %d cached, %d need classification",
                len(all_names) - len(uncached), len(uncached))

    # Step 3: Classify uncached names
    if uncached:
        logger.info("Step 3: Classifying %d uncached names...", len(uncached))
        new_predictions = _classify_names(uncached)
        cache.update(new_predictions)
        _save_cache(cache)
    else:
        logger.info("Step 3: All names cached -- skipping LLM calls")

    # Step 4: Compute confusion matrix
    logger.info("Step 4: Computing confusion matrix...")
    results = _compute_confusion_matrix(gt, cache)

    logger.info("  Overall accuracy: %.1f%% (%d samples)",
                results["overallAccuracy"] * 100, results["totalSamples"])
    for m in results["perClassMetrics"]:
        if m["support"] > 0:
            logger.info("    %-15s  P=%.2f  R=%.2f  F1=%.2f  n=%d",
                        m["label"], m["precision"], m["recall"],
                        m["f1"], m["support"])

    # Step 5: Save
    logger.info("Step 5: Saving results...")
    _save_results(results)

    logger.info("LLM fund validation complete")
    return results


# ---------------------------------------------------------------------------
# 7. Classify unclassified fund positions
# ---------------------------------------------------------------------------

# Classes where LLM precision is high enough to auto-apply
_AUTO_APPLY_LABELS = {
    "PRIVATE_EQUITY_FUND",
    "PRIVATE_CREDIT_FUND",
    "REAL_ESTATE_FUND",
}

# Classes that need manual review (low precision)
_REVIEW_LABELS = {
    "HEDGE_FUND",
    "STRUCTURED_CREDIT",
}

# Map index_classification -> asset_class for consistency with 2-axis system
_INDEX_TO_ASSET_CLASS = {
    "PRIVATE_EQUITY_FUND": "PRIVATE_EQUITY",
    "PRIVATE_CREDIT_FUND": "PRIVATE_CREDIT",
    "REAL_ESTATE_FUND": "REAL_ESTATE",
}


def classify_unclassified_funds() -> dict:
    """Classify UNCLASSIFIED fund positions via LLM and apply high-precision labels.

    Steps:
    1. Query unique issuer_names where issuer_category='FUND' AND
       index_classification='UNCLASSIFIED'
    2. Check LLM cache for existing predictions
    3. Call GPT-4o-mini for uncached names
    4. Auto-apply PE/Credit/RE (high precision); write HF/SC to review CSV
    5. Re-save unified holdings with updated classifications

    Returns dict with counts: auto_applied, review_needed, other_fund, total.
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("CLASSIFY UNCLASSIFIED FUND POSITIONS")
    logger.info("=" * 60)

    if not UNIFIED_HOLDINGS_FILE.exists():
        logger.error("Unified holdings file not found: %s",
                     UNIFIED_HOLDINGS_FILE)
        return {}

    holdings_path = UNIFIED_HOLDINGS_FILE.as_posix()

    # ------------------------------------------------------------------
    # Step 1: Get unique unclassified fund names with row count and FV
    # ------------------------------------------------------------------
    logger.info("Step 1: Querying unclassified fund positions...")
    con = duckdb.connect()
    try:
        names_df = con.execute(f"""
            SELECT
                TRIM(issuer_name) AS issuer_name,
                COUNT(*) AS row_count,
                SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
            FROM read_csv_auto('{holdings_path}', all_varchar=true)
            WHERE issuer_category = 'FUND'
              AND index_classification = 'UNCLASSIFIED'
              AND TRIM(issuer_name) != ''
              AND issuer_name IS NOT NULL
            GROUP BY TRIM(issuer_name)
            ORDER BY total_fv DESC NULLS LAST
        """).fetchdf()
    finally:
        con.close()

    if names_df.empty:
        logger.info("  No unclassified fund positions found -- nothing to do")
        return {"auto_applied": 0, "review_needed": 0,
                "other_fund": 0, "total": 0}

    unique_names = names_df["issuer_name"].tolist()
    total_rows = int(names_df["row_count"].sum())
    total_fv = names_df["total_fv"].sum()
    logger.info("  %d unique names, %d rows, $%.1fB FV",
                len(unique_names), total_rows, total_fv / 1e9)

    # ------------------------------------------------------------------
    # Step 2: Check cache
    # ------------------------------------------------------------------
    logger.info("Step 2: Checking cache...")
    cache = _load_cache()
    uncached = [n for n in unique_names if n not in cache]
    logger.info("  %d cached, %d need classification",
                len(unique_names) - len(uncached), len(uncached))

    # ------------------------------------------------------------------
    # Step 3: Classify uncached names
    # ------------------------------------------------------------------
    if uncached:
        logger.info("Step 3: Classifying %d uncached names...", len(uncached))
        new_predictions = _classify_names(uncached)
        cache.update(new_predictions)
        _save_cache(cache)
    else:
        logger.info("Step 3: All names cached -- skipping LLM calls")

    # ------------------------------------------------------------------
    # Step 4: Split predictions into auto-apply / review / other
    # ------------------------------------------------------------------
    logger.info("Step 4: Splitting predictions...")

    auto_apply: dict[str, str] = {}
    review_names: list[str] = []
    other_count = 0

    for name in unique_names:
        pred = cache.get(name, "OTHER_FUND")
        if pred in _AUTO_APPLY_LABELS:
            auto_apply[name] = pred
        elif pred in _REVIEW_LABELS:
            review_names.append(name)
        else:
            other_count += 1

    auto_rows = int(
        names_df[names_df["issuer_name"].isin(auto_apply)]["row_count"].sum()
    )
    review_rows = int(
        names_df[names_df["issuer_name"].isin(review_names)]["row_count"].sum()
    )

    logger.info("  Auto-apply: %d names (%d rows)", len(auto_apply), auto_rows)
    for label in sorted(set(auto_apply.values())):
        n = sum(1 for v in auto_apply.values() if v == label)
        logger.info("    %s: %d names", label, n)
    logger.info("  Review needed (HF/SC): %d names (%d rows)",
                len(review_names), review_rows)
    logger.info("  OTHER_FUND (no change): %d names", other_count)

    # ------------------------------------------------------------------
    # Step 5: Apply auto-apply classifications via DuckDB
    # ------------------------------------------------------------------
    if auto_apply:
        logger.info("Step 5: Applying %d classifications to unified holdings...",
                     len(auto_apply))

        # Build mapping rows for the temp table
        mapping_rows = [
            {"issuer_name": name, "new_index_classification": label,
             "new_asset_class": _INDEX_TO_ASSET_CLASS[label]}
            for name, label in auto_apply.items()
        ]
        mapping_df = pd.DataFrame(mapping_rows)

        con = duckdb.connect()
        try:
            # Register mapping as a DuckDB table
            con.register("_llm_mapping", mapping_df)

            # Read holdings, LEFT JOIN mapping, UPDATE classification columns
            con.execute(f"""
                CREATE TABLE _holdings AS
                SELECT * FROM read_csv_auto('{holdings_path}', all_varchar=true)
            """)

            con.execute("""
                UPDATE _holdings
                SET index_classification = m.new_index_classification,
                    asset_class = m.new_asset_class
                FROM _llm_mapping m
                WHERE TRIM(_holdings.issuer_name) = m.issuer_name
                  AND _holdings.issuer_category = 'FUND'
                  AND _holdings.index_classification = 'UNCLASSIFIED'
            """)

            # Count affected rows
            affected = con.execute("""
                SELECT COUNT(*) FROM _holdings h
                INNER JOIN _llm_mapping m
                    ON TRIM(h.issuer_name) = m.issuer_name
                WHERE h.index_classification = m.new_index_classification
            """).fetchone()[0]
            logger.info("  Updated %d rows in unified holdings", affected)

            # Re-save
            con.execute(f"""
                COPY _holdings TO '{holdings_path}'
                (HEADER, DELIMITER ',')
            """)
            logger.info("  Saved -> %s", UNIFIED_HOLDINGS_FILE.name)
        finally:
            con.close()
    else:
        logger.info("Step 5: No auto-apply classifications -- skipping")

    # ------------------------------------------------------------------
    # Step 6: Write review CSV for HF/SC predictions
    # ------------------------------------------------------------------
    if review_names:
        logger.info("Step 6: Writing review file...")
        review_rows_list = []
        for name in review_names:
            row_data = names_df[names_df["issuer_name"] == name].iloc[0]
            review_rows_list.append({
                "issuer_name": name,
                "predicted_label": cache.get(name, "OTHER_FUND"),
                "row_count": int(row_data["row_count"]),
                "total_fv": row_data["total_fv"],
            })
        review_df = pd.DataFrame(review_rows_list)
        review_df = review_df.sort_values("total_fv", ascending=False)
        review_df.to_csv(LLM_FUND_CLASSIFICATION_REVIEW_FILE, index=False)
        logger.info("  Review file: %d names -> %s",
                     len(review_df), LLM_FUND_CLASSIFICATION_REVIEW_FILE.name)
    else:
        logger.info("Step 6: No HF/SC predictions -- skipping review file")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    result = {
        "auto_applied": len(auto_apply),
        "auto_applied_rows": auto_rows,
        "review_needed": len(review_names),
        "review_needed_rows": review_rows,
        "other_fund": other_count,
        "total": len(unique_names),
    }
    logger.info("")
    logger.info("Classification complete: %d auto-applied, %d review, %d other",
                result["auto_applied"], result["review_needed"],
                result["other_fund"])
    return result
