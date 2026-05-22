"""Grouped fund-strategy review workflow.

This module reads the cached fund-strategy correction candidate artifact and
writes review-only artifacts under data/output/fund_strategy_group_review. It
does not mutate classifier logic, unified holdings, or frontend exports.
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
from typing import Any, Iterable

import jsonschema

from pipeline.config import (
    BDC_HTML_CACHE_DIR,
    BDC_XBRL_CACHE_DIR,
    NPORT_XML_CACHE_DIR,
    OUTPUT_DIR,
    PROJECT_ROOT,
)

INPUT_FILE = OUTPUT_DIR / "fund_strategy_correction_candidates.csv"
REVIEW_DIR = OUTPUT_DIR / "fund_strategy_group_review"
SCHEMA_FILE = PROJECT_ROOT / "schemas" / "fund_strategy_group_review" / "verdict.schema.json"
SPOT_CHECK_FILE = OUTPUT_DIR / "fund_strategy_review_spot_check_samples.csv"

GROUP_KEYS = [
    "cik",
    "entity_name",
    "issuer_name",
    "instrument_description",
    "asset_category",
    "issuer_category",
    "current_index_classification",
    "current_asset_class",
    "fund_strategy",
    "rule_id",
    "mechanism",
]

WORKLIST_COLUMNS = [
    "group_id",
    *GROUP_KEYS,
    "proposed_index_classification",
    "proposed_asset_class",
    "affected_fair_value",
    "row_count",
    "report_date_count",
    "report_dates",
    "accession_count",
    "accession_numbers",
    "sources",
    "fund_strategy_sources",
    "fund_strategy_evidence",
    "row_source_evidence",
    "source_field_summary",
    "candidate_row_ids",
]

GROUP_ROW_COLUMNS = [
    "group_id",
    "candidate_row_id",
    "correction_status",
    "rule_id",
    "mechanism",
    "confidence",
    "residual_risk",
    "cik",
    "entity_name",
    "report_date",
    "source",
    "accession_number",
    "bdc_investment_identifier",
    "nport_holding_id",
    "issuer_name",
    "instrument_description",
    "asset_category",
    "issuer_category",
    "nport_asset_cat",
    "nport_issuer_type",
    "current_index_classification",
    "current_asset_class",
    "proposed_index_classification",
    "proposed_asset_class",
    "fund_strategy",
    "fund_strategy_source",
    "fund_strategy_evidence",
    "row_source_evidence",
    "affected_fair_value",
    "before_metric",
    "after_metric",
]

VERDICTS = {
    "KEEP_REVIEW",
    "CONFIRMED_RULE_GAP",
    "SOURCE_CONFLICT",
    "INSUFFICIENT_EVIDENCE",
    "ALREADY_CLASSIFIED_CONSISTENTLY",
}
CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}
NEXT_ACTIONS = {"GLOBAL_DETERMINISTIC_RULE", "PER_CIK_CONFIG", "MANUAL_REVIEW", "NO_ACTION"}


class FundStrategyReviewError(RuntimeError):
    """Raised when review inputs or outputs fail closed."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.lower() == "nan":
        return ""
    return text.strip()


def normalize_cik(value: Any) -> str:
    digits = re.sub(r"\D", "", normalize_text(value))
    return digits.zfill(10) if digits else ""


def accession_compact(value: Any) -> str:
    return re.sub(r"\D", "", normalize_text(value))


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_float(value: Any) -> float:
    text = normalize_text(value).replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FundStrategyReviewError(f"Missing required CSV: {path}")
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
    unique = sorted({normalize_text(value) for value in values if normalize_text(value)})
    return "|".join(unique)


def _group_key(row: dict[str, str]) -> tuple[str, ...]:
    values: list[str] = []
    for key in GROUP_KEYS:
        if key == "cik":
            values.append(normalize_cik(row.get(key)))
        else:
            values.append(normalize_text(row.get(key)))
    return tuple(values)


