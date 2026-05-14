"""Constrained FAIL verification harness.

This module builds deterministic samples and evidence bundles from validation
FAIL artifacts, then validates agent-authored verdict JSON files. It is
intentionally separate from the production extraction pipeline: this code reads
existing CSV artifacts and writes only under data/output/fail_verification.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from pipeline.config import OUTPUT_DIR, PROJECT_ROOT

HOLDINGS_DATASET = "private_markets_holdings"
FUND_DATASET = "fund_financials"
DATASET_ALIASES = {
    "holdings": HOLDINGS_DATASET,
    HOLDINGS_DATASET: HOLDINGS_DATASET,
    "funds": FUND_DATASET,
    FUND_DATASET: FUND_DATASET,
}
HOLDINGS_RULES = ("C101", "X06", "GAV_BDC01", "GAV_NPORT01", "X09", "C402")
FUND_RULES = tuple(
    [f"F{i}" for i in range(1, 9)]
    + [f"F{i}" for i in range(10, 19)]
    + [f"F{i}" for i in range(20, 29)]
    + [f"F{i}" for i in range(30, 43)]
)
FUND_RULE_PRIORITY = ("F10", "F17", "F20", "F21", "F22", "F23", "F28")
RULES = HOLDINGS_RULES + FUND_RULES
ROW_LEVEL_RULES = {"C101", "X06", "X09", "C402"}
CIK_QUARTER_RULES = {"GAV01", "GAV_BDC01", "GAV_NPORT01"}
FUND_PERIOD_RULES = {rule for rule in FUND_RULES if rule not in {f"F{i}" for i in range(1, 9)}}
FRONTEND_EXPORT_RULES = {f"F{i}" for i in range(1, 9)}
CROSS_LEVEL_FUND_RULES = {f"F{i}" for i in range(20, 29)}
SMALL_POPULATION_EXHAUSTIVE_MAX = 100
DEFAULT_SEED = 20260511
SAMPLE_MARGIN = 0.10
Z_95 = 1.96

VERDICTS = {
    "CONFIRMED_DATA_ERROR",
    "CONFIRMED_VALID_EXCEPTION",
    "VALIDATOR_FALSE_POSITIVE",
    "INSUFFICIENT_EVIDENCE",
}
EVIDENCE_VERDICT_CLASSES = {
    "DATA_ERROR",
    "VALID_EXCEPTION",
    "FALSE_POSITIVE",
    "INSUFFICIENT",
}
INSUFFICIENT_ROOT_CAUSES = {
    "BUNDLE_MISSING_LOCAL_EVIDENCE",
    "RULE_OR_MODEL_NOT_DETERMINATIVE",
}

PROTECTED_RELATIVE_PATHS = [
    "pipeline",
    "scripts",
    "schemas",
    "docs",
    "frontend/public/data",
    "data/output/row_validation_issues.csv",
    "data/output/private_markets_holdings.csv",
    "data/output/holdings_gav_reconciliation.csv",
    "data/output/fund_financials.csv",
    "data/output/holdings_pct_sum.csv",
    "data/output/holdings_count_stability.csv",
    "data/output/fund_financials_validation_current.csv",
    "data/output/fund_financials_quality_metrics.csv",
    "data/output/fund_financials_cross_level.csv",
    "data/output/bdc_fund_income.csv",
    "data/output/nport_fund_info.csv",
    "data/output/ncsr_financials.csv",
    "data/output/combined_universe.csv",
    "data/output/fund_identity.csv",
    "data/output/bdc_filings_index.csv",
    "data/output/bdc_holdings.csv",
    "data/output/nport_holdings.csv",
]


class FailVerificationError(RuntimeError):
    """Raised when fail-verification inputs or outputs fail closed."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def normalize_cik(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits.zfill(10) if digits else ""


def normalize_dataset(dataset: str) -> str:
    try:
        return DATASET_ALIASES[dataset]
    except KeyError as exc:
        raise FailVerificationError(f"Unsupported dataset: {dataset}") from exc


