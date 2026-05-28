"""BDC source-blocker review harness.

This module builds review-only artifacts for existing BDC source reconciliation
blockers.  It reads cached validation CSVs and writes only under
data/output/bdc_cik_review; proposed patches remain human-reviewed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import jsonschema
import pandas as pd

from pipeline import config
from pipeline.bdc_cik_validator import build_cik_validation_packet, gav_gate_role
from pipeline.html_soi_evidence import HTML_EVIDENCE_IDS, build_html_soi_evidence, resolve_accessions_from_rows

REVIEW_DIR = config.OUTPUT_DIR / "bdc_cik_review"
SCHEMA_FILE = config.PROJECT_ROOT / "schemas" / "bdc_cik_review" / "verdict.schema.json"
PROMPT_TEMPLATE = config.PROJECT_ROOT / "prompts" / "bdc_cik_review_prompt.md"

WORKLIST_COLUMNS = [
    "review_id",
    "cik",
    "entity_name",
    "report_date",
    "mechanism",
    "blocking_issue_count",
    "issue_count",
    "affected_source_fair_value",
    "affected_output_fair_value",
    "confidence",
    "recommended_action",
    "residual_classes",
    "statuses",
    "match_tiers",
    "sample_identifiers",
    "sample_accessions",
    "source_rows",
    "output_rows",
    "matched_rows",
    "missing_from_pipeline_rows",
    "extra_in_pipeline_rows",
    "value_mismatch_rows",
    "reconciliation_status",
    "source_only_blocker_rows",
    "source_only_blocker_fv",
    "gav_gate_role",
    "gav_reconciliation_status",
    "gav_flag",
    "bdc_source_reconciliation_flag",
    "gav_ratio",
    "bdc_source_reconciliation_ratio",
    "sum_holdings_fv",
    "holdings_row_count",
    "holdings_fair_value",
]

BUNDLE_MANIFEST_COLUMNS = ["review_id", "bundle_path", "bundle_sha256"]

PROTECTED_GENERATED_PATH_PREFIXES = [
    "frontend/public/data/",
]
PROTECTED_GENERATED_PATHS = {
    "data/output/private_markets_holdings.csv",
    "data/output/holdings_gav_reconciliation.csv",
    "data/output/source_reconciliation_detail.csv",
    "data/output/source_reconciliation_metrics.csv",
    "data/output/source_reconciliation_residual_classification.csv",
    "data/output/source_reconciliation_source_only_detail.csv",
    "data/output/row_validation_issues.csv",
}

RECONCILIATION_DIAGNOSES = {
    "",
    "REAL_POSITION_MISSING_FROM_UNIFIED",
    "HTML_PRESENT_TABLE_NOT_PARSED",
    "AGGREGATE_OR_HEADER",
    "COMPARATIVE_PERIOD",
    "ZERO_OR_UNFUNDED_NON_INDEX_ROW",
    "DUPLICATE_DIMENSION_PATH",
    "XBRL_ONLY_NO_HTML_COORDINATE",
    "RAW_XBRL_PRESENT_BUT_UNIFIED_FILTERED",
    "INSUFFICIENT_EVIDENCE",
}
HTML_BASED_DIAGNOSES = {
    "REAL_POSITION_MISSING_FROM_UNIFIED",
    "HTML_PRESENT_TABLE_NOT_PARSED",
    "AGGREGATE_OR_HEADER",
    "COMPARATIVE_PERIOD",
    "ZERO_OR_UNFUNDED_NON_INDEX_ROW",
}


class BdcCikReviewError(RuntimeError):
    """Raised when BDC review inputs or outputs fail closed."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return "" if text.lower() == "nan" else text.strip()


def normalize_cik(value: Any) -> str:
    digits = re.sub(r"\D", "", normalize_text(value))
    return digits.zfill(10) if digits else ""


def parse_float(value: Any) -> float:
    text = normalize_text(value).replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def trueish(value: Any) -> bool:
    return normalize_text(value).lower() in {"true", "1", "yes", "y"}