def _make_group_id(key: tuple[str, ...]) -> str:
    cik = key[0] or "NO_CIK"
    rule_id = key[-2] or "NO_RULE"
    issuer = re.sub(r"[^A-Za-z0-9]+", "_", key[2]).strip("_").upper()[:32] or "NO_ISSUER"
    return f"FSG_{cik}_{rule_id}_{issuer}_{short_hash('|'.join(key), 10)}"


def _summarize_source_fields(rows: list[dict[str, str]]) -> str:
    fields = [
        "bdc_investment_identifier",
        "instrument_description",
        "asset_category",
        "issuer_category",
        "nport_asset_cat",
        "nport_issuer_type",
    ]
    parts = []
    for field in fields:
        values = [normalize_text(row.get(field)) for row in rows if normalize_text(row.get(field))]
        if values:
            common = Counter(values).most_common(3)
            parts.append(f"{field}=" + "; ".join(f"{value} ({count})" for value, count in common))
    return " | ".join(parts)


def build_grouped_worklist(
    input_file: Path = INPUT_FILE,
    output_dir: Path = REVIEW_DIR,
    top_n: int = 1000,
    batch_size: int = 25,
) -> dict[str, Any]:
    rows = read_csv_rows(input_file)
    review_rows: list[dict[str, str]] = []
    review_total_fv = 0.0
    for idx, row in enumerate(rows):
        if normalize_text(row.get("correction_status")) != "REVIEW":
            continue
        item = dict(row)
        item["candidate_row_id"] = str(idx)
        item["cik"] = normalize_cik(item.get("cik"))
        review_total_fv += parse_float(item.get("affected_fair_value"))
        review_rows.append(item)

    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in review_rows:
        grouped[_group_key(row)].append(row)

    worklist: list[dict[str, Any]] = []
    row_map: list[dict[str, Any]] = []
    for key, items in grouped.items():
        group_id = _make_group_id(key)
        total_fv = sum(parse_float(item.get("affected_fair_value")) for item in items)
        row = {GROUP_KEYS[i]: key[i] for i in range(len(GROUP_KEYS))}
        row.update(
            {
                "group_id": group_id,
                "proposed_index_classification": _stable_join(item.get("proposed_index_classification") for item in items),
                "proposed_asset_class": _stable_join(item.get("proposed_asset_class") for item in items),
                "affected_fair_value": f"{total_fv:.6f}",
                "row_count": str(len(items)),
                "report_date_count": str(len({normalize_text(item.get("report_date")) for item in items if normalize_text(item.get("report_date"))})),
                "report_dates": _stable_join(item.get("report_date") for item in items),
                "accession_count": str(len({normalize_text(item.get("accession_number")) for item in items if normalize_text(item.get("accession_number"))})),
                "accession_numbers": _stable_join(item.get("accession_number") for item in items),
                "sources": _stable_join(item.get("source") for item in items),
                "fund_strategy_sources": _stable_join(item.get("fund_strategy_source") for item in items),
                "fund_strategy_evidence": _stable_join(item.get("fund_strategy_evidence") for item in items),
                "row_source_evidence": _stable_join(item.get("row_source_evidence") for item in items),
                "source_field_summary": _summarize_source_fields(items),
                "candidate_row_ids": _stable_join(item.get("candidate_row_id") for item in items),
            }
        )
        worklist.append(row)
        for item in sorted(items, key=lambda r: (normalize_text(r.get("report_date")), normalize_text(r.get("accession_number")), normalize_text(r.get("candidate_row_id")))):
            mapped = {col: item.get(col, "") for col in GROUP_ROW_COLUMNS}
            mapped["group_id"] = group_id
            mapped["candidate_row_id"] = item["candidate_row_id"]
            row_map.append(mapped)

    worklist.sort(
        key=lambda r: (
            -parse_float(r["affected_fair_value"]),
            r["group_id"],
        )
    )
    selected_ids = {row["group_id"] for row in worklist[:top_n]}
    selected_worklist = worklist[:top_n]
    selected_rows = [row for row in row_map if row["group_id"] in selected_ids]
    selected_rows.sort(key=lambda r: (r["group_id"], r.get("report_date", ""), r.get("accession_number", ""), r.get("candidate_row_id", "")))

    ensure_dir(output_dir)
    write_csv_rows(output_dir / "grouped_worklist.csv", selected_worklist, WORKLIST_COLUMNS)
    write_csv_rows(output_dir / "group_rows.csv", selected_rows, GROUP_ROW_COLUMNS)
    batch_dir = output_dir / "batches"
    ensure_dir(batch_dir)
    for batch_idx, start in enumerate(range(0, len(selected_worklist), batch_size), start=1):
        write_csv_rows(batch_dir / f"batch_{batch_idx:03d}.csv", selected_worklist[start : start + batch_size], WORKLIST_COLUMNS)

    selected_fv = sum(parse_float(row["affected_fair_value"]) for row in selected_worklist)
    return {
        "review_row_count": len(review_rows),
        "review_total_fv": review_total_fv,
        "selected_group_count": len(selected_worklist),
        "selected_row_count": len(selected_rows),
        "selected_total_fv": selected_fv,
        "selected_review_fv_pct": selected_fv / review_total_fv if review_total_fv else 0.0,
        "batch_count": (len(selected_worklist) + batch_size - 1) // batch_size if batch_size else 0,
    }


