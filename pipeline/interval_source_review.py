"""Interval/tender source reconciliation review harness.

This module builds review-only artifacts for N-PORT rows from interval and
tender-offer funds that do not reconcile conservatively to unified holdings.
N-PORT is the structured denominator; N-CSR HTML is bundled only as
coordinate-level evidence.
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

REVIEW_DIR = config.OUTPUT_DIR / "interval_source_review"
SCHEMA_FILE = config.PROJECT_ROOT / "schemas" / "interval_source_review" / "verdict.schema.json"
PROMPT_TEMPLATE = config.PROJECT_ROOT / "prompts" / "interval_source_review_prompt.md"

TARGET_VEHICLE_TYPES = {"interval_fund", "tender_offer_fund"}

WORKLIST_COLUMNS = [
    "review_id",
    "cik",
    "entity_name",
    "series_id",
    "series_name",
    "vehicle_type",
    "report_date",
    "mechanism",
    "blocking_issue_count",
    "source_rows",
    "output_rows",
    "matched_rows",
    "affected_source_fair_value",
    "affected_output_fair_value",
    "sample_identifiers",
    "source_only_blocker_rows",
    "source_only_blocker_fv",
    "pipeline_only_rows",
    "pipeline_only_fv",
]

BUNDLE_MANIFEST_COLUMNS = ["review_id", "bundle_path", "bundle_sha256"]

PROTECTED_GENERATED_PATH_PREFIXES = ["frontend/public/data/"]
PROTECTED_GENERATED_PATHS = {
    "data/output/private_markets_holdings.csv",
    "data/output/nport_holdings.csv",
    "data/output/html_extraction_holdings.csv",
}

RECONCILIATION_DIAGNOSES = {
    "",
    "REAL_SOURCE_POSITION_MISSING_FROM_UNIFIED",
    "HTML_PRESENT_TABLE_NOT_PARSED",
    "NPORT_ONLY_NO_HTML_COORDINATE",
    "PIPELINE_ONLY_POSITION",
    "PUBLIC_MARKET_OR_NON_PRIVATE_FILTERED",
    "MONEY_MARKET_OR_CASH_EQUIVALENT",
    "AGGREGATE_OR_HEADER",
    "COMPARATIVE_PERIOD",
    "DUPLICATE_OR_ALIAS",
    "INSUFFICIENT_EVIDENCE",
}
HTML_BASED_DIAGNOSES = {
    "REAL_SOURCE_POSITION_MISSING_FROM_UNIFIED",
    "HTML_PRESENT_TABLE_NOT_PARSED",
    "AGGREGATE_OR_HEADER",
    "COMPARATIVE_PERIOD",
}


class IntervalSourceReviewError(RuntimeError):
    """Raised when interval/tender review inputs or outputs fail closed."""


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
        raise IntervalSourceReviewError(f"Missing required CSV: {path}")
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def make_review_id(cik: str, series_id: str, report_date: str, mechanism: str) -> str:
    series_slug = re.sub(r"[^A-Za-z0-9]+", "", normalize_text(series_id))[:16] or "NOSERIES"
    mech_slug = re.sub(r"[^A-Za-z0-9]+", "_", mechanism).strip("_").upper()[:44] or "NO_MECHANISM"
    # report_date may arrive as a datetime string ('2025-12-31 00:00:00') when the
    # holdings frame carries a DATE column (typed parquet, 2026-09-03). Keep only
    # the 'YYYY-MM-DD' date part so the review_id is a valid filename -- Windows
    # rejects the ':' in the time component (Errno 22).
    date_part = str(report_date).strip()[:10]
    digest = short_hash("|".join([normalize_cik(cik), series_slug, date_part, mechanism]), 10)
    return f"INTSRC_{normalize_cik(cik)}_{series_slug}_{date_part}_{mech_slug}_{digest}"


def _stable_join(values: Iterable[Any], limit: int = 8) -> str:
    out: list[str] = []
    for value in values:
        text = normalize_text(value)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return " | ".join(out)


def _artifact(path: Path) -> dict[str, str]:
    return {"path": display_path(path), "sha256": sha256_file(path) if path.exists() else "", "exists": str(path.exists())}


def _norm_key(value: Any) -> str:
    text = normalize_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _source_identifier(row: dict[str, str]) -> str:
    return _stable_join(
        [
            row.get("issuer_name"),
            row.get("issuer_title"),
            row.get("holding_id"),
            row.get("identifier_isin"),
            row.get("issuer_cusip"),
            row.get("issuer_lei"),
            row.get("identifier_ticker"),
        ],
        limit=4,
    )


def _source_fv(row: dict[str, str]) -> float:
    return parse_float(row.get("currency_value"))


def _output_fv(row: dict[str, str]) -> float:
    return parse_float(row.get("fair_value"))


def _value_bucket(value: float) -> str:
    return f"{round(value, 2):.2f}"


def _group_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        normalize_cik(row.get("cik")),
        normalize_text(row.get("series_id") or row.get("nport_series_id")),
        normalize_text(row.get("report_date")),
    )


def _load_universe(universe_path: Path) -> dict[tuple[str, str], dict[str, str]]:
    universe: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_csv_rows(universe_path):
        vehicle_type = normalize_text(row.get("vehicle_type")).lower()
        if vehicle_type not in TARGET_VEHICLE_TYPES:
            continue
        cik = normalize_cik(row.get("cik"))
        series_id = normalize_text(row.get("series_id"))
        universe[(cik, series_id)] = {
            "cik": cik,
            "series_id": series_id,
            "entity_name": normalize_text(row.get("entity_name")),
            "fund_name": normalize_text(row.get("fund_name")),
            "vehicle_type": vehicle_type,
        }
    return universe


def _source_in_scope(row: dict[str, str], universe: dict[tuple[str, str], dict[str, str]]) -> bool:
    cik = normalize_cik(row.get("cik"))
    series_id = normalize_text(row.get("series_id"))
    return (cik, series_id) in universe or (cik, "") in universe


def _universe_row(row: dict[str, str], universe: dict[tuple[str, str], dict[str, str]]) -> dict[str, str]:
    cik = normalize_cik(row.get("cik"))
    series_id = normalize_text(row.get("series_id") or row.get("nport_series_id"))
    return universe.get((cik, series_id)) or universe.get((cik, "")) or {}


def _source_to_review_row(row: dict[str, str], universe: dict[tuple[str, str], dict[str, str]]) -> dict[str, str]:
    u = _universe_row(row, universe)
    source_id = normalize_text(row.get("holding_id")) or short_hash(json.dumps(row, sort_keys=True), 12)
    return {
        "source_row_id": source_id,
        "cik": normalize_cik(row.get("cik")),
        "entity_name": normalize_text(row.get("registrant_name") or u.get("entity_name")),
        "series_id": normalize_text(row.get("series_id")),
        "series_name": normalize_text(row.get("series_name") or u.get("fund_name")),
        "vehicle_type": normalize_text(u.get("vehicle_type")),
        "report_date": normalize_text(row.get("report_date")),
        "accession_number": normalize_text(row.get("accession_number")),
        "issuer_name": normalize_text(row.get("issuer_name")),
        "issuer_title": normalize_text(row.get("issuer_title")),
        "issuer_cusip": normalize_text(row.get("issuer_cusip")),
        "issuer_lei": normalize_text(row.get("issuer_lei")),
        "identifier_isin": normalize_text(row.get("identifier_isin")),
        "identifier_ticker": normalize_text(row.get("identifier_ticker")),
        "other_identifier": normalize_text(row.get("other_identifier")),
        "asset_cat": normalize_text(row.get("asset_cat")),
        "issuer_type": normalize_text(row.get("issuer_type")),
        "payoff_profile": normalize_text(row.get("payoff_profile")),
        "maturity_date": normalize_text(row.get("maturity_date")),
        "annualized_rate": normalize_text(row.get("annualized_rate")),
        "currency_value": normalize_text(row.get("currency_value")),
        "percentage": normalize_text(row.get("percentage")),
        "is_restricted_security": normalize_text(row.get("is_restricted_security")),
        "raw_investment_identifier": _source_identifier(row),
        "normalized_investment_identifier": _norm_key(_source_identifier(row)),
        "source_fair_value": normalize_text(row.get("currency_value")),
    }


def _output_to_review_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "output_row_id": normalize_text(row.get("nport_holding_id")) or short_hash(json.dumps(row, sort_keys=True), 12),
        "cik": normalize_cik(row.get("cik")),
        "entity_name": normalize_text(row.get("entity_name")),
        "series_id": normalize_text(row.get("nport_series_id")),
        "series_name": normalize_text(row.get("nport_series_name")),
        "report_date": normalize_text(row.get("report_date")),
        "accession_number": normalize_text(row.get("accession_number")),
        "issuer_name": normalize_text(row.get("issuer_name")),
        "instrument_description": normalize_text(row.get("instrument_description")),
        "cusip": normalize_text(row.get("cusip")),
        "isin": normalize_text(row.get("isin")),
        "lei": normalize_text(row.get("lei")),
        "ticker": normalize_text(row.get("ticker")),
        "fair_value": normalize_text(row.get("fair_value")),
        "nport_holding_id": normalize_text(row.get("nport_holding_id")),
        "nport_asset_cat": normalize_text(row.get("nport_asset_cat")),
        "nport_issuer_type": normalize_text(row.get("nport_issuer_type")),
        "nport_payoff_profile": normalize_text(row.get("nport_payoff_profile")),
        "maturity_date": normalize_text(row.get("maturity_date")),
        "interest_rate": normalize_text(row.get("interest_rate")),
        "entity_id": normalize_text(row.get("entity_id")),
        "canonical_name": normalize_text(row.get("canonical_name")),
    }


def _strong_keys_source(row: dict[str, str]) -> list[tuple[str, str]]:
    pairs = [
        ("holding_id", row.get("source_row_id")),
        ("cusip", row.get("issuer_cusip")),
        ("isin", row.get("identifier_isin")),
        ("lei", row.get("issuer_lei")),
        ("ticker", row.get("identifier_ticker")),
    ]
    return [(kind, _norm_key(value)) for kind, value in pairs if _norm_key(value)]


def _strong_keys_output(row: dict[str, str]) -> list[tuple[str, str]]:
    pairs = [
        ("holding_id", row.get("nport_holding_id")),
        ("cusip", row.get("cusip")),
        ("isin", row.get("isin")),
        ("lei", row.get("lei")),
        ("ticker", row.get("ticker")),
    ]
    return [(kind, _norm_key(value)) for kind, value in pairs if _norm_key(value)]


def _fallback_source_key(row: dict[str, str]) -> tuple[str, ...]:
    return (
        _norm_key(row.get("issuer_name")),
        _norm_key(row.get("issuer_title")),
        _value_bucket(_source_fv(row)),
        _norm_key(row.get("asset_cat")),
        _norm_key(row.get("issuer_type")),
        _norm_key(row.get("maturity_date")),
        _norm_key(row.get("annualized_rate")),
    )


def _fallback_output_key(row: dict[str, str]) -> tuple[str, ...]:
    return (
        _norm_key(row.get("issuer_name")),
        _norm_key(row.get("instrument_description")),
        _value_bucket(_output_fv(row)),
        _norm_key(row.get("nport_asset_cat")),
        _norm_key(row.get("nport_issuer_type")),
        _norm_key(row.get("maturity_date")),
        _norm_key(row.get("interest_rate")),
    )


def _is_money_market_or_cash(row: dict[str, str]) -> bool:
    text = " ".join([row.get("issuer_name", ""), row.get("issuer_title", ""), row.get("asset_cat", ""), row.get("issuer_type", "")]).lower()
    return any(term in text for term in ["money market", "cash", "treasury bill", "t-bill"]) or row.get("asset_cat", "").upper() in {"STIV", "CASH", "CSH"}


def _is_public_or_non_private(row: dict[str, str]) -> bool:
    asset = row.get("asset_cat", "").upper()
    issuer_type = row.get("issuer_type", "").upper()
    has_market_id = bool(row.get("identifier_ticker") or row.get("issuer_cusip") or row.get("identifier_isin"))
    restricted = row.get("is_restricted_security", "").strip().lower()
    if issuer_type in {"SOV", "MUN"}:
        return True
    if issuer_type == "RF":
        return True
    if asset in {"EC", "EP"} and has_market_id and restricted in {"", "n", "no", "false", "0"}:
        return True
    return False


def _classify_source_only(row: dict[str, str]) -> tuple[bool, str, str]:
    if _is_money_market_or_cash(row):
        return False, "MONEY_MARKET_OR_CASH_EQUIVALENT", "Source row appears to be cash or money-market exposure intentionally outside private markets."
    if _is_public_or_non_private(row):
        return False, "PUBLIC_MARKET_OR_NON_PRIVATE_FILTERED", "Source row appears public, sovereign, municipal, or registered-fund exposure intentionally outside private markets."
    return True, "REAL_SOURCE_POSITION_MISSING_FROM_UNIFIED", "N-PORT source row is private-market-like and has no conservative one-to-one unified match."


def _match_group(source_rows: list[dict[str, str]], output_rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], set[int], set[int]]:
    details: list[dict[str, Any]] = []
    matched_source: set[int] = set()
    matched_output: set[int] = set()
    source_key_map: dict[tuple[str, str], list[int]] = defaultdict(list)
    output_key_map: dict[tuple[str, str], list[int]] = defaultdict(list)
    for idx, row in enumerate(source_rows):
        for key in _strong_keys_source(row):
            source_key_map[key].append(idx)
    for idx, row in enumerate(output_rows):
        for key in _strong_keys_output(row):
            output_key_map[key].append(idx)
    for key, sidxs in sorted(source_key_map.items()):
        oidxs = output_key_map.get(key, [])
        if len(sidxs) == 1 and len(oidxs) == 1 and sidxs[0] not in matched_source and oidxs[0] not in matched_output:
            sidx, oidx = sidxs[0], oidxs[0]
            matched_source.add(sidx)
            matched_output.add(oidx)
            details.append(_detail_row(source_rows[sidx], output_rows[oidx], "MATCHED", key[0], "unique structured identifier"))

    fallback_sources: dict[tuple[str, ...], list[int]] = defaultdict(list)
    fallback_outputs: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for idx, row in enumerate(source_rows):
        if idx not in matched_source:
            fallback_sources[_fallback_source_key(row)].append(idx)
    for idx, row in enumerate(output_rows):
        if idx not in matched_output:
            fallback_outputs[_fallback_output_key(row)].append(idx)
    for key, sidxs in sorted(fallback_sources.items()):
        oidxs = fallback_outputs.get(key, [])
        if key[0] and len(sidxs) == 1 and len(oidxs) == 1 and sidxs[0] not in matched_source and oidxs[0] not in matched_output:
            sidx, oidx = sidxs[0], oidxs[0]
            matched_source.add(sidx)
            matched_output.add(oidx)
            details.append(_detail_row(source_rows[sidx], output_rows[oidx], "MATCHED", "fallback_exact_identity", "unique exact name/value/attribute identity"))
    return details, matched_source, matched_output


def _detail_row(source_row: dict[str, str] | None, output_row: dict[str, str] | None, status: str, match_tier: str, reason: str) -> dict[str, Any]:
    source_row = source_row or {}
    output_row = output_row or {}
    base = source_row or output_row
    return {
        "cik": normalize_cik(base.get("cik")),
        "entity_name": normalize_text(base.get("entity_name")),
        "series_id": normalize_text(base.get("series_id")),
        "series_name": normalize_text(base.get("series_name")),
        "report_date": normalize_text(base.get("report_date")),
        "source_row_id": normalize_text(source_row.get("source_row_id")),
        "output_row_id": normalize_text(output_row.get("output_row_id")),
        "source_identifier": _source_identifier(source_row) if source_row else "",
        "output_identifier": _stable_join([output_row.get("issuer_name"), output_row.get("instrument_description"), output_row.get("nport_holding_id")]) if output_row else "",
        "source_fair_value": f"{_source_fv(source_row):.6f}" if source_row else "",
        "output_fair_value": f"{_output_fv(output_row):.6f}" if output_row else "",
        "status": status,
        "match_tier": match_tier,
        "blocking_issue": "False",
        "diagnosis": "",
        "reason": reason,
        "mechanism": "",
    }


def build_reconciliation_artifacts(
    *,
    nport_path: Path = config.NPORT_HOLDINGS_FILE,
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
    universe_path: Path = config.COMBINED_UNIVERSE_FILE,
    output_dir: Path = REVIEW_DIR,
) -> dict[str, Any]:
    universe = _load_universe(universe_path)
    source_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    output_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)

    for row in read_csv_rows(nport_path):
        if _source_in_scope(row, universe):
            review_row = _source_to_review_row(row, universe)
            source_by_key[_group_key(review_row)].append(review_row)

    if holdings_path.exists():
        for row in read_csv_rows(holdings_path):
            if normalize_text(row.get("source")).lower() != "nport":
                continue
            if _source_in_scope({"cik": row.get("cik"), "series_id": row.get("nport_series_id")}, universe):
                review_row = _output_to_review_row(row)
                output_by_key[_group_key(review_row)].append(review_row)

    detail_rows: list[dict[str, Any]] = []
    source_only_rows: list[dict[str, Any]] = []
    keys = set(source_by_key) | set(output_by_key)
    for key in sorted(keys):
        source_rows = source_by_key.get(key, [])
        output_rows = output_by_key.get(key, [])
        matched_details, matched_source, matched_output = _match_group(source_rows, output_rows)
        detail_rows.extend(matched_details)
        for idx, source_row in enumerate(source_rows):
            if idx in matched_source:
                continue
            is_blocking, diagnosis, reason = _classify_source_only(source_row)
            mechanism = "interval_source_position_missing_from_unified" if is_blocking else "interval_source_intentionally_filtered"
            row = _detail_row(source_row, None, "SOURCE_ONLY", "", reason)
            row.update(
                {
                    "blocking_issue": str(is_blocking),
                    "diagnosis": diagnosis,
                    "mechanism": mechanism,
                    "vehicle_type": source_row.get("vehicle_type", ""),
                    "asset_cat": source_row.get("asset_cat", ""),
                    "issuer_type": source_row.get("issuer_type", ""),
                    "accession_number": source_row.get("accession_number", ""),
                    "raw_investment_identifier": source_row.get("raw_investment_identifier", ""),
                    "normalized_investment_identifier": source_row.get("normalized_investment_identifier", ""),
                }
            )
            detail_rows.append(row)
            source_only_rows.append(row)
        for idx, output_row in enumerate(output_rows):
            if idx in matched_output:
                continue
            row = _detail_row(None, output_row, "PIPELINE_ONLY", "", "Unified N-PORT row has no conservative one-to-one source row match.")
            row.update(
                {
                    "blocking_issue": "True",
                    "diagnosis": "PIPELINE_ONLY_POSITION",
                    "mechanism": "interval_pipeline_only_position",
                    "accession_number": output_row.get("accession_number", ""),
                }
            )
            detail_rows.append(row)

    ensure_dir(output_dir)
    detail_cols = sorted({key for row in detail_rows for key in row})
    source_only_cols = sorted({key for row in source_only_rows for key in row})
    write_csv_rows(output_dir / "source_reconciliation_detail.csv", detail_rows, detail_cols)
    write_csv_rows(output_dir / "source_only_detail.csv", source_only_rows, source_only_cols or ["cik"])
    return {
        "source_groups": len(source_by_key),
        "detail_rows": len(detail_rows),
        "source_only_rows": len(source_only_rows),
        "blocking_rows": sum(1 for row in detail_rows if trueish(row.get("blocking_issue"))),
    }


def build_worklist(
    *,
    nport_path: Path = config.NPORT_HOLDINGS_FILE,
    holdings_path: Path = config.UNIFIED_HOLDINGS_FILE,
    universe_path: Path = config.COMBINED_UNIVERSE_FILE,
    output_dir: Path = REVIEW_DIR,
    top_n: int = 100,
    batch_size: int = 1,
) -> dict[str, Any]:
    stats = build_reconciliation_artifacts(
        nport_path=nport_path,
        holdings_path=holdings_path,
        universe_path=universe_path,
        output_dir=output_dir,
    )
    details = read_csv_rows(output_dir / "source_reconciliation_detail.csv")
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    pair_counts: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    for row in details:
        pair = (normalize_cik(row.get("cik")), normalize_text(row.get("series_id")), normalize_text(row.get("report_date")))
        pair_counts[pair][normalize_text(row.get("status"))] += 1
        if trueish(row.get("blocking_issue")):
            key = (*pair, normalize_text(row.get("mechanism")))
            grouped[key].append(row)

    worklist: list[dict[str, Any]] = []
    for (cik, series_id, report_date, mechanism), rows in grouped.items():
        first = rows[0]
        pair = (cik, series_id, report_date)
        source_fv = sum(parse_float(row.get("source_fair_value")) for row in rows)
        output_fv = sum(parse_float(row.get("output_fair_value")) for row in rows)
        worklist.append(
            {
                "review_id": make_review_id(cik, series_id, report_date, mechanism),
                "cik": cik,
                "entity_name": first.get("entity_name", ""),
                "series_id": series_id,
                "series_name": first.get("series_name", ""),
                "vehicle_type": first.get("vehicle_type", ""),
                "report_date": report_date,
                "mechanism": mechanism,
                "blocking_issue_count": len(rows),
                "source_rows": pair_counts[pair]["SOURCE_ONLY"] + pair_counts[pair]["MATCHED"],
                "output_rows": pair_counts[pair]["PIPELINE_ONLY"] + pair_counts[pair]["MATCHED"],
                "matched_rows": pair_counts[pair]["MATCHED"],
                "affected_source_fair_value": f"{source_fv:.6f}",
                "affected_output_fair_value": f"{output_fv:.6f}",
                "sample_identifiers": _stable_join(row.get("source_identifier") or row.get("output_identifier") for row in rows),
                "source_only_blocker_rows": sum(1 for row in rows if row.get("status") == "SOURCE_ONLY"),
                "source_only_blocker_fv": f"{sum(parse_float(row.get('source_fair_value')) for row in rows if row.get('status') == 'SOURCE_ONLY'):.6f}",
                "pipeline_only_rows": sum(1 for row in rows if row.get("status") == "PIPELINE_ONLY"),
                "pipeline_only_fv": f"{sum(parse_float(row.get('output_fair_value')) for row in rows if row.get('status') == 'PIPELINE_ONLY'):.6f}",
            }
        )
    worklist.sort(key=lambda r: (-int(r["blocking_issue_count"]), -parse_float(r["affected_source_fair_value"]), r["cik"], r["series_id"]))
    worklist = worklist[:top_n]
    write_csv_rows(output_dir / "worklist.csv", worklist, WORKLIST_COLUMNS)
    _write_batches(output_dir, worklist, batch_size)
    stats.update({"worklist_count": len(worklist), "blocking_group_count": len(grouped), "batch_size": batch_size})
    return stats


def _write_batches(output_dir: Path, worklist: list[dict[str, Any]], batch_size: int) -> None:
    batch_dir = output_dir / "batches"
    ensure_dir(batch_dir)
    batch_size = max(1, batch_size)
    for idx in range(0, len(worklist), batch_size):
        write_csv_rows(batch_dir / f"batch_{idx // batch_size + 1:03d}.csv", worklist[idx : idx + batch_size], WORKLIST_COLUMNS)


def _rows_by_group(
    path: Path,
    targets: set[tuple[str, str, str, str]],
    predicate: Callable[[dict[str, str]], bool],
    limit_per_group: int | None,
) -> dict[tuple[str, str, str, str], list[dict[str, str]]]:
    rows: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    if not path.exists() or not targets:
        return rows
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (
                normalize_cik(row.get("cik")),
                normalize_text(row.get("series_id")),
                normalize_text(row.get("report_date")),
                normalize_text(row.get("mechanism")),
            )
            if key not in targets or not predicate(row):
                continue
            if limit_per_group is None or len(rows[key]) < limit_per_group:
                rows[key].append(row)
    return rows


def _rows_by_pair(path: Path, pairs: set[tuple[str, str, str]], limit_per_pair: int | None) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    rows: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    if not path.exists() or not pairs:
        return rows
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (normalize_cik(row.get("cik")), normalize_text(row.get("series_id") or row.get("nport_series_id")), normalize_text(row.get("report_date")))
            if key not in pairs:
                continue
            if limit_per_pair is None or len(rows[key]) < limit_per_pair:
                rows[key].append(row)
    return rows


def _load_entity_candidates(rows: Iterable[dict[str, str]], max_rows: int = 25) -> list[dict[str, str]]:
    if not config.ENTITY_LOOKUP_FILE.exists():
        return []
    names = {_norm_key(row.get("source_identifier") or row.get("raw_investment_identifier") or row.get("issuer_name")) for row in rows}
    names = {name for name in names if name}
    out: list[dict[str, str]] = []
    if not names:
        return out
    with config.ENTITY_LOOKUP_FILE.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            normalized = _norm_key(row.get("issuer_name_variant") or row.get("canonical_name") or row.get("normalized_name"))
            if normalized in names:
                out.append(
                    {
                        "candidate_entity_id": normalize_text(row.get("entity_id")),
                        "candidate_canonical_name": normalize_text(row.get("canonical_name")),
                        "issuer_name_variant": normalize_text(row.get("issuer_name_variant")),
                        "source": normalize_text(row.get("source")),
                        "entity_match_status": "candidate_exact_normalized_name",
                    }
                )
                if len(out) >= max_rows:
                    break
    return out


def _ncsr_accession(cik: str, report_date: str) -> str:
    if not config.NCSR_FILINGS_INDEX_FILE.exists():
        return ""
    candidates: list[dict[str, str]] = []
    for row in read_csv_rows(config.NCSR_FILINGS_INDEX_FILE):
        if normalize_cik(row.get("cik")) == normalize_cik(cik) and normalize_text(row.get("report_date")) == report_date:
            candidates.append(row)
    if not candidates:
        return ""
    candidates.sort(key=lambda r: normalize_text(r.get("filing_date")), reverse=True)
    return normalize_text(candidates[0].get("accession_number"))


def build_bundles(
    *,
    output_dir: Path = REVIEW_DIR,
    review_ids: set[str] | None = None,
    overwrite: bool = False,
    max_rows: int = 25,
    allow_html_download: bool = False,
) -> list[dict[str, str]]:
    worklist = [row for row in read_csv_rows(output_dir / "worklist.csv") if review_ids is None or row.get("review_id") in review_ids]
    bundle_dir = output_dir / "bundles"
    ensure_dir(bundle_dir)
    artifact_paths = [
        config.NPORT_HOLDINGS_FILE,
        config.UNIFIED_HOLDINGS_FILE,
        config.COMBINED_UNIVERSE_FILE,
        config.NCSR_FILINGS_INDEX_FILE,
        output_dir / "source_reconciliation_detail.csv",
        output_dir / "source_only_detail.csv",
    ]
    artifacts = [_artifact(path) for path in artifact_paths if path.exists()]
    targets = {
        (normalize_cik(row.get("cik")), normalize_text(row.get("series_id")), normalize_text(row.get("report_date")), normalize_text(row.get("mechanism")))
        for row in worklist
    }
    pairs = {(cik, series_id, report_date) for cik, series_id, report_date, _ in targets}
    detail_by_group = _rows_by_group(output_dir / "source_reconciliation_detail.csv", targets, lambda r: trueish(r.get("blocking_issue")), max_rows)
    source_only_by_group = _rows_by_group(output_dir / "source_only_detail.csv", targets, lambda r: trueish(r.get("blocking_issue")), max_rows)
    holdings_by_pair = _rows_by_pair(config.UNIFIED_HOLDINGS_FILE, pairs, max_rows)
    manifest: list[dict[str, str]] = []
    for row in worklist:
        review_id = row["review_id"]
        target = bundle_dir / f"{review_id}.json"
        if target.exists() and not overwrite:
            manifest.append({"review_id": review_id, "bundle_path": display_path(target), "bundle_sha256": sha256_file(target)})
            continue
        cik = normalize_cik(row.get("cik"))
        series_id = normalize_text(row.get("series_id"))
        report_date = normalize_text(row.get("report_date"))
        mechanism = normalize_text(row.get("mechanism"))
        group_key = (cik, series_id, report_date, mechanism)
        pair_key = (cik, series_id, report_date)
        detail_rows = detail_by_group.get(group_key, [])
        source_only_rows = source_only_by_group.get(group_key, [])
        holdings_rows = holdings_by_pair.get(pair_key, [])
        accession_candidates = resolve_accessions_from_rows(detail_rows + source_only_rows + holdings_rows)
        accession = accession_candidates[0] if accession_candidates else _ncsr_accession(cik, report_date)
        evidence_items = [
            {"evidence_id": "worklist_row", "description": "Selected interval/tender source blocker group.", "data": row},
            {"evidence_id": "source_reconciliation_detail_rows", "description": "Review-generated N-PORT to unified reconciliation rows.", "data": detail_rows},
            {"evidence_id": "source_only_blocker_rows", "description": "N-PORT source-only blocker rows for the selected group.", "data": source_only_rows},
            {"evidence_id": "holdings_examples", "description": "Sample unified N-PORT holdings rows for the same fund/date.", "data": holdings_rows},
            {"evidence_id": "entity_candidate_context", "description": "Review-only candidate entity IDs from entity_lookup; not a clearing mechanism.", "data": _load_entity_candidates(detail_rows + source_only_rows, max_rows)},
        ]
        evidence_items.extend(
            build_html_soi_evidence(
                source="ncsr",
                cik=cik,
                report_date=report_date,
                accession=accession,
                residual_names=[
                    row.get("sample_identifiers", ""),
                    *[r.get("source_identifier", "") for r in detail_rows],
                    *[r.get("raw_investment_identifier", "") for r in source_only_rows],
                ],
                fair_values=[
                    row.get("affected_source_fair_value", ""),
                    *[r.get("source_fair_value", "") for r in source_only_rows],
                ],
                source_identifiers=accession_candidates,
                source_rows=source_only_rows,
                xbrl_rows_same_accession=[],
                allow_html_download=allow_html_download,
                max_rows=max_rows,
            )
        )
        bundle = {
            "schema_version": "interval-source-review-bundle.v1",
            "created_at": now_iso(),
            "review_id": review_id,
            "cik": cik,
            "series_id": series_id,
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
                "pytest tests/test_interval_source_review.py tests/test_html_soi_evidence.py",
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
        lines.append(f"- `{display_path(bundle_path)}` -> write `data/output/interval_source_review/verdicts/{review_id}.json`")
    target = output_dir / "prompt.md"
    ensure_dir(target.parent)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
    return normalized in PROTECTED_GENERATED_PATHS or any(normalized.startswith(prefix) for prefix in PROTECTED_GENERATED_PATH_PREFIXES)


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
    citation_refs = {normalize_text(c.get("evidence_ref")) for c in citations if _valid_html_citation(c)}
    coordinate_required_refs = set(verdict.get("evidence_refs", [])) & (HTML_EVIDENCE_IDS - {"html_artifact", "xbrl_rows_same_accession"})
    for ref in sorted(coordinate_required_refs - citation_refs):
        errors.append(f"HTML evidence_ref {ref} requires table_index,row_index,cell_indices coordinate citation")
    diagnosis = normalize_text(verdict.get("reconciliation_diagnosis")).upper()
    if diagnosis in HTML_BASED_DIAGNOSES and not citations:
        errors.append(f"{diagnosis} requires coordinate-level html_citations")
    for idx, citation in enumerate(citations if isinstance(citations, list) else []):
        row_class = normalize_text(citation.get("row_classification")).upper() if isinstance(citation, dict) else ""
        if diagnosis == "REAL_SOURCE_POSITION_MISSING_FROM_UNIFIED" and row_class in {
            "AGGREGATE_HEADER",
            "SUBTOTAL_ROW",
            "COMPARATIVE_PERIOD_ROW",
            "UNCLASSIFIABLE",
            "INSUFFICIENT_EVIDENCE",
        }:
            errors.append(f"html_citations[{idx}] cannot support REAL_SOURCE_POSITION_MISSING_FROM_UNIFIED with {row_class}")
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
    for changed in verdict.get("changed_files", []):
        if _protected_edit(str(changed)):
            errors.append(f"protected generated-output edit is not allowed: {changed}")
    if verdict.get("verdict") == "PATCH_PROPOSED":
        if not verdict.get("changed_files"):
            errors.append("PATCH_PROPOSED requires changed_files")
        for key in ["patch_summary", "source_reconciliation_effect", "gav_effect", "tests_validation_plan"]:
            if not verdict.get(key):
                errors.append(f"PATCH_PROPOSED requires {key}")
        if verdict.get("requires_human_merge") is not True:
            errors.append("PATCH_PROPOSED requires requires_human_merge=true")
    if verdict.get("verdict") in {"INSUFFICIENT_EVIDENCE", "ESCALATE"} and len(normalize_text(verdict.get("missing_evidence"))) < 10:
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
    "series_id",
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
        raise IntervalSourceReviewError(f"Verdict validation failed with {len(validation_errors)} error(s)")
    worklist = {row["review_id"]: row for row in read_csv_rows(output_dir / "worklist.csv")}
    rows: list[dict[str, Any]] = []
    for path in sorted((output_dir / "verdicts").glob("*.json")):
        verdict = json.loads(path.read_text(encoding="utf-8-sig"))
        work = worklist[verdict["review_id"]]
        rows.append(
            {
                "review_id": verdict["review_id"],
                "cik": verdict["cik"],
                "series_id": work.get("series_id", ""),
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
            }
        )
    write_csv_rows(output_dir / "summary.csv", rows, SUMMARY_COLUMNS)
    counts = Counter(row["verdict"] for row in rows)
    diagnosis_counts = Counter(row["reconciliation_diagnosis"] or "UNSPECIFIED_LEGACY" for row in rows)
    md = [
        "# Interval/Tender Source Review Summary",
        "",
        f"Generated: {now_iso()}",
        f"Verdicts reviewed: {len(rows)}",
        "",
        "## Verdict Counts",
        "",
    ]
    for verdict, count in sorted(counts.items()):
        md.append(f"- {verdict}: {count} reviews")
    md.extend(["", "## Reconciliation Diagnosis Counts", ""])
    for diagnosis, count in sorted(diagnosis_counts.items()):
        md.append(f"- {diagnosis}: {count} reviews")
    (output_dir / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return {"verdict_count": len(rows), "counts": dict(counts), "diagnosis_counts": dict(diagnosis_counts)}


def cli_build_worklist(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build interval/tender source review worklist.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args(argv)
    print(json.dumps(build_worklist(output_dir=args.output_dir, top_n=args.top_n, batch_size=args.batch_size), indent=2, sort_keys=True))
    return 0


def cli_build_bundles(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build interval/tender source review bundles.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--review-id", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--allow-html-download", action="store_true")
    args = parser.parse_args(argv)
    review_ids = None if args.all or not args.review_id else set(args.review_id)
    manifest = build_bundles(output_dir=args.output_dir, review_ids=review_ids, overwrite=args.overwrite, allow_html_download=args.allow_html_download)
    print(json.dumps({"bundle_count": len(manifest)}, indent=2, sort_keys=True))
    return 0


def cli_build_prompt(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build manual-launch prompt for an interval/tender review batch.")
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    args = parser.parse_args(argv)
    print(display_path(build_prompt(args.batch, args.output_dir)))
    return 0


def cli_validate_verdicts(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate interval/tender source review verdicts.")
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
    parser = argparse.ArgumentParser(description="Summarize interval/tender source review verdicts.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--schema-file", type=Path, default=SCHEMA_FILE)
    args = parser.parse_args(argv)
    print(json.dumps(summarize_verdicts(args.output_dir, args.schema_file), indent=2, sort_keys=True))
    return 0
