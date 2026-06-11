"""Quality gate for the v1 39-wrapper BDC cohort.

This gate is intentionally cohort-specific.  It answers whether the public v1
sample is clean enough to ship, without requiring every platform-wide WARN to
be resolved first.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from pipeline.config import (
    HOLDINGS_GAV_RECONCILIATION_FILE,
    OUTPUT_DIR,
    SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE,
    VALIDATE_ALL_RESIDUAL_SUMMARY_FILE,
    VALIDATION_RULES_AGGREGATE_FILE,
)
from pipeline.export.helpers import FRONTEND_DATA_DIR

DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "data"
    / "overrides"
    / "wrapper_cohorts"
    / "v1_39_wrapper_manifest.json"
)
DEFAULT_CSV_OUT = OUTPUT_DIR / "wrapper_v1_quality_gate.csv"
DEFAULT_MD_OUT = OUTPUT_DIR / "wrapper_v1_quality_gate.md"
FRONTEND_FUND_LIST_FILE = FRONTEND_DATA_DIR / "fund_list.json"

PASSING_PUBLIC_GAV = {"PASS", "SKIP", ""}

GATE_COLUMNS = [
    "cohort_id",
    "cohort_basis",
    "cohort_rank",
    "cik",
    "wrapper_file",
    "frontend_present",
    "frontend_validation_tier",
    "frontend_gav_status",
    "latest_source_residual_report_date",
    "latest_source_blocking_issue_count",
    "all_period_source_blocking_issue_count",
    "validation_residual_issue_count",
    "validation_residual_fail_count",
    "latest_gav_report_date",
    "latest_gav_flag",
    "latest_gav_reconciliation_status",
    "latest_gav_ratio_adjusted",
    "promoted_rule_fail_count",
    "status",
    "blocking_reasons",
]


@dataclass(frozen=True)
class CohortEntry:
    rank: int
    cik: str
    wrapper_file: str


def _norm_cik(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.zfill(10)


def load_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[dict[str, Any], list[CohortEntry]]:
    with path.open(encoding="utf-8") as fh:
        manifest = json.load(fh)

    if manifest.get("schema_version") != "wrapper-cohort-manifest.v1":
        raise ValueError(f"Unsupported wrapper cohort manifest schema: {manifest.get('schema_version')}")

    entries = [
        CohortEntry(
            rank=int(entry["rank"]),
            cik=_norm_cik(entry["cik"]),
            wrapper_file=str(entry.get("wrapper_file", "")).strip(),
        )
        for entry in manifest.get("entries", [])
    ]
    ciks = [entry.cik for entry in entries]
    if len(entries) != 39:
        raise ValueError(f"Expected 39 cohort entries, found {len(entries)}")
    if len(set(ciks)) != len(ciks):
        raise ValueError("Duplicate CIKs in wrapper cohort manifest")
    if any(not cik for cik in ciks):
        raise ValueError("Blank CIK in wrapper cohort manifest")
    return manifest, sorted(entries, key=lambda entry: entry.rank)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False).fillna("")


def _read_frontend_funds(path: Path = FRONTEND_FUND_LIST_FILE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["cik", "validationTier", "gavStatus"])
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        return pd.DataFrame(columns=["cik", "validationTier", "gavStatus"])
    df = pd.DataFrame(data)
    for col in ["cik", "validationTier", "gavStatus"]:
        if col not in df.columns:
            df[col] = ""
    df["cik"] = df["cik"].map(_norm_cik)
    return df


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _source_blocking_summary(source_df: pd.DataFrame) -> pd.DataFrame:
    if source_df.empty:
        return pd.DataFrame(columns=[
            "cik",
            "latest_source_residual_report_date",
            "latest_source_blocking_issue_count",
            "all_period_source_blocking_issue_count",
        ])

    df = source_df.copy()
    df["cik"] = df["cik"].map(_norm_cik)
    if "blocking_issue" in df.columns:
        df = df[df["blocking_issue"].astype(str).str.lower().isin({"true", "1", "yes"})]
    if df.empty:
        return pd.DataFrame(columns=[
            "cik",
            "latest_source_residual_report_date",
            "latest_source_blocking_issue_count",
            "all_period_source_blocking_issue_count",
        ])

    df["issue_count_num"] = df["issue_count"].map(_to_float)
    all_period = (
        df.groupby("cik", as_index=False)["issue_count_num"]
        .sum()
        .rename(columns={"issue_count_num": "all_period_source_blocking_issue_count"})
    )
    latest_date = (
        df[df["report_date"].astype(str).str.strip() != ""]
        .groupby("cik", as_index=False)["report_date"]
        .max()
        .rename(columns={"report_date": "latest_source_residual_report_date"})
    )
    latest = df.merge(latest_date, left_on=["cik", "report_date"], right_on=["cik", "latest_source_residual_report_date"], how="inner")
    latest_sum = (
        latest.groupby("cik", as_index=False)["issue_count_num"]
        .sum()
        .rename(columns={"issue_count_num": "latest_source_blocking_issue_count"})
    )
    return all_period.merge(latest_date, on="cik", how="left").merge(latest_sum, on="cik", how="left")


def _validate_residual_summary(validate_df: pd.DataFrame) -> pd.DataFrame:
    if validate_df.empty:
        return pd.DataFrame(columns=["cik", "validation_residual_issue_count", "validation_residual_fail_count"])
    df = validate_df.copy()
    df["cik"] = df["cik"].map(_norm_cik)
    df = df[df["cik"] != ""]
    df["issue_count_num"] = df["issue_count"].map(_to_float)
    df["fail_count_num"] = df["fail_count"].map(_to_float)
    return (
        df.groupby("cik", as_index=False)[["issue_count_num", "fail_count_num"]]
        .sum()
        .rename(columns={
            "issue_count_num": "validation_residual_issue_count",
            "fail_count_num": "validation_residual_fail_count",
        })
    )


def _latest_gav_summary(gav_df: pd.DataFrame) -> pd.DataFrame:
    if gav_df.empty:
        return pd.DataFrame(columns=[
            "cik",
            "latest_gav_report_date",
            "latest_gav_flag",
            "latest_gav_reconciliation_status",
            "latest_gav_ratio_adjusted",
        ])
    df = gav_df.copy()
    df["cik"] = df["cik"].map(_norm_cik)
    df = df[df["cik"] != ""]
    latest = (
        df.groupby("cik", as_index=False)["report_date"]
        .max()
        .rename(columns={"report_date": "latest_gav_report_date"})
    )
    out = df.merge(latest, left_on=["cik", "report_date"], right_on=["cik", "latest_gav_report_date"], how="inner")
    out = out.sort_values(["cik", "latest_gav_report_date"]).drop_duplicates("cik", keep="last")
    for col in ["flag", "reconciliation_status", "gav_ratio_adjusted"]:
        if col not in out.columns:
            out[col] = ""
    return out[["cik", "latest_gav_report_date", "flag", "reconciliation_status", "gav_ratio_adjusted"]].rename(columns={
        "flag": "latest_gav_flag",
        "reconciliation_status": "latest_gav_reconciliation_status",
        "gav_ratio_adjusted": "latest_gav_ratio_adjusted",
    })


def _promoted_fail_count(rules_df: pd.DataFrame) -> int:
    if rules_df.empty:
        return 0
    df = rules_df.copy()
    promoted = df.get("promoted", pd.Series("", index=df.index)).astype(str).str.lower().isin({"true", "1", "yes"})
    failed = df.get("status", pd.Series("", index=df.index)).astype(str).str.upper().eq("FAIL")
    return int((promoted & failed).sum())


def build_gate(
    manifest_path: Path = DEFAULT_MANIFEST,
    source_residual_path: Path = SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE,
    validate_residual_path: Path = VALIDATE_ALL_RESIDUAL_SUMMARY_FILE,
    validation_rules_path: Path = VALIDATION_RULES_AGGREGATE_FILE,
    gav_path: Path = HOLDINGS_GAV_RECONCILIATION_FILE,
    frontend_fund_list_path: Path = FRONTEND_FUND_LIST_FILE,
) -> pd.DataFrame:
    manifest, entries = load_manifest(manifest_path)
    base = pd.DataFrame([{
        "cohort_id": manifest["cohort_id"],
        "cohort_basis": manifest.get("cohort_basis", ""),
        "cohort_rank": entry.rank,
        "cik": entry.cik,
        "wrapper_file": entry.wrapper_file,
    } for entry in entries])

    source = _source_blocking_summary(_read_csv(source_residual_path))
    residuals = _validate_residual_summary(_read_csv(validate_residual_path))
    gav = _latest_gav_summary(_read_csv(gav_path))
    frontend = _read_frontend_funds(frontend_fund_list_path)[["cik", "validationTier", "gavStatus"]].rename(columns={
        "validationTier": "frontend_validation_tier",
        "gavStatus": "frontend_gav_status",
    })
    if not frontend.empty:
        frontend = frontend.drop_duplicates("cik", keep="first")

    out = (
        base.merge(source, on="cik", how="left")
        .merge(residuals, on="cik", how="left")
        .merge(gav, on="cik", how="left")
        .merge(frontend, on="cik", how="left")
    )
    out["frontend_present"] = out["frontend_validation_tier"].notna()
    for col in [
        "latest_source_blocking_issue_count",
        "all_period_source_blocking_issue_count",
        "validation_residual_issue_count",
        "validation_residual_fail_count",
    ]:
        out[col] = out[col].fillna(0).map(_to_float)
    for col in [
        "latest_source_residual_report_date",
        "frontend_validation_tier",
        "frontend_gav_status",
        "latest_gav_report_date",
        "latest_gav_flag",
        "latest_gav_reconciliation_status",
        "latest_gav_ratio_adjusted",
    ]:
        out[col] = out[col].fillna("")

    promoted_fail_count = _promoted_fail_count(_read_csv(validation_rules_path))
    out["promoted_rule_fail_count"] = promoted_fail_count

    statuses: list[str] = []
    reasons: list[str] = []
    for _, row in out.iterrows():
        row_reasons = []
        if not bool(row["frontend_present"]):
            row_reasons.append("missing_frontend_fund")
        if _to_float(row["latest_source_blocking_issue_count"]) > 0:
            row_reasons.append("latest_source_blockers")
        if promoted_fail_count > 0:
            row_reasons.append("promoted_validation_rule_failures")
        public_gav = str(row["frontend_gav_status"]).strip().upper()
        if public_gav not in PASSING_PUBLIC_GAV:
            row_reasons.append("frontend_gav_not_pass_or_skip")
        statuses.append("PASS" if not row_reasons else "FAIL")
        reasons.append(";".join(row_reasons))
    out["status"] = statuses
    out["blocking_reasons"] = reasons
    return out[GATE_COLUMNS]


def write_gate(
    gate: pd.DataFrame,
    csv_path: Path = DEFAULT_CSV_OUT,
    markdown_path: Path = DEFAULT_MD_OUT,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    gate.to_csv(csv_path, index=False)

    failing = gate[gate["status"] != "PASS"]
    lines = [
        "# Wrapper V1 Quality Gate",
        "",
        f"Rows: {len(gate)}",
        f"Status: {'PASS' if failing.empty else 'FAIL'}",
        f"Failing CIKs: {len(failing)}",
        f"Latest source blocking issue_count: {int(gate['latest_source_blocking_issue_count'].sum())}",
        f"All-period source blocking issue_count: {int(gate['all_period_source_blocking_issue_count'].sum())}",
        f"Validate-all residual issue_count: {int(gate['validation_residual_issue_count'].sum())}",
        f"Promoted rule FAIL count: {int(gate['promoted_rule_fail_count'].max() if len(gate) else 0)}",
        "",
    ]
    if not failing.empty:
        lines.append("## Failing CIKs")
        lines.append("")
        for row in failing.sort_values(["latest_source_blocking_issue_count", "cik"], ascending=[False, True]).itertuples(index=False):
            lines.append(
                f"- {row.cik}: {int(row.latest_source_blocking_issue_count)} latest source blockers; "
                f"frontend_gav={row.frontend_gav_status or 'blank'}; reasons={row.blocking_reasons}"
            )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the v1 39-wrapper cohort quality gate")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--csv-out", type=Path, default=DEFAULT_CSV_OUT)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT)
    parser.add_argument("--allow-fail", action="store_true", help="Write artifacts but return zero even when the gate fails")
    args = parser.parse_args(argv)

    gate = build_gate(manifest_path=args.manifest)
    write_gate(gate, csv_path=args.csv_out, markdown_path=args.md_out)
    failed = bool((gate["status"] != "PASS").any())
    return 0 if args.allow_fail or not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
