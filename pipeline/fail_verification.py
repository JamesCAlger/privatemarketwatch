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

RULES = ("C101", "X06", "GAV_BDC01", "GAV_NPORT01", "X09", "C402")
ROW_LEVEL_RULES = {"C101", "X06", "X09", "C402"}
CIK_QUARTER_RULES = {"GAV01", "GAV_BDC01", "GAV_NPORT01"}
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
) -> Path:
    issue_path = output_dir / "row_validation_issues.csv"
    source_hash = sha256_file(issue_path)
    rows = [
        row for row in read_csv_rows(issue_path)
        if row.get("status") == "OPEN"
        and row.get("severity") == "FAIL"
        and row.get("rule_id") in RULES
    ]

    rows_by_rule: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        rows_by_rule[row["rule_id"]].append(row)
    for rule_id in CIK_QUARTER_RULES:
        if rule_id in rows_by_rule:
            rows_by_rule[rule_id] = _dedupe_gav_units(rows_by_rule[rule_id])

    sampled: list[dict[str, Any]] = []
    for rule_id in RULES:
        sampled.extend(_sample_units_for_rule(rows_by_rule.get(rule_id, []), rule_id, seed))

    row_keys = {
        int(row["row_key"])
        for row in sampled
        if row.get("row_key", "").isdigit() and row.get("rule_id") in ROW_LEVEL_RULES
    }
    holdings_by_row_key = _read_holdings_by_row_key(output_dir / "private_markets_holdings.csv", row_keys)
    gav_by_key = _read_keyed_rows(output_dir / "holdings_gav_reconciliation.csv", ("cik", "report_date"))

    manifest_rows = []
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

    target = out_path or output_dir / "fail_verification" / "sample_manifest.csv"
    write_csv_rows(target, manifest_rows, MANIFEST_COLUMNS)
    return target


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


def build_all_evidence_bundles(output_dir: Path = OUTPUT_DIR, overwrite: bool = False) -> list[Path]:
    rows = read_csv_rows(output_dir / "fail_verification" / "sample_manifest.csv")
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
            if stale.name not in current:
                stale.unlink()
    _write_bundle_manifest_rows(output_dir, paths)
    return paths


def _build_evidence_context(output_dir: Path, manifest_rows: list[dict[str, str]]) -> dict[str, Any]:
    """Preload sampled evidence slices so batch bundle builds avoid repeated CSV scans."""
    manifest_by_vid = {row["verification_id"]: row for row in manifest_rows}
    row_keys = {
        int(row["row_key"])
        for row in manifest_rows
        if row.get("row_key", "").isdigit() and row.get("rule_id") in ROW_LEVEL_RULES
    }
    holdings_by_row_key = _read_holdings_by_row_key(output_dir / "private_markets_holdings.csv", row_keys)

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

    for issue in read_csv_rows(output_dir / "row_validation_issues.csv"):
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
    return context


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
    with (output_dir / "private_markets_holdings.csv").open(newline="", encoding="utf-8-sig") as f:
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


def _write_bundle_manifest_rows(output_dir: Path, bundle_paths: list[Path]) -> None:
    path = output_dir / "fail_verification" / "bundle_manifest.csv"
    rows = [
        {
            "verification_id": bundle_path.stem,
            "bundle_path": display_path(bundle_path),
            "bundle_sha256": sha256_file(bundle_path),
            "created_at": now_iso(),
        }
        for bundle_path in bundle_paths
    ]
    write_csv_rows(path, rows, BUNDLE_MANIFEST_COLUMNS)


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

    bundle_path = output_dir / "fail_verification" / "bundles" / f"{verification_id}.json"
    bundle = _load_json(bundle_path, errors)
    if bundle is None:
        return errors

    actual_bundle_sha = sha256_file(bundle_path)
    if verdict.get("bundle_id") != bundle.get("bundle_id"):
        errors.append("bundle_id does not match bundle file")
    if verdict.get("bundle_sha256") != actual_bundle_sha:
        errors.append("bundle_sha256 does not match actual bundle file")

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

    if verdict.get("confidence") == "high" and len(verdict.get("evidence_refs", [])) < 2:
        errors.append("high confidence verdicts must cite at least two evidence refs")

    if verdict.get("verdict") == "INSUFFICIENT_EVIDENCE":
        residual = verdict.get("determination_rationale", {}).get("residual_uncertainty", "")
        if len(str(residual).strip()) < 20:
            errors.append("INSUFFICIENT_EVIDENCE verdicts must describe missing or ambiguous evidence")

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
    "rule_id",
    "verdict",
    "count",
    "weighted_count",
    "affected_fair_value",
]


