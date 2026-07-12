"""Unified review queue derived from the shadow validation ledger.

The shadow ledger (``data/output/shadow/validation_results_ledger.csv``) is the
union of every validation engine. This module turns that single ledger into ONE
prioritized review queue -- the "single set of all blockers + strong rules (as
blockers) + weak rules (for review)" -- by tagging each actionable (fail/warn)
row with a ``lane``:

  blocker : tier='tight'  -- a strong / source-anchored check failed; gate-eligible.
  review  : tier='weak'   -- a weak / heuristic check; route to (agentic) review.

It does NOT re-run any engine. Read-only on production artifacts: it reads the
ledger and writes only under ``data/output/review_queue/``.

review_id compatibility: for ``source_recon`` items the review_id is computed
with ``bdc_cik_review.make_review_id(cik, report_date, mechanism)`` so the
blocker lane joins cleanly to the existing bdc_cik_review worklist, bundles, and
verdicts. The blocker/source lane can be projected to the bdc worklist schema
(``bdc_worklist_projection``) so the existing bundle builder consumes the
ledger-derived queue without modification.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Any

from pipeline import config
from pipeline.bdc_cik_review import (
    BdcCikReviewError,
    ensure_dir,
    make_review_id,
    normalize_cik,
    normalize_text,
    parse_float,
    read_csv_rows,
    short_hash,
    write_csv_rows,
)

logger = logging.getLogger(__name__)

LEDGER_FILE = config.OUTPUT_DIR / "shadow" / "validation_results_ledger.csv"
REVIEW_QUEUE_DIR = config.OUTPUT_DIR / "review_queue"

# Metric names whose value is a fair-value-at-risk figure (in USD millions).
# All other engines carry rate/count metrics that are not directly comparable.
FV_METRIC_NAMES = {"affected_fv_m", "total_fv_m", "uncertain_deriv_fv_m"}

_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

REVIEW_QUEUE_COLUMNS = [
    "priority_rank",
    "review_id",
    "lane",
    "anchor",
    "engine",
    "rule_name",
    "tier",
    "enforcement",
    "cik",
    "report_date",
    "period",
    "period_kind",
    "unit_label",
    "status",
    "mechanism",
    "confidence",
    "src_confidence",
    "surface",
    "n_units",
    "metric_name",
    "metric",
    "fv_at_risk_m",
    "fund_quarter_fv_m",
]

REVIEW_QUEUE_SUMMARY_COLUMNS = [
    "lane",
    "anchor",
    "engine",
    "items",
    "fv_at_risk_m",
    "n_units",
]

# Projection of the blocker/source lane into the bdc_cik_review worklist schema.
# build_bundles only consumes review_id/cik/report_date/mechanism from a worklist
# row (it re-fetches all detail from the residual artifacts by that key), so the
# projection carries those plus a few display fields.
BDC_WORKLIST_PROJECTION_COLUMNS = [
    "review_id",
    "cik",
    "entity_name",
    "report_date",
    "mechanism",
    "affected_source_fair_value",
    "confidence",
]


def default_holdings_path() -> Path | None:
    """Production unified holdings, preferring parquet. None if neither exists."""
    if config.UNIFIED_HOLDINGS_PARQUET_FILE.exists():
        return config.UNIFIED_HOLDINGS_PARQUET_FILE
    if config.UNIFIED_HOLDINGS_FILE.exists():
        return config.UNIFIED_HOLDINGS_FILE
    return None


def _load_fund_quarter_fv(holdings_path: Path) -> dict[tuple[str, str], float]:
    """(cik10, report_date) -> total fund-quarter fair value in USD millions.

    This is the EXPOSURE weight for FV-prioritizing queue items whose engine
    reports no FV metric of its own (review-lane rules count rows, not dollars).
    It is the whole fund-quarter's FV, an upper bound -- NOT the FV actually at
    risk from the specific flag; fv_at_risk_m stays the engine-declared figure.
    """
    import duckdb

    src = (
        f"read_csv_auto('{holdings_path.as_posix()}', sample_size=-1)"
        if holdings_path.suffix == ".csv"
        else f"read_parquet('{holdings_path.as_posix()}')"
    )
    rows = duckdb.connect().execute(
        f"""SELECT lpad(CAST(cik AS VARCHAR), 10, '0') AS cik,
                   CAST(report_date AS VARCHAR) AS report_date,
                   sum(TRY_CAST(fair_value AS DOUBLE)) / 1e6 AS fv_m
            FROM {src}
            WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
            GROUP BY 1, 2"""
    ).fetchall()
    return {(c, d): float(v) for c, d, v in rows if v is not None}


def _lane(tier: str) -> str:
    return "blocker" if tier == "tight" else "review"


def _anchor(engine: str, rule_name: str, confidence: str, tier: str) -> str:
    """Whether the check reconciles against an INDEPENDENT external quantity.

    A "source" anchor means the failure was measured against the source filing,
    an independent fund-level figure, or companyfacts -- not against the
    pipeline's own algebra. This is the distinction the FP-clear governance
    guard cares about (an independent anchor can refute a flag; an internal one
    cannot). Heuristic, documented; refine as engines gain explicit provenance.
    """
    if engine in {"source_recon", "gav_recon", "conservation"}:
        return "source"
    if engine == "html_extract" and rule_name == "html_agg":
        return "source"
    if engine == "fund_financials" and tier == "tight":
        return "source"
    if confidence == "row_block_verified":
        return "source"
    return "internal"


def _review_id(
    *,
    engine: str,
    lane: str,
    cik: str,
    report_date: str,
    mechanism: str,
    rule_name: str,
    period_kind: str,
    unit_label: str,
) -> str:
    # source_recon ids must match the existing bdc_cik_review worklist/verdicts.
    if engine == "source_recon" and report_date:
        return make_review_id(cik, report_date, mechanism)
    base = "|".join([engine, rule_name, unit_label, period_kind, report_date, mechanism])
    prefix = "BLK" if lane == "blocker" else "REV"
    return f"RVQ_{prefix}_{short_hash(base, 12)}"


def _queue_item(row: dict[str, str]) -> dict[str, Any] | None:
    status = normalize_text(row.get("status")).lower()
    if status not in {"fail", "warn"}:
        return None

    tier = normalize_text(row.get("tier")).lower()
    lane = _lane(tier)
    engine = normalize_text(row.get("engine"))
    rule_name = normalize_text(row.get("rule_name"))
    period_kind = normalize_text(row.get("period_kind"))
    period = normalize_text(row.get("period"))
    mechanism = normalize_text(row.get("mechanism"))
    confidence = normalize_text(row.get("confidence"))
    metric_name = normalize_text(row.get("metric_name"))

    # The ledger's `cik` column holds a 10-digit CIK for per-fund engines, but a
    # name for name-keyed engines (aggregate_header) and may be blank for global
    # ones. Preserve the raw value as unit_label; localize to a CIK + report_date
    # only when the row is genuinely fund-quarter grained.
    unit_label = normalize_text(row.get("cik"))
    localizable = bool(_DATE_RE.fullmatch(period)) and bool(re.search(r"\d", unit_label))
    cik = normalize_cik(unit_label) if localizable else ""
    report_date = period if localizable else ""

    fv_at_risk_m = parse_float(row.get("metric")) if metric_name in FV_METRIC_NAMES else None

    return {
        "review_id": _review_id(
            engine=engine,
            lane=lane,
            cik=cik,
            report_date=report_date,
            mechanism=mechanism,
            rule_name=rule_name,
            period_kind=period_kind,
            unit_label=unit_label,
        ),
        "lane": lane,
        "anchor": _anchor(engine, rule_name, confidence, tier),
        "engine": engine,
        "rule_name": rule_name,
        "tier": tier,
        "enforcement": normalize_text(row.get("enforcement")),
        "cik": cik,
        "report_date": report_date,
        "period": period,
        "period_kind": period_kind,
        "unit_label": unit_label,
        "status": status,
        "mechanism": mechanism,
        "confidence": confidence,
        "src_confidence": normalize_text(row.get("src_confidence")),
        "surface": normalize_text(row.get("surface")),
        "n_units": int(parse_float(row.get("n_units"))),
        "metric_name": metric_name,
        "metric": normalize_text(row.get("metric")),
        "fv_at_risk_m": "" if fv_at_risk_m is None else f"{fv_at_risk_m:.6f}",
        "_sort_fv": fv_at_risk_m,
        "_sort_metric_abs": abs(parse_float(row.get("metric"))),
    }


def _sort_key(item: dict[str, Any]) -> tuple:
    lane_order = 0 if item["lane"] == "blocker" else 1
    has_fv = 0 if item["_sort_fv"] is None else 1
    return (
        lane_order,
        -has_fv,
        -(item["_sort_fv"] or 0.0),
        -item["n_units"],
        -item["_sort_metric_abs"],
        item["cik"],
        item["report_date"],
        item["engine"],
        item["rule_name"],
        item["review_id"],
    )


def build_review_queue(
    *,
    ledger_path: Path = LEDGER_FILE,
    output_dir: Path = REVIEW_QUEUE_DIR,
    lanes: tuple[str, ...] = ("blocker", "review"),
    holdings_path: Path | None = None,
) -> dict[str, Any]:
    """Build the single prioritized review queue from the shadow ledger.

    ``holdings_path`` (unified holdings CSV/parquet) enables the fund-quarter FV
    join: every localizable item gets ``fund_quarter_fv_m`` (fund-quarter total
    FV, an exposure weight). None skips the join (column left empty); the CLI
    defaults it to the production holdings file.

    Returns a summary dict; writes review_queue.csv + review_queue_summary.csv.
    """
    if not ledger_path.exists():
        raise BdcCikReviewError(
            f"Missing shadow ledger: {ledger_path} "
            "(run scripts/shadow_validation_runner.py first)"
        )

    fund_fv: dict[tuple[str, str], float] = {}
    if holdings_path is not None:
        if holdings_path.exists():
            fund_fv = _load_fund_quarter_fv(holdings_path)
            logger.info("fund-quarter FV join: %d fund-quarters from %s",
                        len(fund_fv), holdings_path.name)
        else:
            logger.warning("holdings file missing, fund_quarter_fv_m left empty: %s",
                           holdings_path)

    items: list[dict[str, Any]] = []
    for row in read_csv_rows(ledger_path):
        item = _queue_item(row)
        if item is None or item["lane"] not in lanes:
            continue
        fv = fund_fv.get((item["cik"], item["report_date"]))
        item["fund_quarter_fv_m"] = "" if fv is None else f"{fv:.6f}"
        items.append(item)

    items.sort(key=_sort_key)
    for rank, item in enumerate(items, start=1):
        item["priority_rank"] = rank

    ensure_dir(output_dir)
    queue_path = output_dir / "review_queue.csv"
    write_csv_rows(queue_path, items, REVIEW_QUEUE_COLUMNS)

    summary = _summarize(items)
    summary_path = output_dir / "review_queue_summary.csv"
    write_csv_rows(summary_path, summary, REVIEW_QUEUE_SUMMARY_COLUMNS)

    result = {
        "items": len(items),
        "blocker": sum(1 for i in items if i["lane"] == "blocker"),
        "review": sum(1 for i in items if i["lane"] == "review"),
        "source_anchored": sum(1 for i in items if i["anchor"] == "source"),
        "fund_fv_weighted": sum(1 for i in items if i["fund_quarter_fv_m"]),
        "queue_path": str(queue_path),
        "summary_path": str(summary_path),
    }
    return result


def _summarize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[tuple[str, str, str], dict[str, float]] = {}
    for item in items:
        key = (item["lane"], item["anchor"], item["engine"])
        bucket = agg.setdefault(key, {"items": 0, "fv": 0.0, "n_units": 0})
        bucket["items"] += 1
        bucket["fv"] += item["_sort_fv"] or 0.0
        bucket["n_units"] += item["n_units"]
    rows = [
        {
            "lane": lane,
            "anchor": anchor,
            "engine": engine,
            "items": int(b["items"]),
            "fv_at_risk_m": f"{b['fv']:.6f}",
            "n_units": int(b["n_units"]),
        }
        for (lane, anchor, engine), b in agg.items()
    ]
    rows.sort(key=lambda r: (0 if r["lane"] == "blocker" else 1, -float(r["fv_at_risk_m"]), -r["items"]))
    return rows


def bdc_worklist_projection(
    *,
    queue_path: Path | None = None,
    items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Project the blocker/source lane (source_recon) to the bdc worklist schema.

    Lets the existing bdc_cik_review.build_bundles consume the ledger-derived
    queue: point build_bundles at a dir whose worklist.csv is this projection.
    """
    if items is None:
        if queue_path is None:
            queue_path = REVIEW_QUEUE_DIR / "review_queue.csv"
        items = read_csv_rows(queue_path)
    projection: list[dict[str, Any]] = []
    for item in items:
        if normalize_text(item.get("engine")) != "source_recon":
            continue
        fv_m = parse_float(item.get("fv_at_risk_m"))
        projection.append(
            {
                "review_id": normalize_text(item.get("review_id")),
                "cik": normalize_cik(item.get("cik")),
                "entity_name": "",
                "report_date": normalize_text(item.get("report_date")),
                "mechanism": normalize_text(item.get("mechanism")),
                "affected_source_fair_value": f"{fv_m * 1_000_000:.6f}",
                "confidence": normalize_text(item.get("confidence")),
            }
        )
    return projection