def _find_source_file(source: str, cik: str, accession: str) -> Path | None:
    compact = accession_compact(accession)
    cik_short = str(int(cik)) if cik and cik.isdigit() else cik.lstrip("0")
    if not compact or not cik_short:
        return None
    roots = [NPORT_XML_CACHE_DIR] if source == "nport" else [BDC_XBRL_CACHE_DIR, BDC_HTML_CACHE_DIR]
    suffixes = [".xml", ".html", ".htm"]
    for root in roots:
        for suffix in suffixes:
            candidate = root / cik_short / f"{compact}{suffix}"
            if candidate.exists():
                return candidate
    return None


def _read_text_limited(path: Path, limit: int = 3_000_000) -> str:
    with path.open("rb") as f:
        data = f.read(limit)
    return data.decode("utf-8", errors="ignore")


def _snippet_around(text: str, needle: str, radius: int = 450) -> str:
    if not needle:
        return ""
    match = re.search(re.escape(needle), text, flags=re.IGNORECASE)
    if not match:
        return ""
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    snippet = re.sub(r"\s+", " ", text[start:end]).strip()
    return snippet[:1000]


def _source_evidence_for_row(row: dict[str, str]) -> dict[str, Any]:
    source = normalize_text(row.get("source")).lower()
    path = _find_source_file(source, normalize_cik(row.get("cik")), row.get("accession_number", ""))
    evidence: dict[str, Any] = {
        "candidate_row_id": row.get("candidate_row_id", ""),
        "source": source,
        "accession_number": row.get("accession_number", ""),
        "source_file": display_path(path) if path else "",
        "source_file_sha256": sha256_file(path) if path else "",
        "snippets": [],
    }
    if not path:
        return evidence
    text = _read_text_limited(path)
    needles = [
        normalize_text(row.get("issuer_name")),
        normalize_text(row.get("instrument_description")),
        normalize_text(row.get("bdc_investment_identifier")),
        normalize_text(row.get("nport_holding_id")),
    ]
    snippets = []
    for needle in needles:
        snippet = _snippet_around(text, needle)
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= 3:
            break
    evidence["snippets"] = snippets
    return evidence


def _load_worklist(output_dir: Path) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    worklist = read_csv_rows(output_dir / "grouped_worklist.csv")
    group_rows = read_csv_rows(output_dir / "group_rows.csv")
    by_group: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in group_rows:
        by_group[row.get("group_id", "")].append(row)
    return worklist, by_group


