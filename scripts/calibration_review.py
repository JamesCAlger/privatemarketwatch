"""Position match calibration sample & review protocol.

Generates a stratified calibration sample of position matches, assembles
self-contained per-CIK review bundles with portfolio context, and computes
calibration metrics from collected verdicts.

Subcommands:
    (default)    Generate sample + bundles + print summary
    --generate   Same as default
    --dry-run    Show sample allocation only
    --status     Show progress: total/reviewed/pending batches, per-tier counts
    --collect    Read verdict JSONs, merge into sample CSV, compute calibration metrics
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline import config
from scripts.spot_check_position_matching import (
    REVIEW_LABELS,
    TIER_ORDER,
    _apply_heuristic_flags,
    build_audit_frame,
    compute_weighted_error_estimate,
    error_rate_by_tier,
    flag_vs_actual_correlation,
    render_review_summary,
)

logger = logging.getLogger("calibration_review")

SEED = 20260610
BATCH_SIZE = 5

# Custom allocation overweighting lower tiers where errors concentrate
CALIBRATION_ALLOCATION: dict[str, int] = {
    "A_within_filing": 40,
    "B1b_position_key": 40,
    "B2_exact_name": 200,
    "C_normalized_name": 80,
    "D_fuzzy": 150,
    "E_entity_fingerprint": 90,
}
TARGET_TOTAL = sum(CALIBRATION_ALLOCATION.values())  # 600

# Output paths
CALIBRATION_DIR = config.OUTPUT_DIR / "position_match_calibration"
SAMPLE_FILE = CALIBRATION_DIR / "sample.csv"
BUNDLES_DIR = CALIBRATION_DIR / "bundles"
VERDICTS_DIR = CALIBRATION_DIR / "verdicts"
BATCH_MANIFEST_FILE = CALIBRATION_DIR / "batch_manifest.csv"
CALIBRATION_SUMMARY_FILE = CALIBRATION_DIR / "calibration_summary.md"

# Context columns included in portfolio context for each holding
CONTEXT_COLUMNS = [
    "issuer_name",
    "bdc_investment_identifier",
    "instrument_description",
    "fair_value",
    "cost",
    "interest_rate",
    "principal_amount",
    "maturity_date",
    "lien_position",
    "index_classification",
    "coupon_type",
    "position_key",
    "cusip",
    "accession_number",
]

# Max non-entity context holdings per report_date (beyond same-entity matches)
MAX_EXTRA_CONTEXT = 20


def _csv_rel(path: Path) -> str:
    return path.as_posix().replace("'", "''")


def _normalize_date(d) -> str:
    """Normalize a date value to YYYY-MM-DD string."""
    s = str(d).strip()
    # Strip timestamp suffix like " 00:00:00"
    if " " in s:
        s = s.split(" ")[0]
    return s


def generate_calibration_sample(
    matches_path: Path = config.POSITION_MATCHES_FILE,
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
) -> pd.DataFrame:
    """Generate a stratified calibration sample with custom allocation."""
    audit_df = build_audit_frame(matches_path, holdings_path)
    if audit_df.empty:
        logger.error("Audit frame is empty -- no matches to sample")
        return pd.DataFrame()

    # Deduplicate by sample_row_key
    if audit_df["sample_row_key"].duplicated().any():
        dupes = int(audit_df["sample_row_key"].duplicated().sum())
        logger.warning("Deduplicating %d duplicate sample_row_key values", dupes)
        audit_df = audit_df.drop_duplicates(subset=["sample_row_key"])

    stratum_sizes = audit_df.groupby("match_method", dropna=False).size().to_dict()

    # Apply custom allocation, capping at population size
    allocation: dict[str, int] = {}
    for tier, target in CALIBRATION_ALLOCATION.items():
        pop = stratum_sizes.get(tier, 0)
        if pop == 0:
            continue
        allocation[tier] = min(target, pop)

    parts = []
    for stratum, sample_n in allocation.items():
        group = audit_df[audit_df["match_method"] == stratum].copy()
        if group.empty:
            continue
        # Deterministic hash-based selection
        group["_sort_key"] = group["sample_row_key"].map(
            lambda value, s=SEED: hashlib.sha256(
                f"{s}|{value}".encode("utf-8")
            ).hexdigest()
        )
        parts.append(group.sort_values("_sort_key", kind="mergesort").head(sample_n))

    if not parts:
        return pd.DataFrame()

    sample = pd.concat(parts, ignore_index=True)
    observed_sizes = sample.groupby("match_method", dropna=False).size().to_dict()
    sample["sample_seed"] = SEED
    sample["stratum_size"] = sample["match_method"].map(stratum_sizes).astype("int64")
    sample["stratum_sample_size"] = (
        sample["match_method"].map(observed_sizes).astype("int64")
    )
    sample["inclusion_weight"] = sample["stratum_size"] / sample["stratum_sample_size"]

    # Apply heuristic flags
    sample = _apply_heuristic_flags(sample)

    # Add blank review columns
    for col in ("review_label", "review_confidence", "evidence_summary"):
        sample[col] = ""

    sample = sample.drop(
        columns=[c for c in sample.columns if c.startswith("_")], errors="ignore"
    )

    return (
        sample.sort_values(["match_method", "sample_row_key"])
        .reset_index(drop=True)
    )


def _build_portfolio_context(
    cik: str,
    report_dates: list[str],
    entity_names: set[str],
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
) -> dict[str, list[dict]]:
    """Build portfolio context for a CIK at given report dates.

    Returns same-entity positions plus up to MAX_EXTRA_CONTEXT additional
    positions sorted by FV descending. Entity matching uses substring/prefix
    matching because BDC issuer_name fields are often sector-prefixed
    identifiers (e.g., "Consumer Goods Non-durable Sequential Brands...").
    """
    con = duckdb.connect()
    holdings_csv = _csv_rel(holdings_path)
    # Normalize dates to YYYY-MM-DD for matching against holdings
    report_dates = [_normalize_date(d) for d in report_dates]
    date_list = ", ".join(f"'{d}'" for d in report_dates)

    # Build entity-match clauses using substring containment.
    # BDC issuer_name in unified holdings can be sector-prefixed, so we
    # check if the holdings issuer_name contains the match-side name as
    # a substring, or vice versa.
    entity_like_clauses = []
    for name in entity_names:
        safe_name = name.replace("'", "''").strip().lower()
        if not safe_name or len(safe_name) < 3:
            continue
        escaped = safe_name.replace("%", "\\%").replace("_", "\\_")
        entity_like_clauses.append(
            f"LOWER(TRIM(CAST(issuer_name AS VARCHAR))) LIKE '%{escaped}%' ESCAPE '\\'"
        )
        entity_like_clauses.append(
            f"LOWER('{safe_name}') LIKE '%' || LOWER(TRIM(CAST(issuer_name AS VARCHAR))) || '%'"
        )

    # Load all holdings for this CIK at these dates
    base_sql = f"""
    SELECT *
    FROM read_csv_auto('{holdings_csv}', all_varchar=false)
    WHERE CAST(source AS VARCHAR) = 'bdc'
      AND lpad(regexp_replace(CAST(cik AS VARCHAR), '^0+', ''), 10, '0')
          = lpad('{cik.lstrip("0")}', 10, '0')
      AND CAST(report_date AS VARCHAR) IN ({date_list})
    """

    try:
        all_holdings = con.execute(base_sql).fetchdf()
    finally:
        con.close()

    if all_holdings.empty:
        return {rd: [] for rd in report_dates}

    # Tag same-entity rows using Python (more robust than SQL LIKE for
    # complex entity names with special characters)
    lower_names = {n.strip().lower() for n in entity_names if n.strip()}

    def _is_same_entity(issuer: str) -> bool:
        if pd.isna(issuer):
            return False
        issuer_lower = str(issuer).strip().lower()
        for name in lower_names:
            if name in issuer_lower or issuer_lower in name:
                return True
        return False

    all_holdings["_is_same_entity"] = all_holdings["issuer_name"].map(_is_same_entity)

    context: dict[str, list[dict]] = {}
    for rd in report_dates:
        rd_rows = all_holdings[
            all_holdings["report_date"].astype(str).map(_normalize_date) == rd
        ]
        # Same-entity first, then extras capped at MAX_EXTRA_CONTEXT
        same = rd_rows[rd_rows["_is_same_entity"]]
        other = rd_rows[~rd_rows["_is_same_entity"]].sort_values(
            by="fair_value",
            key=lambda s: pd.to_numeric(s, errors="coerce").abs(),
            ascending=False,
        ).head(MAX_EXTRA_CONTEXT)
        rd_combined = pd.concat([same, other], ignore_index=True)

        holdings_list = []
        for _, row in rd_combined.iterrows():
            holding = {}
            for col in CONTEXT_COLUMNS:
                val = row.get(col)
                if pd.isna(val):
                    holding[col] = None
                else:
                    holding[col] = val
            holdings_list.append(holding)
        context[rd] = holdings_list

    return context


def _get_filing_paths(
    cik: str,
    report_dates: list[str],
    filings_index_path: Path = config.BDC_FILINGS_INDEX_FILE,
) -> dict[str, str]:
    """Look up filing paths from the BDC filings index."""
    if not filings_index_path.exists():
        return {}

    con = duckdb.connect()
    filings_csv = _csv_rel(filings_index_path)
    report_dates = [_normalize_date(d) for d in report_dates]
    date_list = ", ".join(f"'{d}'" for d in report_dates)

    try:
        sql = f"""
        SELECT
            CAST(report_date AS VARCHAR) AS report_date,
            CAST(xbrl_local_path AS VARCHAR) AS xbrl_local_path
        FROM read_csv_auto('{filings_csv}', all_varchar=false)
        WHERE lpad(regexp_replace(CAST(cik AS VARCHAR), '^0+', ''), 10, '0')
              = lpad('{cik.lstrip("0")}', 10, '0')
          AND CAST(report_date AS VARCHAR) IN ({date_list})
        ORDER BY report_date
        """
        df = con.execute(sql).fetchdf()
    finally:
        con.close()

    paths: dict[str, str] = {}
    for _, row in df.iterrows():
        rd = str(row["report_date"])
        lp = row.get("xbrl_local_path")
        if pd.notna(lp) and str(lp).strip():
            paths[rd] = str(lp)

    return paths


def build_review_bundles(
    sample_df: pd.DataFrame,
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
) -> pd.DataFrame:
    """Group sample into CIK batches and write self-contained review bundles.

    Returns the batch manifest as a DataFrame.
    """
    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    batch_num = 0

    # Group by CIK
    for cik, cik_group in sample_df.groupby("cik", dropna=False):
        cik_str = str(cik).zfill(10)
        entity_name = str(cik_group["entity_name"].iloc[0])

        # Split into batches of BATCH_SIZE
        for chunk_start in range(0, len(cik_group), BATCH_SIZE):
            batch_num += 1
            chunk = cik_group.iloc[chunk_start:chunk_start + BATCH_SIZE]
            batch_id = f"BATCH_{batch_num:03d}_{cik_str}"

            # Collect unique report dates and entity names from this batch
            report_dates = set()
            entity_names = set()
            for _, row in chunk.iterrows():
                for side in ("begin", "end"):
                    rd = row.get(f"{side}_report_date")
                    if pd.notna(rd):
                        report_dates.add(_normalize_date(rd))
                    name = row.get(f"{side}_issuer_name")
                    if pd.notna(name) and str(name).strip():
                        entity_names.add(str(name).strip())

            report_dates_list = sorted(report_dates)

            # Build match pairs
            match_pairs = []
            for pair_idx, (_, row) in enumerate(chunk.iterrows(), 1):
                pair = {
                    "pair_index": pair_idx,
                    "sample_row_key": str(row.get("sample_row_key", "")),
                    "match_method": str(row.get("match_method", "")),
                    "match_score": _safe_json_val(row.get("match_score")),
                    "span_months": _safe_json_val(row.get("span_months")),
                    "begin": _extract_side(row, "begin"),
                    "end": _extract_side(row, "end"),
                    "heuristic_flags": {
                        "flag_fv_ratio_extreme": bool(row.get("flag_fv_ratio_extreme", False)),
                        "flag_name_divergence": bool(row.get("flag_name_divergence", False)),
                        "flag_classification_flip": bool(row.get("flag_classification_flip", False)),
                        "flag_rate_discontinuity": bool(row.get("flag_rate_discontinuity", False)),
                        "flag_maturity_mismatch": bool(row.get("flag_maturity_mismatch", False)),
                        "flag_principal_ratio_extreme": bool(row.get("flag_principal_ratio_extreme", False)),
                        "flag_count": int(row.get("flag_count", 0)),
                        "programmatic_verdict": str(row.get("programmatic_verdict", "")),
                    },
                }
                match_pairs.append(pair)

            # Build portfolio context
            portfolio_context = _build_portfolio_context(
                cik_str, report_dates_list, entity_names, holdings_path
            )

            # Look up filing paths
            filing_paths = _get_filing_paths(cik_str, report_dates_list)

            bundle = {
                "batch_id": batch_id,
                "cik": cik_str,
                "entity_name": entity_name,
                "match_count": len(match_pairs),
                "review_instructions": (
                    "For each match pair, determine whether the begin and end "
                    "positions are the SAME financial instrument tracked across "
                    "quarters. See prompts/position_match_calibration_prompt.md "
                    "for full review protocol."
                ),
                "match_pairs": match_pairs,
                "portfolio_context": portfolio_context,
                "filing_paths": filing_paths,
            }

            bundle_path = BUNDLES_DIR / f"{batch_id}.json"
            bundle_path.write_text(
                json.dumps(bundle, indent=2, default=str), encoding="utf-8"
            )

            manifest_rows.append({
                "batch_id": batch_id,
                "cik": cik_str,
                "entity_name": entity_name,
                "match_count": len(match_pairs),
                "status": "pending",
            })

    manifest_df = pd.DataFrame(manifest_rows)
    manifest_df.to_csv(BATCH_MANIFEST_FILE, index=False)
    logger.info(
        "Wrote %d bundles to %s and manifest to %s",
        len(manifest_rows), BUNDLES_DIR, BATCH_MANIFEST_FILE,
    )
    return manifest_df


def _extract_side(row: pd.Series, side: str) -> dict:
    """Extract begin or end side attributes from a sample row."""
    fields = [
        "report_date", "issuer_name", "bdc_investment_identifier",
        "instrument_description", "fair_value", "interest_rate",
        "principal_amount", "maturity_date", "index_classification",
        "position_key", "cusip",
    ]
    result = {}
    for field in fields:
        col = f"{side}_{field}"
        val = row.get(col)
        result[field] = _safe_json_val(val)
    return result


def _safe_json_val(val):
    """Convert a value to a JSON-safe type."""
    if pd.isna(val):
        return None
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    return str(val)


def show_status() -> int:
    """Show progress of calibration review."""
    if not BATCH_MANIFEST_FILE.exists():
        print("No calibration sample generated yet. Run without --status first.")
        return 1

    manifest = pd.read_csv(BATCH_MANIFEST_FILE)
    total_batches = len(manifest)

    # Check which batches have verdicts
    reviewed_batches = 0
    reviewed_pairs = 0
    pending_batches = 0
    if VERDICTS_DIR.exists():
        verdict_files = list(VERDICTS_DIR.glob("BATCH_*.json"))
        reviewed_batch_ids = set()
        for vf in verdict_files:
            try:
                vdata = json.loads(vf.read_text(encoding="utf-8"))
                reviewed_batch_ids.add(vdata.get("batch_id", ""))
                reviewed_pairs += len(vdata.get("verdicts", []))
            except (json.JSONDecodeError, KeyError):
                logger.warning("Could not parse verdict file: %s", vf)
        reviewed_batches = len(
            reviewed_batch_ids & set(manifest["batch_id"])
        )

    pending_batches = total_batches - reviewed_batches

    # Load sample for per-tier stats
    if SAMPLE_FILE.exists():
        sample = pd.read_csv(SAMPLE_FILE)
        total_pairs = len(sample)
    else:
        total_pairs = int(manifest["match_count"].sum())

    print(f"\n{'='*60}")
    print("CALIBRATION REVIEW STATUS")
    print(f"{'='*60}")
    print(f"\nBatches: {reviewed_batches}/{total_batches} reviewed, {pending_batches} pending")
    print(f"Match pairs: {reviewed_pairs}/{total_pairs} reviewed")

    if SAMPLE_FILE.exists():
        sample = pd.read_csv(SAMPLE_FILE)
        print(f"\nPer-tier sample allocation:")
        for tier in TIER_ORDER:
            tier_rows = sample[sample["match_method"] == tier]
            if tier_rows.empty:
                continue
            n = len(tier_rows)
            pop = int(tier_rows["stratum_size"].iloc[0]) if "stratum_size" in tier_rows.columns else 0
            print(f"  {tier:25s}: {n:4d} / {pop:6d}")

    print(f"\n{'='*60}\n")
    return 0


def collect_verdicts() -> int:
    """Read verdict JSONs, merge into sample, compute calibration metrics."""
    if not SAMPLE_FILE.exists():
        print("No sample file found. Run --generate first.")
        return 1

    if not VERDICTS_DIR.exists() or not list(VERDICTS_DIR.glob("BATCH_*.json")):
        print("No verdict files found in", VERDICTS_DIR)
        return 1

    sample = pd.read_csv(SAMPLE_FILE)

    # Collect all verdicts
    all_verdicts: dict[str, dict] = {}  # sample_row_key -> verdict
    verdict_files = sorted(VERDICTS_DIR.glob("BATCH_*.json"))
    for vf in verdict_files:
        try:
            vdata = json.loads(vf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Could not parse %s: %s", vf, exc)
            continue
        for v in vdata.get("verdicts", []):
            key = v.get("sample_row_key", "")
            if key:
                all_verdicts[key] = v

    if not all_verdicts:
        print("No valid verdicts found.")
        return 1

    # Ensure review columns are string dtype before merging
    for col in ("review_label", "review_confidence", "evidence_summary"):
        sample[col] = sample[col].fillna("").astype(str)

    # Merge verdicts into sample
    for idx, row in sample.iterrows():
        key = str(row.get("sample_row_key", ""))
        if key in all_verdicts:
            verdict = all_verdicts[key]
            sample.at[idx, "review_label"] = verdict.get("review_label", "")
            sample.at[idx, "review_confidence"] = verdict.get("review_confidence", "")
            sample.at[idx, "evidence_summary"] = verdict.get("evidence_summary", "")

    # Save updated sample
    sample.to_csv(SAMPLE_FILE, index=False)
    logger.info("Merged %d verdicts into %s", len(all_verdicts), SAMPLE_FILE)

    # Compute metrics
    reviewed = sample[
        sample["review_label"].fillna("").astype(str).str.strip().str.len() > 0
    ]
    if reviewed.empty:
        print("No reviewed rows after merge.")
        return 1

    print(f"\n{'='*60}")
    print("CALIBRATION RESULTS")
    print(f"{'='*60}")

    # Overall estimate
    estimate = compute_weighted_error_estimate(sample)
    print(f"\nReviewed rows: {estimate['reviewed_rows']}")
    print(f"Rows in point estimate: {estimate.get('estimate_rows', 'n/a')}")
    print(f"Ambiguous rows excluded: {estimate.get('ambiguous_rows', 'n/a')}")
    wr = estimate["weighted_error_rate"]
    if not math.isnan(wr):
        print(f"Weighted error rate: {wr:.1%}")
        print(f"95% CI: {estimate['ci95_low']:.1%} to {estimate['ci95_high']:.1%}")
    else:
        print("Weighted error rate: n/a")

    # Per-tier breakdown
    by_tier = error_rate_by_tier(sample)
    print(f"\nError rate by tier:")
    print(f"  {'Tier':25s} {'Reviewed':>10s} {'Errors':>8s} {'Rate':>8s}")
    print(f"  {'-'*55}")
    for _, tr in by_tier.iterrows():
        rate_str = f"{tr['error_rate']:.1%}" if not pd.isna(tr["error_rate"]) else "n/a"
        print(
            f"  {tr['match_method']:25s} "
            f"{int(tr['reviewed_rows']):10d} "
            f"{int(tr['error_rows']):8d} "
            f"{rate_str:>8s}"
        )

    # Flag correlation
    flag_corr = flag_vs_actual_correlation(sample)
    print(f"\nFlag vs actual error correlation:")
    print(f"  {'Flag':30s} {'Flagged':>8s} {'Err%':>8s} {'Unflagged':>10s} {'Err%':>8s}")
    print(f"  {'-'*68}")
    for _, fr in flag_corr.iterrows():
        f_rate = f"{fr['flag_true_error_rate']:.1%}" if not pd.isna(fr["flag_true_error_rate"]) else "n/a"
        u_rate = f"{fr['flag_false_error_rate']:.1%}" if not pd.isna(fr["flag_false_error_rate"]) else "n/a"
        print(
            f"  {fr['flag']:30s} "
            f"{int(fr['flag_true_count']):8d} "
            f"{f_rate:>8s} "
            f"{int(fr['flag_false_count']):10d} "
            f"{u_rate:>8s}"
        )

    # Verdict label distribution
    label_counts = (
        sample["review_label"]
        .fillna("")
        .replace("", "unreviewed")
        .value_counts()
    )
    print(f"\nVerdict distribution:")
    for label, count in label_counts.items():
        print(f"  {label:25s}: {count:4d}")

    # Write calibration summary markdown
    summary_text = _render_calibration_summary(sample, estimate, by_tier, flag_corr)
    CALIBRATION_SUMMARY_FILE.write_text(summary_text, encoding="utf-8")
    logger.info("Wrote calibration summary to %s", CALIBRATION_SUMMARY_FILE)
    print(f"\nCalibration summary written to {CALIBRATION_SUMMARY_FILE}")
    print(f"\n{'='*60}\n")

    return 0


def _render_calibration_summary(
    sample: pd.DataFrame,
    estimate: dict,
    by_tier: pd.DataFrame,
    flag_corr: pd.DataFrame,
) -> str:
    """Render calibration results as markdown."""
    def pct(v: float) -> str:
        if pd.isna(v) or math.isnan(v):
            return "n/a"
        return f"{v:.1%}"

    def table(frame: pd.DataFrame) -> str:
        if frame.empty:
            return "(no data)"
        safe = frame.copy()
        for col in safe.columns:
            safe[col] = safe[col].map(lambda v: "" if pd.isna(v) else str(v))
        header = "| " + " | ".join(map(str, safe.columns)) + " |"
        separator = "| " + " | ".join("---" for _ in safe.columns) + " |"
        body = [
            "| " + " | ".join(row) + " |"
            for row in safe.astype(str).values.tolist()
        ]
        return "\n".join([header, separator, *body])

    reviewed_count = estimate.get("reviewed_rows", 0)
    total_count = len(sample)
    label_counts = (
        sample["review_label"]
        .fillna("")
        .replace("", "unreviewed")
        .value_counts()
        .reset_index()
    )
    label_counts.columns = ["review_label", "rows"]

    lines = [
        "# Position Match Calibration Results",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Sample: {total_count} match pairs, {reviewed_count} reviewed",
        "",
        "## Overall Weighted Error Estimate",
        "",
        f"- Reviewed rows: {estimate['reviewed_rows']}",
        f"- Rows in point estimate: {estimate.get('estimate_rows', 'n/a')}",
        f"- Ambiguous rows excluded: {estimate.get('ambiguous_rows', 'n/a')}",
        f"- **Weighted error rate: {pct(float(estimate['weighted_error_rate']))}**",
        f"- 95% CI: {pct(float(estimate['ci95_low']))} to {pct(float(estimate['ci95_high']))}",
        "",
        "## Verdict Distribution",
        "",
        table(label_counts),
        "",
        "## Error Rate by Tier",
        "",
        table(by_tier),
        "",
        "## Flag vs Actual Error Correlation",
        "",
        table(flag_corr),
        "",
        "## Methodology",
        "",
        "Stratified random sample with custom allocation overweighting lower-confidence",
        "tiers (C, D, E). Deterministic hash-based selection with seed %d." % SEED,
        "Weighted error rate uses stratified Horvitz-Thompson estimator with",
        "finite population correction and Wald 95%% confidence intervals.",
        "",
        "### Sample Allocation",
        "",
        "| Tier | Target | Rationale |",
        "| --- | --- | --- |",
        "| A_within_filing | 40 | Floor -- baseline calibration |",
        "| B1b_position_key | 40 | Floor -- baseline |",
        "| B2_exact_name | 200 | Primary target -- tiebreaker logic |",
        "| C_normalized_name | 80 | High error rate, near-census |",
        "| D_fuzzy | 150 | Fuzzy matches need ground truth |",
        "| E_entity_fingerprint | 90 | Least reliable tier |",
        "",
    ]
    return "\n".join(lines)


def print_generation_summary(sample: pd.DataFrame, manifest: pd.DataFrame) -> None:
    """Print summary after generating sample and bundles."""
    n = len(sample)
    print(f"\n{'='*60}")
    print("CALIBRATION SAMPLE GENERATED")
    print(f"{'='*60}")
    print(f"\nTotal sampled matches: {n}")
    print(f"Bundles created: {len(manifest)}")

    # Per-tier allocation
    print(f"\nSample allocation by tier:")
    for tier in TIER_ORDER:
        tier_rows = sample[sample["match_method"] == tier]
        if tier_rows.empty:
            continue
        nt = len(tier_rows)
        pop = int(tier_rows["stratum_size"].iloc[0])
        target = CALIBRATION_ALLOCATION.get(tier, 0)
        print(f"  {tier:25s}: {nt:4d} / {pop:6d} (target {target}, weight {pop/nt:.1f}x)")

    # Programmatic verdict distribution
    if "programmatic_verdict" in sample.columns:
        verdict_counts = sample["programmatic_verdict"].value_counts()
        print(f"\nProgrammatic verdict distribution:")
        for verdict in ["likely_correct", "suspect", "likely_error"]:
            count = verdict_counts.get(verdict, 0)
            pct = 100 * count / n if n else 0
            print(f"  {verdict:20s}: {count:4d} ({pct:5.1f}%)")

    print(f"\nOutput files:")
    print(f"  Sample CSV:      {SAMPLE_FILE}")
    print(f"  Bundles:         {BUNDLES_DIR}/")
    print(f"  Batch manifest:  {BATCH_MANIFEST_FILE}")
    print(f"  Verdicts dir:    {VERDICTS_DIR}/ (write verdicts here)")
    print(f"\n{'='*60}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generate", action="store_true", default=False,
        help="Generate sample + bundles (default action)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show sample allocation only, no output written",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show progress of calibration review",
    )
    parser.add_argument(
        "--collect", action="store_true",
        help="Read verdict JSONs, merge into sample, compute calibration metrics",
    )
    parser.add_argument(
        "--matches", type=Path, default=config.POSITION_MATCHES_FILE,
        help="Path to position_matches.csv",
    )
    parser.add_argument(
        "--holdings", type=Path, default=config.UNIFIED_HOLDINGS_FILE,
        help="Path to private_markets_holdings.csv",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.status:
        return show_status()

    if args.collect:
        return collect_verdicts()

    if args.dry_run:
        audit_df = build_audit_frame(args.matches, args.holdings)
        stratum_sizes = (
            audit_df.groupby("match_method", dropna=False).size().to_dict()
        )
        total = sum(stratum_sizes.values())

        # Apply custom allocation
        allocation: dict[str, int] = {}
        for tier, target in CALIBRATION_ALLOCATION.items():
            pop = stratum_sizes.get(tier, 0)
            if pop == 0:
                continue
            allocation[tier] = min(target, pop)

        print(f"\nDry run: {total:,} total matches across {len(stratum_sizes)} tiers")
        print(f"Target sample: {TARGET_TOTAL}\n")
        print(f"{'Tier':25s} {'Population':>10s} {'Target':>8s} {'Actual':>8s} {'Weight':>8s}")
        print("-" * 65)
        for tier in TIER_ORDER:
            if tier in stratum_sizes:
                pop = stratum_sizes[tier]
                target = CALIBRATION_ALLOCATION.get(tier, 0)
                actual = allocation.get(tier, 0)
                weight = f"{pop / actual:.1f}x" if actual else "n/a"
                print(f"{tier:25s} {pop:10,d} {target:8d} {actual:8d} {weight:>8s}")
        print("-" * 65)
        actual_total = sum(allocation.values())
        print(f"{'TOTAL':25s} {total:10,d} {TARGET_TOTAL:8d} {actual_total:8d}")
        print()
        return 0

    # Default: generate sample + bundles
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    BUNDLES_DIR.mkdir(parents=True, exist_ok=True)
    VERDICTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Generating calibration sample...")
    sample = generate_calibration_sample(args.matches, args.holdings)
    if sample.empty:
        logger.error("No sample generated")
        return 1

    sample.to_csv(SAMPLE_FILE, index=False)
    logger.info("Wrote %d sample rows to %s", len(sample), SAMPLE_FILE)

    logger.info("Building review bundles...")
    manifest = build_review_bundles(sample, args.holdings)

    print_generation_summary(sample, manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
