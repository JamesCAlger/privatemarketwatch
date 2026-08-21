"""Validate and clean GICS enrichment artifacts before public export.

The public contract is intentionally strict: ``gics_sub_industry`` values must
be exact names from ``data/reference/gics_sub_industries.json``. Numeric GICS
codes, stale taxonomy labels, and broad industry-group labels are not published
as sub-industry facts unless they have an unambiguous alias below.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline.config import (
    AGGREGATE_HEADER_FLAGS_FILE,
    COMPANY_GICS_CACHE_FILE,
    GICS_REFERENCE_FILE,
    OUTPUT_DIR,
    PROJECT_ROOT,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger("gics_quality_gate")

EXPECTED_AGENT_COLS = [
    "name_norm",
    "verdict",
    "gics_sub_industry",
    "confidence",
    "evidence",
]
VALID_VERDICTS = {"GICS", "AGGREGATE_HEADER", "JV_SUBSIDIARY", "UNRESOLVABLE"}
VALID_CONFIDENCE = {"high", "medium", "low"}
QUARANTINE_FILE = OUTPUT_DIR / "gics_cache_quarantine.csv"
# Campaign shards live under campaign_results/ -- relocated 2026-08-20.
GICS_CAMPAIGN_DIR = OUTPUT_DIR / "campaign_results" / "gics"

# Only aliases where the target is a direct spelling/taxonomy update or a
# one-to-one old-name-to-current-name mapping. Broad industry groups and numeric
# codes stay quarantined until reviewed with source evidence.
GICS_LABEL_ALIASES = {
    "Apparel Accessories & Luxury Goods": "Apparel, Accessories & Luxury Goods",
    "Apparel; Accessories & Luxury Goods": "Apparel, Accessories & Luxury Goods",
    "Automotive Parts & Equipment": "Automobile Parts & Equipment",
    "Auto Parts & Equipment": "Automobile Parts & Equipment",
    "Building Products & Equipment": "Building Products",
    "Industrial Machinery": "Industrial Machinery & Supplies & Components",
    "Metal & Glass Containers": "Metal, Glass & Plastic Containers",
    "Metal Glass & Plastic Containers": "Metal, Glass & Plastic Containers",
    "Metal Packaging": "Metal, Glass & Plastic Containers",
    "Multi-Family Residential REITs": "Residential REITs",
    "Other Specialty Retail": "Specialty Stores",
    "Paper Packaging": "Paper & Plastic Packaging Products & Materials",
    "Professional Services": "Research & Consulting Services",
    "Railroads": "Rail Transportation",
    "Technology Hardware": "Technology Hardware, Storage & Peripherals",
    "Technology Hardware Storage & Peripherals": "Technology Hardware, Storage & Peripherals",
}


@dataclass
class GateResult:
    name: str
    issue_count: int
    details: list[str]

    @property
    def ok(self) -> bool:
        return self.issue_count == 0


def _load_valid_gics() -> set[str]:
    with GICS_REFERENCE_FILE.open(encoding="utf-8") as fh:
        return set(json.load(fh))


def _normalize_confidence(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_CONFIDENCE else "medium"


def _is_numeric_code(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", value.strip()))


def validate_cache(path: Path = COMPANY_GICS_CACHE_FILE) -> GateResult:
    valid_gics = _load_valid_gics() | {"Other"}
    details: list[str] = []
    if not path.exists():
        return GateResult("cache", 1, [f"Missing cache file: {path}"])

    df = pd.read_csv(path, dtype=str).fillna("")
    required = {"company_name_norm", "gics_sub_industry", "confidence", "source", "timestamp"}
    missing = required - set(df.columns)
    if missing:
        details.append(f"Missing cache columns: {sorted(missing)}")

    if "gics_sub_industry" in df.columns:
        bad = df[~df["gics_sub_industry"].isin(valid_gics)]
        numeric = df[df["gics_sub_industry"].map(_is_numeric_code)]
        if len(bad):
            labels = ", ".join(sorted(bad["gics_sub_industry"].unique())[:20])
            details.append(f"{len(bad)} invalid GICS labels ({labels})")
        if len(numeric):
            details.append(f"{len(numeric)} numeric GICS code rows")

    if "confidence" in df.columns:
        bad_conf = df[~df["confidence"].isin(VALID_CONFIDENCE)]
        if len(bad_conf):
            details.append(f"{len(bad_conf)} rows with invalid confidence")

    if "company_name_norm" in df.columns:
        blank = df["company_name_norm"].astype(str).str.strip().eq("")
        if blank.any():
            details.append(f"{int(blank.sum())} blank company_name_norm rows")
        dupes = df[df.duplicated("company_name_norm", keep=False)]
        if len(dupes):
            details.append(
                f"{len(dupes)} duplicate cache rows across "
                f"{dupes['company_name_norm'].nunique()} names"
            )

    return GateResult("cache", len(details), details)


def validate_flags(path: Path = AGGREGATE_HEADER_FLAGS_FILE) -> GateResult:
    details: list[str] = []
    if not path.exists():
        return GateResult("flags", 0, [])

    df = pd.read_csv(path, dtype=str).fillna("")
    required = {"name_norm", "verdict", "confidence", "evidence"}
    missing = required - set(df.columns)
    if missing:
        details.append(f"Missing flag columns: {sorted(missing)}")
        return GateResult("flags", len(details), details)

    bad_verdict = df[~df["verdict"].isin(VALID_VERDICTS)]
    bad_conf = df[~df["confidence"].isin(VALID_CONFIDENCE)]
    blank_name = df["name_norm"].astype(str).str.strip().eq("")
    if len(bad_verdict):
        details.append(f"{len(bad_verdict)} rows with invalid verdict")
    if len(bad_conf):
        details.append(f"{len(bad_conf)} rows with invalid confidence")
    if blank_name.any():
        details.append(f"{int(blank_name.sum())} blank name_norm rows")
    return GateResult("flags", len(details), details)


def _read_strict_agent_result(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def validate_agent_result_file(
    result_path: Path,
    chunk_path: Path | None = None,
) -> GateResult:
    valid_gics = _load_valid_gics()
    details: list[str] = []
    try:
        df = _read_strict_agent_result(result_path).fillna("")
    except Exception as exc:
        return GateResult(result_path.name, 1, [f"CSV parse failed: {exc}"])

    if list(df.columns) != EXPECTED_AGENT_COLS:
        details.append(f"Unexpected columns: {list(df.columns)}")

    chunk_names: list[str] = []
    if chunk_path is None:
        suffix = result_path.stem.replace("gics_agent_results_", "")
        chunk_path = result_path.with_name(f"gics_agent_chunk_{suffix}.txt")
    if chunk_path.exists():
        chunk_names = [
            line.split("||", 1)[0]
            for line in chunk_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        details.append(f"Missing chunk file: {chunk_path.name}")

    if chunk_names and len(df) != len(chunk_names):
        details.append(f"Row count mismatch result={len(df)} chunk={len(chunk_names)}")
    if chunk_names and "name_norm" in df.columns:
        result_names = [str(v).strip() for v in df["name_norm"].tolist()]
        if result_names != chunk_names:
            details.append("name_norm sequence differs from chunk")

    if set(EXPECTED_AGENT_COLS).issubset(df.columns):
        for idx, row in df.iterrows():
            verdict = str(row["verdict"]).strip()
            gics = str(row["gics_sub_industry"]).strip()
            confidence = str(row["confidence"]).strip()
            evidence = str(row["evidence"]).strip()
            if verdict not in VALID_VERDICTS:
                details.append(f"row {idx}: invalid verdict {verdict!r}")
            if confidence not in VALID_CONFIDENCE:
                details.append(f"row {idx}: invalid confidence {confidence!r}")
            if not evidence:
                details.append(f"row {idx}: blank evidence")
            if _is_numeric_code(gics):
                details.append(f"row {idx}: numeric GICS code {gics!r}")
            if verdict == "GICS" and gics not in valid_gics:
                details.append(f"row {idx}: invalid GICS label {gics!r}")
            if verdict != "GICS" and gics:
                details.append(f"row {idx}: non-GICS verdict has label {gics!r}")

    return GateResult(result_path.name, len(details), details)


def validate_agent_results(
    output_dir: Path = GICS_CAMPAIGN_DIR,
    start: int = 0,
    end: int = 9999,
) -> list[GateResult]:
    results = []
    for path in sorted(output_dir.glob("gics_agent_results_*.csv")):
        try:
            number = int(path.stem.replace("gics_agent_results_", ""))
        except ValueError:
            continue
        if start <= number <= end:
            results.append(validate_agent_result_file(path))
    return results


def validate_public_outputs() -> GateResult:
    valid_gics = _load_valid_gics()
    details: list[str] = []

    if not UNIFIED_HOLDINGS_FILE.exists():
        details.append(f"Missing unified holdings file: {UNIFIED_HOLDINGS_FILE}")
    else:
        cols = pd.read_csv(UNIFIED_HOLDINGS_FILE, nrows=0).columns
        if "gics_sub_industry" not in cols:
            details.append("Unified holdings missing gics_sub_industry")
        else:
            df = pd.read_csv(
                UNIFIED_HOLDINGS_FILE,
                usecols=["gics_sub_industry"],
                dtype=str,
                keep_default_na=False,
            )
            labels = df["gics_sub_industry"].astype(str).str.strip()
            bad = labels[(labels != "") & ~labels.isin(valid_gics)]
            numeric = labels[labels.map(_is_numeric_code)]
            if len(bad):
                details.append(f"{len(bad)} invalid unified GICS rows")
            if len(numeric):
                details.append(f"{len(numeric)} numeric unified GICS rows")

    gics_json = PROJECT_ROOT / "frontend" / "public" / "data" / "gics_sector_breakdown.json"
    if not gics_json.exists():
        details.append(f"Missing frontend GICS export: {gics_json}")
    else:
        try:
            payload = json.loads(gics_json.read_text(encoding="utf-8"))
        except Exception as exc:
            details.append(f"Frontend GICS JSON parse failed: {exc}")
        else:
            if not isinstance(payload, list):
                details.append("Frontend GICS export is not a list")

    return GateResult("public_outputs", len(details), details)


def _deduplicate_cache(df: pd.DataFrame) -> pd.DataFrame:
    rank = {"high": 3, "medium": 2, "low": 1}
    out = df.copy()
    out["_conf_rank"] = out["confidence"].map(rank).fillna(0)
    out["_is_other"] = (out["gics_sub_industry"] == "Other").astype(int)
    out = out.sort_values(
        ["company_name_norm", "_is_other", "_conf_rank"],
        ascending=[True, True, False],
    )
    out = out.drop_duplicates("company_name_norm", keep="first")
    return out.drop(columns=["_conf_rank", "_is_other"])


def clean_cache(path: Path = COMPANY_GICS_CACHE_FILE, apply: bool = False) -> dict[str, int]:
    valid_gics = _load_valid_gics() | {"Other"}
    df = pd.read_csv(path, dtype=str).fillna("")
    for col in ["company_name_norm", "gics_sub_industry", "confidence", "source", "timestamp"]:
        if col not in df.columns:
            df[col] = ""

    now = datetime.now(timezone.utc).isoformat()
    kept_rows = []
    quarantine_rows = []
    alias_count = 0
    confidence_fixed = 0

    for _, row in df.iterrows():
        rec = row.to_dict()
        rec["company_name_norm"] = str(rec.get("company_name_norm", "")).strip()
        rec["gics_sub_industry"] = str(rec.get("gics_sub_industry", "")).strip()
        rec["confidence"] = str(rec.get("confidence", "")).strip()
        original_gics = rec["gics_sub_industry"]
        original_confidence = rec["confidence"]

        normalized_conf = _normalize_confidence(original_confidence)
        if normalized_conf != original_confidence:
            confidence_fixed += 1
        rec["confidence"] = normalized_conf

        if original_gics in valid_gics:
            kept_rows.append(rec)
            continue

        alias = GICS_LABEL_ALIASES.get(original_gics)
        if alias and alias in valid_gics:
            rec["gics_sub_industry"] = alias
            kept_rows.append(rec)
            alias_count += 1
            continue

        reason = "numeric_code" if _is_numeric_code(original_gics) else "invalid_or_ambiguous_label"
        quarantine = rec.copy()
        quarantine["original_gics_sub_industry"] = original_gics
        quarantine["original_confidence"] = original_confidence
        quarantine["quarantine_reason"] = reason
        quarantine["quarantined_at"] = now
        quarantine_rows.append(quarantine)

    cleaned = pd.DataFrame(kept_rows)
    cleaned = cleaned[["company_name_norm", "gics_sub_industry", "confidence", "source", "timestamp"]]
    cleaned = cleaned[cleaned["company_name_norm"].astype(str).str.strip().ne("")]
    cleaned = _deduplicate_cache(cleaned)

    if apply:
        cleaned.to_csv(path, index=False)
        if quarantine_rows:
            quarantine_df = pd.DataFrame(quarantine_rows)
            if QUARANTINE_FILE.exists():
                existing = pd.read_csv(QUARANTINE_FILE, dtype=str).fillna("")
                quarantine_df = pd.concat([existing, quarantine_df], ignore_index=True)
                quarantine_df = quarantine_df.drop_duplicates(
                    ["company_name_norm", "original_gics_sub_industry", "quarantine_reason"],
                    keep="last",
                )
            quarantine_df.to_csv(QUARANTINE_FILE, index=False)

    return {
        "input_rows": len(df),
        "output_rows": len(cleaned),
        "aliased_rows": alias_count,
        "quarantined_rows": len(quarantine_rows),
        "confidence_fixed_rows": confidence_fixed,
    }


def clean_flags(path: Path = AGGREGATE_HEADER_FLAGS_FILE, apply: bool = False) -> dict[str, int]:
    if not path.exists():
        return {"input_rows": 0, "confidence_fixed_rows": 0}
    df = pd.read_csv(path, dtype=str).fillna("")
    for col in ["name_norm", "verdict", "confidence", "evidence"]:
        if col not in df.columns:
            df[col] = ""

    before = df["confidence"].copy()
    df["confidence"] = df["confidence"].map(_normalize_confidence)
    fixed = int((before != df["confidence"]).sum())
    df["name_norm"] = df["name_norm"].astype(str).str.strip().str.lower()
    df = df[df["name_norm"].ne("")]

    if apply:
        df.to_csv(path, index=False)

    return {"input_rows": len(before), "output_rows": len(df), "confidence_fixed_rows": fixed}


def _print_result(result: GateResult) -> None:
    if result.ok:
        logger.info("%s: PASS", result.name)
        return
    logger.error("%s: FAIL (%d issue groups)", result.name, result.issue_count)
    for detail in result.details[:40]:
        logger.error("  %s", detail)
    if len(result.details) > 40:
        logger.error("  ... and %d more", len(result.details) - 40)


def main() -> None:
    parser = argparse.ArgumentParser(description="GICS public-readiness quality gate")
    parser.add_argument("--clean", action="store_true", help="Clean cache and flags in place")
    parser.add_argument("--validate", action="store_true", help="Validate cache, flags, and public outputs")
    parser.add_argument("--validate-agent-results", action="store_true", help="Validate agent result files")
    parser.add_argument("--range", nargs=2, type=int, metavar=("START", "END"), default=None)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.clean:
        logger.info("Cleaning GICS cache...")
        cache_summary = clean_cache(apply=True)
        logger.info("Cache cleanup: %s", cache_summary)
        flag_summary = clean_flags(apply=True)
        logger.info("Flag cleanup: %s", flag_summary)

    failed = False
    if args.validate or not any([args.clean, args.validate_agent_results]):
        for result in [validate_cache(), validate_flags(), validate_public_outputs()]:
            _print_result(result)
            failed = failed or not result.ok

    if args.validate_agent_results:
        start, end = args.range if args.range else (0, 9999)
        results = validate_agent_results(start=start, end=end)
        failed_files = [r for r in results if not r.ok]
        logger.info(
            "Agent result validation: %d files checked, %d passed, %d failed",
            len(results),
            len(results) - len(failed_files),
            len(failed_files),
        )
        for result in failed_files[:40]:
            _print_result(result)
        if len(failed_files) > 40:
            logger.error("... and %d more failed files", len(failed_files) - 40)
        failed = failed or bool(failed_files)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