def summarize_verdicts(output_dir: Path = OUTPUT_DIR) -> Path:
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
        rows.append({
            "rule_id": verdict.get("rule_id", ""),
            "verdict": verdict.get("verdict", ""),
            "weight": float(manifest_row.get("sample_weight") or 1),
            "fair_value": _bundle_fair_value(output_dir, vid),
        })

    grouped: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"count": 0, "weighted_count": 0.0, "affected_fair_value": 0.0})
    for row in rows:
        key = (row["rule_id"], row["verdict"])
        grouped[key]["count"] += 1
        grouped[key]["weighted_count"] += row["weight"]
        grouped[key]["affected_fair_value"] += row["fair_value"]

    summary_rows = [
        {
            "rule_id": rule,
            "verdict": verdict,
            "count": int(values["count"]),
            "weighted_count": f"{values['weighted_count']:.6g}",
            "affected_fair_value": f"{values['affected_fair_value']:.2f}",
        }
        for (rule, verdict), values in sorted(grouped.items())
    ]
    target = output_dir / "fail_verification" / "summaries" / "verdict_summary.csv"
    write_csv_rows(target, summary_rows, SUMMARY_COLUMNS)

    estimate_path = output_dir / "fail_verification" / "summaries" / "rule_estimates.json"
    ensure_dir(estimate_path.parent)
    estimate_path.write_text(json.dumps(_rule_estimates(rows), indent=2, sort_keys=True), encoding="utf-8")
    return target


def _bundle_fair_value(output_dir: Path, verification_id: str) -> float:
    path = output_dir / "fail_verification" / "bundles" / f"{verification_id}.json"
    if not path.exists():
        return 0.0
    bundle = json.loads(path.read_text(encoding="utf-8"))
    for item in bundle.get("evidence_items", []):
        if item.get("evidence_id") == "holdings_row":
            try:
                return float(item.get("data", {}).get("fair_value") or 0)
            except ValueError:
                return 0.0
        if item.get("evidence_id") == "gav_reconciliation":
            rows = item.get("data") or []
            if rows:
                try:
                    return float(rows[0].get("sum_holdings_fv") or 0)
                except ValueError:
                    return 0.0
    return 0.0


def _rule_estimates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_rule[row["rule_id"]].append(row)
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
    args = parser.parse_args(argv)
    print(build_sample_manifest(output_dir=args.output_dir, seed=args.seed))
    return 0


def cli_build_evidence_bundle(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build FAIL verification evidence bundles.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--verification-id")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if not args.all and not args.verification_id:
        parser.error("pass --verification-id or --all")
    if args.all:
        paths = build_all_evidence_bundles(output_dir=args.output_dir, overwrite=args.overwrite)
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
        for verdict_path in sorted(verdict_dir.glob("*.json")):
            errors = validate_verdict(verdict_path, output_dir=args.output_dir, check_run_guard=False)
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

    errors = validate_verdict(args.verdict, output_dir=args.output_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK")
    return 0


def cli_summarize_verdicts(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize FAIL verification verdicts.")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args(argv)
    print(summarize_verdicts(output_dir=args.output_dir))
    return 0