def selected_datasets(dataset: str) -> list[str]:
    if dataset == "all":
        return [HOLDINGS_DATASET, FUND_DATASET]
    return [normalize_dataset(dataset)]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FailVerificationError(f"Missing required CSV: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def finite_population_sample_size(population: int, margin: float = SAMPLE_MARGIN) -> int:
    if population <= 0:
        return 0
    n = (Z_95 * Z_95 * 0.25) / (margin * margin)
    adjusted = n / (1 + ((n - 1) / population))
    return max(1, math.ceil(adjusted))


def _sample_units_for_rule(
    rows: list[dict[str, str]],
    rule_id: str,
    seed: int,
) -> list[dict[str, Any]]:
    population = len(rows)
    if population <= SMALL_POPULATION_EXHAUSTIVE_MAX:
        selected = list(rows)
        by_cik = Counter(normalize_cik(r.get("cik")) for r in rows)
        for row in selected:
            row["_sample_weight"] = "1"
            row["_sample_stratum"] = normalize_cik(row.get("cik"))
            row["_population"] = str(population)
            row["_sample_size"] = str(population)
            row["_stratum_population"] = str(by_cik[normalize_cik(row.get("cik"))])
            row["_stratum_sample_size"] = str(by_cik[normalize_cik(row.get("cik"))])
        return selected

    sample_size = finite_population_sample_size(population)
    by_cik: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_cik[normalize_cik(row.get("cik"))].append(row)

    rng = random.Random(seed + int(short_hash(rule_id, 8), 16))
    allocations = _allocate_stratified_sample(
        {cik: len(items) for cik, items in by_cik.items()},
        sample_size,
        rng,
    )

    selected: list[dict[str, Any]] = []
    for cik, n_h in sorted(allocations.items()):
        stratum_rows = list(by_cik[cik])
        rng.shuffle(stratum_rows)
        for row in stratum_rows[:n_h]:
            item = dict(row)
            item["_sample_weight"] = f"{len(stratum_rows) / n_h:.10g}"
            item["_sample_stratum"] = cik
            item["_population"] = str(population)
            item["_sample_size"] = str(sample_size)
            item["_stratum_population"] = str(len(stratum_rows))
            item["_stratum_sample_size"] = str(n_h)
            selected.append(item)
    selected.sort(key=lambda r: (r.get("rule_id", ""), r.get("cik", ""), r.get("report_date", ""), r.get("row_key", "")))
    return selected


def _allocate_stratified_sample(
    stratum_counts: dict[str, int],
    sample_size: int,
    rng: random.Random,
) -> dict[str, int]:
    distinct = len(stratum_counts)
    if sample_size >= distinct:
        allocations = {cik: 1 for cik in stratum_counts}
        remaining = sample_size - distinct
        if remaining <= 0:
            return allocations
        total = sum(stratum_counts.values())
        raw = {
            cik: (count / total) * remaining
            for cik, count in stratum_counts.items()
        }
        floors = {cik: int(math.floor(value)) for cik, value in raw.items()}
        for cik, value in floors.items():
            allocations[cik] += value
        left = remaining - sum(floors.values())
        ranked = sorted(
            raw,
            key=lambda cik: (raw[cik] - floors[cik], rng.random()),
            reverse=True,
        )
        for cik in ranked[:left]:
            allocations[cik] += 1
        capped = {cik: min(n, stratum_counts[cik]) for cik, n in allocations.items()}
        return _redistribute_allocation_capacity(capped, stratum_counts, sample_size, rng)

    weighted = []
    total = sum(stratum_counts.values())
    for cik, count in stratum_counts.items():
        weighted.append((rng.random() ** (1 / (count / total)), cik))
    selected = [cik for _, cik in sorted(weighted, reverse=True)[:sample_size]]
    return {cik: 1 for cik in selected}


def _redistribute_allocation_capacity(
    allocations: dict[str, int],
    stratum_counts: dict[str, int],
    sample_size: int,
    rng: random.Random,
) -> dict[str, int]:
    """Fill capped allocation shortfalls where other strata still have capacity."""
    target = min(sample_size, sum(stratum_counts.values()))
    while sum(allocations.values()) < target:
        candidates = [
            cik for cik, count in stratum_counts.items()
            if allocations.get(cik, 0) < count
        ]
        if not candidates:
            break
        candidates.sort(
            key=lambda cik: (stratum_counts[cik] - allocations.get(cik, 0), rng.random()),
            reverse=True,
        )
        allocations[candidates[0]] = allocations.get(candidates[0], 0) + 1
    return allocations


def _dedupe_gav_units(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result = []
    for row in rows:
        key = (normalize_cik(row.get("cik")), row.get("report_date", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _is_cik_quarter_rule(rule_id: str) -> bool:
    return rule_id in CIK_QUARTER_RULES


MANIFEST_COLUMNS = [
    "dataset",
    "verification_id",
    "rule_id",
    "sampling_unit",
    "cik",
    "report_date",
    "row_key",
    "source",
    "accession_number",
    "source_record_id",
    "issuer_name",
    "position_id",
    "sample_stratum",
    "sample_weight",
    "random_seed",
    "source_file",
    "source_file_sha256",
    "population",
    "sample_size",
    "stratum_population",
    "stratum_sample_size",
]


def build_sample_manifest(
    output_dir: Path = OUTPUT_DIR,
    seed: int = DEFAULT_SEED,
    out_path: Path | None = None,
    dataset: str = "holdings",
) -> Path:
    manifest_rows: list[dict[str, Any]] = []
    datasets = selected_datasets(dataset)
    if HOLDINGS_DATASET in datasets:
        manifest_rows.extend(_build_holdings_sample_manifest_rows(output_dir, seed))
    if FUND_DATASET in datasets:
        manifest_rows.extend(_build_fund_sample_manifest_rows(output_dir, seed))

    target = out_path or output_dir / "fail_verification" / "sample_manifest.csv"
    write_csv_rows(target, manifest_rows, MANIFEST_COLUMNS)
    return target


def _build_holdings_sample_manifest_rows(
    output_dir: Path,
    seed: int,
) -> list[dict[str, Any]]:
    issue_path = output_dir / "row_validation_issues.csv"
    source_hash = sha256_file(issue_path)
    rows = [
        row for row in read_csv_rows(issue_path)
        if row.get("status") == "OPEN"
        and row.get("severity") == "FAIL"
        and row.get("rule_id") in HOLDINGS_RULES
    ]

    rows_by_rule: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        rows_by_rule[row["rule_id"]].append(row)
    for rule_id in CIK_QUARTER_RULES:
        if rule_id in rows_by_rule:
            rows_by_rule[rule_id] = _dedupe_gav_units(rows_by_rule[rule_id])

    sampled: list[dict[str, Any]] = []
    for rule_id in HOLDINGS_RULES:
        sampled.extend(_sample_units_for_rule(rows_by_rule.get(rule_id, []), rule_id, seed))

    row_keys = {
        int(row["row_key"])
        for row in sampled
        if row.get("row_key", "").isdigit() and row.get("rule_id") in ROW_LEVEL_RULES
    }
    holdings_by_row_key = _read_holdings_by_row_key(output_dir / "private_markets_holdings.csv", row_keys)
    gav_by_key = _read_keyed_rows(output_dir / "holdings_gav_reconciliation.csv", ("cik", "report_date"))

    manifest_rows: list[dict[str, Any]] = []
    for row in sampled:
        rule_id = row.get("rule_id", "")
        cik = normalize_cik(row.get("cik"))
        report_date = row.get("report_date", "")
        sampling_unit = "cik_quarter" if _is_cik_quarter_rule(rule_id) else "issue_row"
        holdings_row = holdings_by_row_key.get(row.get("row_key", ""))
        gav_row = gav_by_key.get((cik, report_date), {})

        source = row.get("source") or (holdings_row or {}).get("source", "")
        accession = (holdings_row or {}).get("accession_number", "")
        issuer = (holdings_row or {}).get("issuer_name", "")
        position_id = (holdings_row or {}).get("position_id", "")
        source_record_id = _source_record_id(holdings_row or gav_row or row)

        identity = "|".join([
            rule_id,
            sampling_unit,
            cik,
            report_date,
            row.get("row_key", ""),
            source,
            accession,
            source_record_id,
        ])
        verification_id = f"{rule_id}_{cik}_{report_date}_{short_hash(identity)}"

        manifest_rows.append({
            "dataset": HOLDINGS_DATASET,
            "verification_id": verification_id,
            "rule_id": rule_id,
            "sampling_unit": sampling_unit,
            "cik": cik,
            "report_date": report_date,
            "row_key": row.get("row_key", ""),
            "source": source,
            "accession_number": accession,
            "source_record_id": source_record_id,
            "issuer_name": issuer,
            "position_id": position_id,
            "sample_stratum": row.get("_sample_stratum", cik),
            "sample_weight": row.get("_sample_weight", "1"),
            "random_seed": str(seed),
            "source_file": display_path(issue_path),
            "source_file_sha256": source_hash,
            "population": row.get("_population", ""),
            "sample_size": row.get("_sample_size", ""),
            "stratum_population": row.get("_stratum_population", ""),
            "stratum_sample_size": row.get("_stratum_sample_size", ""),
        })

    return manifest_rows


def _build_fund_sample_manifest_rows(
    output_dir: Path,
    seed: int,
) -> list[dict[str, Any]]:
    validation_path = output_dir / "fund_financials_validation_current.csv"
    source_hash = sha256_file(validation_path)
    rows = []
    for index, row in enumerate(read_csv_rows(validation_path)):
        check_code = row.get("check_code", "")
        if row.get("status") != "FAIL" or check_code not in FUND_RULES:
            continue
        item = dict(row)
        item["rule_id"] = check_code
        item["row_key"] = str(index)
        rows.append(item)

    rows_by_rule: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        rows_by_rule[row["rule_id"]].append(row)

    sampled: list[dict[str, Any]] = []
    ordered_rules = list(FUND_RULE_PRIORITY) + [
        rule for rule in FUND_RULES if rule not in FUND_RULE_PRIORITY
    ]
    for rule_id in ordered_rules:
        sampled.extend(_sample_units_for_rule(rows_by_rule.get(rule_id, []), rule_id, seed))

    manifest_rows: list[dict[str, Any]] = []
    for row in sampled:
        rule_id = row.get("rule_id", "")
        cik = normalize_cik(row.get("cik"))
        report_date = row.get("report_date", "")
        sampling_unit = "frontend_export" if rule_id in FRONTEND_EXPORT_RULES else "fund_period"
        row_key = row.get("row_key", "")
        source = "fund_financials"
        source_record_id = "|".join([cik, report_date, row.get("report_quarter", ""), rule_id])
        identity = "|".join([
            FUND_DATASET,
            rule_id,
            sampling_unit,
            cik,
            report_date,
            row_key,
            source_record_id,
        ])
        verification_id = f"{rule_id}_{cik}_{report_date}_{short_hash(identity)}"

        manifest_rows.append({
            "dataset": FUND_DATASET,
            "verification_id": verification_id,
            "rule_id": rule_id,
            "sampling_unit": sampling_unit,
            "cik": cik,
            "report_date": report_date,
            "row_key": row_key,
            "source": source,
            "accession_number": "",
            "source_record_id": source_record_id,
            "issuer_name": "",
            "position_id": "",
            "sample_stratum": row.get("_sample_stratum", cik),
            "sample_weight": row.get("_sample_weight", "1"),
            "random_seed": str(seed),
            "source_file": display_path(validation_path),
            "source_file_sha256": source_hash,
            "population": row.get("_population", ""),
            "sample_size": row.get("_sample_size", ""),
            "stratum_population": row.get("_stratum_population", ""),
            "stratum_sample_size": row.get("_stratum_sample_size", ""),
        })
    return manifest_rows


def _source_record_id(row: dict[str, str]) -> str:
    for key in (
        "bdc_investment_identifier",
        "investment_identifier",
        "nport_holding_id",
        "holding_id",
        "position_id",
        "accession_number",
    ):
        if row.get(key):
            return str(row[key])
    return ""


def _read_holdings_by_row_key(path: Path, row_keys: set[int]) -> dict[str, dict[str, str]]:
    if not row_keys:
        return {}
    result = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for index, row in enumerate(reader):
            if index in row_keys:
                result[str(index)] = row
                if len(result) == len(row_keys):
                    break
    return result


def _read_keyed_rows(path: Path, keys: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, str]]:
    if not path.exists():
        return {}
    result = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = tuple(normalize_cik(row.get(k)) if k == "cik" else row.get(k, "") for k in keys)
            result[key] = row
    return result


def _read_matching_rows(
    path: Path,
    predicate,
    limit: int | None = None,
) -> list[dict[str, str]]:
    if not path.exists():
        return []
    result = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if predicate(row):
                result.append(row)
                if limit is not None and len(result) >= limit:
                    break
    return result


def _artifact(path: Path, cache: dict[Path, str]) -> dict[str, str]:
    if not path.exists():
        return {
            "path": display_path(path),
            "sha256": "",
            "status": "missing",
        }
    if path not in cache:
        cache[path] = sha256_file(path)
    return {
        "path": display_path(path),
        "sha256": cache[path],
        "status": "present",
    }


def _evidence(evidence_id: str, kind: str, description: str, data: Any) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "description": description,
        "data": data,
    }


def build_evidence_bundle(
    verification_id: str,
    output_dir: Path = OUTPUT_DIR,
    overwrite: bool = False,
    hash_cache: dict[Path, str] | None = None,
    _context: dict[str, Any] | None = None,
    _append_manifest: bool = True,
) -> Path:
    manifest_path = output_dir / "fail_verification" / "sample_manifest.csv"
    manifest_rows = _context["manifest_rows"] if _context else {
        row["verification_id"]: row
        for row in read_csv_rows(manifest_path)
    }
    if verification_id not in manifest_rows:
        raise FailVerificationError(f"verification_id not in sample manifest: {verification_id}")
    manifest_row = manifest_rows[verification_id]
    target = output_dir / "fail_verification" / "bundles" / f"{verification_id}.json"
    if target.exists() and not overwrite:
        raise FailVerificationError(f"Bundle already exists: {target}")

    if manifest_row.get("dataset", HOLDINGS_DATASET) == FUND_DATASET:
        return _build_fund_evidence_bundle(
            verification_id,
            manifest_row,
            output_dir,
            target,
            overwrite,
            hash_cache,
            _append_manifest,
            _context,
        )

    cache = hash_cache if hash_cache is not None else {}
    issue_path = output_dir / "row_validation_issues.csv"
    holdings_path = output_dir / "private_markets_holdings.csv"
    bdc_path = output_dir / "bdc_holdings.csv"
    nport_path = output_dir / "nport_holdings.csv"
    fund_financials_path = output_dir / "fund_financials.csv"
    gav_path = output_dir / "holdings_gav_reconciliation.csv"
    pct_path = output_dir / "holdings_pct_sum.csv"
    stability_path = output_dir / "holdings_count_stability.csv"
    filings_path = output_dir / "bdc_filings_index.csv"

    cik = manifest_row["cik"]
    report_date = manifest_row["report_date"]
    rule_id = manifest_row["rule_id"]
    row_key = manifest_row.get("row_key", "")

    if _context:
        issue_rows = _context["issue_rows_by_vid"].get(verification_id, [])
        holdings_row = _context["holdings_by_row_key"].get(row_key, {})
    else:
        issue_rows = _read_matching_rows(
            issue_path,
            lambda r: (
                normalize_cik(r.get("cik")) == cik
                and r.get("report_date", "") == report_date
                and r.get("rule_id", "") == rule_id
                and (_is_cik_quarter_rule(rule_id) or r.get("row_key", "") == row_key)
            ),
        )
        holdings_row = {}
        if row_key.isdigit():
            holdings_row = _read_holdings_by_row_key(holdings_path, {int(row_key)}).get(row_key, {})

    evidence_items = [
        _evidence("manifest_row", "sample_manifest_row", "Sample manifest identity row.", manifest_row),
        _evidence("issue_rows", "validation_issue", "Matching validation issue row or rows.", issue_rows),
    ]
    if holdings_row:
        evidence_items.append(_evidence("holdings_row", "unified_holding", "Materialized private_markets_holdings row.", holdings_row))

    nearby = (
        _nearby_holdings_from_context(_context, cik, report_date, holdings_row, rule_id)
        if _context else _nearby_holdings(output_dir, cik, report_date, holdings_row, rule_id)
    )
    evidence_items.append(_evidence("nearby_holdings", "context_rows", "Nearby/context holdings for same CIK and date.", nearby))

    raw_rows, raw_diagnostics = (
        _raw_source_evidence_from_context(_context, holdings_row, cik, report_date)
        if _context else _raw_source_evidence(bdc_path, nport_path, holdings_row, cik, report_date)
    )
    evidence_items.append(_evidence("raw_source_rows", "raw_source_rows", "Raw BDC or N-PORT source rows matched to the sampled holding.", raw_rows))
    evidence_items.append(_evidence(
        "raw_source_match_diagnostics",
        "raw_source_match_diagnostics",
        "How raw source rows were matched to the sampled holding.",
        raw_diagnostics,
    ))

    fund_rows = (
        _context["fund_rows_by_pair"].get((cik, report_date), [])
        if _context else _read_matching_rows(
            fund_financials_path,
            lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        )
    )
    evidence_items.append(_evidence("fund_financials", "fund_financials", "Fund financial rows for the sampled CIK/date.", fund_rows))

    if _is_cik_quarter_rule(rule_id):
        evidence_items.append(_evidence(
            "gav_reconciliation",
            "gav_reconciliation",
            "CIK-quarter GAV reconciliation row.",
            _context["gav_rows_by_pair"].get((cik, report_date), []) if _context else
            _read_matching_rows(gav_path, lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date),
        ))
        evidence_items.append(_evidence(
            "related_row_fail_counts",
            "related_fail_counts",
            "Open row-level FAIL counts for this CIK/date.",
            _context["related_fail_counts_by_pair"].get((cik, report_date), {}) if _context else
            dict(Counter(r.get("rule_id", "") for r in _read_matching_rows(
                issue_path,
                lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date and r.get("severity") == "FAIL",
            ))),
        ))
        evidence_items.append(_evidence(
            "related_row_fail_examples",
            "related_fail_examples",
            "Open row-level FAIL examples for this CIK/date.",
            _context["related_fail_examples_by_pair"].get((cik, report_date), []) if _context else
            _read_matching_rows(
                issue_path,
                lambda r: (
                    normalize_cik(r.get("cik")) == cik
                    and r.get("report_date", "") == report_date
                    and r.get("severity") == "FAIL"
                    and not _is_cik_quarter_rule(r.get("rule_id", ""))
                ),
                limit=20,
            ),
        ))
        evidence_items.append(_evidence(
            "gav_holdings_examples",
            "gav_holdings_examples",
            "Sample holdings rows for this CIK/date.",
            _context["gav_holdings_by_pair"].get((cik, report_date), []) if _context else
            _read_matching_rows(
                holdings_path,
                lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
                limit=20,
            ),
        ))
        evidence_items.append(_evidence(
            "count_stability",
            "count_stability",
            "Position count stability row for this CIK/date.",
            _context["stability_rows_by_pair"].get((cik, report_date), []) if _context else
            _read_matching_rows(stability_path, lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date),
        ))
        evidence_items.append(_evidence(
            "bdc_filing_index",
            "filing_index",
            "BDC filing index rows for this CIK/date.",
            _context["filing_rows_by_pair"].get((cik, report_date), []) if _context else
            _read_matching_rows(filings_path, lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date),
        ))
        evidence_items.append(_evidence(
            "raw_bdc_cik_date_rows",
            "raw_source_rows",
            "Raw BDC source rows for this GAV CIK/date, with row count and examples.",
            _context["raw_bdc_gav_rows_by_pair"].get((cik, report_date), {}) if _context else
            _raw_bdc_rows_for_gav_pair(bdc_path, cik, report_date),
        ))

    if rule_id == "X09":
        evidence_items.append(_evidence(
            "pct_sum",
            "pct_sum",
            "CIK-quarter pct_of_net_assets sum row.",
            _context["pct_rows_by_pair"].get((cik, report_date), []) if _context else
            _read_matching_rows(pct_path, lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date),
        ))
        evidence_items.append(_evidence(
            "same_issuer_dimension_rows",
            "same_issuer_dimension_rows",
            "Same issuer/accession rows for duplicate dimension-path review.",
            _same_issuer_dimension_rows_from_context(_context, cik, report_date, holdings_row) if _context else
            _same_issuer_dimension_rows(output_dir, cik, report_date, holdings_row),
        ))

    source_artifacts = [
        _artifact(issue_path, cache),
        _artifact(holdings_path, cache),
        _artifact(fund_financials_path, cache),
    ]
    for extra in (bdc_path, nport_path, gav_path, pct_path, stability_path, filings_path):
        if extra.exists():
            source_artifacts.append(_artifact(extra, cache))

    bundle = {
        "schema_version": "1.0",
        "dataset": HOLDINGS_DATASET,
        "bundle_id": verification_id,
        "created_at": now_iso(),
        "source_artifacts": source_artifacts,
        "sample_manifest_row": manifest_row,
        "evidence_items": evidence_items,
    }
    ensure_dir(target.parent)
    target.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    bundle_sha = sha256_file(target)
    if _append_manifest:
        _append_bundle_manifest(output_dir, verification_id, target, bundle_sha)
    _write_run_guard(output_dir)
    return target


def _build_fund_evidence_bundle(
    verification_id: str,
    manifest_row: dict[str, str],
    output_dir: Path,
    target: Path,
    overwrite: bool,
    hash_cache: dict[Path, str] | None,
    append_manifest: bool,
    context: dict[str, Any] | None = None,
) -> Path:
    if target.exists() and not overwrite:
        raise FailVerificationError(f"Bundle already exists: {target}")

    cache = hash_cache if hash_cache is not None else {}
    validation_path = output_dir / "fund_financials_validation_current.csv"
    fund_financials_path = output_dir / "fund_financials.csv"
    quality_path = output_dir / "fund_financials_quality_metrics.csv"
    cross_path = output_dir / "fund_financials_cross_level.csv"
    holdings_path = output_dir / "private_markets_holdings.csv"
    gav_path = output_dir / "holdings_gav_reconciliation.csv"
    pct_path = output_dir / "holdings_pct_sum.csv"
    stability_path = output_dir / "holdings_count_stability.csv"
    source_paths = {
        "bdc_fund_income": output_dir / "bdc_fund_income.csv",
        "nport_fund_info": output_dir / "nport_fund_info.csv",
        "ncsr_financials": output_dir / "ncsr_financials.csv",
        "combined_universe": output_dir / "combined_universe.csv",
        "fund_identity": output_dir / "fund_identity.csv",
    }

    cik = manifest_row["cik"]
    report_date = manifest_row["report_date"]
    rule_id = manifest_row["rule_id"]
    row_key = manifest_row.get("row_key", "")

    if context:
        validation_rows = context["fund_validation_rows_by_vid"].get(verification_id, [])
    else:
        validation_rows = _read_fund_validation_rows(validation_path, cik, report_date, rule_id, row_key)
    if not validation_rows and not context:
        validation_rows = _read_matching_rows(
            validation_path,
            lambda r: normalize_cik(r.get("cik")) == cik
            and r.get("report_date", "") == report_date
            and r.get("check_code", "") == rule_id,
        )

    pair = (cik, report_date)
    fund_rows = (
        context["fund_financials_rows_by_pair"].get(pair, [])
        if context else _read_matching_rows(
            fund_financials_path,
            lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        )
    )
    nearby_fund_rows = (
        context["nearby_fund_rows_by_pair"].get(pair, [])
        if context else _nearby_fund_rows(fund_financials_path, cik, report_date)
    )
    quality_rows = (
        context["fund_quality_rows_by_pair"].get(pair, [])
        if context else _read_matching_rows(
            quality_path,
            lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        )
    )

    evidence_items = [
        _evidence("manifest_row", "sample_manifest_row", "Sample manifest identity row.", manifest_row),
        _evidence("validation_rows", "fund_validation_row", "Matching fund_financials validation FAIL row or rows.", validation_rows),
        _evidence("fund_financials_row", "fund_financials", "Materialized fund_financials row for the sampled CIK/date.", fund_rows),
        _evidence("nearby_fund_rows", "fund_period_context", "Prior/current/next fund_financials rows for the same CIK.", nearby_fund_rows),
        _evidence("fund_quality_metrics", "fund_quality_metrics", "Fund validation quality metrics for the sampled CIK/date.", quality_rows),
    ]

    if rule_id in CROSS_LEVEL_FUND_RULES:
        evidence_items.extend(
            _cross_level_fund_evidence_from_context(context, cik, report_date)
            if context else _cross_level_fund_evidence(output_dir, cik, report_date)
        )
        evidence_items.append(_evidence(
            "fund_cross_level_validation",
            "fund_cross_level_validation",
            "Cross-level validation rows for this CIK/date.",
            context["fund_cross_level_rows_by_pair"].get(pair, []) if context else
            _read_matching_rows(cross_path, lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date),
        ))

    source_rows = (
        context["fund_source_rows_by_cik"].get(cik, {})
        if context else _fund_source_rows_for_cik(source_paths, cik, report_date)
    )
    evidence_items.append(_evidence(
        "source_specific_rows",
        "source_specific_rows",
        "Available cached fund-level source rows for the sampled CIK.",
        source_rows,
    ))

    companyfacts_path = PROJECT_ROOT / "data" / "raw" / "companyfacts_cache" / f"{cik}.json"
    companyfacts_summary = _companyfacts_cache_summary(companyfacts_path)
    evidence_items.append(_evidence(
        "companyfacts_cache",
        "companyfacts_cache",
        "Bounded metadata from cached companyfacts JSON if available. No network call is made.",
        companyfacts_summary,
    ))
    evidence_items.extend(_fund_rule_specific_evidence(
        rule_id=rule_id,
        cik=cik,
        report_date=report_date,
        output_dir=output_dir,
        manifest_row=manifest_row,
        validation_rows=validation_rows,
        fund_rows=fund_rows,
        nearby_fund_rows=nearby_fund_rows,
        source_rows=source_rows,
        companyfacts_path=companyfacts_path,
        context=context,
    ))

    source_artifacts = [
        _artifact(validation_path, cache),
        _artifact(fund_financials_path, cache),
        _artifact(quality_path, cache),
        _artifact(cross_path, cache),
        _artifact(companyfacts_path, cache),
    ]
    for path in [holdings_path, gav_path, pct_path, stability_path, *source_paths.values()]:
        if path.exists():
            source_artifacts.append(_artifact(path, cache))

    bundle = {
        "schema_version": "1.0",
        "dataset": FUND_DATASET,
        "bundle_id": verification_id,
        "created_at": now_iso(),
        "source_artifacts": source_artifacts,
        "sample_manifest_row": manifest_row,
        "evidence_items": evidence_items,
    }
    ensure_dir(target.parent)
    target.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    bundle_sha = sha256_file(target)
    if append_manifest:
        _append_bundle_manifest(output_dir, verification_id, target, bundle_sha)
    _write_run_guard(output_dir)
    return target


def _fund_source_rows_for_cik(
    source_paths: dict[str, Path],
    cik: str,
    report_date: str,
) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for name, path in source_paths.items():
        if not path.exists():
            result[name] = []
            continue
        exact: list[dict[str, str]] = []
        context_rows: list[dict[str, str]] = []
        for row in read_csv_rows(path):
            row_matches = (
                normalize_cik(row.get("cik")) == cik
                or normalize_cik(row.get("CIK")) == cik
                or normalize_cik(row.get("series_cik")) == cik
            )
            if not row_matches:
                continue
            if row.get("report_date", "") == report_date and len(exact) < 20:
                exact.append(row)
            elif len(context_rows) < 20:
                context_rows.append(row)
        result[name] = exact + context_rows[: max(0, 20 - len(exact))]
    return result


def _read_fund_validation_rows(
    path: Path,
    cik: str,
    report_date: str,
    rule_id: str,
    row_key: str,
) -> list[dict[str, str]]:
    if not path.exists():
        return []
    matches: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for index, row in enumerate(reader):
            if row_key.isdigit() and index != int(row_key):
                continue
            if (
                normalize_cik(row.get("cik")) == cik
                and row.get("report_date", "") == report_date
                and row.get("check_code", "") == rule_id
            ):
                matches.append(row)
            if row_key.isdigit() and index >= int(row_key):
                break
    return matches


def _nearby_fund_rows(path: Path, cik: str, report_date: str) -> list[dict[str, str]]:
    rows = _read_matching_rows(path, lambda r: normalize_cik(r.get("cik")) == cik)
    rows.sort(key=lambda r: r.get("report_date", ""))
    current_indexes = [i for i, row in enumerate(rows) if row.get("report_date", "") == report_date]
    if not current_indexes:
        return rows[-3:]
    idx = current_indexes[0]
    return rows[max(0, idx - 1): idx + 2]


def _cross_level_fund_evidence(output_dir: Path, cik: str, report_date: str) -> list[dict[str, Any]]:
    holdings_examples = _read_matching_rows(
        output_dir / "private_markets_holdings.csv",
        lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        limit=20,
    )
    aggregate = _holdings_aggregate(output_dir / "private_markets_holdings.csv", cik, report_date)
    same_period_issues = _read_matching_rows(
        output_dir / "row_validation_issues.csv",
        lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        limit=50,
    )
    return [
        _evidence("holdings_aggregate", "holdings_aggregate", "Holdings aggregate for the sampled CIK/date.", aggregate),
        _evidence("holdings_examples", "holdings_examples", "Sample holdings rows for the sampled CIK/date.", holdings_examples),
        _evidence("same_period_holdings_validation", "holdings_validation", "Holdings validation artifacts for the sampled CIK/date.", same_period_issues),
        _evidence("gav_reconciliation", "gav_reconciliation", "GAV reconciliation row for the sampled CIK/date.", _read_matching_rows(
            output_dir / "holdings_gav_reconciliation.csv",
            lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        )),
        _evidence("pct_sum", "pct_sum", "pct_of_net_assets sum row for the sampled CIK/date.", _read_matching_rows(
            output_dir / "holdings_pct_sum.csv",
            lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        )),
        _evidence("count_stability", "count_stability", "Holdings count stability row for the sampled CIK/date.", _read_matching_rows(
            output_dir / "holdings_count_stability.csv",
            lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        )),
    ]


def _cross_level_fund_evidence_from_context(
    context: dict[str, Any],
    cik: str,
    report_date: str,
) -> list[dict[str, Any]]:
    pair = (cik, report_date)
    return [
        _evidence("holdings_aggregate", "holdings_aggregate", "Holdings aggregate for the sampled CIK/date.", context["fund_holdings_aggregate_by_pair"].get(
            pair,
            {
                "cik": cik,
                "report_date": report_date,
                "has_holdings": False,
                "position_count": 0,
                "sum_fair_value": 0.0,
                "sum_pct_of_net_assets": 0.0,
            },
        )),
        _evidence("holdings_examples", "holdings_examples", "Sample holdings rows for the sampled CIK/date.", context["fund_holdings_examples_by_pair"].get(pair, [])),
        _evidence("same_period_holdings_validation", "holdings_validation", "Holdings validation artifacts for the sampled CIK/date.", context["fund_same_period_issues_by_pair"].get(pair, [])),
        _evidence("gav_reconciliation", "gav_reconciliation", "GAV reconciliation row for the sampled CIK/date.", context["gav_rows_by_pair"].get(pair, [])),
        _evidence("pct_sum", "pct_sum", "pct_of_net_assets sum row for the sampled CIK/date.", context["pct_rows_by_pair"].get(pair, [])),
        _evidence("count_stability", "count_stability", "Holdings count stability row for the sampled CIK/date.", context["stability_rows_by_pair"].get(pair, [])),
    ]


def _holdings_aggregate(path: Path, cik: str, report_date: str) -> dict[str, Any]:
    result = {
        "cik": cik,
        "report_date": report_date,
        "has_holdings": False,
        "position_count": 0,
        "sum_fair_value": 0.0,
        "sum_pct_of_net_assets": 0.0,
    }
    if not path.exists():
        return result
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if normalize_cik(row.get("cik")) != cik or row.get("report_date", "") != report_date:
                continue
            result["has_holdings"] = True
            result["position_count"] += 1
            for source_col, target_col in [
                ("fair_value", "sum_fair_value"),
                ("pct_of_net_assets", "sum_pct_of_net_assets"),
            ]:
                try:
                    result[target_col] += float(row.get(source_col) or 0)
                except ValueError:
                    pass
    return result


_COMPANYFACTS_JSON_CACHE: dict[str, Any] = {}


def _read_companyfacts_json(path: Path) -> Any:
    """Return parsed companyfacts JSON, caching in memory to avoid re-reads."""
    key = str(path)
    if key not in _COMPANYFACTS_JSON_CACHE:
        _COMPANYFACTS_JSON_CACHE[key] = json.loads(path.read_text(encoding="utf-8"))
    return _COMPANYFACTS_JSON_CACHE[key]


def _companyfacts_cache_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": display_path(path), "status": "missing"}
    try:
        data = _read_companyfacts_json(path)
    except Exception as exc:
        return {"path": display_path(path), "status": "unreadable", "error": str(exc)}
    facts = data.get("facts", {})
    us_gaap = facts.get("us-gaap", {}) if isinstance(facts, dict) else {}
    dei = facts.get("dei", {}) if isinstance(facts, dict) else {}
    return {
        "path": display_path(path),
        "status": "present",
        "entityName": data.get("entityName", ""),
        "cik": data.get("cik", ""),
        "us_gaap_concepts": sorted(us_gaap.keys())[:50],
        "dei_concepts": sorted(dei.keys())[:20],
    }


def _fund_rule_specific_evidence(
    rule_id: str,
    cik: str,
    report_date: str,
    output_dir: Path,
    manifest_row: dict[str, str],
    validation_rows: list[dict[str, str]],
    fund_rows: list[dict[str, str]],
    nearby_fund_rows: list[dict[str, str]],
    source_rows: dict[str, list[dict[str, str]]],
    companyfacts_path: Path,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Add rule-named evidence so reviewers can adjudicate instead of guessing."""
    period_sources = _period_source_rows(source_rows, report_date)
    items: list[dict[str, Any]] = []

    if rule_id in FRONTEND_EXPORT_RULES:
        items.append(_evidence(
            "f1_export_value_trace" if rule_id == "F1" else "frontend_export_value_trace",
            "frontend_export_value_trace",
            "Export-facing values, raw fund_financials values, parsed numerics, and frontend JSON rows when available.",
            _frontend_export_value_trace(cik, report_date, validation_rows, fund_rows),
        ))

    if rule_id == "F2":
        items.append(_evidence(
            "f2_future_date_sources",
            "future_report_date_sources",
            "Source accessions, filing metadata, and nearby valid report dates for a future report date.",
            {
                "validation_rows": validation_rows,
                "current_fund_rows": fund_rows,
                "nearby_valid_report_dates": [
                    row for row in nearby_fund_rows
                    if row.get("report_date", "") and row.get("report_date", "") <= now_iso()[:10]
                ],
                "source_period_rows": period_sources,
                "companyfacts_date_candidates": _companyfacts_candidate_facts(
                    companyfacts_path,
                    ["DocumentPeriodEndDate", "DocumentFiscalPeriodFocus", "DocumentFiscalYearFocus"],
                    report_date,
                    namespaces=("dei",),
                ),
            },
        ))

    if rule_id == "F10":
        items.append(_evidence(
            "f10_companyfacts_balance_sheet_candidates",
            "companyfacts_candidate_facts",
            "Companyfacts candidates for assets, liabilities, net assets/equity concepts, frames, accessions, periods, and dimensions.",
            _companyfacts_candidate_facts(companyfacts_path, _F10_CONCEPTS, report_date),
        ))

    if rule_id == "F11":
        nav_identity = _computed_nav_identity(fund_rows)
        items.append(_evidence(
            "f11_nav_identity_source_candidates",
            "nav_identity_source_candidates",
            "Source candidates for NAV/share, shares outstanding, and net assets with class or series metadata where available.",
            {
                "period_source_rows": period_sources,
                "companyfacts_candidates": _companyfacts_candidate_facts(companyfacts_path, _F11_CONCEPTS, report_date),
                "computed_from_fund_rows": nav_identity,
            },
        ))
        items.append(_evidence(
            "f11_nav_identity_metric_trace",
            "fund_metric_source_trace",
            "Normalized source trace for net assets/equity, NAV/share, shares outstanding, and NAV identity recomputation.",
            {
                **_fund_metric_source_trace(
                metric_name="nav_identity",
                materialized_value=_first_value(fund_rows, ["net_assets", "assets_net", "stockholders_equity"]),
                formula="nav_per_share * shares_outstanding = net_assets",
                input_specs=[
                    {
                        "name": "net_assets_or_equity",
                        "columns": ["net_assets", "assets_net", "stockholders_equity"],
                        "field_hints": ["net_assets", "assets_net", "equity"],
                        "concepts": ["NetAssets", "AssetsNet", "StockholdersEquity"],
                    },
                    {
                        "name": "nav_per_share",
                        "columns": ["nav_per_share", "net_asset_value_per_share"],
                        "field_hints": ["nav", "net_asset_value", "per_share"],
                        "concepts": ["NetAssetValuePerShare"],
                    },
                    {
                        "name": "shares_outstanding",
                        "columns": ["shares_outstanding", "common_shares_outstanding"],
                        "field_hints": ["share", "shares_outstanding"],
                        "concepts": ["CommonStockSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
                    },
                ],
                fund_rows=fund_rows,
                source_rows=source_rows,
                companyfacts_path=companyfacts_path,
                report_date=report_date,
                computed_value=nav_identity[0].get("recomputed_net_assets") if nav_identity else None,
                ),
                "share_scope_evidence": _share_scope_evidence(fund_rows, source_rows, companyfacts_path, report_date),
            },
        ))

    if rule_id == "F13":
        items.append(_evidence(
            "f13_fee_expense_sources",
            "fee_expense_sources",
            "N-PORT/N-CSR/BDC fee and expense rows for the exact period, with explicit missing markers.",
            _source_fact_or_missing(period_sources, ["management_fee", "advisory_fee", "total_expenses", "average_net_assets", "expense_ratio"]),
        ))

    if rule_id == "F16":
        items.append(_evidence(
            "f16_distribution_income_sources",
            "distribution_income_sources",
            "Distribution, income, per-share, ROC, gains, and trailing-period source context.",
            {
                "current_period_sources": _source_fact_or_missing(period_sources, _F16_FIELD_HINTS),
                "trailing_four_quarters": nearby_fund_rows[-4:],
                "companyfacts_candidates": _companyfacts_candidate_facts(companyfacts_path, _F16_CONCEPTS, report_date),
            },
        ))

    if rule_id == "F18":
        items.append(_evidence(
            "f18_bdc_asset_coverage_sources",
            "bdc_asset_coverage_sources",
            "Asset coverage, senior securities, debt, asset/liability, status, and lifecycle evidence.",
            {
                "period_source_rows": _source_fact_or_missing(period_sources, _F18_FIELD_HINTS),
                "companyfacts_candidates": _companyfacts_candidate_facts(companyfacts_path, _F18_CONCEPTS, report_date),
                "lifecycle_flags": _fund_lifecycle_flags(fund_rows, source_rows),
            },
        ))

    if rule_id in CROSS_LEVEL_FUND_RULES:
        items.extend(_cross_level_rule_specific_evidence(
            rule_id,
            cik,
            report_date,
            output_dir,
            fund_rows,
            nearby_fund_rows,
            period_sources,
            source_rows,
            companyfacts_path,
            context,
        ))

    if rule_id == "F30":
        items.append(_evidence(
            "f30_nav_share_range_sources",
            "nav_share_range_sources",
            "NAV/share source facts, share class metadata, net assets, shares, lifecycle flags, and adjacent NAVs.",
            {
                "period_source_rows": _source_fact_or_missing(period_sources, _F30_FIELD_HINTS),
                "companyfacts_candidates": _companyfacts_candidate_facts(companyfacts_path, _F30_CONCEPTS, report_date),
                "adjacent_periods": nearby_fund_rows,
                "lifecycle_flags": _fund_lifecycle_flags(fund_rows, source_rows),
            },
        ))

    if rule_id == "F32":
        computed_expense_ratio = _computed_expense_ratio(fund_rows)
        items.append(_evidence(
            "f32_expense_ratio_scale_sources",
            "expense_ratio_scale_sources",
            "Expense ratio, total expenses, average net assets, management fee, units/scale, and adjacent periods.",
            {
                "period_source_rows": _source_fact_or_missing(period_sources, _F32_FIELD_HINTS),
                "adjacent_periods": nearby_fund_rows,
                "computed_from_fund_rows": computed_expense_ratio,
            },
        ))
        items.append(_evidence(
            "f32_expense_ratio_metric_trace",
            "fund_metric_source_trace",
            "Normalized source trace distinguishing direct expense ratio evidence from missing total-expense and average-net-assets inputs.",
            {
                **_fund_metric_source_trace(
                metric_name="expense_ratio",
                materialized_value=_first_value(fund_rows, ["expense_ratio", "net_expense_ratio", "gross_expense_ratio"]),
                formula="direct expense_ratio or total_expenses / average_net_assets",
                input_specs=[
                    {
                        "name": "direct_expense_ratio",
                        "columns": ["expense_ratio", "net_expense_ratio", "gross_expense_ratio"],
                        "field_hints": ["expense_ratio", "net_expense_ratio", "gross_expense_ratio"],
                        "concepts": [],
                    },
                    {
                        "name": "total_expenses",
                        "columns": ["total_expenses", "expenses"],
                        "field_hints": ["total_expenses", "expenses", "management_fee", "advisory_fee"],
                        "concepts": ["Expenses", "OperatingExpenses", "ManagementFees"],
                    },
                    {
                        "name": "average_net_assets",
                        "columns": ["average_net_assets"],
                        "field_hints": ["average_net_assets"],
                        "concepts": [],
                    },
                ],
                fund_rows=fund_rows,
                source_rows=source_rows,
                companyfacts_path=companyfacts_path,
                report_date=report_date,
                computed_value=computed_expense_ratio[0].get("computed_expense_ratio") if computed_expense_ratio else None,
                ),
                "expense_source_availability_matrix": _source_availability_matrix(
                    fund_rows,
                    source_rows,
                    companyfacts_path,
                    report_date,
                    _F32_FIELD_HINTS,
                    ["Expenses", "OperatingExpenses", "ManagementFees"],
                ),
            },
        ))

    if rule_id == "F33":
        distribution_rate = _computed_distribution_rate(fund_rows)
        items.append(_evidence(
            "f33_distribution_rate_sources",
            "distribution_rate_sources",
            "Distribution per share, NAV/share, computed rate, source facts, income/ROC/gains split, and adjacent periods.",
            {
                "computed_from_fund_rows": distribution_rate,
                "period_source_rows": _source_fact_or_missing(period_sources, _F33_FIELD_HINTS),
                "companyfacts_candidates": _companyfacts_candidate_facts(companyfacts_path, _F33_CONCEPTS, report_date),
                "adjacent_periods": nearby_fund_rows,
            },
        ))
        items.append(_evidence(
            "f33_distribution_rate_metric_trace",
            "fund_metric_source_trace",
            "Normalized source trace for distribution per share, NAV/share, distribution decomposition, and computed distribution rate.",
            {
                **_fund_metric_source_trace(
                metric_name="distribution_rate",
                materialized_value=_first_value(fund_rows, ["distribution_rate", "dividend_yield"]),
                formula="distribution_per_share / nav_per_share",
                input_specs=[
                    {
                        "name": "distribution_per_share",
                        "columns": ["distributions_per_share", "distribution_per_share", "dividend_per_share"],
                        "field_hints": ["distribution", "dividend", "per_share"],
                        "concepts": ["DividendsCommonStockCash", "DistributionToShareholders"],
                    },
                    {
                        "name": "nav_per_share",
                        "columns": ["nav_per_share", "net_asset_value_per_share"],
                        "field_hints": ["nav", "net_asset_value", "per_share"],
                        "concepts": ["NetAssetValuePerShare"],
                    },
                    {
                        "name": "distribution_decomposition",
                        "columns": ["return_of_capital_per_share", "ordinary_income_distribution_per_share", "capital_gain_distribution_per_share"],
                        "field_hints": ["return_of_capital", "roc", "ordinary", "income", "gain"],
                        "concepts": ["ReturnOfCapitalDistributions", "RealizedInvestmentGainsLosses"],
                    },
                ],
                fund_rows=fund_rows,
                source_rows=source_rows,
                companyfacts_path=companyfacts_path,
                report_date=report_date,
                computed_value=distribution_rate[0].get("computed_distribution_rate") if distribution_rate else None,
                ),
                "distribution_source_availability_matrix": _source_availability_matrix(
                    fund_rows,
                    source_rows,
                    companyfacts_path,
                    report_date,
                    _F33_FIELD_HINTS,
                    _F33_CONCEPTS,
                ),
            },
        ))

    return items


_F10_CONCEPTS = [
    "Assets", "Liabilities", "AssetsNet", "StockholdersEquity",
    "LiabilitiesAndStockholdersEquity", "PartnersCapital", "NetAssets",
]
_F11_CONCEPTS = [
    "NetAssetValuePerShare", "NetAssets", "AssetsNet",
    "CommonStocksIncludingAdditionalPaidInCapital", "CommonStockSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
]
_F16_CONCEPTS = [
    "InvestmentIncomeInterest", "InvestmentIncomeNet", "NetInvestmentIncome",
    "Dividends", "DividendsCommonStockCash", "ReturnOfCapitalDistributions",
    "RealizedInvestmentGainsLosses", "DistributionToShareholders",
]
_F18_CONCEPTS = [
    "AssetCoverageRatio", "DebtInstrumentCarryingAmount", "Borrowings",
    "LongTermDebt", "SeniorSecurities", "Assets", "AssetsNet", "Liabilities",
]
_F26_CONCEPTS = [
    "DebtInstrumentCarryingAmount", "Borrowings", "LongTermDebt", "NotesPayable",
    "PreferredStocksIncludingAdditionalPaidInCapital", "Assets", "AssetsNet",
    "CashAndCashEquivalentsAtCarryingValue", "ReceivablesNetCurrent",
]
_F30_CONCEPTS = ["NetAssetValuePerShare", "NetAssets", "CommonStockSharesOutstanding", "StockholdersEquity"]
_F33_CONCEPTS = ["DividendsCommonStockCash", "DistributionToShareholders", "ReturnOfCapitalDistributions", "NetAssetValuePerShare"]
_F16_FIELD_HINTS = ["distribution", "dividend", "net_investment_income", "income", "per_share", "ordinary", "roc", "return_of_capital", "gain", "special"]
_F18_FIELD_HINTS = ["asset_coverage", "borrowing", "debt", "senior", "total_assets", "net_assets", "liabilities", "bdc"]
_F30_FIELD_HINTS = ["nav", "net_asset_value", "share", "shares", "split", "liquidation", "formation"]
_F32_FIELD_HINTS = ["expense_ratio", "expenses", "average_net_assets", "management_fee", "advisory_fee", "unit", "scale"]
_F33_FIELD_HINTS = ["distribution", "dividend", "nav", "per_share", "return_of_capital", "roc", "gain", "income"]


_METRIC_TRACE_LIMIT = 25


def _share_scope_evidence(
    fund_rows: list[dict[str, str]],
    source_rows: dict[str, list[dict[str, str]]],
    companyfacts_path: Path,
    report_date: str,
) -> dict[str, Any]:
    companyfacts_candidates = _companyfacts_trace_candidates(
        companyfacts_path,
        ["NetAssetValuePerShare", "CommonStockSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
        report_date,
    )
    exact_companyfacts = companyfacts_candidates.get("exact_period", [])
    dimensioned = [candidate for candidate in exact_companyfacts if candidate.get("dimensions")]
    fund_scope_fields = [
        {
            key: value for key, value in row.items()
            if str(value).strip()
            and any(hint in key.lower() for hint in ["class", "series", "ticker", "cusip"])
        }
        for row in fund_rows
    ]
    source_scope_rows = []
    for source_name, rows in source_rows.items():
        for row in rows:
            if not _row_period_matches(row, report_date):
                continue
            scoped = {
                key: value for key, value in row.items()
                if str(value).strip()
                and any(hint in key.lower() for hint in ["class", "series", "ticker", "cusip"])
            }
            if scoped and len(source_scope_rows) < _METRIC_TRACE_LIMIT:
                source_scope_rows.append({"source": source_name, "scope_fields": scoped, "source_row": row})
    unresolved = not dimensioned and not any(fund_scope_fields) and not source_scope_rows
    return {
        "companyfacts_exact_period_share_facts": exact_companyfacts,
        "companyfacts_dimensioned_share_facts": dimensioned,
        "fund_row_scope_fields": fund_scope_fields,
        "source_row_scope_fields": source_scope_rows,
        "share_class_scope_resolved": not unresolved,
        "residual_ambiguity": (
            "No exact-period companyfacts dimensions or fund/source share-class fields identify whether "
            "NAV/share and shares outstanding use the same share-class scope."
            if unresolved else ""
        ),
    }


def _source_availability_matrix(
    fund_rows: list[dict[str, str]],
    source_rows: dict[str, list[dict[str, str]]],
    companyfacts_path: Path,
    report_date: str,
    field_hints: list[str],
    companyfacts_concepts: list[str],
) -> list[dict[str, Any]]:
    hints = [hint.lower() for hint in field_hints]
    rows = []
    for artifact, artifact_rows in {"fund_financials": fund_rows, **source_rows}.items():
        exact = [row for row in artifact_rows if _row_period_matches(row, report_date)]
        adjacent = [row for row in artifact_rows if not _row_period_matches(row, report_date)]
        exact_with_fields = [row for row in exact if _row_has_hint_value(row, hints)]
        rows.append({
            "artifact": artifact,
            "report_date": report_date,
            "exact_period_row_count": len(exact),
            "exact_period_matching_field_count": len(exact_with_fields),
            "adjacent_period_row_count": len(adjacent),
            "exact_period_source_rows": exact_with_fields[:_METRIC_TRACE_LIMIT],
            "adjacent_period_source_rows": adjacent[:_METRIC_TRACE_LIMIT],
            "rejected_candidates": [
                {
                    "reason": "exact-period row lacks requested field/concept hints",
                    "available_fields": sorted(key for key, value in row.items() if str(value).strip())[:25],
                    "source_row": row,
                }
                for row in exact
                if row not in exact_with_fields
            ][:_METRIC_TRACE_LIMIT],
            "source_absent": not exact_with_fields,
        })
    companyfacts_candidates = _companyfacts_trace_candidates(companyfacts_path, companyfacts_concepts, report_date)
    rows.append({
        "artifact": "companyfacts",
        "report_date": report_date,
        "exact_period_row_count": len(companyfacts_candidates.get("exact_period", [])),
        "exact_period_matching_field_count": len(companyfacts_candidates.get("exact_period", [])),
        "adjacent_period_row_count": len(companyfacts_candidates.get("adjacent_period_context", [])),
        "exact_period_source_rows": companyfacts_candidates.get("exact_period", []),
        "adjacent_period_source_rows": companyfacts_candidates.get("adjacent_period_context", []),
        "rejected_candidates": [],
        "source_absent": not companyfacts_candidates.get("exact_period", []),
    })
    return rows


def _fund_metric_source_trace(
    metric_name: str,
    materialized_value: Any,
    formula: str,
    input_specs: list[dict[str, Any]],
    fund_rows: list[dict[str, str]],
    source_rows: dict[str, list[dict[str, str]]],
    companyfacts_path: Path,
    report_date: str,
    computed_value: float | None = None,
) -> dict[str, Any]:
    """Normalize local source provenance for a fund metric without changing outputs."""
    selected_inputs = []
    missing_sources = []
    source_candidates: dict[str, dict[str, Any]] = {}
    rejected_candidates: dict[str, list[dict[str, Any]]] = {}

    fund_row = fund_rows[0] if fund_rows else {}
    for spec in input_specs:
        input_name = spec["name"]
        materialized_columns = spec.get("columns", [])
        row_candidates = _source_row_trace_candidates(
            source_rows,
            spec.get("field_hints", []),
            report_date,
        )
        companyfacts_candidates = _companyfacts_trace_candidates(
            companyfacts_path,
            spec.get("concepts", []),
            report_date,
        )
        candidates = {
            **row_candidates,
            "companyfacts": companyfacts_candidates,
        }
        exact_count = sum(len(value.get("exact_period", [])) for value in candidates.values())
        context_count = sum(len(value.get("adjacent_period_context", [])) for value in candidates.values())
        if exact_count == 0:
            missing_sources.append({
                "input": input_name,
                "reason": "no exact-period local source candidate",
                "context_candidate_count": context_count,
            })
        selected_inputs.append({
            "input": input_name,
            "materialized_columns": {
                column: fund_row.get(column, "")
                for column in materialized_columns
                if column in fund_row
            },
            "first_numeric_materialized_value": _first_numeric(fund_row, materialized_columns),
            "exact_source_candidate_count": exact_count,
            "context_source_candidate_count": context_count,
        })
        source_candidates[input_name] = candidates
        rejected_candidates[input_name] = _rejected_trace_candidates(
            source_rows,
            spec.get("field_hints", []),
            report_date,
        )

    materialized_numeric = _safe_float(materialized_value)
    delta = (
        materialized_numeric - computed_value
        if materialized_numeric is not None and computed_value is not None
        else None
    )
    return {
        "metric_name": metric_name,
        "materialized_value": materialized_value,
        "formula": formula,
        "selected_inputs": selected_inputs,
        "source_candidates": source_candidates,
        "exact_period_source_rows": _flatten_metric_source_rows(source_candidates, "exact_period"),
        "adjacent_period_source_rows": _flatten_metric_source_rows(source_candidates, "adjacent_period_context"),
        "missing_sources": missing_sources,
        "rejected_candidates": rejected_candidates,
        "source_absence_by_artifact": _metric_source_absence(source_candidates, report_date),
        "computed_value": computed_value,
        "delta_vs_materialized": delta,
        "residual_ambiguity": _metric_residual_ambiguity(metric_name, missing_sources, rejected_candidates),
        "trace_status": "source_backed" if not missing_sources else "missing_exact_period_sources",
    }


def _flatten_metric_source_rows(
    source_candidates: dict[str, dict[str, Any]],
    bucket_name: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for input_name, candidates_by_source in source_candidates.items():
        for source_name, buckets in candidates_by_source.items():
            if not isinstance(buckets, dict):
                continue
            for candidate in buckets.get(bucket_name, []):
                item = dict(candidate)
                item["input"] = input_name
                item["artifact"] = source_name
                rows.append(item)
                if len(rows) >= _METRIC_TRACE_LIMIT:
                    return rows
    return rows


def _metric_source_absence(
    source_candidates: dict[str, dict[str, Any]],
    report_date: str,
) -> list[dict[str, Any]]:
    absence = []
    for input_name, candidates_by_source in source_candidates.items():
        for source_name, buckets in candidates_by_source.items():
            if not isinstance(buckets, dict):
                continue
            exact = buckets.get("exact_period", [])
            adjacent = buckets.get("adjacent_period_context", [])
            absence.append({
                "input": input_name,
                "artifact": source_name,
                "report_date": report_date,
                "has_exact_period_source_rows": bool(exact),
                "exact_period_row_count": len(exact),
                "adjacent_period_row_count": len(adjacent),
                "absence_reason": "" if exact else "no exact-period cached source candidate",
            })
    return absence


def _metric_residual_ambiguity(
    metric_name: str,
    missing_sources: list[dict[str, Any]],
    rejected_candidates: dict[str, list[dict[str, Any]]],
) -> str:
    if not missing_sources:
        return ""
    rejected_count = sum(len(rows) for rows in rejected_candidates.values())
    return (
        f"{metric_name} has materialized or nearby context but lacks exact-period cached "
        f"source support for {len(missing_sources)} input(s); {rejected_count} exact-period "
        "row(s) were rejected because they did not expose the requested fields or concepts."
    )


def _source_row_trace_candidates(
    source_rows: dict[str, list[dict[str, str]]],
    field_hints: list[str],
    report_date: str,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    hints = [hint.lower() for hint in field_hints]
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for source_name, rows in source_rows.items():
        exact: list[dict[str, Any]] = []
        context: list[dict[str, Any]] = []
        for row in rows:
            if not _row_has_hint_value(row, hints):
                continue
            candidate = _normalize_source_candidate(source_name, row)
            if _row_period_matches(row, report_date):
                if len(exact) < _METRIC_TRACE_LIMIT:
                    exact.append(candidate)
            elif len(context) < _METRIC_TRACE_LIMIT:
                candidate["context_only"] = True
                context.append(candidate)
        result[source_name] = {
            "exact_period": exact,
            "adjacent_period_context": context,
        }
    return result


def _rejected_trace_candidates(
    source_rows: dict[str, list[dict[str, str]]],
    field_hints: list[str],
    report_date: str,
) -> list[dict[str, Any]]:
    hints = [hint.lower() for hint in field_hints]
    rejected: list[dict[str, Any]] = []
    for source_name, rows in source_rows.items():
        for row in rows:
            if _row_has_hint_value(row, hints):
                continue
            if _row_period_matches(row, report_date) and len(rejected) < _METRIC_TRACE_LIMIT:
                rejected.append({
                    "source": source_name,
                    "reason": "exact-period row lacks requested field/concept hints",
                    "available_fields": sorted(key for key, value in row.items() if str(value).strip())[:25],
                })
    return rejected


def _row_has_hint_value(row: dict[str, Any], hints: list[str]) -> bool:
    if not hints:
        return True
    return any(
        hint in str(key).lower() and str(value).strip() != ""
        for key, value in row.items()
        for hint in hints
    )


def _row_period_matches(row: dict[str, Any], report_date: str) -> bool:
    return any(
        row.get(key, "") == report_date
        for key in ["report_date", "period", "end_date", "date"]
    )


def _normalize_source_candidate(source_name: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": source_name,
        "field_or_concept": row.get("concept") or row.get("metric") or row.get("field") or "",
        "value": row.get("value") or row.get("val") or "",
        "unit": row.get("unit") or row.get("units") or "",
        "period": row.get("report_date") or row.get("period") or row.get("end_date") or "",
        "accession": row.get("accession_number") or row.get("accn") or "",
        "filing_date": row.get("filing_date") or row.get("filed") or "",
        "frame": row.get("frame", ""),
        "dimensions": row.get("dimensions") or row.get("bdc_dimensions_raw") or "",
        "source_row": row,
    }


def _companyfacts_trace_candidates(
    path: Path,
    concepts: list[str],
    report_date: str,
    namespaces: tuple[str, ...] = ("us-gaap", "dei", "invest"),
) -> dict[str, list[dict[str, Any]]]:
    result = {"exact_period": [], "adjacent_period_context": []}
    if not concepts:
        return result
    if not path.exists():
        return result
    try:
        data = _read_companyfacts_json(path)
    except Exception:
        return result
    facts = data.get("facts", {})
    for namespace in namespaces:
        ns_facts = facts.get(namespace, {}) if isinstance(facts, dict) else {}
        if not isinstance(ns_facts, dict):
            continue
        for concept in concepts:
            concept_data = ns_facts.get(concept)
            if not isinstance(concept_data, dict):
                continue
            units = concept_data.get("units", {})
            if not isinstance(units, dict):
                continue
            for unit, unit_facts in units.items():
                if not isinstance(unit_facts, list):
                    continue
                for fact in unit_facts:
                    candidate = {
                        "source": "companyfacts",
                        "namespace": namespace,
                        "field_or_concept": concept,
                        "label": concept_data.get("label", ""),
                        "value": fact.get("val"),
                        "unit": unit,
                        "period": fact.get("end", ""),
                        "start": fact.get("start", ""),
                        "accession": fact.get("accn", ""),
                        "filing_date": fact.get("filed", ""),
                        "frame": fact.get("frame", ""),
                        "dimensions": fact.get("dimensions", {}),
                        "source_row": fact,
                    }
                    if fact.get("end") == report_date or fact.get("frame") == report_date:
                        if len(result["exact_period"]) < _METRIC_TRACE_LIMIT:
                            result["exact_period"].append(candidate)
                    elif len(result["adjacent_period_context"]) < _METRIC_TRACE_LIMIT:
                        candidate["context_only"] = True
                        result["adjacent_period_context"].append(candidate)
    return result


def _period_source_rows(source_rows: dict[str, list[dict[str, str]]], report_date: str) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for name, rows in source_rows.items():
        matches = [
            row for row in rows
            if row.get("report_date", "") == report_date
            or row.get("period", "") == report_date
            or row.get("end_date", "") == report_date
        ]
        result[name] = matches or [{"source_fact_missing": True, "source": name, "report_date": report_date}]
    return result


def _source_fact_or_missing(rows_by_source: dict[str, list[dict[str, str]]], field_hints: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    hints = [hint.lower() for hint in field_hints]
    for source, rows in rows_by_source.items():
        extracted = []
        for row in rows:
            if row.get("source_fact_missing") is True:
                continue
            matched = {
                key: value for key, value in row.items()
                if any(hint in key.lower() for hint in hints) and str(value).strip() != ""
            }
            if matched:
                extracted.append({"matched_fields": matched, "source_row": row})
        result[source] = extracted or [{"source_fact_missing": True, "field_hints": field_hints}]
    return result


def _companyfacts_candidate_facts(
    path: Path,
    concepts: list[str],
    report_date: str,
    namespaces: tuple[str, ...] = ("us-gaap", "dei", "invest"),
) -> dict[str, Any]:
    if not path.exists():
        return {"path": display_path(path), "status": "missing", "concepts": concepts}
    try:
        data = _read_companyfacts_json(path)
    except Exception as exc:
        return {"path": display_path(path), "status": "unreadable", "error": str(exc), "concepts": concepts}
    facts = data.get("facts", {})
    candidates: dict[str, list[dict[str, Any]]] = {}
    for namespace in namespaces:
        ns_facts = facts.get(namespace, {}) if isinstance(facts, dict) else {}
        if not isinstance(ns_facts, dict):
            continue
        for concept in concepts:
            concept_data = ns_facts.get(concept)
            if not isinstance(concept_data, dict):
                continue
            units = concept_data.get("units", {})
            rows = []
            if isinstance(units, dict):
                for unit, unit_facts in units.items():
                    if not isinstance(unit_facts, list):
                        continue
                    exact = [
                        fact for fact in unit_facts
                        if fact.get("end") == report_date
                        or fact.get("fy") == report_date
                        or fact.get("frame") == report_date
                    ]
                    sample = exact[:20] if exact else unit_facts[-5:]
                    for fact in sample:
                        rows.append({
                            "namespace": namespace,
                            "concept": concept,
                            "label": concept_data.get("label", ""),
                            "description": concept_data.get("description", ""),
                            "unit": unit,
                            "val": fact.get("val"),
                            "start": fact.get("start", ""),
                            "end": fact.get("end", ""),
                            "fy": fact.get("fy", ""),
                            "fp": fact.get("fp", ""),
                            "form": fact.get("form", ""),
                            "filed": fact.get("filed", ""),
                            "frame": fact.get("frame", ""),
                            "accn": fact.get("accn", ""),
                            "dimensions": fact.get("dimensions", {}),
                        })
            if rows:
                candidates[f"{namespace}:{concept}"] = rows
    return {
        "path": display_path(path),
        "status": "present",
        "report_date": report_date,
        "candidates": candidates,
        "missing_concepts": [
            concept for concept in concepts
            if not any(key.endswith(f":{concept}") for key in candidates)
        ],
    }


def _frontend_export_value_trace(
    cik: str,
    report_date: str,
    validation_rows: list[dict[str, str]],
    fund_rows: list[dict[str, str]],
) -> dict[str, Any]:
    flagged_fields = sorted({
        row.get("field") or row.get("column") or row.get("metric") or row.get("check_code", "")
        for row in validation_rows
        if row.get("field") or row.get("column") or row.get("metric") or row.get("check_code")
    })
    traces = []
    for fund_row in fund_rows:
        fields = flagged_fields or list(fund_row.keys())
        for field in fields:
            raw_value = fund_row.get(field, "")
            parsed = _parse_numeric_marker(raw_value)
            traces.append({
                "field": field,
                "raw_fund_financials_value": raw_value,
                "parsed_numeric_result": parsed,
                "serialized_export_value": _json_serialized_value(raw_value),
            })
    frontend_row = _frontend_fund_detail_row(cik, report_date)
    return {
        "cik": cik,
        "report_date": report_date,
        "flagged_fields": flagged_fields,
        "value_traces": traces,
        "frontend_json_row": frontend_row,
    }


def _parse_numeric_marker(value: Any) -> dict[str, Any]:
    text = "" if value is None else str(value)
    if text.strip() == "":
        return {"state": "blank_became_nan", "value": None}
    try:
        parsed = float(text)
    except ValueError:
        return {"state": "non_numeric_string", "value": text}
    if math.isnan(parsed):
        return {"state": "string_nan", "value": text}
    if math.isinf(parsed):
        return {"state": "infinity", "value": text}
    return {"state": "finite", "value": parsed}


def _json_serialized_value(value: Any) -> dict[str, Any]:
    try:
        serialized = json.dumps(value, allow_nan=False)
        return {"state": "json_serializable", "serialized": serialized}
    except ValueError:
        return {"state": "json_non_finite", "serialized": ""}


def _frontend_fund_detail_row(cik: str, report_date: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "frontend" / "public" / "data" / "fund_details" / f"{cik}.json"
    if not path.exists():
        return {"path": display_path(path), "status": "missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"path": display_path(path), "status": "unreadable", "error": str(exc)}
    matches = _find_json_rows_for_report_date(data, report_date)
    return {"path": display_path(path), "status": "present", "matches": matches[:5]}


def _find_json_rows_for_report_date(value: Any, report_date: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("report_date") == report_date or value.get("date") == report_date:
            found.append(value)
        for child in value.values():
            found.extend(_find_json_rows_for_report_date(child, report_date))
            if len(found) >= 5:
                break
    elif isinstance(value, list):
        for child in value:
            found.extend(_find_json_rows_for_report_date(child, report_date))
            if len(found) >= 5:
                break
    return found


def _fund_lifecycle_flags(fund_rows: list[dict[str, str]], source_rows: dict[str, list[dict[str, str]]]) -> dict[str, bool]:
    text = json.dumps({"fund_rows": fund_rows, "source_rows": source_rows}, sort_keys=True).lower()
    return {
        "formation_stage_candidate": any(term in text for term in ["formation", "newly launched", "commenced operations", "post-effective"]),
        "liquidation_candidate": any(term in text for term in ["liquidation", "liquidating", "wind down", "wind-down"]),
        "zero_asset_candidate": any(_safe_float(row.get("total_assets")) == 0 for row in fund_rows),
        "bdc_status_candidate": "bdc" in text or "business development company" in text,
    }


def _computed_distribution_rate(fund_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result = []
    for row in fund_rows:
        distribution = _first_numeric(row, ["distributions_per_share", "distribution_per_share", "dividend_per_share"])
        nav = _first_numeric(row, ["nav_per_share", "net_asset_value_per_share"])
        result.append({
            "report_date": row.get("report_date", ""),
            "distribution_per_share": distribution,
            "nav_per_share": nav,
            "computed_distribution_rate": distribution / nav if distribution is not None and nav not in (None, 0) else None,
        })
    return result


def _computed_nav_identity(fund_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result = []
    for row in fund_rows:
        nav = _first_numeric(row, ["nav_per_share", "net_asset_value_per_share"])
        shares = _first_numeric(row, ["shares_outstanding", "common_shares_outstanding"])
        net_assets = _first_numeric(row, ["net_assets", "assets_net", "stockholders_equity"])
        computed = nav * shares if nav is not None and shares is not None else None
        result.append({
            "report_date": row.get("report_date", ""),
            "nav_per_share": nav,
            "shares_outstanding": shares,
            "materialized_net_assets": net_assets,
            "recomputed_net_assets": computed,
            "delta_vs_materialized": net_assets - computed if net_assets is not None and computed is not None else None,
        })
    return result


def _computed_expense_ratio(fund_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    result = []
    for row in fund_rows:
        expenses = _first_numeric(row, ["total_expenses", "expenses"])
        average_net_assets = _first_numeric(row, ["average_net_assets"])
        direct = _first_numeric(row, ["expense_ratio", "net_expense_ratio", "gross_expense_ratio"])
        computed = expenses / average_net_assets if expenses is not None and average_net_assets not in (None, 0) else None
        result.append({
            "report_date": row.get("report_date", ""),
            "direct_expense_ratio": direct,
            "total_expenses": expenses,
            "average_net_assets": average_net_assets,
            "computed_expense_ratio": computed,
            "delta_vs_direct": direct - computed if direct is not None and computed is not None else None,
        })
    return result


def _first_value(rows: list[dict[str, str]], keys: list[str]) -> Any:
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip() != "":
                return value
    return None


def _first_numeric(row: dict[str, str], keys: list[str]) -> float | None:
    for key in keys:
        value = _safe_float(row.get(key))
        if value is not None:
            return value
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _cross_level_rule_specific_evidence(
    rule_id: str,
    cik: str,
    report_date: str,
    output_dir: Path,
    fund_rows: list[dict[str, str]],
    nearby_fund_rows: list[dict[str, str]],
    period_sources: dict[str, list[dict[str, str]]],
    source_rows: dict[str, list[dict[str, str]]],
    companyfacts_path: Path,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if rule_id in {"F20", "F21"}:
        evidence_id = "f20_gav_reconciliation_detail" if rule_id == "F20" else "f21_net_assets_scope_reconciliation"
        kind = "raw_to_unified_holdings_reconciliation" if rule_id == "F20" else "cross_level_reconciliation_detail"
        description = (
            "Full GAV reconciliation, raw/unified row counts and FV sums, duplicate samples, exclusions, and denominator source."
            if rule_id == "F20" else
            "Denominator scope evidence distinguishing full-fund net assets from private-market-filtered holdings."
        )
        return [_evidence(
            evidence_id,
            kind,
            description,
            _gav_scope_detail(
                output_dir,
                cik,
                report_date,
                fund_rows,
                period_sources,
                context,
                include_bdc_schedule=rule_id == "F20",
            ),
        )]
    if rule_id in {"F22", "F23"}:
        return [_evidence(
            "f22_pct_sum_detail" if rule_id == "F22" else "f23_reported_vs_computed_pct_detail",
            "pct_reconciliation_detail" if rule_id == "F22" else "nport_pct_denominator_trace",
            "Pct rows, reported vs computed pct, denominator facts, and largest row-level divergences.",
            _pct_reconciliation_detail(output_dir, cik, report_date, fund_rows, context),
        )]
    if rule_id == "F24":
        return [_evidence(
            "f24_position_count_stability_detail",
            "position_transition_trace",
            "Prior/current/next counts, FV sums, raw source counts, filing changes, and top added/dropped positions.",
            _position_stability_detail(output_dir, cik, report_date, context),
        )]
    if rule_id == "F25":
        return [_evidence(
            "f25_holdings_fv_stability_detail",
            "holdings_fv_stability_detail",
            "Prior/current/next holdings FV, total assets, investments FV, raw FV, and largest movers.",
            _fv_stability_detail(output_dir, cik, report_date, nearby_fund_rows, context),
        )]
    if rule_id == "F26":
        return [_evidence(
            "f26_leverage_two_view_sources",
            "leverage_two_view_sources",
            "Borrowing/debt concept candidates, assets, holdings FV, non-investment assets, preferred stock, notes, securitizations, and leverage-like instruments.",
            {
                "period_source_rows": _source_fact_or_missing(period_sources, ["debt", "borrowing", "asset", "cash", "receivable", "preferred", "note", "securitization", "leverage"]),
                "companyfacts_candidates": _companyfacts_candidate_facts(companyfacts_path, _F26_CONCEPTS, report_date),
            },
        )]
    if rule_id == "F27":
        detail = _wac_income_yield_detail(output_dir, cik, report_date, period_sources, context)
        return [
            _evidence(
            "f27_wac_income_yield_sources",
            "wac_income_yield_sources",
            "Debt FV with rate coverage, WAC numerator/denominator, income components, and missing-rate dominance evidence.",
            detail,
            ),
            _evidence(
                "f27_income_yield_metric_trace",
                "fund_metric_source_trace",
                "Normalized source trace for income yield direct ratio and local income components.",
                {
                    **_fund_metric_source_trace(
                    metric_name="income_yield",
                    materialized_value=_first_value(fund_rows, ["income_yield", "net_investment_income_yield", "weighted_average_yield"]),
                    formula="income / relevant asset denominator",
                    input_specs=[
                        {
                            "name": "direct_income_yield",
                            "columns": ["income_yield", "net_investment_income_yield", "weighted_average_yield"],
                            "field_hints": ["yield", "income_yield"],
                            "concepts": [],
                        },
                        {
                            "name": "income_components",
                            "columns": ["total_investment_income", "net_investment_income", "interest_income"],
                            "field_hints": ["income", "interest", "fee", "dividend", "nii", "net_investment_income"],
                            "concepts": ["InvestmentIncomeInterest", "InvestmentIncomeNet", "NetInvestmentIncome"],
                        },
                    ],
                    fund_rows=fund_rows,
                    source_rows=source_rows,
                    companyfacts_path=companyfacts_path,
                    report_date=report_date,
                    ),
                    "income_yield_source_availability_matrix": _source_availability_matrix(
                        fund_rows,
                        source_rows,
                        companyfacts_path,
                        report_date,
                        ["income_yield", "net_investment_income_yield", "weighted_average_yield", "income", "interest", "fee", "dividend", "nii", "net_investment_income"],
                        ["InvestmentIncomeInterest", "InvestmentIncomeNet", "NetInvestmentIncome"],
                    ),
                },
            ),
        ]
    if rule_id == "F28":
        return [_evidence(
            "f28_coverage_completeness_sources",
            "coverage_provenance_matrix",
            "Source rows proving fund info exists or is absent, holdings counts/FV, filing indexes, extraction progress, vehicle type, and out-of-scope flags.",
            _coverage_completeness_detail(output_dir, cik, report_date, fund_rows, period_sources, context),
        )]
    return []


def _gav_scope_detail(
    output_dir: Path,
    cik: str,
    report_date: str,
    fund_rows: list[dict[str, str]],
    period_sources: dict[str, list[dict[str, str]]],
    context: dict[str, Any] | None = None,
    include_bdc_schedule: bool = True,
) -> dict[str, Any]:
    pair = (cik, report_date)
    holdings = (
        context["fund_holdings_examples_by_pair"].get(pair, [])
        if context else _matching_holdings(output_dir, cik, report_date, limit=200)
    )
    aggregate = (
        context["fund_holdings_aggregate_by_pair"].get(pair)
        if context else None
    ) or _holdings_aggregate(output_dir / "private_markets_holdings.csv", cik, report_date)
    net_assets = _first_numeric(fund_rows[0], ["net_assets"]) if fund_rows else None
    investments = _first_numeric(fund_rows[0], ["investments_at_fair_value"]) if fund_rows else None
    gav_rows = (
        context["gav_rows_by_pair"].get(pair, [])
        if context else _read_matching_rows(output_dir / "holdings_gav_reconciliation.csv", lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date)
    )
    return {
        "fund_denominators": {
            "net_assets": net_assets,
            "investments_at_fair_value": investments,
            "denominator_source_rows": fund_rows,
        },
        "denominator_scope": "full_fund_assets" if net_assets or investments else "unknown",
        "holdings_scope": "unified_private_markets_filter",
        "scope_mismatch_candidate": bool(net_assets and aggregate["sum_fair_value"] and aggregate["sum_fair_value"] < net_assets * 0.8),
        "gav_reconciliation_rows": gav_rows,
        "unified_holdings": aggregate,
        "raw_bdc_source": (
            context["fund_raw_bdc_summary_by_pair"].get(pair)
            if context else _raw_source_summary_not_preloaded(output_dir / "bdc_holdings.csv")
        ),
        "raw_nport_source": (
            context["fund_raw_nport_summary_by_pair"].get(pair)
            if context else _raw_source_summary_not_preloaded(output_dir / "nport_holdings.csv")
        ),
        "bdc_schedule_reconciliation": (
            _bdc_schedule_reconciliation(output_dir, cik, report_date, context)
            if include_bdc_schedule else
            {"status": "not_requested_for_rule"}
        ),
        "duplicate_dimension_path_samples": _duplicate_dimension_samples(holdings),
        "excluded_row_counts_by_reason": _excluded_row_counts(output_dir, cik, report_date, context),
        "period_source_rows": period_sources,
    }


def _pct_reconciliation_detail(
    output_dir: Path,
    cik: str,
    report_date: str,
    fund_rows: list[dict[str, str]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pair = (cik, report_date)
    holdings = (
        context["fund_holdings_examples_by_pair"].get(pair, [])
        if context else _matching_holdings(output_dir, cik, report_date, limit=200)
    )
    net_assets = _first_numeric(fund_rows[0], ["net_assets"]) if fund_rows else None
    rows_with_pct = [row for row in holdings if str(row.get("pct_of_net_assets", "")).strip() != ""]
    sum_fv = sum(_safe_float(row.get("fair_value")) or 0.0 for row in holdings)
    computed_pct = (sum_fv / net_assets * 100.0) if net_assets not in (None, 0) else None
    divergences = []
    for row in rows_with_pct:
        fv = _safe_float(row.get("fair_value"))
        reported = _safe_float(row.get("pct_of_net_assets"))
        computed = (fv / net_assets * 100.0) if fv is not None and net_assets not in (None, 0) else None
        if reported is not None and computed is not None:
            divergences.append((abs(reported - computed), row, computed))
    divergences.sort(key=lambda item: item[0], reverse=True)
    pct_rows = (
        context["pct_rows_by_pair"].get(pair, [])
        if context else _read_matching_rows(output_dir / "holdings_pct_sum.csv", lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date)
    )
    return {
        "pct_sum_rows": pct_rows,
        "rows_with_pct_count": len(rows_with_pct),
        "reported_pct_sum": sum(_safe_float(row.get("pct_of_net_assets")) or 0.0 for row in rows_with_pct),
        "computed_sum_fv_over_net_assets_pct": computed_pct,
        "net_assets_source_rows": fund_rows,
        "nport_denominator_trace": _nport_pct_denominator_trace(output_dir, cik, report_date, net_assets, context),
        "pct_rows_sample": rows_with_pct[:25],
        "largest_reported_vs_computed_divergences": [
            {"absolute_difference": diff, "computed_pct": computed, "row": row}
            for diff, row, computed in divergences[:10]
        ],
        "duplicate_dimension_path_samples": _duplicate_dimension_samples(holdings),
    }


def _position_stability_detail(output_dir: Path, cik: str, report_date: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    windows = (
        context["fund_adjacent_holdings_windows_by_pair"].get((cik, report_date))
        if context else None
    ) or _adjacent_holdings_windows(output_dir, cik, report_date)
    current_ids = set(windows["current"]["position_ids"])
    prior_ids = set(windows["prior"]["position_ids"])
    next_ids = set(windows["next"]["position_ids"])
    return {
        "count_stability_rows": (
            context["stability_rows_by_pair"].get((cik, report_date), [])
            if context else _read_matching_rows(output_dir / "holdings_count_stability.csv", lambda r: normalize_cik(r.get("cik")) == cik)
        ),
        "prior_current_next": windows,
        "position_transition_mapping": _position_transition_mapping(output_dir, cik, report_date, context),
        "source_row_transition_evidence": _source_row_transition_evidence(output_dir, cik, report_date, windows, context),
        "raw_bdc_counts": _raw_counts_from_context_or_file(context, "fund_raw_bdc_summary_by_pair", output_dir / "bdc_holdings.csv", cik, report_date),
        "raw_nport_counts": _raw_counts_from_context_or_file(context, "fund_raw_nport_summary_by_pair", output_dir / "nport_holdings.csv", cik, report_date),
        "filing_index_rows": (
            context["fund_filing_rows_by_cik"].get(cik, [])
            if context else _read_matching_rows(output_dir / "bdc_filings_index.csv", lambda r: normalize_cik(r.get("cik")) == cik, limit=20)
        ),
        "top_added_positions": sorted((current_ids - prior_ids) or (next_ids - current_ids))[:20],
        "top_dropped_positions": sorted((prior_ids - current_ids) or (current_ids - next_ids))[:20],
    }


def _source_row_transition_evidence(
    output_dir: Path,
    cik: str,
    report_date: str,
    windows: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dates = {
        label: data.get("report_date", "")
        for label, data in windows.items()
        if isinstance(data, dict) and data.get("report_date")
    }
    raw_by_date = _raw_position_rows_by_date(output_dir, cik, set(dates.values()), context)
    current_ids = set(windows.get("current", {}).get("position_ids", []))
    prior_ids = set(windows.get("prior", {}).get("position_ids", []))
    next_ids = set(windows.get("next", {}).get("position_ids", []))
    added = sorted(current_ids - prior_ids)
    dropped = sorted(prior_ids - current_ids)
    return {
        "dates": dates,
        "raw_source_rows_by_window": {
            label: raw_by_date.get(date, [])[:25]
            for label, date in dates.items()
        },
        "added_private_market_rows": _transition_classification_examples(
            added,
            raw_by_date.get(dates.get("current", ""), []),
            "added",
        ),
        "dropped_private_market_rows": _transition_classification_examples(
            dropped,
            raw_by_date.get(dates.get("prior", ""), []),
            "dropped",
        ),
        "next_period_persistence": {
            "added_still_present_next_count": len(set(added) & next_ids),
            "current_dropped_next_count": len(current_ids - next_ids) if next_ids else 0,
        },
    }


def _raw_position_rows_by_date(
    output_dir: Path,
    cik: str,
    dates: set[str],
    context: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, str]]]:
    rows_by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    current_rows = []
    if context:
        for rows in [
            *context.get("fund_raw_bdc_rows_by_pair", {}).values(),
            *context.get("fund_raw_nport_rows_by_pair", {}).values(),
        ]:
            current_rows.extend(rows)
    for row in current_rows:
        date = row.get("report_date", "")
        if normalize_cik(row.get("cik")) == cik and date in dates:
            rows_by_date[date].append(row)
    for filename in ["bdc_holdings.csv", "nport_holdings.csv"]:
        path = output_dir / filename
        if not path.exists():
            continue
        for row in read_csv_rows(path):
            date = row.get("report_date", "")
            if normalize_cik(row.get("cik")) == cik and date in dates and len(rows_by_date[date]) < 100:
                rows_by_date[date].append(row)
    return rows_by_date


def _transition_classification_examples(
    position_ids: list[str],
    raw_rows: list[dict[str, str]],
    transition_type: str,
) -> list[dict[str, Any]]:
    raw_by_identity = {_position_identity(row) or _bdc_row_match_key(row): row for row in raw_rows}
    examples = []
    for position_id in position_ids[:25]:
        raw_row = raw_by_identity.get(position_id, {})
        fair_value = _safe_float(raw_row.get("fair_value")) or _safe_float(raw_row.get("value_usd"))
        examples.append({
            "position_id": position_id,
            "transition_type": transition_type,
            "raw_source_row_anchor": raw_row,
            "zero_fair_value_source_row": fair_value == 0 if fair_value is not None else False,
            "transition_interpretation": (
                "classification_or_filter_change_candidate"
                if raw_row else "true_source_change_or_missing_cached_raw_anchor"
            ),
            "classification_reason": (
                raw_row.get("classification_reason")
                or raw_row.get("private_market_classification_reason")
                or raw_row.get("asset_type")
                or raw_row.get("investment_type")
                or ""
            ),
        })
    return examples


def _fv_stability_detail(output_dir: Path, cik: str, report_date: str, nearby_fund_rows: list[dict[str, str]], context: dict[str, Any] | None = None) -> dict[str, Any]:
    windows = (
        context["fund_adjacent_holdings_windows_by_pair"].get((cik, report_date))
        if context else None
    ) or _adjacent_holdings_windows(output_dir, cik, report_date)
    return {
        "prior_current_next_holdings": windows,
        "nearby_fund_rows": nearby_fund_rows,
        "raw_bdc_fv_by_date": _raw_fv_from_context_or_file(context, "fund_raw_bdc_summary_by_pair", output_dir / "bdc_holdings.csv", cik, report_date),
        "raw_nport_fv_by_date": _raw_fv_from_context_or_file(context, "fund_raw_nport_summary_by_pair", output_dir / "nport_holdings.csv", cik, report_date),
        "largest_fv_movers": _largest_fv_movers(windows),
    }


def _wac_income_yield_detail(output_dir: Path, cik: str, report_date: str, period_sources: dict[str, list[dict[str, str]]], context: dict[str, Any] | None = None) -> dict[str, Any]:
    holdings = (
        context["fund_holdings_examples_by_pair"].get((cik, report_date), [])
        if context else _matching_holdings(output_dir, cik, report_date, limit=200)
    )
    debt_rows = [row for row in holdings if "debt" in json.dumps(row, sort_keys=True).lower() or "loan" in json.dumps(row, sort_keys=True).lower()]
    debt_fv = sum(_safe_float(row.get("fair_value")) or 0.0 for row in debt_rows)
    rate_rows = [row for row in debt_rows if _safe_float(row.get("interest_rate")) is not None or _safe_float(row.get("coupon")) is not None]
    rate_fv = sum(_safe_float(row.get("fair_value")) or 0.0 for row in rate_rows)
    return {
        "debt_fair_value": debt_fv,
        "rate_covered_fair_value": rate_fv,
        "rate_coverage_pct": (rate_fv / debt_fv * 100.0) if debt_fv else None,
        "wac_inputs_sample": rate_rows[:25],
        "income_source_rows": _source_fact_or_missing(period_sources, ["income", "interest", "fee", "dividend", "nii", "net_investment_income"]),
        "missing_rates_dominate_fv": bool(debt_fv and rate_fv / debt_fv < 0.5),
    }


def _coverage_completeness_detail(output_dir: Path, cik: str, report_date: str, fund_rows: list[dict[str, str]], period_sources: dict[str, list[dict[str, str]]], context: dict[str, Any] | None = None) -> dict[str, Any]:
    pair = (cik, report_date)
    return {
        "fund_info_exists": bool(fund_rows),
        "fund_info_rows": fund_rows,
        "holdings_aggregate": (
            context["fund_holdings_aggregate_by_pair"].get(pair)
            if context else _holdings_aggregate(output_dir / "private_markets_holdings.csv", cik, report_date)
        ),
        "holdings_examples": (
            context["fund_holdings_examples_by_pair"].get(pair, [])
            if context else _matching_holdings(output_dir, cik, report_date, limit=20)
        ),
        "bdc_filing_index_rows": (
            context["filing_rows_by_pair"].get(pair, [])
            if context else _read_matching_rows(output_dir / "bdc_filings_index.csv", lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date)
        ),
        "extraction_progress_rows": _read_matching_rows(output_dir / "progress.csv", lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date),
        "vehicle_identity_rows": (
            context["fund_vehicle_rows_by_cik"].get(cik, [])
            if context else _read_matching_rows(output_dir / "combined_universe.csv", lambda r: normalize_cik(r.get("cik")) == cik, limit=10)
        ),
        "period_source_rows": period_sources,
        "same_period_source_coverage_matrix": _coverage_provenance_matrix(output_dir, cik, report_date, fund_rows, context),
        "fund_info_to_fund_financials_materialization": _fund_info_materialization_provenance(
            output_dir,
            cik,
            report_date,
            fund_rows,
            period_sources,
            context,
        ),
        "known_scope_flags": {
            "pre_xbrl_candidate": report_date < "2022-01-01",
            "out_of_scope_hint": "consumer" in json.dumps(period_sources, sort_keys=True).lower() or "marketplace" in json.dumps(period_sources, sort_keys=True).lower(),
        },
    }


def _fund_info_materialization_provenance(
    output_dir: Path,
    cik: str,
    report_date: str,
    fund_rows: list[dict[str, str]],
    period_sources: dict[str, list[dict[str, str]]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    nport_rows = [
        row for row in period_sources.get("nport_fund_info", [])
        if not row.get("source_fact_missing")
    ]
    progress_specs = [
        output_dir / "progress.csv",
        output_dir / "nport_parse_progress.csv",
        output_dir / "bdc_parse_progress.csv",
        output_dir / "extraction_progress.csv",
    ]
    progress_rows = []
    for path in progress_specs:
        if not path.exists():
            continue
        for row in _read_matching_rows(
            path,
            lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
            limit=25,
        ):
            progress_rows.append({"artifact": display_path(path), "row": row})
    return {
        "has_nport_fund_info_same_period": bool(nport_rows),
        "has_fund_financials_same_period": bool(fund_rows),
        "nport_fund_info_rows": nport_rows[:25],
        "fund_financials_rows": fund_rows[:25],
        "parse_progress_rows": progress_rows,
        "coverage_matrix_rows": _coverage_provenance_matrix(output_dir, cik, report_date, fund_rows, context),
        "materialization_status": (
            "fund_info_and_fund_financials_present" if nport_rows and fund_rows
            else "fund_info_present_without_fund_financials" if nport_rows
            else "fund_financials_present_without_nport_fund_info" if fund_rows
            else "no_same_period_fund_info_or_fund_financials"
        ),
    }


def _bdc_schedule_reconciliation(output_dir: Path, cik: str, report_date: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    pair = (cik, report_date)
    source_rows = (
        context["fund_raw_bdc_rows_by_pair"].get(pair, [])
        if context else _read_matching_rows(
            output_dir / "bdc_holdings.csv",
            lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
            limit=None,
        )
    )
    unified_rows = (
        context["fund_holdings_rows_by_pair"].get(pair, [])
        if context else _matching_holdings(output_dir, cik, report_date, limit=None)
    )
    comparative_rows = [row for row in source_rows if _is_comparative_period_row(row, report_date)]
    current_rows = [row for row in source_rows if row not in comparative_rows]
    raw_to_unified = _raw_to_unified_bdc_row_match(current_rows, unified_rows)
    by_dimension: dict[str, dict[str, Any]] = defaultdict(lambda: {"row_count": 0, "fair_value_sum": 0.0, "examples": []})
    for row in source_rows:
        dimension_path = row.get("dimension_path") or row.get("dimensions") or row.get("bdc_dimensions_raw") or ""
        bucket = by_dimension[dimension_path]
        bucket["row_count"] += 1
        bucket["fair_value_sum"] += _safe_float(row.get("fair_value")) or _safe_float(row.get("value_usd")) or 0.0
        if len(bucket["examples"]) < 5:
            bucket["examples"].append(row)
    return {
        "source_bdc_schedule": {
            "row_count": len(source_rows),
            "fair_value_sum": sum(_safe_float(row.get("fair_value")) or _safe_float(row.get("value_usd")) or 0.0 for row in source_rows),
            "current_period_row_count": len(current_rows),
            "comparative_period_row_count": len(comparative_rows),
            "by_dimension_path": dict(by_dimension),
            "examples": source_rows[:25],
        },
        "unified_holdings": {
            "row_count": len(unified_rows),
            "fair_value_sum": sum(_safe_float(row.get("fair_value")) or 0.0 for row in unified_rows),
            "examples": unified_rows[:25],
        },
        "row_match_summary": raw_to_unified["row_match_summary"],
        "unmatched_raw_rows": raw_to_unified["unmatched_raw_rows"],
        "unmatched_unified_rows": raw_to_unified["unmatched_unified_rows"],
        "duplicate_dimension_path_candidates": _duplicate_dimension_samples(current_rows + unified_rows),
        "excluded_rows": {
            "counts_by_reason": _excluded_row_counts(output_dir, cik, report_date, context),
            "examples": (
                context["fund_same_period_issues_by_pair"].get(pair, [])[:25]
                if context else _read_matching_rows(
                    output_dir / "row_validation_issues.csv",
                    lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
                    limit=25,
                )
            ),
        },
    }


def _raw_to_unified_bdc_row_match(
    raw_rows: list[dict[str, str]],
    unified_rows: list[dict[str, str]],
) -> dict[str, Any]:
    raw_by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
    unified_by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in raw_rows:
        raw_by_key[_bdc_row_match_key(row)].append(row)
    for row in unified_rows:
        unified_by_key[_bdc_row_match_key(row)].append(row)
    matched_keys = {key for key in raw_by_key if key and key in unified_by_key}
    unmatched_raw = [
        row for key, rows in raw_by_key.items()
        if key not in matched_keys
        for row in rows
    ]
    unmatched_unified = [
        row for key, rows in unified_by_key.items()
        if key not in matched_keys
        for row in rows
    ]
    return {
        "row_match_summary": {
            "raw_current_period_row_count": len(raw_rows),
            "unified_row_count": len(unified_rows),
            "matched_key_count": len(matched_keys),
            "matched_raw_row_count": sum(len(raw_by_key[key]) for key in matched_keys),
            "matched_unified_row_count": sum(len(unified_by_key[key]) for key in matched_keys),
            "unmatched_raw_row_count": len(unmatched_raw),
            "unmatched_unified_row_count": len(unmatched_unified),
            "match_key_method": "normalized issuer/investment identifier plus rounded fair value",
        },
        "unmatched_raw_rows": unmatched_raw[:25],
        "unmatched_unified_rows": unmatched_unified[:25],
    }


def _bdc_row_match_key(row: dict[str, str]) -> str:
    identifier = (
        row.get("bdc_investment_identifier")
        or row.get("investment_identifier")
        or row.get("issuer_name")
        or row.get("name")
        or ""
    )
    fair_value = _safe_float(row.get("fair_value")) or _safe_float(row.get("value_usd"))
    value_part = f"{fair_value:.2f}" if fair_value is not None else ""
    return f"{_normalize_bdc_match_identifier(identifier)}|{value_part}"


def _is_comparative_period_row(row: dict[str, str], report_date: str) -> bool:
    period = row.get("period") or row.get("end_date") or row.get("source_period") or row.get("report_date", "")
    if period and period != report_date:
        return True
    text = json.dumps(row, sort_keys=True).lower()
    return "comparative" in text or "priorperiod" in text or "prior period" in text


def _nport_pct_denominator_trace(output_dir: Path, cik: str, report_date: str, net_assets: float | None, context: dict[str, Any] | None = None) -> dict[str, Any]:
    raw_rows = (
        context["fund_raw_nport_rows_by_pair"].get((cik, report_date), [])
        if context else _read_matching_rows(
            output_dir / "nport_holdings.csv",
            lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
            limit=None,
        )
    )
    examples = []
    for row in raw_rows[:25]:
        currency_value = _first_numeric(row, ["currency_value", "value_usd", "fair_value"])
        reported_pct = _first_numeric(row, ["percentage", "pct_of_net_assets"])
        computed_pct = (currency_value / net_assets * 100.0) if currency_value is not None and net_assets not in (None, 0) else None
        examples.append({
            "raw_nport_row": row,
            "reported_percentage": reported_pct,
            "currency_value": currency_value,
            "fund_net_assets": net_assets,
            "computed_pct": computed_pct,
            "reported_vs_computed_delta": reported_pct - computed_pct if reported_pct is not None and computed_pct is not None else None,
        })
    return {
        "raw_nport_row_count": len(raw_rows),
        "raw_nport_currency_value_sum": sum(_first_numeric(row, ["currency_value", "value_usd", "fair_value"]) or 0.0 for row in raw_rows),
        "fund_net_assets": net_assets,
        "examples": examples,
    }


def _position_transition_mapping(output_dir: Path, cik: str, report_date: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    rows_by_date: dict[str, list[dict[str, str]]] = (
        context["fund_holdings_rows_by_cik_date"].get(cik, defaultdict(list))
        if context else defaultdict(list)
    )
    if not context:
        path = output_dir / "private_markets_holdings.csv"
        if path.exists():
            for row in read_csv_rows(path):
                if normalize_cik(row.get("cik")) == cik:
                    rows_by_date[row.get("report_date", "")].append(row)
    dates = sorted(rows_by_date)
    idx = dates.index(report_date) if report_date in dates else -1
    prior_date = dates[idx - 1] if idx > 0 else ""
    next_date = dates[idx + 1] if idx >= 0 and idx + 1 < len(dates) else ""

    def keyed(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
        return {_position_identity(row): row for row in rows if _position_identity(row)}

    prior = keyed(rows_by_date.get(prior_date, []))
    current = keyed(rows_by_date.get(report_date, []))
    next_rows = keyed(rows_by_date.get(next_date, []))
    added = sorted(set(current) - set(prior))
    dropped = sorted(set(prior) - set(current))
    return {
        "prior_date": prior_date,
        "current_date": report_date,
        "next_date": next_date,
        "stable_prior_current_count": len(set(prior) & set(current)),
        "stable_current_next_count": len(set(current) & set(next_rows)),
        "added_count": len(added),
        "dropped_count": len(dropped),
        "added_examples": [_position_transition_example(current[key]) for key in added[:25]],
        "dropped_examples": [_position_transition_example(prior[key]) for key in dropped[:25]],
    }


def _position_transition_example(row: dict[str, str]) -> dict[str, Any]:
    return {
        "position_key": _position_identity(row),
        "issuer_name": row.get("issuer_name", ""),
        "fair_value": row.get("fair_value", ""),
        "index_classification": row.get("index_classification", ""),
        "private_market_classification_reason": (
            row.get("classification_reason")
            or row.get("private_market_classification_reason")
            or row.get("asset_type")
            or row.get("investment_type")
            or ""
        ),
        "row": row,
    }


def _coverage_provenance_matrix(output_dir: Path, cik: str, report_date: str, fund_rows: list[dict[str, str]], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    specs = [
        ("fund_info", output_dir / "nport_fund_info.csv"),
        ("raw_bdc_holdings", output_dir / "bdc_holdings.csv"),
        ("raw_nport_holdings", output_dir / "nport_holdings.csv"),
        ("parsed_unified_holdings", output_dir / "private_markets_holdings.csv"),
        ("fund_financials", output_dir / "fund_financials.csv"),
        ("bdc_fund_income", output_dir / "bdc_fund_income.csv"),
        ("ncsr_financials", output_dir / "ncsr_financials.csv"),
    ]
    matrix = []
    for name, path in specs:
        rows = (
            context["fund_coverage_rows_by_artifact_pair"].get((name, cik, report_date), [])
            if context else (
                _read_matching_rows(
                    path,
                    lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
                    limit=25,
                ) if path.exists() else []
            )
        )
        matrix.append({
            "artifact": name,
            "path": display_path(path),
            "exists": path.exists(),
            "same_period_row_count_sampled": len(rows),
            "has_same_period_rows": bool(rows) or (name == "fund_financials" and bool(fund_rows)),
            "examples": rows if name != "fund_financials" else (fund_rows[:25] or rows),
        })
    return matrix


def _matching_holdings(output_dir: Path, cik: str, report_date: str, limit: int | None = None) -> list[dict[str, str]]:
    return _read_matching_rows(
        output_dir / "private_markets_holdings.csv",
        lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        limit=limit,
    )


def _raw_source_summary(path: Path, cik: str, report_date: str) -> dict[str, Any]:
    rows = _read_matching_rows(path, lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date, limit=None)
    return {
        "path": display_path(path),
        "row_count": len(rows),
        "sum_fair_value": sum(_safe_float(row.get("fair_value")) or _safe_float(row.get("value_usd")) or 0.0 for row in rows),
        "examples": rows[:20],
    }


def _raw_source_summary_limited(path: Path, cik: str, report_date: str, limit: int = 50) -> dict[str, Any]:
    rows = _read_matching_rows(
        path,
        lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        limit=limit,
    )
    return {
        "path": display_path(path),
        "row_count_sampled": len(rows),
        "row_count_note": "sample is capped for pilot bundle generation; use raw source CSV for exhaustive count if needed",
        "sample_fair_value_sum": sum(_safe_float(row.get("fair_value")) or _safe_float(row.get("value_usd")) or 0.0 for row in rows),
        "examples": rows,
    }


def _raw_source_summary_not_preloaded(path: Path) -> dict[str, Any]:
    return {
        "path": display_path(path),
        "status": "not_preloaded",
        "note": "Raw source counts are populated during batch builds with preload context; rebuild with --all or pilot context for exhaustive raw counts.",
        "examples": [],
    }


def _duplicate_dimension_samples(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (row.get("issuer_name", ""), row.get("bdc_investment_identifier", ""), row.get("accession_number", ""))
        groups[key].append(row)
    return [
        {"group_key": key, "row_count": len(group), "examples": group[:5]}
        for key, group in groups.items()
        if len(group) > 1
    ][:10]


def _excluded_row_counts(output_dir: Path, cik: str, report_date: str, context: dict[str, Any] | None = None) -> dict[str, int]:
    counts: Counter[str] = Counter()
    rows = (
        context["fund_same_period_issues_by_pair"].get((cik, report_date), [])
        if context else _read_matching_rows(output_dir / "row_validation_issues.csv", lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date)
    )
    for row in rows:
        action = row.get("action") or row.get("status") or "unknown"
        counts[action] += 1
    return dict(counts)


def _adjacent_holdings_windows(output_dir: Path, cik: str, report_date: str) -> dict[str, Any]:
    rows_by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    path = output_dir / "private_markets_holdings.csv"
    if path.exists():
        for row in read_csv_rows(path):
            if normalize_cik(row.get("cik")) == cik:
                rows_by_date[row.get("report_date", "")].append(row)
    dates = sorted(rows_by_date)
    idx = dates.index(report_date) if report_date in dates else -1

    def summarize(date: str | None) -> dict[str, Any]:
        rows = rows_by_date.get(date or "", [])
        return {
            "report_date": date or "",
            "row_count": len(rows),
            "fair_value_sum": sum(_safe_float(row.get("fair_value")) or 0.0 for row in rows),
            "position_ids": [_position_identity(row) for row in rows],
        }

    return {
        "prior": summarize(dates[idx - 1] if idx > 0 else None),
        "current": summarize(report_date if report_date in rows_by_date else None),
        "next": summarize(dates[idx + 1] if idx >= 0 and idx + 1 < len(dates) else None),
    }


def _position_identity(row: dict[str, str]) -> str:
    return row.get("position_id") or row.get("bdc_investment_identifier") or row.get("issuer_name") or row.get("nport_holding_id") or ""


def _raw_counts_by_date(path: Path, cik: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    if path.exists():
        for row in read_csv_rows(path):
            if normalize_cik(row.get("cik")) == cik:
                counts[row.get("report_date", "")] += 1
    return dict(counts)


def _raw_counts_from_context_or_file(
    context: dict[str, Any] | None,
    context_key: str,
    path: Path,
    cik: str,
    report_date: str,
) -> dict[str, int]:
    if context:
        summary = context.get(context_key, {}).get((cik, report_date), {})
        return {report_date: int(summary.get("row_count", 0))}
    return _raw_counts_by_date(path, cik)


def _raw_fv_by_date(path: Path, cik: str) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    if path.exists():
        for row in read_csv_rows(path):
            if normalize_cik(row.get("cik")) == cik:
                totals[row.get("report_date", "")] += _safe_float(row.get("fair_value")) or _safe_float(row.get("value_usd")) or 0.0
    return dict(totals)


def _raw_fv_from_context_or_file(
    context: dict[str, Any] | None,
    context_key: str,
    path: Path,
    cik: str,
    report_date: str,
) -> dict[str, float]:
    if context:
        summary = context.get(context_key, {}).get((cik, report_date), {})
        return {report_date: float(summary.get("fair_value_sum", 0.0))}
    return _raw_fv_by_date(path, cik)


def _largest_fv_movers(windows: dict[str, Any]) -> dict[str, Any]:
    return {
        "prior_to_current_fv_change": windows["current"]["fair_value_sum"] - windows["prior"]["fair_value_sum"],
        "current_to_next_fv_change": windows["next"]["fair_value_sum"] - windows["current"]["fair_value_sum"],
    }


def build_all_evidence_bundles(
    output_dir: Path = OUTPUT_DIR,
    overwrite: bool = False,
    dataset: str = "holdings",
) -> list[Path]:
    allowed_datasets = selected_datasets(dataset)
    rows = [
        row for row in read_csv_rows(output_dir / "fail_verification" / "sample_manifest.csv")
        if row.get("dataset", HOLDINGS_DATASET) in allowed_datasets
    ]
    if overwrite:
        _remove_run_guard(output_dir)
    _COMPANYFACTS_JSON_CACHE.clear()
    cache: dict[Path, str] = {}
    context = _build_evidence_context(output_dir, rows)
    paths = [
        build_evidence_bundle(
            row["verification_id"],
            output_dir=output_dir,
            overwrite=overwrite,
            hash_cache=cache,
            _context=context,
            _append_manifest=False,
        )
        for row in rows
    ]
    if overwrite:
        current = {path.name for path in paths}
        bundle_dir = output_dir / "fail_verification" / "bundles"
        for stale in bundle_dir.glob("*.json"):
            stale_dataset = _dataset_for_verification_id(output_dir, stale.stem)
            if stale_dataset in allowed_datasets and stale.name not in current:
                stale.unlink()
    _write_bundle_manifest_rows(output_dir, paths, dataset=dataset)
    return paths


def _build_evidence_context(output_dir: Path, manifest_rows: list[dict[str, str]]) -> dict[str, Any]:
    """Preload sampled evidence slices so batch bundle builds avoid repeated CSV scans."""
    manifest_by_vid = {row["verification_id"]: row for row in manifest_rows}
    row_keys = {
        int(row["row_key"])
        for row in manifest_rows
        if row.get("row_key", "").isdigit() and row.get("rule_id") in ROW_LEVEL_RULES
    }
    holdings_path = output_dir / "private_markets_holdings.csv"
    holdings_by_row_key = (
        _read_holdings_by_row_key(holdings_path, row_keys)
        if holdings_path.exists() else {}
    )

    issue_rows_by_vid: dict[str, list[dict[str, str]]] = defaultdict(list)
    related_fail_counts_by_pair: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    related_fail_examples_by_pair: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    manifest_issue_keys = set()
    gav_pairs = set()
    for row in manifest_rows:
        cik = row["cik"]
        report_date = row["report_date"]
        rule_id = row["rule_id"]
        if _is_cik_quarter_rule(rule_id):
            gav_pairs.add((cik, report_date))
            manifest_issue_keys.add((cik, report_date, rule_id, ""))
        else:
            manifest_issue_keys.add((cik, report_date, rule_id, row.get("row_key", "")))

    issue_path = output_dir / "row_validation_issues.csv"
    needs_holdings_issues = any(
        row.get("dataset", HOLDINGS_DATASET) != FUND_DATASET
        for row in manifest_rows
    )
    issue_rows = read_csv_rows(issue_path) if issue_path.exists() and needs_holdings_issues else []
    for issue in issue_rows:
        cik = normalize_cik(issue.get("cik"))
        report_date = issue.get("report_date", "")
        rule_id = issue.get("rule_id", "")
        row_key = issue.get("row_key", "")
        key = (cik, report_date, rule_id, "" if _is_cik_quarter_rule(rule_id) else row_key)
        if key in manifest_issue_keys:
            for vid, manifest_row in manifest_by_vid.items():
                if (
                    manifest_row["cik"] == cik
                    and manifest_row["report_date"] == report_date
                    and manifest_row["rule_id"] == rule_id
                    and (_is_cik_quarter_rule(rule_id) or manifest_row.get("row_key", "") == row_key)
                ):
                    issue_rows_by_vid[vid].append(issue)
        pair = (cik, report_date)
        if pair in gav_pairs and issue.get("severity") == "FAIL":
            related_fail_counts_by_pair[pair][rule_id] += 1
            if not _is_cik_quarter_rule(rule_id) and len(related_fail_examples_by_pair[pair]) < 20:
                related_fail_examples_by_pair[pair].append(issue)

    context: dict[str, Any] = {
        "manifest_rows": manifest_by_vid,
        "holdings_by_row_key": holdings_by_row_key,
        "issue_rows_by_vid": issue_rows_by_vid,
        "related_fail_counts_by_pair": {
            key: dict(value) for key, value in related_fail_counts_by_pair.items()
        },
        "related_fail_examples_by_pair": related_fail_examples_by_pair,
    }
    _populate_context_from_holdings(output_dir, manifest_rows, holdings_by_row_key, context)
    _populate_context_from_sources(output_dir, manifest_rows, holdings_by_row_key, context)
    _populate_gav_raw_bdc_context(output_dir, manifest_rows, context)
    _populate_small_keyed_context(output_dir, manifest_rows, context)
    _populate_fund_evidence_context(output_dir, manifest_rows, context)
    return context


def _populate_fund_evidence_context(
    output_dir: Path,
    manifest_rows: list[dict[str, str]],
    context: dict[str, Any],
) -> None:
    fund_rows = [
        row for row in manifest_rows
        if row.get("dataset", HOLDINGS_DATASET) == FUND_DATASET
    ]
    if not fund_rows:
        return

    pairs = {(row["cik"], row["report_date"]) for row in fund_rows}
    ciks = {row["cik"] for row in fund_rows}
    cross_pairs = {
        (row["cik"], row["report_date"])
        for row in fund_rows
        if row.get("rule_id") in CROSS_LEVEL_FUND_RULES
    }
    stability_pairs = {
        (row["cik"], row["report_date"])
        for row in fund_rows
        if row.get("rule_id") in {"F24", "F25"}
    }
    stability_ciks = {cik for cik, _ in stability_pairs}
    manifest_by_vid = {row["verification_id"]: row for row in fund_rows}
    validation_by_vid: dict[str, list[dict[str, str]]] = defaultdict(list)

    validation_path = output_dir / "fund_financials_validation_current.csv"
    if validation_path.exists():
        vid_by_row_key = {
            row.get("row_key", ""): row["verification_id"]
            for row in fund_rows
            if row.get("row_key", "").isdigit()
        }
        for index, row in enumerate(read_csv_rows(validation_path)):
            row_key = str(index)
            vid = vid_by_row_key.get(row_key)
            if vid:
                manifest = manifest_by_vid[vid]
                if (
                    normalize_cik(row.get("cik")) == manifest["cik"]
                    and row.get("report_date", "") == manifest["report_date"]
                    and row.get("check_code", "") == manifest["rule_id"]
                ):
                    validation_by_vid[vid].append(row)

    fund_rows_by_pair: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    fund_rows_by_cik: dict[str, list[dict[str, str]]] = defaultdict(list)
    fund_financials_path = output_dir / "fund_financials.csv"
    if fund_financials_path.exists():
        for row in read_csv_rows(fund_financials_path):
            cik = normalize_cik(row.get("cik"))
            if cik not in ciks:
                continue
            fund_rows_by_cik[cik].append(row)
            pair = (cik, row.get("report_date", ""))
            if pair in pairs:
                fund_rows_by_pair[pair].append(row)

    nearby_by_pair: dict[tuple[str, str], list[dict[str, str]]] = {}
    for cik, rows in fund_rows_by_cik.items():
        rows.sort(key=lambda r: r.get("report_date", ""))
        indexes_by_date: dict[str, int] = {}
        for index, row in enumerate(rows):
            indexes_by_date.setdefault(row.get("report_date", ""), index)
        for pair in [pair for pair in pairs if pair[0] == cik]:
            idx = indexes_by_date.get(pair[1])
            if idx is None:
                nearby_by_pair[pair] = rows[-3:]
            else:
                nearby_by_pair[pair] = rows[max(0, idx - 1): idx + 2]

    quality_by_pair = _read_rows_by_pair(output_dir / "fund_financials_quality_metrics.csv", pairs)
    cross_by_pair = _read_rows_by_pair(output_dir / "fund_financials_cross_level.csv", cross_pairs)

    source_specs = {
        "bdc_fund_income": output_dir / "bdc_fund_income.csv",
        "nport_fund_info": output_dir / "nport_fund_info.csv",
        "ncsr_financials": output_dir / "ncsr_financials.csv",
        "combined_universe": output_dir / "combined_universe.csv",
        "fund_identity": output_dir / "fund_identity.csv",
    }
    source_rows_by_cik: dict[str, dict[str, list[dict[str, str]]]] = {
        cik: {name: [] for name in source_specs}
        for cik in ciks
    }
    for name, path in source_specs.items():
        if not path.exists():
            continue
        for row in read_csv_rows(path):
            row_ciks = {
                normalize_cik(row.get("cik")),
                normalize_cik(row.get("CIK")),
                normalize_cik(row.get("series_cik")),
            }
            for cik in row_ciks & ciks:
                if not cik:
                    continue
                bucket = source_rows_by_cik[cik][name]
                is_sampled_period = (cik, row.get("report_date", "")) in pairs
                sampled_period_count = sum(
                    1 for existing in bucket
                    if existing.get("report_date", "") == row.get("report_date", "")
                )
                if is_sampled_period and sampled_period_count < 20:
                    bucket.append(row)
                elif len(bucket) < 20:
                    bucket.append(row)

    holdings_examples: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    holdings_rows_by_pair: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    holdings_rows_by_cik_date: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    holdings_aggregate: dict[tuple[str, str], dict[str, Any]] = {
        pair: {
            "cik": pair[0],
            "report_date": pair[1],
            "has_holdings": False,
            "position_count": 0,
            "sum_fair_value": 0.0,
            "sum_pct_of_net_assets": 0.0,
        }
        for pair in cross_pairs
    }
    stability_by_cik_date: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    holdings_path = output_dir / "private_markets_holdings.csv"
    if holdings_path.exists() and cross_pairs:
        with holdings_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cik = normalize_cik(row.get("cik"))
                report_date = row.get("report_date", "")
                pair = (cik, report_date)
                if cik in stability_ciks:
                    _update_holdings_window_summary(stability_by_cik_date[cik], report_date, row)
                    holdings_rows_by_cik_date[cik][report_date].append(row)
                if pair in cross_pairs:
                    if len(holdings_examples[pair]) < 20:
                        holdings_examples[pair].append(row)
                    holdings_rows_by_pair[pair].append(row)
                    aggregate = holdings_aggregate[pair]
                    aggregate["has_holdings"] = True
                    aggregate["position_count"] += 1
                    for source_col, target_col in [
                        ("fair_value", "sum_fair_value"),
                        ("pct_of_net_assets", "sum_pct_of_net_assets"),
                    ]:
                        try:
                            aggregate[target_col] += float(row.get(source_col) or 0)
                        except ValueError:
                            pass

    adjacent_windows_by_pair = {
        pair: _adjacent_windows_from_summaries(stability_by_cik_date.get(pair[0], {}), pair[1])
        for pair in stability_pairs
    }

    same_period_issues: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    issue_path = output_dir / "row_validation_issues.csv"
    if issue_path.exists() and cross_pairs:
        for row in read_csv_rows(issue_path):
            pair = (normalize_cik(row.get("cik")), row.get("report_date", ""))
            if pair in cross_pairs and len(same_period_issues[pair]) < 50:
                same_period_issues[pair].append(row)

    raw_bdc_summary_by_pair, raw_bdc_rows_by_pair = _raw_source_summaries_and_rows_for_pairs(output_dir / "bdc_holdings.csv", cross_pairs)
    raw_nport_summary_by_pair, raw_nport_rows_by_pair = _raw_source_summaries_and_rows_for_pairs(output_dir / "nport_holdings.csv", cross_pairs)
    coverage_by_artifact_pair, filing_rows_by_cik, vehicle_rows_by_cik = _fund_coverage_context(
        output_dir,
        pairs,
        ciks,
        holdings_examples,
        raw_bdc_rows_by_pair,
        raw_nport_rows_by_pair,
        fund_rows_by_pair,
        source_rows_by_cik,
    )

    context.update({
        "fund_validation_rows_by_vid": validation_by_vid,
        "fund_financials_rows_by_pair": fund_rows_by_pair,
        "nearby_fund_rows_by_pair": nearby_by_pair,
        "fund_quality_rows_by_pair": quality_by_pair,
        "fund_cross_level_rows_by_pair": cross_by_pair,
        "fund_source_rows_by_cik": source_rows_by_cik,
        "fund_holdings_examples_by_pair": holdings_examples,
        "fund_holdings_rows_by_pair": holdings_rows_by_pair,
        "fund_holdings_rows_by_cik_date": holdings_rows_by_cik_date,
        "fund_holdings_aggregate_by_pair": holdings_aggregate,
        "fund_same_period_issues_by_pair": same_period_issues,
        "fund_raw_bdc_summary_by_pair": raw_bdc_summary_by_pair,
        "fund_raw_bdc_rows_by_pair": raw_bdc_rows_by_pair,
        "fund_raw_nport_summary_by_pair": raw_nport_summary_by_pair,
        "fund_raw_nport_rows_by_pair": raw_nport_rows_by_pair,
        "fund_adjacent_holdings_windows_by_pair": adjacent_windows_by_pair,
        "fund_coverage_rows_by_artifact_pair": coverage_by_artifact_pair,
        "fund_filing_rows_by_cik": filing_rows_by_cik,
        "fund_vehicle_rows_by_cik": vehicle_rows_by_cik,
    })


def _update_holdings_window_summary(
    summaries_by_date: dict[str, dict[str, Any]],
    report_date: str,
    row: dict[str, str],
) -> None:
    summary = summaries_by_date.setdefault(report_date, {
        "report_date": report_date,
        "row_count": 0,
        "fair_value_sum": 0.0,
        "position_ids": [],
    })
    summary["row_count"] += 1
    summary["fair_value_sum"] += _safe_float(row.get("fair_value")) or 0.0
    if len(summary["position_ids"]) < 500:
        summary["position_ids"].append(_position_identity(row))


def _adjacent_windows_from_summaries(
    summaries_by_date: dict[str, dict[str, Any]],
    report_date: str,
) -> dict[str, Any]:
    dates = sorted(summaries_by_date)
    idx = dates.index(report_date) if report_date in summaries_by_date else -1

    def empty(date: str = "") -> dict[str, Any]:
        return {"report_date": date, "row_count": 0, "fair_value_sum": 0.0, "position_ids": []}

    def item(date: str | None) -> dict[str, Any]:
        if not date:
            return empty()
        return summaries_by_date.get(date, empty(date))

    return {
        "prior": item(dates[idx - 1] if idx > 0 else None),
        "current": item(report_date if report_date in summaries_by_date else None),
        "next": item(dates[idx + 1] if idx >= 0 and idx + 1 < len(dates) else None),
    }


def _raw_source_summaries_for_pairs(
    path: Path,
    pairs: set[tuple[str, str]],
    sample_limit: int = 50,
) -> dict[tuple[str, str], dict[str, Any]]:
    summaries, _rows = _raw_source_summaries_and_rows_for_pairs(path, pairs, sample_limit)
    return summaries


def _raw_source_summaries_and_rows_for_pairs(
    path: Path,
    pairs: set[tuple[str, str]],
    sample_limit: int = 50,
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str], list[dict[str, str]]]]:
    summaries = {
        pair: {
            "path": display_path(path),
            "row_count": 0,
            "fair_value_sum": 0.0,
            "examples": [],
        }
        for pair in pairs
    }
    rows_by_pair: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    if not path.exists() or not pairs:
        return summaries, rows_by_pair
    for row in _read_pair_filtered_csv_rows(path, pairs):
        pair = (normalize_cik(row.get("cik")), row.get("report_date", ""))
        if pair not in summaries:
            continue
        rows_by_pair[pair].append(row)
        summary = summaries[pair]
        summary["row_count"] += 1
        summary["fair_value_sum"] += _safe_float(row.get("fair_value")) or _safe_float(row.get("value_usd")) or 0.0
        if len(summary["examples"]) < sample_limit:
            summary["examples"].append(row)
    return summaries, rows_by_pair


def _read_pair_filtered_csv_rows(path: Path, pairs: set[tuple[str, str]]) -> list[dict[str, str]]:
    if not pairs:
        return []
    try:
        return _read_pair_filtered_csv_rows_duckdb(path, pairs)
    except Exception:
        return _read_pair_filtered_csv_rows_python(path, pairs)


def _read_pair_filtered_csv_rows_duckdb(path: Path, pairs: set[tuple[str, str]]) -> list[dict[str, str]]:
    import duckdb

    pair_literals = ", ".join(_sql_quote(f"{cik}|{report_date}") for cik, report_date in sorted(pairs))
    query = f"""
        select *
        from read_csv_auto({_sql_quote(str(path))}, header=true, all_varchar=true)
        where lpad(regexp_replace(coalesce(cik, ''), '[^0-9]', '', 'g'), 10, '0') || '|' || coalesce(report_date, '')
            in ({pair_literals})
    """
    relation = duckdb.sql(query)
    columns = [column[0] for column in relation.description]
    return [
        {column: "" if value is None else str(value) for column, value in zip(columns, row)}
        for row in relation.fetchall()
    ]


def _read_pair_filtered_csv_rows_python(path: Path, pairs: set[tuple[str, str]]) -> list[dict[str, str]]:
    cik_values = _raw_cik_match_values({cik for cik, _ in pairs})
    dates = {report_date for _, report_date in pairs}
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_cik = str(row.get("cik", "")).strip()
            report_date = row.get("report_date", "")
            if report_date not in dates or raw_cik not in cik_values:
                continue
            pair = (normalize_cik(raw_cik), report_date)
            if pair in pairs:
                rows.append(row)
    return rows


def _raw_cik_match_values(ciks: set[str]) -> set[str]:
    values = set()
    for cik in ciks:
        normalized = normalize_cik(cik)
        if not normalized:
            continue
        values.add(normalized)
        values.add(str(int(normalized)))
    return values


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _fund_coverage_context(
    output_dir: Path,
    pairs: set[tuple[str, str]],
    ciks: set[str],
    holdings_examples: dict[tuple[str, str], list[dict[str, str]]],
    raw_bdc_rows_by_pair: dict[tuple[str, str], list[dict[str, str]]],
    raw_nport_rows_by_pair: dict[tuple[str, str], list[dict[str, str]]],
    fund_rows_by_pair: dict[tuple[str, str], list[dict[str, str]]],
    source_rows_by_cik: dict[str, dict[str, list[dict[str, str]]]],
) -> tuple[
    dict[tuple[str, str, str], list[dict[str, str]]],
    dict[str, list[dict[str, str]]],
    dict[str, list[dict[str, str]]],
]:
    coverage: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for pair, rows in holdings_examples.items():
        coverage[("parsed_unified_holdings", pair[0], pair[1])] = rows[:25]
    for pair, rows in raw_bdc_rows_by_pair.items():
        coverage[("raw_bdc_holdings", pair[0], pair[1])] = rows[:25]
    for pair, rows in raw_nport_rows_by_pair.items():
        coverage[("raw_nport_holdings", pair[0], pair[1])] = rows[:25]
    for pair, rows in fund_rows_by_pair.items():
        coverage[("fund_financials", pair[0], pair[1])] = rows[:25]

    filing_rows_by_cik: dict[str, list[dict[str, str]]] = defaultdict(list)
    filing_path = output_dir / "bdc_filings_index.csv"
    if filing_path.exists():
        for row in read_csv_rows(filing_path):
            cik = normalize_cik(row.get("cik"))
            if cik in ciks and len(filing_rows_by_cik[cik]) < 20:
                filing_rows_by_cik[cik].append(row)

    vehicle_rows_by_cik: dict[str, list[dict[str, str]]] = defaultdict(list)
    for cik, rows_by_source in source_rows_by_cik.items():
        for row in rows_by_source.get("combined_universe", []):
            if len(vehicle_rows_by_cik[cik]) < 10:
                vehicle_rows_by_cik[cik].append(row)
        for source_name, artifact in [
            ("fund_info", "nport_fund_info"),
            ("bdc_fund_income", "bdc_fund_income"),
            ("ncsr_financials", "ncsr_financials"),
        ]:
            for row in rows_by_source.get(artifact, []):
                pair = (cik, row.get("report_date", ""))
                if pair in pairs and len(coverage[(source_name, cik, pair[1])]) < 25:
                    coverage[(source_name, cik, pair[1])].append(row)
    return coverage, filing_rows_by_cik, vehicle_rows_by_cik


def _read_rows_by_pair(
    path: Path,
    pairs: set[tuple[str, str]],
) -> dict[tuple[str, str], list[dict[str, str]]]:
    rows_by_pair: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    if not path.exists() or not pairs:
        return rows_by_pair
    for row in read_csv_rows(path):
        pair = (normalize_cik(row.get("cik")), row.get("report_date", ""))
        if pair in pairs:
            rows_by_pair[pair].append(row)
    return rows_by_pair


def _populate_context_from_holdings(
    output_dir: Path,
    manifest_rows: list[dict[str, str]],
    holdings_by_row_key: dict[str, dict[str, str]],
    context: dict[str, Any],
) -> None:
    x06_keys = set()
    issuer_keys = set()
    gav_pairs = set()
    for row in manifest_rows:
        holding = holdings_by_row_key.get(row.get("row_key", ""), {})
        cik = row["cik"]
        report_date = row["report_date"]
        rule_id = row["rule_id"]
        if _is_cik_quarter_rule(rule_id):
            gav_pairs.add((cik, report_date))
            continue
        accession = holding.get("accession_number", "")
        issuer = holding.get("issuer_name", "")
        if rule_id == "X06":
            x06_keys.add((cik, report_date, accession))
        if issuer:
            issuer_keys.add((cik, report_date, accession, issuer))

    x06_nearby: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    issuer_rows: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    gav_holdings: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    if not x06_keys and not issuer_keys and not gav_pairs:
        context["x06_nearby_by_key"] = x06_nearby
        context["issuer_rows_by_key"] = issuer_rows
        context["gav_holdings_by_pair"] = gav_holdings
        return
    holdings_path = output_dir / "private_markets_holdings.csv"
    if not holdings_path.exists():
        context["x06_nearby_by_key"] = x06_nearby
        context["issuer_rows_by_key"] = issuer_rows
        context["gav_holdings_by_pair"] = gav_holdings
        return
    with holdings_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cik = normalize_cik(row.get("cik"))
            report_date = row.get("report_date", "")
            accession = row.get("accession_number", "")
            issuer = row.get("issuer_name", "")
            x06_key = (cik, report_date, accession)
            if x06_key in x06_keys and len(x06_nearby[x06_key]) < 10:
                x06_nearby[x06_key].append(row)
            issuer_key = (cik, report_date, accession, issuer)
            if issuer_key in issuer_keys and len(issuer_rows[issuer_key]) < 20:
                issuer_rows[issuer_key].append(row)
            gav_key = (cik, report_date)
            if gav_key in gav_pairs and len(gav_holdings[gav_key]) < 20:
                gav_holdings[gav_key].append(row)

    context["x06_nearby_by_key"] = x06_nearby
    context["issuer_rows_by_key"] = issuer_rows
    context["gav_holdings_by_pair"] = gav_holdings


def _populate_context_from_sources(
    output_dir: Path,
    manifest_rows: list[dict[str, str]],
    holdings_by_row_key: dict[str, dict[str, str]],
    context: dict[str, Any],
) -> None:
    bdc_keys = set()
    nport_keys = set()
    nport_holding_ids: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in manifest_rows:
        holding = holdings_by_row_key.get(row.get("row_key", ""), {})
        source = holding.get("source", "")
        if source == "bdc":
            bdc_keys.add((row["cik"], holding.get("accession_number", "")))
        elif source == "nport":
            key = (row["cik"], row["report_date"])
            nport_keys.add(key)
            holding_id = holding.get("nport_holding_id", "")
            if holding_id:
                nport_holding_ids[key].add(holding_id)

    bdc_rows_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    if bdc_keys and (output_dir / "bdc_holdings.csv").exists():
        with (output_dir / "bdc_holdings.csv").open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (normalize_cik(row.get("cik")), row.get("accession_number", ""))
                if key in bdc_keys:
                    bdc_rows_by_key[key].append(row)

    nport_rows_by_key: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    nport_counts_by_key: Counter[tuple[str, str]] = Counter()
    if nport_keys and (output_dir / "nport_holdings.csv").exists():
        with (output_dir / "nport_holdings.csv").open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (normalize_cik(row.get("cik")), row.get("report_date", ""))
                if key not in nport_keys:
                    continue
                nport_counts_by_key[key] += 1
                holding_id = row.get("holding_id", "")
                needed_ids = nport_holding_ids.get(key, set())
                if not needed_ids or holding_id in needed_ids:
                    nport_rows_by_key[key].append(row)

    context["bdc_rows_by_key"] = bdc_rows_by_key
    context["nport_rows_by_key"] = nport_rows_by_key
    context["nport_counts_by_key"] = nport_counts_by_key


def _populate_gav_raw_bdc_context(
    output_dir: Path,
    manifest_rows: list[dict[str, str]],
    context: dict[str, Any],
) -> None:
    gav_pairs = {
        (row["cik"], row["report_date"])
        for row in manifest_rows
        if _is_cik_quarter_rule(row.get("rule_id", ""))
    }
    rows_by_pair: dict[tuple[str, str], dict[str, Any]] = {
        pair: {"row_count": 0, "examples": []}
        for pair in gav_pairs
    }
    path = output_dir / "bdc_holdings.csv"
    if path.exists() and gav_pairs:
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pair = (normalize_cik(row.get("cik")), row.get("report_date", ""))
                if pair not in rows_by_pair:
                    continue
                summary = rows_by_pair[pair]
                summary["row_count"] += 1
                if len(summary["examples"]) < 20:
                    summary["examples"].append(row)
    context["raw_bdc_gav_rows_by_pair"] = rows_by_pair


def _raw_bdc_rows_for_gav_pair(
    bdc_path: Path,
    cik: str,
    report_date: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {"row_count": 0, "examples": []}
    if not bdc_path.exists():
        return result
    with bdc_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if normalize_cik(row.get("cik")) != cik or row.get("report_date", "") != report_date:
                continue
            result["row_count"] += 1
            if len(result["examples"]) < 20:
                result["examples"].append(row)
    return result


def _populate_small_keyed_context(
    output_dir: Path,
    manifest_rows: list[dict[str, str]],
    context: dict[str, Any],
) -> None:
    pairs = {(row["cik"], row["report_date"]) for row in manifest_rows}
    keyed_specs = {
        "fund_rows_by_pair": "fund_financials.csv",
        "gav_rows_by_pair": "holdings_gav_reconciliation.csv",
        "pct_rows_by_pair": "holdings_pct_sum.csv",
        "stability_rows_by_pair": "holdings_count_stability.csv",
        "filing_rows_by_pair": "bdc_filings_index.csv",
    }
    for context_key, filename in keyed_specs.items():
        rows_by_pair: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        path = output_dir / filename
        if path.exists():
            for row in read_csv_rows(path):
                pair = (normalize_cik(row.get("cik")), row.get("report_date", ""))
                if pair in pairs:
                    rows_by_pair[pair].append(row)
        context[context_key] = rows_by_pair


def _nearby_holdings_from_context(
    context: dict[str, Any],
    cik: str,
    report_date: str,
    holding: dict[str, str],
    rule_id: str,
) -> list[dict[str, str]]:
    accession = (holding or {}).get("accession_number", "")
    issuer = (holding or {}).get("issuer_name", "")
    if rule_id == "X06":
        return context["x06_nearby_by_key"].get((cik, report_date, accession), [])
    if issuer:
        return context["issuer_rows_by_key"].get((cik, report_date, accession, issuer), [])[:10]
    return context["gav_holdings_by_pair"].get((cik, report_date), [])[:10]


def _nearby_holdings(output_dir: Path, cik: str, report_date: str, holding: dict[str, str], rule_id: str) -> list[dict[str, str]]:
    issuer = (holding or {}).get("issuer_name", "")
    if rule_id == "X06":
        accession = (holding or {}).get("accession_number", "")
        return _read_matching_rows(
            output_dir / "private_markets_holdings.csv",
            lambda r: (
                normalize_cik(r.get("cik")) == cik
                and r.get("report_date", "") == report_date
                and (not accession or r.get("accession_number", "") == accession)
            ),
            limit=10,
        )
    if issuer:
        return _read_matching_rows(
            output_dir / "private_markets_holdings.csv",
            lambda r: normalize_cik(r.get("cik")) == cik
            and r.get("report_date", "") == report_date
            and r.get("issuer_name", "") == issuer,
            limit=10,
        )
    return _read_matching_rows(
        output_dir / "private_markets_holdings.csv",
        lambda r: normalize_cik(r.get("cik")) == cik and r.get("report_date", "") == report_date,
        limit=10,
    )


_BDC_AFFILIATION_PREFIX_RE = re.compile(
    r"^(?:"
    r"Non-Control(?:led)?(?:[/,]\s*Non-Affiliat(?:e|ed))?\s+Investments"
    r"|Control(?:led)?\s+Investments"
    r"|Affiliat(?:e|ed)\s+Investments"
    r"|Investments\s+in\s+(?:Non-)?Control(?:led)?(?:[,/]\s*(?:Non-)?Affiliat(?:e|ed))?\s+Portfolio\s+Companies"
    r")\s*(?:[-\u2013\u2014]\s*|\s+)",
    re.IGNORECASE,
)
_BDC_AFFILIATION_SUFFIX_RE = re.compile(
    r"\s+-\s+(?:Non-Control(?:led)?(?:[/,]\s*Non-Affiliat(?:e|ed))?|Control(?:led)?|Affiliat(?:e|ed))$",
    re.IGNORECASE,
)


def _normalize_bdc_match_identifier(value: str) -> str:
    """Normalize BDC identifiers enough to align unified and raw evidence."""
    text = str(value or "").strip()
    text = _BDC_AFFILIATION_PREFIX_RE.sub("", text)
    text = _BDC_AFFILIATION_SUFFIX_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _raw_source_evidence(
    bdc_path: Path,
    nport_path: Path,
    holding: dict[str, str],
    cik: str,
    report_date: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not holding:
        return [], {"source": "", "match_method": "no_holding_row"}
    source = holding.get("source", "")
    accession = holding.get("accession_number", "")
    if source == "bdc":
        identifier = holding.get("bdc_investment_identifier", "")
        same_accession = _read_matching_rows(
            bdc_path,
            lambda r: normalize_cik(r.get("cik")) == cik
            and r.get("accession_number", "") == accession,
        )
        if not identifier:
            return same_accession[:20], {
                "source": "bdc",
                "match_method": "same_accession_no_identifier",
                "unified_bdc_investment_identifier": identifier,
                "normalized_unified_bdc_investment_identifier": "",
                "same_accession_candidate_count": len(same_accession),
                "exact_match_count": len(same_accession),
                "normalized_match_count": 0,
            }
        exact = [r for r in same_accession if r.get("investment_identifier", "") == identifier]
        if exact:
            return exact[:20], {
                "source": "bdc",
                "match_method": "exact_identifier",
                "unified_bdc_investment_identifier": identifier,
                "normalized_unified_bdc_investment_identifier": _normalize_bdc_match_identifier(identifier),
                "same_accession_candidate_count": len(same_accession),
                "exact_match_count": len(exact),
                "normalized_match_count": 0,
            }
        normalized_identifier = _normalize_bdc_match_identifier(identifier)
        normalized = [
            r for r in same_accession
            if _normalize_bdc_match_identifier(r.get("investment_identifier", "")) == normalized_identifier
        ]
        related = [
            r for r in same_accession
            if r not in normalized
            and normalized_identifier
            and normalized_identifier in _normalize_bdc_match_identifier(r.get("investment_identifier", ""))
        ]
        matched = (normalized + related)[:20]
        match_method = "no_match"
        if normalized and related:
            match_method = "normalized_identifier_with_related_candidates"
        elif normalized:
            match_method = "normalized_identifier"
        elif related:
            match_method = "related_identifier_candidate"
        return matched, {
            "source": "bdc",
            "match_method": match_method,
            "unified_bdc_investment_identifier": identifier,
            "normalized_unified_bdc_investment_identifier": normalized_identifier,
            "same_accession_candidate_count": len(same_accession),
            "exact_match_count": 0,
            "normalized_match_count": len(normalized),
            "related_candidate_count": len(related),
        }
    if source == "nport":
        holding_id = holding.get("nport_holding_id", "")
        same_period = _read_matching_rows(
            nport_path,
            lambda r: normalize_cik(r.get("cik")) == cik
            and r.get("report_date", "") == report_date,
        )
        matched = [r for r in same_period if not holding_id or r.get("holding_id", "") == holding_id]
        return matched[:20], {
            "source": "nport",
            "match_method": "holding_id" if holding_id else "same_period_no_holding_id",
            "nport_holding_id": holding_id,
            "same_period_candidate_count": len(same_period),
            "exact_match_count": len(matched),
            "normalized_match_count": 0,
        }
    return [], {"source": source, "match_method": "unsupported_source"}


def _raw_source_evidence_from_context(
    context: dict[str, Any],
    holding: dict[str, str],
    cik: str,
    report_date: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not holding:
        return [], {"source": "", "match_method": "no_holding_row"}
    source = holding.get("source", "")
    if source == "bdc":
        return _match_bdc_source_rows(
            context["bdc_rows_by_key"].get((cik, holding.get("accession_number", "")), []),
            holding.get("bdc_investment_identifier", ""),
        )
    if source == "nport":
        key = (cik, report_date)
        holding_id = holding.get("nport_holding_id", "")
        matched = context["nport_rows_by_key"].get(key, [])
        return matched[:20], {
            "source": "nport",
            "match_method": "holding_id" if holding_id else "same_period_no_holding_id",
            "nport_holding_id": holding_id,
            "same_period_candidate_count": context["nport_counts_by_key"].get(key, 0),
            "exact_match_count": len(matched),
            "normalized_match_count": 0,
        }
    return [], {"source": source, "match_method": "unsupported_source"}


def _match_bdc_source_rows(
    same_accession: list[dict[str, str]],
    identifier: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not identifier:
        return same_accession[:20], {
            "source": "bdc",
            "match_method": "same_accession_no_identifier",
            "unified_bdc_investment_identifier": identifier,
            "normalized_unified_bdc_investment_identifier": "",
            "same_accession_candidate_count": len(same_accession),
            "exact_match_count": len(same_accession),
            "normalized_match_count": 0,
        }
    exact = [r for r in same_accession if r.get("investment_identifier", "") == identifier]
    if exact:
        return exact[:20], {
            "source": "bdc",
            "match_method": "exact_identifier",
            "unified_bdc_investment_identifier": identifier,
            "normalized_unified_bdc_investment_identifier": _normalize_bdc_match_identifier(identifier),
            "same_accession_candidate_count": len(same_accession),
            "exact_match_count": len(exact),
            "normalized_match_count": 0,
        }
    normalized_identifier = _normalize_bdc_match_identifier(identifier)
    normalized = [
        r for r in same_accession
        if _normalize_bdc_match_identifier(r.get("investment_identifier", "")) == normalized_identifier
    ]
    related = [
        r for r in same_accession
        if r not in normalized
        and normalized_identifier
        and normalized_identifier in _normalize_bdc_match_identifier(r.get("investment_identifier", ""))
    ]
    matched = (normalized + related)[:20]
    match_method = "no_match"
    if normalized and related:
        match_method = "normalized_identifier_with_related_candidates"
    elif normalized:
        match_method = "normalized_identifier"
    elif related:
        match_method = "related_identifier_candidate"
    return matched, {
        "source": "bdc",
        "match_method": match_method,
        "unified_bdc_investment_identifier": identifier,
        "normalized_unified_bdc_investment_identifier": normalized_identifier,
        "same_accession_candidate_count": len(same_accession),
        "exact_match_count": 0,
        "normalized_match_count": len(normalized),
        "related_candidate_count": len(related),
    }


def _same_issuer_dimension_rows(
    output_dir: Path,
    cik: str,
    report_date: str,
    holding: dict[str, str],
) -> list[dict[str, str]]:
    if not holding:
        return []
    issuer = holding.get("issuer_name", "")
    accession = holding.get("accession_number", "")
    if not issuer:
        return []
    return _read_matching_rows(
        output_dir / "private_markets_holdings.csv",
        lambda r: (
            normalize_cik(r.get("cik")) == cik
            and r.get("report_date", "") == report_date
            and (not accession or r.get("accession_number", "") == accession)
            and r.get("issuer_name", "") == issuer
        ),
        limit=20,
    )


def _same_issuer_dimension_rows_from_context(
    context: dict[str, Any],
    cik: str,
    report_date: str,
    holding: dict[str, str],
) -> list[dict[str, str]]:
    if not holding:
        return []
    issuer = holding.get("issuer_name", "")
    if not issuer:
        return []
    return context["issuer_rows_by_key"].get(
        (cik, report_date, holding.get("accession_number", ""), issuer),
        [],
    )


BUNDLE_MANIFEST_COLUMNS = ["verification_id", "bundle_path", "bundle_sha256", "created_at"]


def _append_bundle_manifest(output_dir: Path, verification_id: str, bundle_path: Path, bundle_sha: str) -> None:
    path = output_dir / "fail_verification" / "bundle_manifest.csv"
    rows = read_csv_rows(path) if path.exists() else []
    rows = [r for r in rows if r.get("verification_id") != verification_id]
    rows.append({
        "verification_id": verification_id,
        "bundle_path": display_path(bundle_path),
        "bundle_sha256": bundle_sha,
        "created_at": now_iso(),
    })
    write_csv_rows(path, rows, BUNDLE_MANIFEST_COLUMNS)


def _write_bundle_manifest_rows(
    output_dir: Path,
    bundle_paths: list[Path],
    dataset: str = "all",
) -> None:
    path = output_dir / "fail_verification" / "bundle_manifest.csv"
    allowed_datasets = selected_datasets(dataset)
    preserved_rows = []
    if path.exists():
        preserved_rows = [
            row for row in read_csv_rows(path)
            if _dataset_for_verification_id(output_dir, row.get("verification_id", "")) not in allowed_datasets
        ]
    rows = [
        {
            "verification_id": bundle_path.stem,
            "bundle_path": display_path(bundle_path),
            "bundle_sha256": sha256_file(bundle_path),
            "created_at": now_iso(),
        }
        for bundle_path in bundle_paths
    ]
    write_csv_rows(path, preserved_rows + rows, BUNDLE_MANIFEST_COLUMNS)


def _dataset_for_verification_id(output_dir: Path, verification_id: str) -> str:
    manifest_path = output_dir / "fail_verification" / "sample_manifest.csv"
    if manifest_path.exists():
        for row in read_csv_rows(manifest_path):
            if row.get("verification_id") == verification_id:
                return row.get("dataset", HOLDINGS_DATASET)
    rule_id = verification_id.split("_", 1)[0]
    if rule_id in FUND_RULES:
        return FUND_DATASET
    return HOLDINGS_DATASET


def _protected_files() -> list[Path]:
    files: list[Path] = []
    for rel in PROTECTED_RELATIVE_PATHS:
        path = PROJECT_ROOT / rel
        if path.is_file():
            if _is_guard_relevant_file(path):
                files.append(path)
        elif path.is_dir():
            files.extend(p for p in path.rglob("*") if p.is_file() and _is_guard_relevant_file(p))
    return sorted(set(files))


def _is_guard_relevant_file(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if "__pycache__" in parts or path.suffix.lower() in {".pyc", ".pyo"}:
        return False
    return True


def _write_run_guard(output_dir: Path) -> None:
    guard_path = output_dir / "fail_verification" / "run_guard.json"
    if guard_path.exists():
        return
    hashes = {
        str(path.relative_to(PROJECT_ROOT)): sha256_file(path)
        for path in _protected_files()
        if "data/output/fail_verification/verdicts" not in str(path).replace("\\", "/")
    }
    guard = {
        "schema_version": "1.0",
        "created_at": now_iso(),
        "protected_hashes": hashes,
        "allowed_write_dir": "data/output/fail_verification/verdicts",
    }
    ensure_dir(guard_path.parent)
    guard_path.write_text(json.dumps(guard, indent=2, sort_keys=True), encoding="utf-8")


def _remove_run_guard(output_dir: Path) -> None:
    guard_path = output_dir / "fail_verification" / "run_guard.json"
    if guard_path.exists():
        guard_path.unlink()


class RunGuardValidator:
    """Validate run_guard.json once for repeated verdict checks.

    Guard validation hashes many protected files. A batch verdict validation
    should pay that cost once, not once per verdict.
    """

    def __init__(self, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir
        self._errors: list[str] | None = None

    def validate(self) -> list[str]:
        if self._errors is None:
            self._errors = _validate_run_guard(self.output_dir)
        return list(self._errors)


def validate_verdict(
    verdict_path: Path,
    output_dir: Path = OUTPUT_DIR,
    run_guard_validator: RunGuardValidator | None = None,
    check_run_guard: bool = True,
    dataset: str = "all",
) -> list[str]:
    errors: list[str] = []
    verdict = _load_json(verdict_path, errors)
    if verdict is None:
        return errors

    schema_path = PROJECT_ROOT / "schemas" / "fail_verification" / "verdict.schema.json"
    schema = _load_json(schema_path, errors)
    if schema is not None:
        try:
            jsonschema.Draft202012Validator(schema).validate(verdict)
        except jsonschema.ValidationError as exc:
            errors.append(f"schema validation failed: {exc.message}")

    verification_id = str(verdict.get("verification_id", ""))
    manifest = {r["verification_id"]: r for r in read_csv_rows(output_dir / "fail_verification" / "sample_manifest.csv")}
    manifest_row = manifest.get(verification_id)
    if not manifest_row:
        errors.append(f"verification_id not found in sample_manifest.csv: {verification_id}")
        return errors
    manifest_dataset = manifest_row.get("dataset", HOLDINGS_DATASET)
    if manifest_dataset not in selected_datasets(dataset):
        errors.append(f"verdict dataset is outside requested dataset scope: {manifest_dataset}")

    bundle_path = output_dir / "fail_verification" / "bundles" / f"{verification_id}.json"
    bundle = _load_json(bundle_path, errors)
    if bundle is None:
        return errors

    actual_bundle_sha = sha256_file(bundle_path)
    if verdict.get("bundle_id") != bundle.get("bundle_id"):
        errors.append("bundle_id does not match bundle file")
    if verdict.get("bundle_sha256") != actual_bundle_sha:
        errors.append("bundle_sha256 does not match actual bundle file")

    if str(verdict.get("dataset", "")) != manifest_dataset:
        errors.append("dataset does not match sample manifest")
    if str(bundle.get("dataset", "")) != manifest_dataset:
        errors.append("dataset does not match bundle file")

    for key in ("rule_id", "cik", "report_date", "row_key"):
        if str(verdict.get(key, "")) != str(manifest_row.get(key, "")):
            errors.append(f"{key} does not match sample manifest")

    evidence_ids = {
        item.get("evidence_id")
        for item in bundle.get("evidence_items", [])
    }
    for ref in verdict.get("evidence_refs", []):
        if ref.get("evidence_id") not in evidence_ids:
            errors.append(f"unknown evidence_id: {ref.get('evidence_id')}")

    errors.extend(_validate_epistemic_assessment(verdict, evidence_ids))
    errors.extend(_validate_evidence_inventory(verdict, evidence_ids))
    errors.extend(_validate_rule_specific_verdict_checks(verdict, bundle))

    if verdict.get("confidence") == "high" and len(verdict.get("evidence_refs", [])) < 2:
        errors.append("high confidence verdicts must cite at least two evidence refs")

    if verdict.get("verdict") == "INSUFFICIENT_EVIDENCE":
        residual = verdict.get("determination_rationale", {}).get("residual_uncertainty", "")
        if len(str(residual).strip()) < 20:
            errors.append("INSUFFICIENT_EVIDENCE verdicts must describe missing or ambiguous evidence")
        root_cause = verdict.get("validator_assessment", {}).get("root_cause")
        if root_cause not in INSUFFICIENT_ROOT_CAUSES:
            errors.append("INSUFFICIENT_EVIDENCE verdicts must use root_cause BUNDLE_MISSING_LOCAL_EVIDENCE or RULE_OR_MODEL_NOT_DETERMINATIVE")
        assessment = verdict.get("already_present_evidence_assessment", {})
        if not assessment.get("required_for_insufficient"):
            errors.append("INSUFFICIENT_EVIDENCE verdicts must include already_present_evidence_assessment.required_for_insufficient=true")
        assessed_ids = {
            item.get("evidence_id")
            for item in assessment.get("assessment", [])
            if isinstance(item, dict)
        }
        missing_assessments = sorted(eid for eid in evidence_ids if eid not in assessed_ids)
        if missing_assessments:
            errors.append(f"INSUFFICIENT_EVIDENCE verdicts must assess already-present evidence ids: {', '.join(missing_assessments[:10])}")

    rec = verdict.get("recommended_next_action", {})
    rec_text = json.dumps(rec, sort_keys=True).lower()
    forbidden = [
        "edit pipeline", "modify pipeline", "patch pipeline", "rewrite csv",
        "edit csv", "modify csv", "change threshold", "suppress rule",
        "edit frontend", "direct mutation",
    ]
    if any(term in rec_text for term in forbidden):
        errors.append("recommended_next_action appears to recommend direct mutation")

    if check_run_guard:
        if run_guard_validator is None:
            errors.extend(_validate_run_guard(output_dir))
        else:
            errors.extend(run_guard_validator.validate())
    return errors


def _validate_evidence_inventory(verdict: dict[str, Any], evidence_ids: set[str]) -> list[str]:
    errors: list[str] = []
    inventory = verdict.get("evidence_inventory")
    if not isinstance(inventory, list) or not inventory:
        return ["evidence_inventory must list every bundled evidence item"]
    seen: set[str] = set()
    for item in inventory:
        if not isinstance(item, dict):
            errors.append("evidence_inventory items must be objects")
            continue
        evidence_id = item.get("evidence_id")
        if evidence_id not in evidence_ids:
            errors.append(f"evidence_inventory cites unknown evidence_id: {evidence_id}")
            continue
        seen.add(evidence_id)
        if item.get("reviewed") is not True:
            errors.append(f"evidence_inventory item was not marked reviewed: {evidence_id}")
        if item.get("classification") not in EVIDENCE_VERDICT_CLASSES:
            errors.append(f"evidence_inventory has unsupported classification for {evidence_id}")
    missing = sorted(eid for eid in evidence_ids if eid not in seen)
    if missing:
        errors.append(f"evidence_inventory must enumerate every bundled evidence id; missing: {', '.join(missing[:10])}")
    return errors


def _validate_rule_specific_verdict_checks(verdict: dict[str, Any], bundle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rule_id = verdict.get("rule_id", "")
    evidence_by_id = {
        item.get("evidence_id"): item
        for item in bundle.get("evidence_items", [])
        if isinstance(item, dict)
    }
    verdict_text = json.dumps(verdict, sort_keys=True).lower()

    if rule_id == "F21":
        data = (evidence_by_id.get("f21_net_assets_scope_reconciliation") or {}).get("data", {})
        if isinstance(data, dict) and data.get("scope_mismatch_candidate"):
            if "scope" not in verdict_text or "mismatch" not in verdict_text:
                errors.append("F21 verdict must address scoped denominator mismatch when bundled evidence flags scope_mismatch_candidate")

    contradiction_signals = _bundle_direct_playbook_signals(bundle)
    for signal in contradiction_signals:
        if signal["term"] not in verdict_text:
            errors.append(
                "verdict appears to ignore direct bundled evidence signal "
                f"{signal['term']} from {signal['evidence_id']}"
            )
    return errors


def _bundle_direct_playbook_signals(bundle: dict[str, Any]) -> list[dict[str, str]]:
    signals: list[dict[str, str]] = []
    for item in bundle.get("evidence_items", []):
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id", ""))
        data = item.get("data")
        if not isinstance(data, dict):
            continue
        if evidence_id.startswith("f21_") and data.get("scope_mismatch_candidate") is True:
            signals.append({"evidence_id": evidence_id, "term": "scope"})
        if evidence_id.startswith("f27_") and data.get("missing_rates_dominate_fv") is True:
            signals.append({"evidence_id": evidence_id, "term": "missing rate"})
        if evidence_id.startswith("f28_") and data.get("fund_info_exists") is True and isinstance(data.get("holdings_aggregate"), dict):
            if data["holdings_aggregate"].get("has_holdings") is False:
                signals.append({"evidence_id": evidence_id, "term": "coverage"})
    return signals


def _validate_epistemic_assessment(verdict: dict[str, Any], evidence_ids: set[str]) -> list[str]:
    """Enforce a general evidence contract beyond JSON shape.

    This prevents a reviewer from converting "we ruled out one bad mechanism"
    into a positive verdict without evidence for the mechanism being asserted.
    """
    errors: list[str] = []
    assessment = verdict.get("epistemic_assessment")
    if not isinstance(assessment, dict):
        return ["epistemic_assessment is required"]

    confirmed = assessment.get("confirmed_mechanism", {})
    if not isinstance(confirmed, dict):
        errors.append("epistemic_assessment.confirmed_mechanism must be an object")
        confirmed = {}
    summary = str(confirmed.get("summary", "")).strip()
    support_strength = str(confirmed.get("support_strength", "")).strip()
    confirmed_refs = confirmed.get("evidence_refs", [])
    if not isinstance(confirmed_refs, list):
        errors.append("confirmed_mechanism.evidence_refs must be an array")
        confirmed_refs = []

    verdict_type = verdict.get("verdict")
    is_insufficient = verdict_type == "INSUFFICIENT_EVIDENCE"
    no_positive_mechanism = (
        not summary
        or support_strength == "NONE"
        or len(confirmed_refs) == 0
    )

    if not is_insufficient and no_positive_mechanism:
        errors.append("non-INSUFFICIENT_EVIDENCE verdicts require a positive confirmed_mechanism with evidence refs")
    if is_insufficient and not no_positive_mechanism:
        errors.append("INSUFFICIENT_EVIDENCE verdicts must not claim a positive confirmed_mechanism")

    for evidence_id in confirmed_refs:
        if evidence_id not in evidence_ids:
            errors.append(f"confirmed_mechanism cites unknown evidence_id: {evidence_id}")

    chain = assessment.get("evidence_chain", [])
    if not isinstance(chain, list):
        errors.append("epistemic_assessment.evidence_chain must be an array")
        chain = []
    if not is_insufficient and len(chain) == 0:
        errors.append("non-INSUFFICIENT_EVIDENCE verdicts require at least one evidence_chain item")
    for item in chain:
        evidence_id = item.get("evidence_id") if isinstance(item, dict) else None
        if evidence_id not in evidence_ids:
            errors.append(f"evidence_chain cites unknown evidence_id: {evidence_id}")

    alternatives = assessment.get("ruled_out_alternatives", [])
    if not isinstance(alternatives, list):
        errors.append("epistemic_assessment.ruled_out_alternatives must be an array")
        alternatives = []
    for item in alternatives:
        evidence_id = item.get("evidence_id") if isinstance(item, dict) else None
        if evidence_id not in evidence_ids:
            errors.append(f"ruled_out_alternatives cites unknown evidence_id: {evidence_id}")

    missing = assessment.get("missing_evidence", [])
    if not isinstance(missing, list):
        errors.append("epistemic_assessment.missing_evidence must be an array")
        missing = []
    if is_insufficient and len(missing) == 0:
        errors.append("INSUFFICIENT_EVIDENCE verdicts must list missing_evidence")

    if support_strength == "ABSENCE_OF_CONTRARY_EVIDENCE":
        if verdict_type in {"CONFIRMED_DATA_ERROR", "CONFIRMED_VALID_EXCEPTION", "VALIDATOR_FALSE_POSITIVE"}:
            errors.append("absence of contrary evidence cannot support a non-INSUFFICIENT_EVIDENCE verdict")
    if support_strength == "CORROBORATED_INFERENCE" and verdict.get("confidence") == "high":
        errors.append("high confidence requires direct source evidence or deterministic reconciliation, not only corroborated inference")
    if support_strength == "DIRECT_SOURCE_EVIDENCE" and len(confirmed_refs) < 1:
        errors.append("direct source evidence requires at least one confirmed_mechanism evidence ref")
    if support_strength == "DETERMINISTIC_RECONCILIATION" and len(confirmed_refs) < 2:
        errors.append("deterministic reconciliation requires at least two confirmed_mechanism evidence refs")

    return errors


def _load_json(path: Path, errors: list[str]) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"could not load JSON {path}: {exc}")
        return None


def _validate_run_guard(output_dir: Path) -> list[str]:
    path = output_dir / "fail_verification" / "run_guard.json"
    if not path.exists():
        return ["run_guard.json is missing"]
    guard = json.loads(path.read_text(encoding="utf-8"))
    errors = []
    for rel, expected in guard.get("protected_hashes", {}).items():
        file_path = PROJECT_ROOT / rel
        if not _is_guard_relevant_file(file_path):
            continue
        if not file_path.exists():
            errors.append(f"protected file missing after run: {rel}")
            continue
        actual = sha256_file(file_path)
        if actual != expected:
            errors.append(f"protected file changed after guard creation: {rel}")
    return errors


SUMMARY_COLUMNS = [
    "dataset",
    "rule_id",
    "verdict",
    "confidence",
    "count",
    "weighted_count",
    "affected_fair_value",
    "affected_fund_assets",
    "affected_holdings_fv",
]


def summarize_verdicts(output_dir: Path = OUTPUT_DIR, dataset: str = "holdings") -> Path:
    datasets = selected_datasets(dataset)
    manifest = {r["verification_id"]: r for r in read_csv_rows(output_dir / "fail_verification" / "sample_manifest.csv")}
    rows = []
    verdict_dir = output_dir / "fail_verification" / "verdicts"
    ensure_dir(verdict_dir)
    for path in sorted(verdict_dir.glob("*.json")):
        verdict = json.loads(path.read_text(encoding="utf-8"))
        vid = verdict.get("verification_id", "")
        manifest_row = manifest.get(vid, {})
        if not manifest_row:
            continue
        manifest_dataset = manifest_row.get("dataset", HOLDINGS_DATASET)
        if manifest_dataset not in datasets:
            continue
        exposure = _bundle_exposure(output_dir, vid)
        rows.append({
            "dataset": manifest_dataset,
            "rule_id": verdict.get("rule_id", ""),
            "verdict": verdict.get("verdict", ""),
            "confidence": verdict.get("confidence", ""),
            "weight": float(manifest_row.get("sample_weight") or 1),
            **exposure,
        })

    grouped: dict[tuple[str, str, str, str], dict[str, float]] = defaultdict(
        lambda: {
            "count": 0,
            "weighted_count": 0.0,
            "affected_fair_value": 0.0,
            "affected_fund_assets": 0.0,
            "affected_holdings_fv": 0.0,
        }
    )
    for row in rows:
        key = (row["dataset"], row["rule_id"], row["verdict"], row["confidence"])
        grouped[key]["count"] += 1
        grouped[key]["weighted_count"] += row["weight"]
        grouped[key]["affected_fair_value"] += row["fair_value"]
        grouped[key]["affected_fund_assets"] += row["fund_assets"]
        grouped[key]["affected_holdings_fv"] += row["holdings_fv"]

    summary_rows = [
        {
            "dataset": dataset_name,
            "rule_id": rule,
            "verdict": verdict,
            "confidence": confidence,
            "count": int(values["count"]),
            "weighted_count": f"{values['weighted_count']:.6g}",
            "affected_fair_value": f"{values['affected_fair_value']:.2f}",
            "affected_fund_assets": f"{values['affected_fund_assets']:.2f}",
            "affected_holdings_fv": f"{values['affected_holdings_fv']:.2f}",
        }
        for (dataset_name, rule, verdict, confidence), values in sorted(grouped.items())
    ]
    target = output_dir / "fail_verification" / "summaries" / "verdict_summary.csv"
    write_csv_rows(target, summary_rows, SUMMARY_COLUMNS)

    estimate_path = output_dir / "fail_verification" / "summaries" / "rule_estimates.json"
    ensure_dir(estimate_path.parent)
    estimate_path.write_text(json.dumps(_rule_estimates(rows), indent=2, sort_keys=True), encoding="utf-8")
    return target


def _bundle_exposure(output_dir: Path, verification_id: str) -> dict[str, float]:
    path = output_dir / "fail_verification" / "bundles" / f"{verification_id}.json"
    if not path.exists():
        return {"fair_value": 0.0, "fund_assets": 0.0, "holdings_fv": 0.0}
    bundle = json.loads(path.read_text(encoding="utf-8"))
    exposure = {"fair_value": 0.0, "fund_assets": 0.0, "holdings_fv": 0.0}
    for item in bundle.get("evidence_items", []):
        if item.get("evidence_id") == "holdings_row":
            try:
                exposure["fair_value"] = float(item.get("data", {}).get("fair_value") or 0)
            except ValueError:
                pass
        if item.get("evidence_id") == "fund_financials_row":
            rows = item.get("data") or []
            if rows:
                try:
                    exposure["fund_assets"] = float(rows[0].get("total_assets") or rows[0].get("investments_at_fair_value") or 0)
                except ValueError:
                    pass
        if item.get("evidence_id") == "holdings_aggregate":
            try:
                exposure["holdings_fv"] = float((item.get("data") or {}).get("sum_fair_value") or 0)
            except ValueError:
                pass
        if item.get("evidence_id") == "gav_reconciliation":
            rows = item.get("data") or []
            if rows:
                try:
                    exposure["fair_value"] = float(rows[0].get("sum_holdings_fv") or 0)
                    exposure["holdings_fv"] = max(exposure["holdings_fv"], exposure["fair_value"])
                except ValueError:
                    pass
    return exposure


def _rule_estimates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_rule[f"{row['dataset']}:{row['rule_id']}"].append(row)
    estimates = {}
    for rule, rule_rows in by_rule.items():
        total_weight = sum(r["weight"] for r in rule_rows)
        if not total_weight:
            continue
        confirmed_weight = sum(r["weight"] for r in rule_rows if r["verdict"] == "CONFIRMED_DATA_ERROR")
        false_positive_weight = sum(r["weight"] for r in rule_rows if r["verdict"] == "VALIDATOR_FALSE_POSITIVE")
        insufficient_weight = sum(r["weight"] for r in rule_rows if r["verdict"] == "INSUFFICIENT_EVIDENCE")
        estimates[rule] = {
            "weighted_confirmed_error_rate": confirmed_weight / total_weight,
            "weighted_false_positive_rate": false_positive_weight / total_weight,
            "weighted_insufficient_evidence_rate": insufficient_weight / total_weight,
            "sample_verdict_count": len(rule_rows),
        }
    return estimates


def cli_build_sample_manifest(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build FAIL verification sample manifest.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--dataset", choices=["holdings", "funds", "all"], default="holdings")
    args = parser.parse_args(argv)
    print(build_sample_manifest(output_dir=args.output_dir, seed=args.seed, dataset=args.dataset))
    return 0


def cli_build_evidence_bundle(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build FAIL verification evidence bundles.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--verification-id")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dataset", choices=["holdings", "funds", "all"], default="holdings")
    args = parser.parse_args(argv)
    if not args.all and not args.verification_id:
        parser.error("pass --verification-id or --all")
    if args.all:
        paths = build_all_evidence_bundles(output_dir=args.output_dir, overwrite=args.overwrite, dataset=args.dataset)
        for path in paths:
            print(path)
    else:
        print(build_evidence_bundle(args.verification_id, output_dir=args.output_dir, overwrite=args.overwrite))
    return 0


def cli_validate_verdict(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate FAIL verification verdicts.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--verdict", type=Path)
    parser.add_argument("--all", action="store_true", help="Validate all verdict JSON files with one run_guard hash pass.")
    parser.add_argument("--dataset", choices=["holdings", "funds", "all"], default="all")
    args = parser.parse_args(argv)
    if args.all and args.verdict:
        parser.error("pass either --verdict or --all, not both")
    if not args.all and not args.verdict:
        parser.error("pass --verdict or --all")

    if args.all:
        verdict_dir = args.output_dir / "fail_verification" / "verdicts"
        guard = RunGuardValidator(args.output_dir)
        total_errors = 0
        guard_errors = guard.validate()
        if guard_errors:
            total_errors += len(guard_errors)
            for error in guard_errors:
                print(f"ERROR run_guard: {error}")
        allowed = selected_datasets(args.dataset)
        manifest = {
            r["verification_id"]: r
            for r in read_csv_rows(args.output_dir / "fail_verification" / "sample_manifest.csv")
        }
        for verdict_path in sorted(verdict_dir.glob("*.json")):
            verdict_preview = _load_json(verdict_path, [])
            vid = (verdict_preview or {}).get("verification_id", "")
            if manifest.get(vid, {}).get("dataset", HOLDINGS_DATASET) not in allowed:
                continue
            errors = validate_verdict(verdict_path, output_dir=args.output_dir, check_run_guard=False, dataset=args.dataset)
            if errors:
                total_errors += len(errors)
                for error in errors:
                    print(f"ERROR {verdict_path.name}: {error}")
            else:
                print(f"OK {verdict_path.name}")
        if total_errors:
            print(f"FAIL: {total_errors} validation errors")
            return 1
        print("OK")
        return 0

    errors = validate_verdict(args.verdict, output_dir=args.output_dir, dataset=args.dataset)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK")
    return 0


def cli_summarize_verdicts(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize FAIL verification verdicts.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--dataset", choices=["holdings", "funds", "all"], default="holdings")
    args = parser.parse_args(argv)
    print(summarize_verdicts(output_dir=args.output_dir, dataset=args.dataset))
    return 0
