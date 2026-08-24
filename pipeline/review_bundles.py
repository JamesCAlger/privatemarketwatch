"""Per-engine evidence bundles for the unified review queue.

The unified review queue (``pipeline.review_queue``) is engine-agnostic: it lists
every flagged (cik, period, rule) item across all 15 validation engines. To send
those to (agentic) review each item needs the EVIDENCE that produced its flag --
which differs per engine. This module owns that mapping.

For each engine it knows the source artifact and how to key into it, so a bundle
carries: the flag (the queue item), the matching rows from the engine's own
source artifact (the closest available raw evidence), and -- for fund-quarter
localizable items -- a slice of the unified holdings for that (cik, report_date).
``evidence_completeness`` records whether real source evidence was attached, so a
bundle is never silently empty.

``source_recon`` is intentionally NOT handled here: it already has the richer
bdc_cik_review bundle path (raw HTML schedule-of-investments evidence, the v3
guardrail). Run that for the blocker/source lane and this for everything else.

Read-only on production artifacts; writes only under the chosen output dir.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import duckdb

from pipeline import config
from pipeline.bdc_cik_review import (
    BdcCikReviewError,
    _artifact,
    display_path,
    ensure_dir,
    normalize_cik,
    normalize_text,
    now_iso,
    read_csv_rows,
    sha256_file,
    write_csv_rows,
)

logger = logging.getLogger(__name__)

REVIEW_QUEUE_DIR = config.OUTPUT_DIR / "review_queue"
NONACCRUAL_FLAGS_FILE = config.OUTPUT_DIR / "nonaccrual_flags.csv"
SHADOW_DIR = config.OUTPUT_DIR / "shadow"
HOLDINGS_FILE = config.OUTPUT_DIR / "private_markets_holdings.csv"

MANIFEST_COLUMNS = ["review_id", "engine", "lane", "evidence_completeness", "bundle_path", "bundle_sha256"]

ALLOWED_PATCH_SCOPE = [
    "pipeline source, parser, normalization, classification, or audited config files when source evidence supports the finding",
    "tests covering the exact finding and at least one false-positive case when adding filters or rules",
]
PROHIBITED_PATCH_SCOPE = [
    "generated data/output CSV edits",
    "frontend/public/data JSON edits",
    "validation suppression without an independent source-anchored mechanism",
    "moving a flag to FALSE_POSITIVE without an independent anchor or human spot-audit",
]
REQUIRED_VALIDATION_COMMANDS = [
    "pytest <tests covering the changed rule/parser>",
    "python -m pipeline.main --unified --validate  (when holdings logic changes)",
]


def _ck(item: dict[str, str]) -> str:
    """The CIK for an item -- from `cik` (localizable rows) or `unit_label`."""
    return normalize_cik(item.get("cik") or item.get("unit_label"))


_nt = normalize_text


@dataclass(frozen=True)
class EvidenceSpec:
    engine: str
    artifact: Path
    art_key: Callable[[dict[str, str]], tuple]
    item_key: Callable[[dict[str, str]], tuple]
    label: str


# engine -> how to pull its own source evidence. source_recon is deliberately
# absent (handled by bdc_cik_review). Keys mirror scripts/shadow_adapter.py.
EVIDENCE_SPECS: dict[str, EvidenceSpec] = {
    "row_validation": EvidenceSpec(
        "row_validation", config.ROW_VALIDATION_ISSUES_FILE,
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date")), _nt(r.get("rule_id"))),
        lambda it: (_ck(it), _nt(it.get("report_date")), _nt(it.get("rule_name"))),
        "validate_holdings row-level issues for this CIK/quarter/rule.",
    ),
    "fund_financials": EvidenceSpec(
        "fund_financials", config.FUND_FINANCIALS_VALIDATION_CURRENT_FILE,
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date") or r.get("report_quarter")), _nt(r.get("check_code"))),
        lambda it: (_ck(it), _nt(it.get("report_date") or it.get("period")), _nt(it.get("rule_name"))),
        "Fund-financials validation check rows (value vs expected).",
    ),
    "html_extract": EvidenceSpec(
        "html_extract", config.HTML_TEMPLATE_VALIDATION_FILE,
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date"))),
        lambda it: (_ck(it), _nt(it.get("report_date"))),
        "HTML-extraction reconciliation row (extracted FV vs companyfacts; carry).",
    ),
    "gav_recon": EvidenceSpec(
        "gav_recon", config.HOLDINGS_GAV_RECONCILIATION_FILE,
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date"))),
        lambda it: (_ck(it), _nt(it.get("report_date"))),
        "Holdings GAV reconciliation row (ratios, scope, flag).",
    ),
    "fund_strategy": EvidenceSpec(
        "fund_strategy", config.FUND_STRATEGY_VALIDATION_FILE,
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date"))),
        lambda it: (_ck(it), _nt(it.get("report_date"))),
        "Fund strategy-vs-mix validation row (declared vs observed).",
    ),
    "nonaccrual": EvidenceSpec(
        "nonaccrual", NONACCRUAL_FLAGS_FILE,
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date"))),
        lambda it: (_ck(it), _nt(it.get("report_date"))),
        "Non-accrual flagged positions for this CIK/quarter.",
    ),
    "derivative_role": EvidenceSpec(
        "derivative_role", config.DERIVATIVE_ROLE_REVIEW_FILE,
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date")), _nt(r.get("mechanism"))),
        lambda it: (_ck(it), _nt(it.get("report_date")), _nt(it.get("mechanism"))),
        "Uncertain derivative-role rows (net FV, notional, evidence).",
    ),
    "identity": EvidenceSpec(
        "identity", SHADOW_DIR / "identity_gate_violations.csv",
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date")), _nt(r.get("rule_name"))),
        lambda it: (_ck(it), _nt(it.get("report_date")), _nt(it.get("rule_name"))),
        "Per-row algebraic identity violations (row_id, residual).",
    ),
    "conservation": EvidenceSpec(
        "conservation", SHADOW_DIR / "conservation_gate_results.csv",
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date")), _nt(r.get("rule_name"))),
        lambda it: (_ck(it), _nt(it.get("report_date")), _nt(it.get("rule_name"))),
        "Conservation residual row (value_sum vs anchor, residual_pct).",
    ),
    "weak": EvidenceSpec(
        "weak", SHADOW_DIR / "weak_gate_results.csv",
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date")), _nt(r.get("rule_name"))),
        lambda it: (_ck(it), _nt(it.get("report_date")), _nt(it.get("rule_name"))),
        "Weak-engine gate result (metric, n_violate).",
    ),
    "cross_source": EvidenceSpec(
        "cross_source", SHADOW_DIR / "cross_source_gate_results.csv",
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_quarter")), _nt(r.get("rule_name"))),
        lambda it: (_ck(it), _nt(it.get("period")), _nt(it.get("rule_name"))),
        "Cross-source comparison row (left vs right value, pct_diff).",
    ),
    "aggregate_header": EvidenceSpec(
        "aggregate_header", config.AGGREGATE_HEADER_FLAGS_FILE,
        lambda r: (_nt(r.get("name_norm")), _nt(r.get("verdict"))),
        lambda it: (_nt(it.get("unit_label")), _nt(it.get("rule_name"))),
        "Reviewed aggregate/JV-header verdict for this issuer name.",
    ),
    "classification": EvidenceSpec(
        "classification", config.CLASSIFICATION_VALIDATION_FILE,
        lambda r: (_nt(r.get("rule")),),
        lambda it: (_nt(it.get("rule_name")),),
        "Classification cross-reference rule (disagreement detail).",
    ),
    "validation_rules": EvidenceSpec(
        "validation_rules", config.VALIDATION_RULES_AGGREGATE_FILE,
        lambda r: (_nt(r.get("rule_id")),),
        lambda it: (_nt(it.get("rule_name")),),
        "validation_rules aggregate rule (hit_rate, affected outputs).",
    ),
    "oracle": EvidenceSpec(
        "oracle", config.ORACLE_CHECK_RESULTS_FILE,
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date")), _nt(r.get("check_id"))),
        lambda it: (_ck(it), _nt(it.get("report_date")), _nt(it.get("rule_name"))),
        "Oracle check result for this CIK/quarter/check.",
    ),
    # Added 2026-07-25: the agentA engine joined the queue 2026-06-28 but never got a
    # spec here, so every agentA bundle was ledger_only and B1 preflight
    # short-circuited it (50 items in the q4t3 fleet). Flag rows carry the grammar
    # metrics + identifier; the evidence CLI resolves the covering filing via the
    # filings-index fallback (rows have no accession field).
    "agentA": EvidenceSpec(
        "agentA", SHADOW_DIR / "agent_a_flags.csv",
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date")), _nt(r.get("rule_name"))),
        lambda it: (_ck(it), _nt(it.get("report_date")), _nt(it.get("rule_name"))),
        "Agent A identifier-grammar flag rows (metric, mechanism, identifier).",
    ),
    # Added 2026-08-24: provenance re-verify engine (shadow ledger Task 1).
    # The ledger is ~676MB so _index_artifact (streaming full-file read) is
    # forbidden here.  build_review_bundles detects this engine key and calls
    # _index_provenance_ledger (DuckDB filtered read) instead.
    "provenance_reverify": EvidenceSpec(
        "provenance_reverify", config.PROVENANCE_LEDGER_FILE,
        lambda r: (normalize_cik(r.get("cik")), _nt(r.get("report_date")), _nt(r.get("reason_code"))),
        lambda it: (_ck(it), _nt(it.get("report_date")), _nt(it.get("rule_name"))),
        "Provenance ledger rows matching this CIK/quarter/reason_code (field, declared_raw, instance_raw, published).",
    ),
}

DEFERRED_ENGINES = {"source_recon"}


def _ev(evidence_id: str, description: str, data: Any) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "description": description, "data": data}


def _index_artifact(
    spec: EvidenceSpec,
    targets: set[tuple],
    cap: int,
) -> dict[tuple, list[dict[str, str]]]:
    idx: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    if not spec.artifact.exists() or not targets:
        return idx
    with spec.artifact.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                key = spec.art_key(row)
            except Exception:  # malformed row -- skip, never crash the run
                continue
            if key not in targets:
                continue
            if len(idx[key]) < cap:
                idx[key].append(row)
    return idx


_PROVENANCE_KEEP_COLS = ("row_id", "cik", "report_date", "reason_code", "field",
                         "declared_raw", "instance_raw", "published")
_PROVENANCE_ENGINE = "provenance_reverify"


def _build_provenance_sql(
    targets: set[tuple],
    cap: int,
) -> tuple[str, list]:
    """Build a parameterized DuckDB SQL string + params list for the provenance ledger.

    Uses ? placeholders for all cik/report_date/reason_code values and a QUALIFY
    ROW_NUMBER() clause to enforce the per-target row cap at the SQL level (not in
    Python).  Returns (sql, params) so callers can unit-test the SQL shape and
    call duckdb.execute(sql, params).

    targets: set of (norm_cik, norm_report_date, norm_reason_code) tuples.
    cap: maximum rows per (cik, report_date, reason_code) group.
    """
    # Cast date-typed columns to VARCHAR so str() gives "2026-03-31" not
    # "2026-03-31 00:00:00" when DuckDB auto-infers a DATE column.
    _date_cols = {"report_date"}
    col_exprs = ", ".join(
        f'CAST("{c}" AS VARCHAR) AS "{c}"' if c in _date_cols else f'"{c}"'
        for c in _PROVENANCE_KEEP_COLS
    )
    # Build WHERE using ? placeholders -- values are bound via params, not interpolated.
    where_parts = []
    params: list = []
    for cik, report_date, reason_code in targets:
        where_parts.append(
            "(LPAD(CAST(cik AS VARCHAR), 10, '0') = ?"
            " AND CAST(report_date AS VARCHAR) = ?"
            " AND CAST(reason_code AS VARCHAR) = ?)"
        )
        params.extend([cik, report_date, reason_code])
    where_clause = " OR ".join(where_parts)
    # QUALIFY enforces per-target cap at SQL level -- DuckDB supports QUALIFY natively.
    sql = (
        f"SELECT {col_exprs}"
        f" FROM __LEDGER__"
        f" WHERE {where_clause}"
        f" QUALIFY ROW_NUMBER() OVER"
        f" (PARTITION BY LPAD(CAST(cik AS VARCHAR), 10, '0'),"
        f" CAST(report_date AS VARCHAR), CAST(reason_code AS VARCHAR)"
        f" ORDER BY row_id) <= ?"
    )
    params.append(cap)
    return sql, params


def _index_provenance_ledger(
    targets: set[tuple],
    cap: int,
) -> dict[tuple, list[dict[str, str]]]:
    """DuckDB filtered read of the provenance ledger (avoids streaming 676MB).

    targets: set of (norm_cik, norm_report_date, norm_reason_code) tuples.
    Returns a dict keyed the same way as _index_artifact.
    """
    # Read config.PROVENANCE_LEDGER_FILE at call time so monkeypatching works in tests.
    ledger_file: Path = config.PROVENANCE_LEDGER_FILE
    idx: dict[tuple, list[dict[str, str]]] = defaultdict(list)
    if not ledger_file.exists() or not targets:
        return idx
    sql_template, params = _build_provenance_sql(targets, cap)
    ledger_path = str(ledger_file).replace("\\", "/")
    # Substitute the __LEDGER__ placeholder with the actual file path (path is local
    # filesystem, not user input, so this f-string substitution is safe).
    sql = sql_template.replace("__LEDGER__", f"read_csv_auto('{ledger_path}', header=true)")
    try:
        rows_df = duckdb.execute(sql, params).fetchdf()
    except Exception as exc:
        logger.warning("provenance ledger DuckDB read failed: %s", exc)
        return idx
    for _, row in rows_df.iterrows():
        row_d = {c: str(row[c]) if c in row.index else "" for c in _PROVENANCE_KEEP_COLS}
        key = (
            normalize_cik(row_d.get("cik")),
            _nt(row_d.get("report_date")),
            _nt(row_d.get("reason_code")),
        )
        if key in targets:
            idx[key].append(row_d)
    return idx


def _index_holdings(pairs: set[tuple[str, str]], cap: int) -> dict[tuple[str, str], list[dict[str, str]]]:
    idx: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    if not HOLDINGS_FILE.exists() or not pairs:
        return idx
    keep_cols = (
        "issuer_name", "investment_identifier", "bdc_investment_identifier",
        "fair_value", "cost", "interest_rate", "maturity_date",
        "index_classification", "asset_class", "source", "accession_number",
    )
    with HOLDINGS_FILE.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pair = (normalize_cik(row.get("cik")), _nt(row.get("report_date")))
            if pair not in pairs or len(idx[pair]) >= cap:
                continue
            idx[pair].append({c: row.get(c, "") for c in keep_cols if c in row})
    return idx


def _load_queue(
    queue_path: Path,
    *,
    lane: str | None,
    engines: set[str] | None,
    review_ids: set[str] | None,
    limit: int | None,
) -> list[dict[str, str]]:
    rows = read_csv_rows(queue_path)
    selected = []
    for r in rows:
        if lane and _nt(r.get("lane")) != lane:
            continue
        eng = _nt(r.get("engine"))
        if engines and eng not in engines:
            continue
        if review_ids and _nt(r.get("review_id")) not in review_ids:
            continue
        if eng in DEFERRED_ENGINES and not (engines and eng in engines):
            # source_recon is bundled by bdc_cik_review; skip unless explicitly asked.
            continue
        selected.append(r)
    # queue is already priority-ordered; honor it.
    if limit is not None:
        selected = selected[:limit]
    return selected


def build_review_bundles(
    *,
    queue_path: Path | None = None,
    output_dir: Path | None = None,
    lane: str | None = None,
    engines: set[str] | None = None,
    review_ids: set[str] | None = None,
    limit: int | None = None,
    max_rows: int = 25,
    attach_holdings: bool = True,
    overwrite: bool = True,
) -> dict[str, Any]:
    if queue_path is None:
        queue_path = REVIEW_QUEUE_DIR / "review_queue.csv"
    if output_dir is None:
        output_dir = REVIEW_QUEUE_DIR
    if not queue_path.exists():
        raise BdcCikReviewError(f"Missing review queue: {queue_path} (run pipeline.review_queue first)")

    items = _load_queue(queue_path, lane=lane, engines=engines, review_ids=review_ids, limit=limit)
    bundle_dir = output_dir / "review_bundles"
    ensure_dir(bundle_dir)

    # Index each engine's source artifact once, scoped to the selected items.
    by_engine: dict[str, list[dict[str, str]]] = defaultdict(list)
    for it in items:
        by_engine[_nt(it.get("engine"))].append(it)

    engine_idx: dict[str, dict[tuple, list[dict[str, str]]]] = {}
    artifact_hashes: dict[str, dict[str, str]] = {}
    for eng, eng_items in by_engine.items():
        spec = EVIDENCE_SPECS.get(eng)
        if spec is None:
            continue
        targets = {spec.item_key(it) for it in eng_items}
        if eng == _PROVENANCE_ENGINE:
            # 676MB ledger -- use DuckDB filtered read instead of full streaming scan.
            engine_idx[eng] = _index_provenance_ledger(targets, max_rows)
            eff_art = config.PROVENANCE_LEDGER_FILE
        else:
            engine_idx[eng] = _index_artifact(spec, targets, max_rows)
            eff_art = spec.artifact
        if eff_art.exists():
            artifact_hashes[str(eff_art)] = _artifact(eff_art)

    holdings_idx: dict[tuple[str, str], list[dict[str, str]]] = {}
    if attach_holdings:
        pairs = {(_ck(it), _nt(it.get("report_date"))) for it in items if _ck(it) and _nt(it.get("report_date"))}
        holdings_idx = _index_holdings(pairs, max_rows)
        if HOLDINGS_FILE.exists() and pairs:
            artifact_hashes[str(HOLDINGS_FILE)] = _artifact(HOLDINGS_FILE)

    manifest: list[dict[str, Any]] = []
    completeness_counts: dict[str, int] = defaultdict(int)
    for it in items:
        review_id = _nt(it.get("review_id"))
        engine = _nt(it.get("engine"))
        target = bundle_dir / f"{review_id}.json"

        spec = EVIDENCE_SPECS.get(engine)
        artifact_rows: list[dict[str, str]] = []
        if spec is not None:
            artifact_rows = engine_idx.get(engine, {}).get(spec.item_key(it), [])

        # For provenance_reverify the ledger path is resolved at call time via
        # config (supports monkeypatching in tests and future path changes).
        _eff_artifact = (
            config.PROVENANCE_LEDGER_FILE if engine == _PROVENANCE_ENGINE and spec is not None
            else (spec.artifact if spec is not None else None)
        )
        if spec is None:
            completeness = "ledger_only"
        elif not _eff_artifact.exists():
            completeness = "artifact_missing"
        elif artifact_rows:
            completeness = "source_artifact"
        else:
            completeness = "no_matching_rows"
        completeness_counts[completeness] += 1

        if target.exists() and not overwrite:
            manifest.append(_manifest_row(it, target, completeness))
            continue

        holdings_rows = holdings_idx.get((_ck(it), _nt(it.get("report_date"))), [])

        evidence_items = [
            _ev("flag", "The queue item (the flag being reviewed), derived from the shadow ledger.", it),
        ]
        if spec is not None:
            evidence_items.append(_ev("source_artifact_rows", spec.label, artifact_rows))
        if holdings_rows:
            evidence_items.append(
                _ev("holdings_slice", "Sample unified holdings rows for this CIK/quarter (position context).", holdings_rows)
            )

        bundle = {
            "schema_version": "review-bundle.v1",
            "created_at": now_iso(),
            "review_id": review_id,
            "lane": _nt(it.get("lane")),
            "anchor": _nt(it.get("anchor")),
            "engine": engine,
            "rule_name": _nt(it.get("rule_name")),
            "mechanism": _nt(it.get("mechanism")),
            "cik": _nt(it.get("cik")),
            "report_date": _nt(it.get("report_date")),
            "period": _nt(it.get("period")),
            "unit_label": _nt(it.get("unit_label")),
            "evidence_completeness": completeness,
            "has_raw_source": bool(artifact_rows or holdings_rows),
            "artifact_hashes": list(artifact_hashes.values()),
            "evidence_items": evidence_items,
            "allowed_patch_scope": ALLOWED_PATCH_SCOPE,
            "prohibited_patch_scope": PROHIBITED_PATCH_SCOPE,
            "required_validation_commands": REQUIRED_VALIDATION_COMMANDS,
        }
        target.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manifest.append(_manifest_row(it, target, completeness))

    write_csv_rows(output_dir / "review_bundle_manifest.csv", manifest, MANIFEST_COLUMNS)
    result = {
        "items": len(items),
        "bundles": len(manifest),
        "completeness": dict(completeness_counts),
        "bundle_dir": str(bundle_dir),
    }
    return result


def _manifest_row(item: dict[str, str], target: Path, completeness: str) -> dict[str, Any]:
    return {
        "review_id": _nt(item.get("review_id")),
        "engine": _nt(item.get("engine")),
        "lane": _nt(item.get("lane")),
        "evidence_completeness": completeness,
        "bundle_path": display_path(target),
        "bundle_sha256": sha256_file(target) if target.exists() else "",
    }


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build per-engine evidence bundles for the unified review queue.")
    parser.add_argument("--queue", type=Path, default=REVIEW_QUEUE_DIR / "review_queue.csv")
    parser.add_argument("--output-dir", type=Path, default=REVIEW_QUEUE_DIR)
    parser.add_argument("--lane", choices=["blocker", "review"], default=None)
    parser.add_argument("--engine", action="append", default=None, help="Restrict to engine(s); repeatable.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-rows", type=int, default=25)
    parser.add_argument("--no-holdings", action="store_true", help="Do not attach the unified holdings slice.")
    args = parser.parse_args(argv)

    result = build_review_bundles(
        queue_path=args.queue,
        output_dir=args.output_dir,
        lane=args.lane,
        engines=set(args.engine) if args.engine else None,
        limit=args.limit,
        max_rows=args.max_rows,
        attach_holdings=not args.no_holdings,
    )
    logger.info("review bundles: %d built in %s", result["bundles"], result["bundle_dir"])
    logger.info("evidence completeness: %s", result["completeness"])
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(cli())
