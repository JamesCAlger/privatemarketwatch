"""Position-match residual review harness.

This module builds review-only artifacts for high-value unmatched position
clusters. Agents may propose deterministic rules, but production matching
continues to come from audited code/config plus validation.
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

from pipeline import config
from pipeline.html_soi_evidence import HTML_EVIDENCE_IDS, build_html_soi_evidence, resolve_accessions_from_rows

REVIEW_DIR = config.OUTPUT_DIR / "position_match_review"
SCHEMA_FILE = config.PROJECT_ROOT / "schemas" / "position_match_review" / "verdict.schema.json"
PROMPT_TEMPLATE = config.PROJECT_ROOT / "prompts" / "position_match_review_prompt.md"

WORKLIST_COLUMNS = [
    "review_id",
    "source",
    "quarter",
    "cik",
    "entity_name",
    "report_date",
    "index_classification",
    "residual_bucket",
    "issuer_cluster",
    "unmatched_rows",
    "unmatched_fv",
    "has_prior_holdings",
    "has_later_holdings",
    "is_interior_cluster",
    "short_span_priority",
    "coverage_any_span_row_rate",
    "coverage_short_span_row_rate",
    "coverage_any_span_fv_rate",
    "coverage_short_span_fv_rate",
    "unmatched_group_rows",
    "unmatched_group_fv",
    "nearby_accepted_match_rows",
    "existing_edge_rows",
    "sample_issuers",
    "sample_identifiers",
    "sample_cusips",
    "sample_instrument_descriptions",
]

BUNDLE_MANIFEST_COLUMNS = ["review_id", "bundle_path", "bundle_sha256"]

PROTECTED_GENERATED_PATH_PREFIXES = ["frontend/public/data/"]
PROTECTED_GENERATED_PATHS = {
    "data/output/private_markets_holdings.csv",
    "data/output/position_matches.csv",
    "data/output/position_returns.csv",
    "data/output/index_returns.csv",
    "data/output/position_id_edges.csv",
    "data/output/position_match_coverage.csv",
    "data/output/position_match_unmatched_summary.csv",
    "data/output/position_match_residuals.csv",
    "data/output/row_validation_issues.csv",
}

RULE_VERDICTS = {"RULE_PROPOSED"}
INCONCLUSIVE_VERDICTS = {"INSUFFICIENT_EVIDENCE", "ESCALATE"}
FORBIDDEN_PRIMARY_TERMS = {"coverage", "row count", "gav"}
REQUIRED_RULE_GUARD_TERMS = {
    "one_to_one": {"one-to-one", "one_to_one", "1:1"},
    "adjacency": {"adjacent", "quarter", "span"},
    "tranche": {"tranche", "maturity", "rate", "coupon", "principal", "fair value", "fv"},
}


class PositionMatchReviewError(RuntimeError):
    """Raised when position-match review inputs or outputs fail closed."""


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


def normalize_key(value: Any) -> str:
    return re.sub(r"\s+", " ", normalize_text(value).lower()).strip()


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
        raise PositionMatchReviewError(f"Missing required CSV: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _stable_join(values: Iterable[Any], limit: int = 8) -> str:
    items = sorted({normalize_text(v) for v in values if normalize_text(v)})
    return " | ".join(items[:limit])


def _issuer_cluster(row: dict[str, str]) -> str:
    issuer = normalize_key(row.get("issuer_name"))
    if issuer:
        return issuer
    for key in ("bdc_investment_identifier", "cusip", "instrument_description"):
        value = normalize_key(row.get(key))
        if value:
            return value
    return "missing_instrument_data"


def make_review_id(
    source: str,
    cik: str,
    quarter: str,
    index_classification: str,
    residual_bucket: str,
    issuer_cluster: str,
) -> str:
    norm_cik = normalize_cik(cik)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", normalize_text(index_classification)).strip("_").upper()[:24] or "NO_CLASS"
    bucket = re.sub(r"[^A-Za-z0-9]+", "_", normalize_text(residual_bucket)).strip("_").upper()[:28] or "NO_BUCKET"
    digest = short_hash("|".join([source, norm_cik, quarter, index_classification, residual_bucket, issuer_cluster]), 10)
    return f"POSMATCH_{normalize_text(source).upper()}_{norm_cik}_{quarter}_{slug}_{bucket}_{digest}"


def _read_keyed(path: Path, keys: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, str]]:
    if not path.exists():
        return {}
    out: dict[tuple[str, ...], dict[str, str]] = {}
    for row in read_csv_rows(path):
        key = tuple(normalize_cik(row.get(k)) if k == "cik" else normalize_text(row.get(k)) for k in keys)
        out[key] = row
    return out


def _read_holdings_dates(path: Path) -> dict[tuple[str, str], set[str]]:
    dates: dict[tuple[str, str], set[str]] = defaultdict(set)
    if not path.exists():
        return dates
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (normalize_cik(row.get("cik")), normalize_text(row.get("source")))
            report_date = normalize_text(row.get("report_date"))
            if key[0] and key[1] and report_date:
                dates[key].add(report_date)
    return dates


def _count_rows_by_keys(
    path: Path,
    key_func: Callable[[dict[str, str]], tuple[str, ...] | None],
) -> dict[tuple[str, ...], int]:
    counts: dict[tuple[str, ...], int] = defaultdict(int)
    if not path.exists():
        return counts
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = key_func(row)
            if key is not None:
                counts[key] += 1
    return counts


def build_worklist(
    *,
    residuals_path: Path = config.POSITION_MATCH_RESIDUALS_FILE,
    coverage_path: Path = config.POSITION_MATCH_COVERAGE_FILE,
    unmatched_summary_path: Path = config.POSITION_MATCH_UNMATCHED_SUMMARY_FILE,
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
    matches_path: Path = config.POSITION_MATCHES_FILE,
    edges_path: Path = config.POSITION_ID_EDGES_FILE,
    output_dir: Path = REVIEW_DIR,
    top_n: int = 100,
    batch_size: int = 1,
    min_unmatched_fv: float = 0.0,
) -> dict[str, Any]:
    residual_rows = read_csv_rows(residuals_path)
    grouped: dict[tuple[str, str, str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in residual_rows:
        fair_value = abs(parse_float(row.get("fair_value")))
        if fair_value < min_unmatched_fv:
            continue
        key = (
            normalize_text(row.get("source")),
            normalize_text(row.get("quarter")),
            normalize_cik(row.get("cik")),
            normalize_text(row.get("index_classification")),
            normalize_text(row.get("residual_bucket")),
            _issuer_cluster(row),
        )
        grouped[key].append(row)

    coverage = _read_keyed(coverage_path, ("source", "quarter", "cik", "index_classification"))
    unmatched = _read_keyed(unmatched_summary_path, ("source", "quarter", "cik", "index_classification"))
    holdings_dates = _read_holdings_dates(holdings_path)
    match_counts = _count_rows_by_keys(
        matches_path,
        lambda r: (
            normalize_text(r.get("source")),
            normalize_cik(r.get("cik")),
            normalize_text(r.get("index_classification")),
            normalize_text(r.get("end_report_date")),
        ),
    )
    edge_counts = _count_rows_by_keys(
        edges_path,
        lambda r: (
            normalize_text(r.get("source")),
            normalize_cik(r.get("cik")),
            normalize_text(r.get("end_report_date")),
        ),
    )

    worklist: list[dict[str, Any]] = []
    for (source, quarter, cik, index_classification, residual_bucket, issuer_cluster), items in grouped.items():
        first = items[0]
        report_date = normalize_text(first.get("report_date"))
        fv = sum(abs(parse_float(item.get("fair_value"))) for item in items)
        dates = sorted(holdings_dates.get((cik, source), set()))
        has_prior = any(date < report_date for date in dates)
        has_later = any(date > report_date for date in dates)
        coverage_row = coverage.get((source, quarter, cik, index_classification), {})
        unmatched_row = unmatched.get((source, quarter, cik, index_classification), {})
        row = {
            "review_id": make_review_id(source, cik, quarter, index_classification, residual_bucket, issuer_cluster),
            "source": source,
            "quarter": quarter,
            "cik": cik,
            "entity_name": first.get("entity_name", ""),
            "report_date": report_date,
            "index_classification": index_classification,
            "residual_bucket": residual_bucket,
            "issuer_cluster": issuer_cluster,
            "unmatched_rows": len(items),
            "unmatched_fv": f"{fv:.6f}",
            "has_prior_holdings": str(has_prior),
            "has_later_holdings": str(has_later),
            "is_interior_cluster": str(has_prior and has_later),
            "short_span_priority": str(has_prior and residual_bucket != "likely_new_or_exit"),
            "coverage_any_span_row_rate": coverage_row.get("any_span_row_match_rate", ""),
            "coverage_short_span_row_rate": coverage_row.get("short_span_row_match_rate", ""),
            "coverage_any_span_fv_rate": coverage_row.get("any_span_fv_match_rate", ""),
            "coverage_short_span_fv_rate": coverage_row.get("short_span_fv_match_rate", ""),
            "unmatched_group_rows": unmatched_row.get("unmatched_rows", ""),
            "unmatched_group_fv": unmatched_row.get("unmatched_fv", ""),
            "nearby_accepted_match_rows": match_counts.get((source, cik, index_classification, report_date), 0),
            "existing_edge_rows": edge_counts.get((source, cik, report_date), 0),
            "sample_issuers": _stable_join(item.get("issuer_name") for item in items),
            "sample_identifiers": _stable_join(item.get("bdc_investment_identifier") for item in items),
            "sample_cusips": _stable_join(item.get("cusip") for item in items),
            "sample_instrument_descriptions": _stable_join(item.get("instrument_description") for item in items),
        }
        worklist.append(row)

    worklist.sort(
        key=lambda r: (
            normalize_text(r["is_interior_cluster"]) != "True",
            normalize_text(r["short_span_priority"]) != "True",
            -parse_float(r["unmatched_fv"]),
            -int(r["unmatched_rows"]),
            r["source"],
            r["cik"],
            r["quarter"],
            r["issuer_cluster"],
        )
    )
    worklist = worklist[:top_n]

    ensure_dir(output_dir)
    write_csv_rows(output_dir / "worklist.csv", worklist, WORKLIST_COLUMNS)
    _write_batches(output_dir, worklist, batch_size)
    return {"worklist_count": len(worklist), "residual_group_count": len(grouped), "batch_size": batch_size}


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


def _evidence_item(evidence_id: str, description: str, data: Any) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "description": description, "data": data}


def _rows_by_review(
    path: Path,
    worklist: list[dict[str, str]],
    predicate: Callable[[dict[str, str], dict[str, str]], bool],
    limit_per_review: int | None,
) -> dict[str, list[dict[str, str]]]:
    rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    if not path.exists() or not worklist:
        return rows
    review_ids = [row["review_id"] for row in worklist]
    with path.open(newline="", encoding="utf-8-sig") as f:
        for source_row in csv.DictReader(f):
            for review_row in worklist:
                review_id = review_row["review_id"]
                if limit_per_review is not None and len(rows[review_id]) >= limit_per_review:
                    continue
                if predicate(review_row, source_row):
                    rows[review_id].append(source_row)
            if limit_per_review is not None and all(len(rows[review_id]) >= limit_per_review for review_id in review_ids):
                break
    return rows


def _same_review_group(review_row: dict[str, str], row: dict[str, str]) -> bool:
    return (
        normalize_text(row.get("source")) == normalize_text(review_row.get("source"))
        and normalize_cik(row.get("cik")) == normalize_cik(review_row.get("cik"))
        and normalize_text(row.get("quarter")) == normalize_text(review_row.get("quarter"))
        and normalize_text(row.get("index_classification")) == normalize_text(review_row.get("index_classification"))
        and normalize_text(row.get("residual_bucket")) == normalize_text(review_row.get("residual_bucket"))
        and _issuer_cluster(row) == normalize_text(review_row.get("issuer_cluster"))
    )


def _same_cik_source_class_date(review_row: dict[str, str], row: dict[str, str], date_field: str = "report_date") -> bool:
    return (
        normalize_text(row.get("source")) == normalize_text(review_row.get("source"))
        and normalize_cik(row.get("cik")) == normalize_cik(review_row.get("cik"))
        and normalize_text(row.get("index_classification")) == normalize_text(review_row.get("index_classification"))
        and normalize_text(row.get(date_field)) == normalize_text(review_row.get("report_date"))
    )


def _candidate_holding(review_row: dict[str, str], row: dict[str, str], *, relation: str) -> bool:
    if normalize_text(row.get("source")) != normalize_text(review_row.get("source")):
        return False
    if normalize_cik(row.get("cik")) != normalize_cik(review_row.get("cik")):
        return False
    if normalize_text(row.get("index_classification")) != normalize_text(review_row.get("index_classification")):
        return False
    row_date = normalize_text(row.get("report_date"))
    review_date = normalize_text(review_row.get("report_date"))
    if relation == "current" and row_date != review_date:
        return False
    if relation == "prior" and row_date >= review_date:
        return False
    if relation == "later" and row_date <= review_date:
        return False
    issuer_cluster = normalize_text(review_row.get("issuer_cluster"))
    return (
        _issuer_cluster(row) == issuer_cluster
        or normalize_key(row.get("issuer_name")) == issuer_cluster
        or normalize_key(row.get("bdc_investment_identifier")) == issuer_cluster
        or normalize_key(row.get("cusip")) == issuer_cluster
    )


def build_bundles(
    *,
    output_dir: Path = REVIEW_DIR,
    review_ids: set[str] | None = None,
    overwrite: bool = False,
    max_rows: int = 25,
) -> list[dict[str, str]]:
    worklist = _load_selected_worklist(output_dir, review_ids)
    bundle_dir = output_dir / "bundles"
    ensure_dir(bundle_dir)

    artifact_paths = [
        config.POSITION_MATCH_RESIDUALS_FILE,
        config.POSITION_MATCH_UNMATCHED_SUMMARY_FILE,
        config.POSITION_MATCH_COVERAGE_FILE,
        config.UNIFIED_HOLDINGS_FILE,
        config.POSITION_MATCHES_FILE,
        config.POSITION_ID_EDGES_FILE,
        config.BDC_HOLDINGS_FILE,
        config.NPORT_HOLDINGS_FILE,
    ]
    artifacts = [_artifact(path) for path in artifact_paths if path.exists()]

    residual_by_review = _rows_by_review(config.POSITION_MATCH_RESIDUALS_FILE, worklist, _same_review_group, None)
    current_holdings = _rows_by_review(
        config.UNIFIED_HOLDINGS_FILE,
        worklist,
        lambda review, row: _candidate_holding(review, row, relation="current"),
        max_rows,
    )
    prior_holdings = _rows_by_review(
        config.UNIFIED_HOLDINGS_FILE,
        worklist,
        lambda review, row: _candidate_holding(review, row, relation="prior"),
        max_rows,
    )
    later_holdings = _rows_by_review(
        config.UNIFIED_HOLDINGS_FILE,
        worklist,
        lambda review, row: _candidate_holding(review, row, relation="later"),
        max_rows,
    )
    nearby_matches = _rows_by_review(
        config.POSITION_MATCHES_FILE,
        worklist,
        lambda review, row: _same_cik_source_class_date(review, row, "end_report_date"),
        max_rows,
    )
    edge_context = _rows_by_review(
        config.POSITION_ID_EDGES_FILE,
        worklist,
        lambda review, row: (
            normalize_text(row.get("source")) == normalize_text(review.get("source"))
            and normalize_cik(row.get("cik")) == normalize_cik(review.get("cik"))
            and normalize_text(row.get("end_report_date")) == normalize_text(review.get("report_date"))
        ),
        max_rows,
    )
    coverage_context = _rows_by_review(
        config.POSITION_MATCH_COVERAGE_FILE,
        worklist,
        lambda review, row: (
            normalize_text(row.get("source")) == normalize_text(review.get("source"))
            and normalize_cik(row.get("cik")) == normalize_cik(review.get("cik"))
            and normalize_text(row.get("quarter")) == normalize_text(review.get("quarter"))
            and normalize_text(row.get("index_classification")) == normalize_text(review.get("index_classification"))
        ),
        None,
    )
    unmatched_context = _rows_by_review(
        config.POSITION_MATCH_UNMATCHED_SUMMARY_FILE,
        worklist,
        lambda review, row: (
            normalize_text(row.get("source")) == normalize_text(review.get("source"))
            and normalize_cik(row.get("cik")) == normalize_cik(review.get("cik"))
            and normalize_text(row.get("quarter")) == normalize_text(review.get("quarter"))
            and normalize_text(row.get("index_classification")) == normalize_text(review.get("index_classification"))
        ),
        None,
    )
    sources = {normalize_text(row.get("source")) for row in worklist}
    raw_bdc_rows = (
        _rows_by_review(
            config.BDC_HOLDINGS_FILE,
            worklist,
            lambda review, row: normalize_text(review.get("source")) == "bdc"
            and normalize_cik(row.get("cik")) == normalize_cik(review.get("cik"))
            and normalize_text(row.get("report_date")) == normalize_text(review.get("report_date")),
            max_rows,
        )
        if "bdc" in sources
        else {}
    )
    raw_nport_rows = (
        _rows_by_review(
            config.NPORT_HOLDINGS_FILE,
            worklist,
            lambda review, row: normalize_text(review.get("source")) == "nport"
            and normalize_cik(row.get("cik")) == normalize_cik(review.get("cik"))
            and normalize_text(row.get("report_date")) == normalize_text(review.get("report_date")),
            max_rows,
        )
        if "nport" in sources
        else {}
    )

    manifest: list[dict[str, str]] = []
    for row in worklist:
        review_id = row["review_id"]
        target = bundle_dir / f"{review_id}.json"
        if target.exists() and not overwrite:
            manifest.append({"review_id": review_id, "bundle_path": display_path(target), "bundle_sha256": sha256_file(target)})
            continue
        evidence_items = [
            _evidence_item("worklist_row", "Selected high-value unmatched position cluster.", row),
            _evidence_item("match_residual_rows", "Unmatched residual rows in this cluster.", residual_by_review.get(review_id, [])),
            _evidence_item("current_candidate_holdings", "Current-quarter unified holdings matching the cluster.", current_holdings.get(review_id, [])),
            _evidence_item("prior_candidate_holdings", "Earlier unified holdings with compatible CIK/source/class/issuer evidence.", prior_holdings.get(review_id, [])),
            _evidence_item("later_candidate_holdings", "Later unified holdings with compatible CIK/source/class/issuer evidence.", later_holdings.get(review_id, [])),
            _evidence_item("accepted_nearby_matches", "Accepted matches for the same CIK/source/class/end date.", nearby_matches.get(review_id, [])),
            _evidence_item("existing_position_id_edges", "Existing chain edges ending on the same CIK/source/date.", edge_context.get(review_id, [])),
            _evidence_item("coverage_context", "Coverage metrics for the same source/CIK/quarter/classification.", coverage_context.get(review_id, [])),
            _evidence_item("unmatched_summary_context", "Unmatched summary for the same source/CIK/quarter/classification.", unmatched_context.get(review_id, [])),
            _evidence_item("raw_bdc_source_rows", "Raw BDC rows for the same CIK/date when source is BDC.", raw_bdc_rows.get(review_id, [])),
            _evidence_item("raw_nport_source_rows", "Raw N-PORT rows for the same CIK/date when source is N-PORT.", raw_nport_rows.get(review_id, [])),
        ]
        if normalize_text(row.get("source")) == "bdc":
            bdc_rows = raw_bdc_rows.get(review_id, [])
            accession_candidates = resolve_accessions_from_rows(
                residual_by_review.get(review_id, [])
                + current_holdings.get(review_id, [])
                + bdc_rows
            )
            accession = accession_candidates[0] if accession_candidates else ""
            evidence_items.extend(
                build_html_soi_evidence(
                    source="bdc",
                    cik=row.get("cik", ""),
                    report_date=row.get("report_date", ""),
                    accession=accession,
                    residual_names=[
                        row.get("issuer_cluster", ""),
                        row.get("sample_issuers", ""),
                    ],
                    fair_values=[item.get("fair_value", "") for item in residual_by_review.get(review_id, [])],
                    source_identifiers=[
                        row.get("sample_identifiers", ""),
                        row.get("sample_cusips", ""),
                        row.get("sample_instrument_descriptions", ""),
                    ],
                    xbrl_rows_same_accession=bdc_rows,
                    max_rows=max_rows,
                )
            )
        bundle = {
            "schema_version": "position-match-review-bundle.v1",
            "created_at": now_iso(),
            "review_id": review_id,
            "source": row["source"],
            "cik": row["cik"],
            "quarter": row["quarter"],
            "report_date": row["report_date"],
            "index_classification": row["index_classification"],
            "residual_bucket": row["residual_bucket"],
            "issuer_cluster": row["issuer_cluster"],
            "artifact_hashes": artifacts,
            "evidence_items": evidence_items,
            "allowed_patch_scope": [
                "audited position-matching config or parser/normalization code when bundled evidence supports the mechanism",
                "tests covering the exact residual mechanism and at least one false-positive multi-tranche or same-borrower case",
            ],
            "prohibited_patch_scope": [
                "generated data/output CSV edits",
                "frontend/public/data JSON edits",
                "direct production match-pair approval by the agent",
                "borrower-level rules that collapse distinct tranches, rates, maturities, equity interests, warrants, or fund interests",
            ],
            "required_validation_commands": [
                "pytest tests/test_position_match_review.py",
                "pytest tests/test_position_matching.py tests/test_validation_rules.py",
                "python scripts/rebuild_outputs.py --returns",
                "python scripts/rebuild_outputs.py --validate-rules",
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
        lines.append(f"- `{display_path(bundle_path)}` -> write `data/output/position_match_review/verdicts/{review_id}.json`")
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


def _guardrail_text(verdict: dict[str, Any]) -> str:
    return normalize_text(verdict.get("guardrails")).lower()


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

    for field in ("positive_examples", "false_positive_examples"):
        for idx, example in enumerate(verdict.get(field, [])):
            if not isinstance(example, dict):
                continue
            ref = normalize_text(example.get("evidence_ref"))
            if ref in HTML_EVIDENCE_IDS - {"html_artifact", "xbrl_rows_same_accession"} and not _valid_html_citation(example, ref):
                errors.append(f"{field}[{idx}] HTML citation requires evidence_ref, table_index, row_index, cell_indices, reason")
            row_class = normalize_text(example.get("row_classification")).upper()
            if ref in HTML_EVIDENCE_IDS and row_class == "POSITION_ROW":
                text = json.dumps(example, sort_keys=True).lower()
                if "aggregate_header" in text or "subtotal_row" in text or "subtotal" in text or "aggregate header" in text:
                    errors.append(f"{field}[{idx}] cannot classify aggregate/header/subtotal HTML row as POSITION_ROW")
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
    if normalize_text(verdict.get("source")) != normalize_text(bundle.get("source")):
        errors.append("source does not match bundle")
    if normalize_text(verdict.get("quarter")) != normalize_text(bundle.get("quarter")):
        errors.append("quarter does not match bundle")
    if normalize_text(verdict.get("index_classification")) != normalize_text(bundle.get("index_classification")):
        errors.append("index_classification does not match bundle")

    evidence_ids = _bundle_evidence_ids(bundle)
    for ref in verdict.get("evidence_refs", []):
        if ref not in evidence_ids:
            errors.append(f"unknown evidence_ref: {ref}")
    errors.extend(_html_coord_validation_errors(verdict))

    primary = normalize_text(verdict.get("primary_justification")).lower()
    for term in FORBIDDEN_PRIMARY_TERMS:
        if term in primary:
            errors.append("coverage, row-count, or GAV improvement cannot be the primary justification")
            break

    for changed in verdict.get("changed_files", []):
        if _protected_edit(str(changed)):
            errors.append(f"protected generated-output edit is not allowed: {changed}")

    if verdict.get("verdict") in RULE_VERDICTS:
        if verdict.get("requires_human_merge") is not True:
            errors.append("RULE_PROPOSED requires requires_human_merge=true")
        for key in [
            "changed_files",
            "rule_scope",
            "rule_type",
            "deterministic_conditions",
            "positive_examples",
            "false_positive_examples",
            "guardrails",
            "expected_coverage_effect",
            "false_match_risk",
            "tests_validation_plan",
        ]:
            value = verdict.get(key)
            if not value:
                errors.append(f"RULE_PROPOSED requires {key}")
        text = _guardrail_text(verdict)
        for name, terms in REQUIRED_RULE_GUARD_TERMS.items():
            if not any(term in text for term in terms):
                errors.append(f"RULE_PROPOSED must specify {name} guardrails")

    if verdict.get("verdict") in INCONCLUSIVE_VERDICTS:
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
    "source",
    "cik",
    "quarter",
    "index_classification",
    "residual_bucket",
    "verdict",
    "confidence",
    "unmatched_fv",
    "changed_files",
    "rule_type",
    "rule_summary",
    "expected_coverage_effect",
    "tests_validation_plan",
    "missing_evidence",
    "residual_risk",
]

EVALUATION_COLUMNS = [
    "review_id",
    "verdict",
    "source",
    "cik",
    "quarter",
    "index_classification",
    "residual_bucket",
    "unmatched_rows",
    "unmatched_fv",
    "rule_type",
    "proposed_candidate_edges",
    "rejected_ambiguous_candidates",
    "before_short_span_fv_rate",
    "before_any_span_fv_rate",
    "expected_coverage_effect",
    "requires_human_merge",
]


def summarize_verdicts(output_dir: Path = REVIEW_DIR, schema_file: Path = SCHEMA_FILE) -> dict[str, Any]:
    validation_errors = validate_all_verdicts(output_dir, schema_file)
    if validation_errors:
        write_csv_rows(output_dir / "verdict_validation_errors.csv", validation_errors, ["verdict_file", "error"])
        raise PositionMatchReviewError(f"Verdict validation failed with {len(validation_errors)} error(s)")

    worklist = {row["review_id"]: row for row in read_csv_rows(output_dir / "worklist.csv")}
    rows: list[dict[str, Any]] = []
    eval_rows: list[dict[str, Any]] = []
    for path in sorted((output_dir / "verdicts").glob("*.json")):
        verdict = json.loads(path.read_text(encoding="utf-8-sig"))
        work = worklist[verdict["review_id"]]
        rows.append({
            "review_id": verdict["review_id"],
            "source": verdict["source"],
            "cik": verdict["cik"],
            "quarter": verdict["quarter"],
            "index_classification": verdict["index_classification"],
            "residual_bucket": work.get("residual_bucket", ""),
            "verdict": verdict["verdict"],
            "confidence": verdict["confidence"],
            "unmatched_fv": work.get("unmatched_fv", "0"),
            "changed_files": " | ".join(verdict.get("changed_files", [])),
            "rule_type": verdict.get("rule_type", ""),
            "rule_summary": verdict.get("rule_summary", ""),
            "expected_coverage_effect": verdict.get("expected_coverage_effect", ""),
            "tests_validation_plan": verdict.get("tests_validation_plan", ""),
            "missing_evidence": verdict.get("missing_evidence", ""),
            "residual_risk": verdict.get("residual_risk", ""),
        })
        eval_rows.append(_evaluation_row(work, verdict))

    write_csv_rows(output_dir / "summary.csv", rows, SUMMARY_COLUMNS)
    write_csv_rows(output_dir / "dry_run_evaluation.csv", eval_rows, EVALUATION_COLUMNS)

    counts = Counter(row["verdict"] for row in rows)
    by_rule_type = Counter((row["rule_type"], row["verdict"]) for row in rows)
    fv_by_verdict: dict[str, float] = defaultdict(float)
    for row in rows:
        fv_by_verdict[row["verdict"]] += parse_float(row["unmatched_fv"])

    md = [
        "# Position Match Rule Review Summary",
        "",
        f"Generated: {now_iso()}",
        f"Verdicts reviewed: {len(rows)}",
        "",
        "## Verdict Counts",
        "",
    ]
    for verdict, count in sorted(counts.items()):
        md.append(f"- {verdict}: {count} reviews, unmatched FV ${fv_by_verdict[verdict]:,.0f}")
    md.extend(["", "## Proposed Rules", ""])
    for row in rows:
        if row["verdict"] == "RULE_PROPOSED":
            md.append(f"- {row['review_id']}: {row['rule_type']} | {row['rule_summary']} | validation: {row['tests_validation_plan']}")
    md.extend(["", "## Escalations And Insufficient Evidence", ""])
    for row in rows:
        if row["verdict"] in INCONCLUSIVE_VERDICTS:
            md.append(f"- {row['review_id']} ({row['verdict']}): {row['missing_evidence']}")
    (output_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return {
        "verdict_count": len(rows),
        "counts": dict(counts),
        "fv_by_verdict": dict(fv_by_verdict),
        "by_rule_type": {" | ".join(key): value for key, value in by_rule_type.items()},
    }


def _evaluation_row(work: dict[str, str], verdict: dict[str, Any]) -> dict[str, Any]:
    positive = verdict.get("positive_examples", [])
    false_positive = verdict.get("false_positive_examples", [])
    return {
        "review_id": verdict.get("review_id", ""),
        "verdict": verdict.get("verdict", ""),
        "source": work.get("source", ""),
        "cik": work.get("cik", ""),
        "quarter": work.get("quarter", ""),
        "index_classification": work.get("index_classification", ""),
        "residual_bucket": work.get("residual_bucket", ""),
        "unmatched_rows": work.get("unmatched_rows", ""),
        "unmatched_fv": work.get("unmatched_fv", ""),
        "rule_type": verdict.get("rule_type", ""),
        "proposed_candidate_edges": len(positive) if isinstance(positive, list) else 0,
        "rejected_ambiguous_candidates": len(false_positive) if isinstance(false_positive, list) else 0,
        "before_short_span_fv_rate": work.get("coverage_short_span_fv_rate", ""),
        "before_any_span_fv_rate": work.get("coverage_any_span_fv_rate", ""),
        "expected_coverage_effect": verdict.get("expected_coverage_effect", ""),
        "requires_human_merge": verdict.get("requires_human_merge", ""),
    }


def cli_build_worklist(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build position-match residual review worklist.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--min-unmatched-fv", type=float, default=0.0)
    args = parser.parse_args(argv)
    print(json.dumps(build_worklist(output_dir=args.output_dir, top_n=args.top_n, batch_size=args.batch_size, min_unmatched_fv=args.min_unmatched_fv), indent=2, sort_keys=True))
    return 0


def cli_build_bundles(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build position-match residual review bundles.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--review-id", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    review_ids = None if args.all or not args.review_id else set(args.review_id)
    manifest = build_bundles(output_dir=args.output_dir, review_ids=review_ids, overwrite=args.overwrite)
    print(json.dumps({"bundle_count": len(manifest)}, indent=2, sort_keys=True))
    return 0


def cli_build_prompt(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build manual-launch prompt for a position-match review batch.")
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    args = parser.parse_args(argv)
    path = build_prompt(args.batch, args.output_dir)
    print(display_path(path))
    return 0


def cli_validate_verdicts(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate position-match rule verdicts.")
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
    print("All verdicts passed validation.")
    return 0


def cli_summarize_verdicts(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize position-match rule verdicts.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--schema-file", type=Path, default=SCHEMA_FILE)
    args = parser.parse_args(argv)
    print(json.dumps(summarize_verdicts(args.output_dir, args.schema_file), indent=2, sort_keys=True))
    return 0