def short_hash(value: str, length: int = 10) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(config.PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise BdcCikReviewError(f"Missing required CSV: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _stable_join(values: Iterable[Any]) -> str:
    return " | ".join(sorted({normalize_text(v) for v in values if normalize_text(v)}))


def make_review_id(cik: str, report_date: str, mechanism: str) -> str:
    norm_cik = normalize_cik(cik)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", mechanism).strip("_").upper()[:48] or "NO_MECHANISM"
    digest = short_hash("|".join([norm_cik, report_date, mechanism]), 10)
    return f"BDCSRC_{norm_cik}_{report_date}_{slug}_{digest}"


def _read_keyed(path: Path, keys: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, str]]:
    if not path.exists():
        return {}
    out: dict[tuple[str, ...], dict[str, str]] = {}
    for row in read_csv_rows(path):
        key = tuple(normalize_cik(row.get(k)) if k == "cik" else normalize_text(row.get(k)) for k in keys)
        out[key] = row
    return out


def _stream_pair_summaries(path: Path, pairs: set[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    summaries = {pair: {"holdings_row_count": 0, "holdings_fair_value": 0.0} for pair in pairs}
    if not path.exists() or not pairs:
        return summaries
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pair = (normalize_cik(row.get("cik")), normalize_text(row.get("report_date")))
            if pair not in summaries:
                continue
            summaries[pair]["holdings_row_count"] += 1
            summaries[pair]["holdings_fair_value"] += parse_float(row.get("fair_value"))
    return summaries


def build_worklist(
    *,
    residual_path: Path = config.SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE,
    metrics_path: Path = config.SOURCE_RECONCILIATION_METRICS_FILE,
    source_only_path: Path = config.SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE,
    gav_path: Path = config.OUTPUT_DIR / "holdings_gav_reconciliation.csv",
    holdings_path: Path = config.OUTPUT_DIR / "private_markets_holdings.csv",
    output_dir: Path = REVIEW_DIR,
    top_n: int = 100,
    batch_size: int = 1,
) -> dict[str, Any]:
    rows = [row for row in read_csv_rows(residual_path) if trueish(row.get("blocking_issue"))]
    grouped: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (
            normalize_cik(row.get("cik")),
            normalize_text(row.get("report_date")),
            normalize_text(row.get("mechanism")),
        )
        grouped[key].append(row)

    metrics = _read_keyed(metrics_path, ("cik", "report_date"))
    gav = _read_keyed(gav_path, ("cik", "report_date"))
    source_only_summary: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: {"rows": 0.0, "fv": 0.0})
    if source_only_path.exists():
        for row in read_csv_rows(source_only_path):
            if not trueish(row.get("is_blocking")):
                continue
            key = (
                normalize_cik(row.get("cik")),
                normalize_text(row.get("report_date")),
                normalize_text(row.get("mechanism")),
            )
            source_only_summary[key]["rows"] += 1
            source_only_summary[key]["fv"] += parse_float(row.get("source_fair_value"))

    worklist: list[dict[str, Any]] = []
    for (cik, report_date, mechanism), items in grouped.items():
        issue_count = sum(int(parse_float(item.get("issue_count")) or 1) for item in items)
        affected_source_fv = sum(parse_float(item.get("affected_source_fair_value")) for item in items)
        affected_output_fv = sum(parse_float(item.get("affected_output_fair_value")) for item in items)
        first = items[0]
        metric = metrics.get((cik, report_date), {})
        gav_row = gav.get((cik, report_date), {})
        src_only = source_only_summary[(cik, report_date, mechanism)]
        row = {
            "review_id": make_review_id(cik, report_date, mechanism),
            "cik": cik,
            "entity_name": first.get("entity_name", ""),
            "report_date": report_date,
            "mechanism": mechanism,
            "blocking_issue_count": len(items),
            "issue_count": issue_count,
            "affected_source_fair_value": f"{affected_source_fv:.6f}",
            "affected_output_fair_value": f"{affected_output_fv:.6f}",
            "confidence": _stable_join(item.get("confidence") for item in items),
            "recommended_action": _stable_join(item.get("recommended_action") for item in items),
            "residual_classes": _stable_join(item.get("residual_class") for item in items),
            "statuses": _stable_join(item.get("status") for item in items),
            "match_tiers": _stable_join(item.get("match_tier") for item in items),
            "sample_identifiers": _stable_join(item.get("sample_identifiers") for item in items),
            "sample_accessions": _stable_join(item.get("sample_accessions") for item in items),
            "source_only_blocker_rows": int(src_only["rows"]),
            "source_only_blocker_fv": f"{src_only['fv']:.6f}",
            "gav_gate_role": gav_gate_role(gav_row) if gav_row else "",
            "gav_reconciliation_status": gav_row.get("reconciliation_status", ""),
            "gav_flag": gav_row.get("flag", ""),
            "bdc_source_reconciliation_flag": gav_row.get("bdc_source_reconciliation_flag", ""),
            "gav_ratio": gav_row.get("gav_ratio", ""),
            "bdc_source_reconciliation_ratio": gav_row.get("bdc_source_reconciliation_ratio", ""),
            "sum_holdings_fv": gav_row.get("sum_holdings_fv", ""),
        }
        for field in [
            "source_rows",
            "output_rows",
            "matched_rows",
            "missing_from_pipeline_rows",
            "extra_in_pipeline_rows",
            "value_mismatch_rows",
            "reconciliation_status",
        ]:
            row[field] = metric.get(field, "")
        worklist.append(row)

    pairs = {(row["cik"], row["report_date"]) for row in worklist}
    holdings_summaries = _stream_pair_summaries(holdings_path, pairs)
    for row in worklist:
        summary = holdings_summaries.get((row["cik"], row["report_date"]), {})
        row["holdings_row_count"] = summary.get("holdings_row_count", 0)
        row["holdings_fair_value"] = f"{summary.get('holdings_fair_value', 0.0):.6f}"

    worklist.sort(
        key=lambda r: (
            -int(r["blocking_issue_count"]),
            -parse_float(r["affected_source_fair_value"]),
            -int(re.sub(r"\D", "", normalize_text(r["report_date"])) or "0"),
            r["cik"],
        )
    )
    worklist = worklist[:top_n]

    ensure_dir(output_dir)
    write_csv_rows(output_dir / "worklist.csv", worklist, WORKLIST_COLUMNS)
    _write_batches(output_dir, worklist, batch_size)
    return {"worklist_count": len(worklist), "blocking_group_count": len(grouped), "batch_size": batch_size}


def _write_batches(output_dir: Path, worklist: list[dict[str, Any]], batch_size: int) -> None:
    batch_dir = output_dir / "batches"
    ensure_dir(batch_dir)
    batch_size = max(1, batch_size)
    for idx in range(0, len(worklist), batch_size):
        batch_num = idx // batch_size + 1
        write_csv_rows(batch_dir / f"batch_{batch_num:03d}.csv", worklist[idx : idx + batch_size], WORKLIST_COLUMNS)


def _artifact(path: Path) -> dict[str, str]:
    return {
        "path": display_path(path),
        "sha256": sha256_file(path) if path.exists() else "",
        "exists": str(path.exists()),
    }


def _load_selected_worklist(output_dir: Path, review_ids: set[str] | None = None) -> list[dict[str, str]]:
    rows = read_csv_rows(output_dir / "worklist.csv")
    if review_ids is None:
        return rows
    return [row for row in rows if row.get("review_id") in review_ids]


def _records_to_df(rows: list[dict[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _evidence_item(evidence_id: str, description: str, data: Any) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "description": description, "data": data}


def _html_source_search_rows(
    source_only_rows: list[dict[str, str]],
    residual_rows: list[dict[str, str]],
    max_rows: int,
) -> list[dict[str, str]]:
    rows = list(source_only_rows)
    if len(rows) >= max_rows:
        return rows[:max_rows]
    for residual in residual_rows:
        samples = normalize_text(residual.get("sample_identifiers"))
        if not samples:
            continue
        for idx, identifier in enumerate(part.strip() for part in samples.split(" | ") if part.strip()):
            rows.append(
                {
                    "source_row_id": f"{normalize_text(residual.get('classification_id'))}:sample:{idx}",
                    "raw_investment_identifier": identifier,
                    "normalized_investment_identifier": identifier.lower(),
                    "source_fair_value": normalize_text(residual.get("affected_source_fair_value")),
                }
            )
            if len(rows) >= max_rows:
                return rows
    return rows


def _rows_by_group(
    path: Path,
    targets: set[tuple[str, str, str]],
    predicate: Callable[[dict[str, str]], bool],
    limit_per_group: int | None,
) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    rows: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    if not path.exists() or not targets:
        return rows
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (
                normalize_cik(row.get("cik")),
                normalize_text(row.get("report_date")),
                normalize_text(row.get("mechanism")),
            )
            if key not in targets or not predicate(row):
                continue
            if limit_per_group is None or len(rows[key]) < limit_per_group:
                rows[key].append(row)
    return rows


def _rows_by_pair(
    path: Path,
    pairs: set[tuple[str, str]],
    predicate: Callable[[dict[str, str]], bool],
    limit_per_pair: int | None,
) -> dict[tuple[str, str], list[dict[str, str]]]:
    rows: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    if not path.exists() or not pairs:
        return rows
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (normalize_cik(row.get("cik")), normalize_text(row.get("report_date")))
            if key not in pairs or not predicate(row):
                continue
            if limit_per_pair is None or len(rows[key]) < limit_per_pair:
                rows[key].append(row)
    return rows


def build_bundles(
    *,
    output_dir: Path = REVIEW_DIR,
    review_ids: set[str] | None = None,
    overwrite: bool = False,
    max_rows: int = 25,
    allow_html_download: bool = False,
) -> list[dict[str, str]]:
    worklist = _load_selected_worklist(output_dir, review_ids)
    bundle_dir = output_dir / "bundles"
    ensure_dir(bundle_dir)

    artifact_paths = [
        config.SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE,
        config.SOURCE_RECONCILIATION_METRICS_FILE,
        config.SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE,
        config.SOURCE_RECONCILIATION_DETAIL_FILE,
        config.OUTPUT_DIR / "holdings_gav_reconciliation.csv",
        config.OUTPUT_DIR / "holdings_pct_sum.csv",
        config.OUTPUT_DIR / "position_purity_metrics.csv",
        config.OUTPUT_DIR / "private_markets_holdings.csv",
    ]
    artifacts = [_artifact(path) for path in artifact_paths if path.exists()]
    manifest: list[dict[str, str]] = []
    targets = {
        (normalize_cik(row.get("cik")), normalize_text(row.get("report_date")), normalize_text(row.get("mechanism")))
        for row in worklist
    }
    pairs = {(cik, report_date) for cik, report_date, _ in targets}
    residual_by_group = _rows_by_group(
        config.SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE,
        targets,
        lambda r: True,
        None,
    )
    source_only_by_group = _rows_by_group(
        config.SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE,
        targets,
        lambda r: trueish(r.get("is_blocking")),
        max_rows,
    )
    detail_by_pair = _rows_by_pair(
        config.SOURCE_RECONCILIATION_DETAIL_FILE,
        pairs,
        lambda r: trueish(r.get("blocking_issue")),
        max_rows,
    )
    gav_by_pair = _rows_by_pair(config.OUTPUT_DIR / "holdings_gav_reconciliation.csv", pairs, lambda r: True, None)
    holdings_by_pair = _rows_by_pair(config.OUTPUT_DIR / "private_markets_holdings.csv", pairs, lambda r: True, max_rows)
    pct_by_pair = _rows_by_pair(config.OUTPUT_DIR / "holdings_pct_sum.csv", pairs, lambda r: True, None)
    purity_by_pair = _rows_by_pair(config.OUTPUT_DIR / "position_purity_metrics.csv", pairs, lambda r: True, None)

    for row in worklist:
        review_id = row["review_id"]
        target = bundle_dir / f"{review_id}.json"
        if target.exists() and not overwrite:
            manifest.append({"review_id": review_id, "bundle_path": display_path(target), "bundle_sha256": sha256_file(target)})
            continue
        cik = normalize_cik(row.get("cik"))
        report_date = normalize_text(row.get("report_date"))
        mechanism = normalize_text(row.get("mechanism"))
        group_key = (cik, report_date, mechanism)
        pair_key = (cik, report_date)

        residual_rows = residual_by_group.get(group_key, [])
        source_only_rows = source_only_by_group.get(group_key, [])
        detail_rows = detail_by_pair.get(pair_key, [])
        gav_rows = gav_by_pair.get(pair_key, [])
        holdings_rows = holdings_by_pair.get(pair_key, [])
        pct_rows = pct_by_pair.get(pair_key, [])
        purity_rows = purity_by_pair.get(pair_key, [])
        html_source_rows = _html_source_search_rows(source_only_rows, residual_rows, max_rows)

        packet = build_cik_validation_packet(
            cik,
            [report_date],
            holdings_df=_records_to_df(holdings_rows),
            source_residual_df=_records_to_df(residual_rows),
            source_only_df=_records_to_df(source_only_rows),
            gav_df=_records_to_df(gav_rows),
            pct_df=_records_to_df(pct_rows),
            purity_df=_records_to_df(purity_rows),
        )
        evidence_items = [
            _evidence_item("worklist_row", "Selected CIK-date-mechanism blocker group.", row),
            _evidence_item("cik_validation_packet", "BDC CIK validation packet assembled from cached artifacts.", packet),
            _evidence_item("source_residual_rows", "Matching source reconciliation residual classification rows.", residual_rows),
            _evidence_item("source_only_blocker_rows", "Matching source-only blocker rows.", source_only_rows),
            _evidence_item("source_reconciliation_detail_samples", "Sample matching source reconciliation detail rows.", detail_rows),
            _evidence_item("gav_reconciliation", "GAV row and gate-role context for the same CIK/date.", gav_rows),
            _evidence_item("holdings_examples", "Sample unified holdings rows for the same CIK/date.", holdings_rows),
            _evidence_item("pct_of_net_assets", "pct_of_net_assets aggregate validation row.", pct_rows),
            _evidence_item("position_purity", "Position purity metrics row.", purity_rows),
        ]
        accession_candidates = resolve_accessions_from_rows(residual_rows + source_only_rows + detail_rows + holdings_rows)
        accession = accession_candidates[0] if accession_candidates else ""
        evidence_items.extend(
            build_html_soi_evidence(
                source="bdc",
                cik=cik,
                report_date=report_date,
                accession=accession,
                residual_names=[
                    row.get("sample_identifiers", ""),
                    *[r.get("sample_identifiers", "") for r in residual_rows],
                    *[r.get("investment_identifier", "") for r in source_only_rows],
                    *[r.get("issuer_name", "") for r in detail_rows],
                ],
                fair_values=[
                    row.get("affected_source_fair_value", ""),
                    *[r.get("source_fair_value", "") for r in source_only_rows],
                    *[r.get("source_fair_value", "") for r in detail_rows],
                ],
                source_identifiers=accession_candidates,
                source_rows=html_source_rows,
                xbrl_rows_same_accession=[
                    r for r in holdings_rows if not accession or normalize_text(r.get("accession_number")) == accession
                ],
                allow_html_download=allow_html_download,
                max_rows=max_rows,
            )
        )
        bundle = {
            "schema_version": "bdc-cik-review-bundle.v1",
            "created_at": now_iso(),
            "review_id": review_id,
            "cik": cik,
            "report_date": report_date,
            "mechanism": mechanism,
            "artifact_hashes": artifacts,
            "evidence_items": evidence_items,
            "allowed_patch_scope": [
                "pipeline source, parser, normalization, or audited config files only when source evidence supports the mechanism",
                "tests covering the exact blocker mechanism and at least one false-positive case when adding filters or rules",
            ],
            "prohibited_patch_scope": [
                "generated data/output CSV edits",
                "frontend/public/data JSON edits",
                "validation suppression without an independent source-reconciliation mechanism",
            ],
            "required_validation_commands": [
                "pytest tests/test_bdc_cik_review.py tests/test_bdc_cik_validator.py",
                "python -m pipeline.main --unified --validate",
            ],
        }
        target.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest.append({"review_id": review_id, "bundle_path": display_path(target), "bundle_sha256": sha256_file(target)})

    write_csv_rows(output_dir / "bundle_manifest.csv", manifest, BUNDLE_MANIFEST_COLUMNS)
    return manifest


def build_prompt(batch_path: Path, output_dir: Path = REVIEW_DIR) -> Path:
    batch_rows = read_csv_rows(batch_path)
    template = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    lines = [template.rstrip(), "", "## Bundle Assignments", ""]
    for row in batch_rows:
        review_id = row["review_id"]
        bundle_path = output_dir / "bundles" / f"{review_id}.json"
        lines.append(f"- `{display_path(bundle_path)}` -> write `data/output/bdc_cik_review/verdicts/{review_id}.json`")
    lines.append("")
    target = output_dir / "prompt.md"
    ensure_dir(target.parent)
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def load_verdict_schema(schema_file: Path = SCHEMA_FILE) -> dict[str, Any]:
    return json.loads(schema_file.read_text(encoding="utf-8"))


def _load_bundle(output_dir: Path, review_id: str) -> dict[str, Any] | None:
    path = output_dir / "bundles" / f"{review_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _bundle_evidence_ids(bundle: dict[str, Any]) -> set[str]:
    return {str(item.get("evidence_id")) for item in bundle.get("evidence_items", []) if isinstance(item, dict)}


def _protected_edit(path_text: str) -> bool:
    normalized = normalize_text(path_text).replace("\\", "/").lstrip("./")
    if normalized in PROTECTED_GENERATED_PATHS:
        return True
    return any(normalized.startswith(prefix) for prefix in PROTECTED_GENERATED_PATH_PREFIXES)


def _valid_html_citation(value: Any, evidence_ref: str | None = None) -> bool:
    if not isinstance(value, dict):
        return False
    if evidence_ref is not None and normalize_text(value.get("evidence_ref")) != evidence_ref:
        return False
    return (
        normalize_text(value.get("evidence_ref")) in HTML_EVIDENCE_IDS
        and isinstance(value.get("table_index"), int)
        and isinstance(value.get("row_index"), int)
        and isinstance(value.get("cell_indices"), list)
        and bool(value.get("cell_indices"))
        and all(isinstance(idx, int) for idx in value.get("cell_indices", []))
        and bool(normalize_text(value.get("reason")))
    )


def _html_coord_validation_errors(verdict: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    citations = verdict.get("html_citations", [])
    if citations and not isinstance(citations, list):
        return ["html_citations must be an array of coordinate citations"]
    citation_refs = {
        normalize_text(c.get("evidence_ref"))
        for c in citations
        if _valid_html_citation(c)
    }
    coordinate_required_refs = set(verdict.get("evidence_refs", [])) & (HTML_EVIDENCE_IDS - {"html_artifact", "xbrl_rows_same_accession"})
    for ref in sorted(coordinate_required_refs - citation_refs):
        errors.append(f"HTML evidence_ref {ref} requires table_index,row_index,cell_indices coordinate citation")

    for idx, citation in enumerate(citations if isinstance(citations, list) else []):
        row_class = normalize_text(citation.get("row_classification")).upper() if isinstance(citation, dict) else ""
        if row_class == "POSITION_ROW":
            text = json.dumps(citation, sort_keys=True).lower()
            if "aggregate_header" in text or "subtotal_row" in text or "subtotal" in text or "aggregate header" in text:
                errors.append(f"html_citations[{idx}] cannot classify aggregate/header/subtotal HTML row as POSITION_ROW")
        diagnosis = normalize_text(verdict.get("reconciliation_diagnosis")).upper()
        if diagnosis == "REAL_POSITION_MISSING_FROM_UNIFIED" and row_class in {
            "AGGREGATE_HEADER",
            "SUBTOTAL_ROW",
            "COMPARATIVE_PERIOD_ROW",
            "UNCLASSIFIABLE",
            "INSUFFICIENT_EVIDENCE",
        }:
            errors.append(f"html_citations[{idx}] cannot support REAL_POSITION_MISSING_FROM_UNIFIED with {row_class}")
    diagnosis = normalize_text(verdict.get("reconciliation_diagnosis")).upper()
    if diagnosis in HTML_BASED_DIAGNOSES and not citations:
        errors.append(f"{diagnosis} requires coordinate-level html_citations")
    if diagnosis in {"XBRL_ONLY_NO_HTML_COORDINATE", "INSUFFICIENT_EVIDENCE"} and coordinate_required_refs:
        errors.append(f"{diagnosis} cannot rely on free-text HTML coordinate evidence")
    return errors


def validate_verdict_file(verdict_file: Path, output_dir: Path = REVIEW_DIR, schema_file: Path = SCHEMA_FILE) -> list[str]:
    errors: list[str] = []
    try:
        verdict = json.loads(verdict_file.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON: {exc}"]

    try:
        jsonschema.Draft202012Validator(load_verdict_schema(schema_file)).validate(verdict)
    except jsonschema.ValidationError as exc:
        errors.append(f"Schema validation failed: {exc.message}")

    review_id = normalize_text(verdict.get("review_id"))
    bundle = _load_bundle(output_dir, review_id)
    if bundle is None:
        errors.append(f"Missing bundle for review_id: {review_id}")
        return errors

    if normalize_cik(verdict.get("cik")) != normalize_cik(bundle.get("cik")):
        errors.append("cik does not match bundle")
    if normalize_text(verdict.get("report_date")) != normalize_text(bundle.get("report_date")):
        errors.append("report_date does not match bundle")

    evidence_ids = _bundle_evidence_ids(bundle)
    for ref in verdict.get("evidence_refs", []):
        if ref not in evidence_ids:
            errors.append(f"unknown evidence_ref: {ref}")
    errors.extend(_html_coord_validation_errors(verdict))

    diagnosis = normalize_text(verdict.get("reconciliation_diagnosis")).upper()
    if diagnosis and diagnosis not in RECONCILIATION_DIAGNOSES:
        errors.append(f"invalid reconciliation_diagnosis: {diagnosis}")

    primary = normalize_text(verdict.get("primary_justification")).lower()
    if "gav" in primary:
        errors.append("GAV improvement cannot be the primary justification")

    changed_files = verdict.get("changed_files", [])
    for changed in changed_files:
        if _protected_edit(str(changed)):
            errors.append(f"protected generated-output edit is not allowed: {changed}")

    if verdict.get("verdict") == "PATCH_PROPOSED":
        if not changed_files:
            errors.append("PATCH_PROPOSED requires changed_files")
        for key in ["patch_summary", "source_reconciliation_effect", "gav_effect", "tests_validation_plan"]:
            if not verdict.get(key):
                errors.append(f"PATCH_PROPOSED requires {key}")
        if verdict.get("requires_human_merge") is not True:
            errors.append("PATCH_PROPOSED requires requires_human_merge=true")

    if verdict.get("verdict") in {"INSUFFICIENT_EVIDENCE", "ESCALATE"}:
        missing = normalize_text(verdict.get("missing_evidence"))
        if len(missing) < 10:
            errors.append(f"{verdict.get('verdict')} requires explicit missing_evidence")

    return errors


def validate_all_verdicts(output_dir: Path = REVIEW_DIR, schema_file: Path = SCHEMA_FILE) -> list[dict[str, str]]:
    verdict_dir = output_dir / "verdicts"
    if not verdict_dir.exists():
        return [{"verdict_file": "", "error": f"Missing verdict directory: {verdict_dir}"}]
    expected = {row["review_id"]: row for row in read_csv_rows(output_dir / "worklist.csv")}
    seen: set[str] = set()
    errors: list[dict[str, str]] = []
    for path in sorted(verdict_dir.glob("*.json")):
        try:
            verdict = json.loads(path.read_text(encoding="utf-8-sig"))
            review_id = normalize_text(verdict.get("review_id"))
            if review_id in seen:
                errors.append({"verdict_file": display_path(path), "error": f"Duplicate verdict for review_id: {review_id}"})
            if review_id:
                seen.add(review_id)
            if review_id and review_id not in expected:
                errors.append({"verdict_file": display_path(path), "error": f"review_id is not in worklist: {review_id}"})
        except json.JSONDecodeError:
            pass
        for error in validate_verdict_file(path, output_dir, schema_file):
            errors.append({"verdict_file": display_path(path), "error": error})
    for missing_id in sorted(set(expected) - seen):
        errors.append({"verdict_file": "", "error": f"Missing verdict for review_id: {missing_id}"})
    return errors


SUMMARY_COLUMNS = [
    "review_id",
    "cik",
    "report_date",
    "mechanism",
    "verdict",
    "reconciliation_diagnosis",
    "confidence",
    "affected_source_fair_value",
    "changed_files",
    "patch_summary",
    "tests_validation_plan",
    "missing_evidence",
    "residual_risk",
]


def summarize_verdicts(output_dir: Path = REVIEW_DIR, schema_file: Path = SCHEMA_FILE) -> dict[str, Any]:
    validation_errors = validate_all_verdicts(output_dir, schema_file)
    if validation_errors:
        write_csv_rows(output_dir / "verdict_validation_errors.csv", validation_errors, ["verdict_file", "error"])
        raise BdcCikReviewError(f"Verdict validation failed with {len(validation_errors)} error(s)")

    worklist = {row["review_id"]: row for row in read_csv_rows(output_dir / "worklist.csv")}
    rows: list[dict[str, Any]] = []
    for path in sorted((output_dir / "verdicts").glob("*.json")):
        verdict = json.loads(path.read_text(encoding="utf-8-sig"))
        work = worklist[verdict["review_id"]]
        rows.append({
            "review_id": verdict["review_id"],
            "cik": verdict["cik"],
            "report_date": verdict["report_date"],
            "mechanism": work.get("mechanism", ""),
            "verdict": verdict["verdict"],
            "reconciliation_diagnosis": verdict.get("reconciliation_diagnosis", ""),
            "confidence": verdict["confidence"],
            "affected_source_fair_value": work.get("affected_source_fair_value", "0"),
            "changed_files": " | ".join(verdict.get("changed_files", [])),
            "patch_summary": verdict.get("patch_summary", ""),
            "tests_validation_plan": verdict.get("tests_validation_plan", ""),
            "missing_evidence": verdict.get("missing_evidence", ""),
            "residual_risk": verdict.get("residual_risk", ""),
        })
    write_csv_rows(output_dir / "summary.csv", rows, SUMMARY_COLUMNS)

    counts = Counter(row["verdict"] for row in rows)
    diagnosis_counts = Counter(row["reconciliation_diagnosis"] or "UNSPECIFIED_LEGACY" for row in rows)
    by_mechanism = Counter((row["mechanism"], row["verdict"]) for row in rows)
    by_confidence = Counter((row["confidence"], row["verdict"]) for row in rows)
    fv_by_verdict: dict[str, float] = defaultdict(float)
    for row in rows:
        fv_by_verdict[row["verdict"]] += parse_float(row["affected_source_fair_value"])

    md = [
        "# BDC CIK Source-Blocker Review Summary",
        "",
        f"Generated: {now_iso()}",
        f"Verdicts reviewed: {len(rows)}",
        "",
        "## Verdict Counts",
        "",
    ]
    for verdict, count in sorted(counts.items()):
        md.append(f"- {verdict}: {count} reviews, affected source FV ${fv_by_verdict[verdict]:,.0f}")
    md.extend(["", "## Reconciliation Diagnosis Counts", ""])
    for diagnosis, count in sorted(diagnosis_counts.items()):
        md.append(f"- {diagnosis}: {count} reviews")
    md.extend(["", "## Proposed Patches", ""])
    for row in rows:
        if row["verdict"] == "PATCH_PROPOSED":
            md.append(f"- {row['review_id']}: {row['patch_summary']} | files: {row['changed_files']} | validation: {row['tests_validation_plan']}")
    md.extend(["", "## Escalations And Insufficient Evidence", ""])
    for row in rows:
        if row["verdict"] in {"ESCALATE", "INSUFFICIENT_EVIDENCE"}:
            md.append(f"- {row['review_id']} ({row['verdict']}): {row['missing_evidence']}")
    (output_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return {
        "verdict_count": len(rows),
        "counts": dict(counts),
        "fv_by_verdict": dict(fv_by_verdict),
        "diagnosis_counts": dict(diagnosis_counts),
        "by_mechanism": {" | ".join(key): value for key, value in by_mechanism.items()},
        "by_confidence": {" | ".join(key): value for key, value in by_confidence.items()},
    }


def cli_build_worklist(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build BDC source-blocker review worklist.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args(argv)
    print(json.dumps(build_worklist(output_dir=args.output_dir, top_n=args.top_n, batch_size=args.batch_size), indent=2, sort_keys=True))
    return 0


def cli_build_bundles(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build BDC source-blocker review bundles.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--review-id", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-html-download", action="store_true")
    args = parser.parse_args(argv)
    review_ids = None if args.all or not args.review_id else set(args.review_id)
    manifest = build_bundles(
        output_dir=args.output_dir,
        review_ids=review_ids,
        overwrite=args.overwrite,
        allow_html_download=args.allow_html_download,
    )
    print(json.dumps({"bundle_count": len(manifest)}, indent=2, sort_keys=True))
    return 0


def cli_build_prompt(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build manual-launch prompt for a BDC review batch.")
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    args = parser.parse_args(argv)
    path = build_prompt(args.batch, args.output_dir)
    print(display_path(path))
    return 0


def cli_validate_verdicts(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate BDC source-blocker verdicts.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--schema-file", type=Path, default=SCHEMA_FILE)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    errors = validate_all_verdicts(args.output_dir, args.schema_file)
    if errors:
        write_csv_rows(args.output_dir / "verdict_validation_errors.csv", errors, ["verdict_file", "error"])
        for error in errors:
            print(f"{error['verdict_file']}: {error['error']}")
        return 1
    error_file = args.output_dir / "verdict_validation_errors.csv"
    if error_file.exists():
        error_file.unlink()
    print("All verdicts passed validation.")
    return 0


def cli_summarize_verdicts(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize BDC source-blocker verdicts.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--schema-file", type=Path, default=SCHEMA_FILE)
    args = parser.parse_args(argv)
    print(json.dumps(summarize_verdicts(args.output_dir, args.schema_file), indent=2, sort_keys=True))
    return 0