def write_bdc_worklist_projection(
    *,
    queue_path: Path | None = None,
    out_path: Path | None = None,
) -> int:
    projection = bdc_worklist_projection(queue_path=queue_path)
    if out_path is None:
        out_path = REVIEW_QUEUE_DIR / "bdc_worklist.csv"
    write_csv_rows(out_path, projection, BDC_WORKLIST_PROJECTION_COLUMNS)
    return len(projection)


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the unified review queue from the shadow ledger.")
    parser.add_argument("--ledger", type=Path, default=LEDGER_FILE)
    parser.add_argument("--output-dir", type=Path, default=REVIEW_QUEUE_DIR)
    parser.add_argument(
        "--lane",
        choices=["blocker", "review", "both"],
        default="both",
        help="Restrict the queue to one lane (default: both).",
    )
    parser.add_argument(
        "--emit-bdc-worklist",
        action="store_true",
        help="Also write the blocker/source lane projected to the bdc worklist schema.",
    )
    parser.add_argument(
        "--holdings",
        type=Path,
        default=None,
        help="Unified holdings CSV/parquet for the fund-quarter FV join "
        "(default: production holdings file). Pass --no-fund-fv to skip.",
    )
    parser.add_argument(
        "--no-fund-fv",
        action="store_true",
        help="Skip the fund-quarter FV join (fund_quarter_fv_m left empty).",
    )
    args = parser.parse_args(argv)

    holdings = None if args.no_fund_fv else (args.holdings or default_holdings_path())
    lanes = ("blocker", "review") if args.lane == "both" else (args.lane,)
    result = build_review_queue(
        ledger_path=args.ledger, output_dir=args.output_dir, lanes=lanes,
        holdings_path=holdings,
    )
    logger.info(
        "review queue: %d items (blocker %d, review %d; source-anchored %d; "
        "fund-FV weighted %d)",
        result["items"],
        result["blocker"],
        result["review"],
        result["source_anchored"],
        result["fund_fv_weighted"],
    )
    logger.info("wrote %s", result["queue_path"])
    logger.info("wrote %s", result["summary_path"])
    if args.emit_bdc_worklist:
        n = write_bdc_worklist_projection(queue_path=args.output_dir / "review_queue.csv")
        logger.info("wrote bdc worklist projection: %d source_recon blocker rows", n)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(cli())