def _load_prior_spot_checks(path: Path | None = None) -> dict[tuple[str, ...], list[dict[str, str]]]:
    path = path or SPOT_CHECK_FILE
    if not path.exists():
        return {}
    checks: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in read_csv_rows(path):
        checks[_group_key(row)].append(
            {
                "selection_bucket": row.get("selection_bucket", ""),
                "analyst_flag": row.get("analyst_flag", ""),
                "analyst_reason": row.get("analyst_reason", ""),
                "recommended_action": row.get("recommended_action", ""),
                "report_date": row.get("report_date", ""),
                "accession_number": row.get("accession_number", ""),
                "affected_fair_value": row.get("affected_fair_value", ""),
            }
        )
    return checks


def build_evidence_bundles(output_dir: Path = REVIEW_DIR, max_source_rows: int = 5) -> list[dict[str, str]]:
    worklist, by_group = _load_worklist(output_dir)
    prior_spot_checks = _load_prior_spot_checks()
    bundle_dir = output_dir / "bundles"
    ensure_dir(bundle_dir)
    manifest: list[dict[str, str]] = []
    for group in worklist:
        group_id = group["group_id"]
        rows = by_group.get(group_id, [])
        if not rows:
            raise FundStrategyReviewError(f"Selected group has no underlying rows: {group_id}")
        spot_checks = prior_spot_checks.get(_group_key(group), [])
        representatives = sorted(rows, key=lambda r: -parse_float(r.get("affected_fair_value")))[:max_source_rows]
        bundle = {
            "schema_version": "1.0",
            "created_at": now_iso(),
            "group_id": group_id,
            "group_summary": group,
            "underlying_rows": rows,
            "representative_rows": representatives,
            "accessions": sorted({normalize_text(row.get("accession_number")) for row in rows if normalize_text(row.get("accession_number"))}),
            "report_dates": sorted({normalize_text(row.get("report_date")) for row in rows if normalize_text(row.get("report_date"))}),
            "current_classification": {
                "index_classification": group.get("current_index_classification", ""),
                "asset_class": group.get("current_asset_class", ""),
            },
            "proposed_classification": {
                "index_classification": group.get("proposed_index_classification", ""),
                "asset_class": group.get("proposed_asset_class", ""),
            },
            "evidence_fields": {
                "fund_strategy": group.get("fund_strategy", ""),
                "fund_strategy_sources": group.get("fund_strategy_sources", ""),
                "fund_strategy_evidence": group.get("fund_strategy_evidence", ""),
                "row_source_evidence": group.get("row_source_evidence", ""),
                "source_field_summary": group.get("source_field_summary", ""),
            },
            "prior_spot_checks": spot_checks,
            "source_evidence": [_source_evidence_for_row(row) for row in representatives],
        }
        target = bundle_dir / f"{group_id}.json"
        with target.open("w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, sort_keys=True)
            f.write("\n")
        manifest.append({"group_id": group_id, "bundle_path": display_path(target), "bundle_sha256": sha256_file(target)})
    write_csv_rows(output_dir / "bundle_manifest.csv", manifest, ["group_id", "bundle_path", "bundle_sha256"])
    return manifest


def load_verdict_schema(schema_file: Path = SCHEMA_FILE) -> dict[str, Any]:
    with schema_file.open(encoding="utf-8") as f:
        return json.load(f)


def validate_verdict_file(verdict_file: Path, output_dir: Path = REVIEW_DIR, schema_file: Path = SCHEMA_FILE) -> list[str]:
    errors: list[str] = []
    schema = load_verdict_schema(schema_file)
    try:
        with verdict_file.open(encoding="utf-8") as f:
            verdict = json.load(f)
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON: {exc}"]

    try:
        jsonschema.Draft202012Validator(schema).validate(verdict)
    except jsonschema.ValidationError as exc:
        errors.append(f"Schema validation failed: {exc.message}")

    group_id = verdict.get("group_id", "")
    bundle_path = output_dir / "bundles" / f"{group_id}.json"
    if not bundle_path.exists():
        errors.append(f"Missing evidence bundle for group_id: {group_id}")
    if verdict.get("verdict") == "CONFIRMED_RULE_GAP":
        if not verdict.get("evidence_refs"):
            errors.append("CONFIRMED_RULE_GAP requires at least one evidence_refs entry")
        if verdict.get("recommended_next_action") not in {"GLOBAL_DETERMINISTIC_RULE", "PER_CIK_CONFIG", "MANUAL_REVIEW"}:
            errors.append("CONFIRMED_RULE_GAP requires a corrective recommended_next_action")
        notes = normalize_text(verdict.get("reviewer_notes"))
        if "source" not in notes.lower() and "evidence" not in notes.lower():
            errors.append("CONFIRMED_RULE_GAP reviewer_notes must describe positive source evidence")
    if verdict.get("verdict") == "ALREADY_CLASSIFIED_CONSISTENTLY":
        if verdict.get("recommended_next_action") != "NO_ACTION":
            errors.append("ALREADY_CLASSIFIED_CONSISTENTLY requires NO_ACTION")
    return errors


def validate_all_verdicts(output_dir: Path = REVIEW_DIR, schema_file: Path = SCHEMA_FILE) -> list[dict[str, str]]:
    verdict_dir = output_dir / "verdicts"
    errors: list[dict[str, str]] = []
    if not verdict_dir.exists():
        return [{"verdict_file": "", "error": f"Missing verdict directory: {verdict_dir}"}]
    verdict_paths = sorted(verdict_dir.glob("*.json"))
    worklist_path = output_dir / "grouped_worklist.csv"
    expected_ids: set[str] = set()
    if worklist_path.exists():
        expected_ids = {row.get("group_id", "") for row in read_csv_rows(worklist_path) if row.get("group_id", "")}
    seen_ids: set[str] = set()
    for path in verdict_paths:
        try:
            with path.open(encoding="utf-8") as f:
                verdict = json.load(f)
            group_id = normalize_text(verdict.get("group_id"))
            if group_id in seen_ids:
                errors.append({"verdict_file": display_path(path), "error": f"Duplicate verdict for group_id: {group_id}"})
            if group_id:
                seen_ids.add(group_id)
            if expected_ids and group_id not in expected_ids:
                errors.append({"verdict_file": display_path(path), "error": f"Verdict group_id is not in worklist: {group_id}"})
        except json.JSONDecodeError:
            pass
        for error in validate_verdict_file(path, output_dir, schema_file):
            errors.append({"verdict_file": display_path(path), "error": error})
    if expected_ids:
        missing = sorted(expected_ids - seen_ids)
        for group_id in missing:
            errors.append({"verdict_file": "", "error": f"Missing verdict for group_id: {group_id}"})
    return errors


def summarize_verdicts(output_dir: Path = REVIEW_DIR, schema_file: Path = SCHEMA_FILE) -> dict[str, Any]:
    validation_errors = validate_all_verdicts(output_dir, schema_file)
    if validation_errors:
        write_csv_rows(output_dir / "verdict_validation_errors.csv", validation_errors, ["verdict_file", "error"])
        raise FundStrategyReviewError(f"Verdict validation failed with {len(validation_errors)} error(s)")

    worklist = read_csv_rows(output_dir / "grouped_worklist.csv")
    by_group = {row["group_id"]: row for row in worklist}
    verdict_rows: list[dict[str, Any]] = []
    verdict_dir = output_dir / "verdicts"
    for path in sorted(verdict_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            verdict = json.load(f)
        group = by_group.get(verdict["group_id"])
        if not group:
            raise FundStrategyReviewError(f"Verdict references group outside worklist: {verdict['group_id']}")
        verdict_rows.append(
            {
                "group_id": verdict["group_id"],
                "verdict": verdict["verdict"],
                "confidence": verdict["confidence"],
                "mechanism": verdict["mechanism"],
                "recommended_next_action": verdict["recommended_next_action"],
                "affected_fair_value": group.get("affected_fair_value", "0"),
                "row_count": group.get("row_count", "0"),
                "rule_id": group.get("rule_id", ""),
                "fund_strategy": group.get("fund_strategy", ""),
                "current_index_classification": group.get("current_index_classification", ""),
                "proposed_index_classification": group.get("proposed_index_classification", ""),
                "reviewer_notes": verdict.get("reviewer_notes", ""),
            }
        )

    write_csv_rows(output_dir / "summary.csv", verdict_rows, [
        "group_id",
        "verdict",
        "confidence",
        "mechanism",
        "recommended_next_action",
        "affected_fair_value",
        "row_count",
        "rule_id",
        "fund_strategy",
        "current_index_classification",
        "proposed_index_classification",
        "reviewer_notes",
    ])

    counts = Counter(row["verdict"] for row in verdict_rows)
    fv_by_verdict: dict[str, float] = defaultdict(float)
    for row in verdict_rows:
        fv_by_verdict[row["verdict"]] += parse_float(row["affected_fair_value"])
    themes = Counter(
        (row["rule_id"], row["mechanism"], row["recommended_next_action"])
        for row in verdict_rows
        if row["verdict"] == "CONFIRMED_RULE_GAP"
    )
    unresolved_fv = sum(
        parse_float(row["affected_fair_value"])
        for row in verdict_rows
        if row["verdict"] in {"SOURCE_CONFLICT", "INSUFFICIENT_EVIDENCE"}
    )
    summary_md = [
        "# Fund Strategy Group Review Summary",
        "",
        f"Generated: {now_iso()}",
        f"Verdicts reviewed: {len(verdict_rows)}",
        "",
        "## Verdict Counts",
        "",
    ]
    for verdict, count in sorted(counts.items()):
        summary_md.append(f"- {verdict}: {count} groups, FV ${fv_by_verdict[verdict]:,.0f}")
    summary_md.extend(["", "## Top Confirmed Themes", ""])
    for (rule_id, mechanism, action), count in themes.most_common(20):
        fv = sum(
            parse_float(row["affected_fair_value"])
            for row in verdict_rows
            if row["verdict"] == "CONFIRMED_RULE_GAP"
            and row["rule_id"] == rule_id
            and row["mechanism"] == mechanism
            and row["recommended_next_action"] == action
        )
        summary_md.append(f"- {rule_id} / {mechanism} / {action}: {count} groups, FV ${fv:,.0f}")
    summary_md.extend(["", "## Recommended Correction Backlog", ""])
    for row in verdict_rows:
        if row["verdict"] == "CONFIRMED_RULE_GAP":
            summary_md.append(
                f"- {row['group_id']}: {row['recommended_next_action']} ({row['rule_id']}, FV ${parse_float(row['affected_fair_value']):,.0f})"
            )
    summary_md.extend(["", "## Unresolved FV", "", f"- SOURCE_CONFLICT or INSUFFICIENT_EVIDENCE FV: ${unresolved_fv:,.0f}"])
    (output_dir / "summary.md").write_text("\n".join(summary_md) + "\n", encoding="utf-8")
    return {"verdict_count": len(verdict_rows), "counts": dict(counts), "fv_by_verdict": dict(fv_by_verdict), "unresolved_fv": unresolved_fv}


def cli_build_worklist(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build grouped fund-strategy review worklist.")
    parser.add_argument("--input-file", type=Path, default=INPUT_FILE)
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--top-n", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args(argv)
    stats = build_grouped_worklist(args.input_file, args.output_dir, args.top_n, args.batch_size)
    print(json.dumps(stats, indent=2, sort_keys=True))
    return 0


def cli_build_bundles(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build evidence bundles for grouped fund-strategy review.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    args = parser.parse_args(argv)
    manifest = build_evidence_bundles(args.output_dir)
    print(json.dumps({"bundle_count": len(manifest)}, indent=2, sort_keys=True))
    return 0


def cli_validate_verdicts(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate grouped fund-strategy verdict JSON files.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--schema-file", type=Path, default=SCHEMA_FILE)
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
    parser = argparse.ArgumentParser(description="Summarize grouped fund-strategy verdict JSON files.")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_DIR)
    parser.add_argument("--schema-file", type=Path, default=SCHEMA_FILE)
    args = parser.parse_args(argv)
    summary = summarize_verdicts(args.output_dir, args.schema_file)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0
