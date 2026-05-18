"""Cache-only reconciliation for BDC non-accrual credit-risk signals.

This module validates the non-accrual slice used by ``credit_risk.json`` by
rebuilding the same BDC direct-lending denominator and reconciling flagged rows
against cached XBRL filings.  It never downloads filings.

Usage:
    python -m pipeline.validate_nonaccruals --quarter 2025q4
"""

from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
from lxml import etree

from pipeline.bdc_filings import _local_name, _parse_xbrl_contexts
from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    FUND_FINANCIALS_FILE,
    OUTPUT_DIR,
    UNIFIED_HOLDINGS_FILE,
)
from pipeline.export.helpers import CONSUMER_LENDING_EXCLUDE_CIKS
from pipeline.nonaccrual_evidence import (
    XBRL_PARSER,
    extract_nonaccrual_candidates,
    has_nonaccrual_dimension,
)

logger = logging.getLogger(__name__)

NONACCRUAL_FLAGS_FILE = OUTPUT_DIR / "nonaccrual_flags.csv"
INVESTIGATION_RESULTS_FILE = OUTPUT_DIR / "data_investigation_results.md"

PASS = "PASS_AGGREGATE"
PASS_POSITION = "PASS_POSITION_EVIDENCE"
FAIL_OVER = "FAIL_OVER_FLAGGED"
FAIL_UNDER = "FAIL_UNDER_FLAGGED"
UNDER_REVIEW = "UNDER_REVIEW_NO_TOTAL"
NO_CACHE = "NO_CACHE"

AGGREGATE_CONCEPT_HINTS = (
    "nonaccrual",
    "nonaccrualstatus",
    "nonperforming",
    "nonperformingasset",
)
FAIR_VALUE_HINTS = ("fairvalue", "value")
COST_HINTS = ("cost", "amortizedcost", "amortisedcost")


@dataclass(frozen=True)
class AggregateEvidence:
    cost: float | None = None
    fair_value: float | None = None
    source: str = ""


def _normalize_cik(cik: Any) -> str:
    text = "" if cik is None else str(cik).strip()
    digits = re.sub(r"\D", "", text)
    return digits.zfill(10) if digits else ""


def _quarter_to_dates(quarter: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}q[1-4]", quarter):
        raise ValueError(f"Invalid quarter: {quarter}")
    year = int(quarter[:4])
    qn = int(quarter[-1])
    month = qn * 3
    end_day = {3: 31, 6: 30, 9: 30, 12: 31}[month]
    return quarter, f"{year}-{month:02d}-{end_day:02d}"


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(",", "")
        if text == "" or text.lower() == "nan":
            return None
        neg = text.startswith("(") and text.endswith(")")
        text = text.strip("()").replace("$", "")
        val = float(text)
        return -val if neg else val
    except (TypeError, ValueError):
        return None


def select_cached_accession(
    holding_row: pd.Series | dict[str, Any],
    filings_index: pd.DataFrame,
) -> tuple[str, str | None]:
    """Return the exact cached XBRL path for the accession on a holdings row."""
    accession = str(holding_row.get("accession_number", "") or "").strip()
    cik = _normalize_cik(holding_row.get("cik", ""))
    if not accession or filings_index.empty:
        return accession, None

    idx = filings_index.copy()
    idx["_cik_norm"] = idx["cik"].map(_normalize_cik)
    match = idx[
        (idx["_cik_norm"] == cik)
        & (idx["accession_number"].astype(str).str.strip() == accession)
    ]
    if match.empty:
        return accession, None

    path = str(match.iloc[0].get("xbrl_local_path", "") or "").strip()
    if not path:
        return accession, None
    p = Path(path)
    if not p.exists():
        return accession, None
    return accession, str(p)


def _chart_population_sql(quarter: str) -> str:
    consumer = ", ".join(f"'{c}'" for c in sorted(CONSUMER_LENDING_EXCLUDE_CIKS))
    return f"""
    WITH raw AS (
        SELECT * FROM read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', all_varchar=true)
    ),
    dl AS (
        SELECT
            cik,
            entity_name,
            accession_number,
            filing_date,
            report_date,
            issuer_name,
            instrument_description,
            bdc_investment_identifier,
            TRY_CAST(fair_value AS DOUBLE) AS fair_value,
            TRY_CAST(cost AS DOUBLE) AS cost_value,
            CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
            || 'q'
            || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) AS report_quarter
        FROM raw
        WHERE source = 'bdc'
          AND index_classification = 'DIRECT_LENDING'
          AND TRY_CAST(fair_value AS DOUBLE) > 0
          AND report_date >= '2022-10-01'
          AND cik NOT IN ({consumer})
    ),
    ff AS (
        SELECT cik, report_quarter,
               TRY_CAST(total_assets AS DOUBLE) AS total_assets
        FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', all_varchar=true)
        WHERE TRY_CAST(total_assets AS DOUBLE) > 0
    ),
    dl_gav AS (
        SELECT cik, report_quarter, SUM(fair_value) AS dl_fv
        FROM dl
        GROUP BY cik, report_quarter
    ),
    all_positions AS (
        SELECT
            cik,
            CAST(YEAR(TRY_CAST(report_date AS DATE)) AS VARCHAR)
            || 'q'
            || CAST(QUARTER(TRY_CAST(report_date AS DATE)) AS VARCHAR) AS report_quarter,
            TRY_CAST(fair_value AS DOUBLE) AS fair_value
        FROM raw
        WHERE TRY_CAST(fair_value AS DOUBLE) > 0
          AND report_date >= '2022-10-01'
          AND cik NOT IN ({consumer})
    ),
    all_gav AS (
        SELECT cik, report_quarter, SUM(fair_value) AS all_fv
        FROM all_positions
        GROUP BY cik, report_quarter
    ),
    good_ciks AS (
        SELECT d.cik, d.report_quarter
        FROM dl_gav d
        JOIN all_gav a ON d.cik = a.cik AND d.report_quarter = a.report_quarter
        JOIN ff ON d.cik = ff.cik AND d.report_quarter = ff.report_quarter
        WHERE d.dl_fv / ff.total_assets BETWEEN 0.7 AND 1.3
           OR a.all_fv / ff.total_assets BETWEEN 0.7 AND 1.3
    ),
    na_flags AS (
        SELECT DISTINCT cik, report_date, investment_identifier, nonaccrual_source
        FROM read_csv_auto('{NONACCRUAL_FLAGS_FILE.as_posix()}', all_varchar=true)
    )
    SELECT
        dl.*,
        CASE WHEN na.cik IS NOT NULL THEN 1 ELSE 0 END AS is_nonaccrual,
        COALESCE(na.nonaccrual_source, '') AS nonaccrual_source
    FROM dl
    INNER JOIN good_ciks gc
      ON dl.cik = gc.cik AND dl.report_quarter = gc.report_quarter
    LEFT JOIN na_flags na
      ON dl.cik = na.cik
     AND dl.report_date = na.report_date
     AND dl.bdc_investment_identifier = na.investment_identifier
    WHERE dl.report_quarter = '{quarter}'
    """


def load_chart_population(quarter: str) -> pd.DataFrame:
    """Load the exact BDC DL population used by the credit-risk export."""
    if not UNIFIED_HOLDINGS_FILE.exists():
        raise FileNotFoundError(UNIFIED_HOLDINGS_FILE)
    if not FUND_FINANCIALS_FILE.exists():
        raise FileNotFoundError(FUND_FINANCIALS_FILE)
    if not NONACCRUAL_FLAGS_FILE.exists():
        raise FileNotFoundError(NONACCRUAL_FLAGS_FILE)

    con = duckdb.connect()
    try:
        return con.execute(_chart_population_sql(quarter)).fetchdf()
    finally:
        con.close()


def _structured_aggregate_evidence(
    root: etree._Element,
    contexts: dict[str, dict],
    report_date: str | None = None,
) -> AggregateEvidence:
    cost_vals: list[tuple[float, str]] = []
    fv_vals: list[tuple[float, str]] = []

    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if not ctx_ref:
            continue
        unit_ref = (elem.get("unitRef") or "").lower()
        if "usd" not in unit_ref:
            continue
        raw = (elem.text or "").strip()
        val = _num(raw)
        if val is None or val <= 1_000_000:
            continue

        local = _local_name(elem.tag).lower()
        context = contexts.get(ctx_ref, {})
        if report_date and str(context.get("period", "") or "")[:10] != report_date:
            continue
        haystack = local + " " + str(context.get("dimensions_raw", "")).lower()
        compact = re.sub(r"[^a-z0-9]", "", haystack)
        if not any(h in compact for h in AGGREGATE_CONCEPT_HINTS):
            continue
        if context.get("is_investment"):
            continue

        if any(h in compact for h in COST_HINTS):
            cost_vals.append((val, _local_name(elem.tag)))
        if any(h in compact for h in FAIR_VALUE_HINTS):
            fv_vals.append((val, _local_name(elem.tag)))

    cost = max(cost_vals, default=(None, ""))[0]
    fv = max(fv_vals, default=(None, ""))[0]
    sources = []
    if cost is not None:
        sources.append("structured_cost")
    if fv is not None:
        sources.append("structured_fair_value")
    return AggregateEvidence(cost=cost, fair_value=fv, source=";".join(sources))


def parse_xbrl_evidence(
    xml_path: str | Path,
    flagged_identifiers: set[str],
    report_date: str | None = None,
) -> tuple[pd.DataFrame, AggregateEvidence, bool]:
    """Extract position-level and aggregate non-accrual evidence from one XML."""
    path = Path(xml_path)
    tree = etree.parse(str(path), parser=XBRL_PARSER)
    root = tree.getroot()
    contexts = _parse_xbrl_contexts(tree)
    id_to_contexts: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for ctx_id, info in contexts.items():
        ident = str(info.get("investment_identifier", "") or "")
        if ident:
            id_to_contexts.setdefault(ident, []).append((ctx_id, info))

    accepted_candidates = extract_nonaccrual_candidates(
        path,
        cik="",
        report_date=report_date or "",
        accession_number="",
    )
    accepted_contexts_by_ident: dict[str, dict[str, set[str]]] = {}
    for row in accepted_candidates:
        if not row.get("accepted"):
            continue
        ident = str(row.get("investment_identifier", "") or "")
        source = str(row.get("nonaccrual_source", "") or "")
        ctx_id = str(row.get("context_id", "") or "")
        if not ident or not ctx_id:
            continue
        entry = accepted_contexts_by_ident.setdefault(
            ident,
            {"dimension": set(), "footnote": set()},
        )
        if source in entry:
            entry[source].add(ctx_id)

    rows: list[dict[str, Any]] = []
    for ident in sorted(flagged_identifiers):
        context_rows = id_to_contexts.get(ident, [])
        dimension_contexts = [
            ctx_id for ctx_id, info in context_rows
            if has_nonaccrual_dimension(info)
        ]
        accepted_for_ident = accepted_contexts_by_ident.get(
            ident,
            {"dimension": set(), "footnote": set()},
        )
        footnote_contexts = sorted(accepted_for_ident["footnote"])
        rows.append({
            "investment_identifier": ident,
            "has_position_evidence": bool(dimension_contexts or footnote_contexts),
            "dimension_evidence": bool(dimension_contexts),
            "footnote_evidence": bool(footnote_contexts),
            "context_ids": "|".join(sorted(set(dimension_contexts + footnote_contexts))),
            "evidence_detail": (
                "nonaccrual dimension"
                if dimension_contexts
                else ("nonaccrual footnote" if footnote_contexts else "")
            ),
        })

    aggregate = _structured_aggregate_evidence(root, contexts, report_date)
    has_nonaccrual_language = any(
        bool(row.get("has_position_evidence")) for row in rows
    ) or aggregate.cost is not None or aggregate.fair_value is not None
    return pd.DataFrame(rows), aggregate, has_nonaccrual_language


def _within_tolerance(flagged: float | None, disclosed: float | None) -> bool | None:
    if flagged is None or disclosed is None:
        return None
    tolerance = max(1_000_000.0, abs(disclosed) * 0.02)
    return abs(flagged - disclosed) <= tolerance


def _aggregate_reconciliation_status(
    flagged: float | None,
    disclosed: float | None,
) -> str:
    ok = _within_tolerance(flagged, disclosed)
    if ok is None:
        return "MISSING_AGGREGATE"
    if ok:
        return PASS
    if flagged is not None and disclosed is not None and flagged > disclosed:
        return FAIL_OVER
    return FAIL_UNDER


def _aggregate_variance_reason(
    *,
    fv_status: str,
    cost_status: str,
    position_evidence_complete: bool,
) -> str:
    if fv_status == PASS:
        return "current-period FV aggregate reconciles"
    if position_evidence_complete:
        return "complete current-period direct position evidence; aggregate variance retained for audit"
    if fv_status == "MISSING_AGGREGATE":
        return "current-period FV aggregate missing or not comparable"
    if fv_status == FAIL_OVER:
        return "flagged FV exceeds current-period disclosed FV"
    if fv_status == FAIL_UNDER:
        return "flagged FV is below current-period disclosed FV"
    if cost_status not in (PASS, "MISSING_AGGREGATE"):
        return "cost aggregate variance is diagnostic for FV chart"
    return "unresolved aggregate variance"


def classify_reconciliation(
    *,
    flagged_fv: float,
    flagged_cost: float,
    disclosed_fv: float | None,
    disclosed_cost: float | None,
    all_positions_evidenced: bool,
    has_nonaccrual_language: bool,
    cache_available: bool,
) -> str:
    if not cache_available:
        return NO_CACHE

    fv_ok = _within_tolerance(flagged_fv, disclosed_fv)
    if fv_ok is True:
        return PASS
    if all_positions_evidenced:
        return PASS_POSITION
    if fv_ok is False:
        if disclosed_fv is not None and flagged_fv > disclosed_fv:
            return FAIL_OVER
        return FAIL_UNDER
    if has_nonaccrual_language:
        return UNDER_REVIEW
    return UNDER_REVIEW


def run_reconciliation(quarter: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Run non-accrual reconciliation and write output artifacts."""
    quarter, report_date = _quarter_to_dates(quarter)
    population = load_chart_population(quarter)
    flagged = population[population["is_nonaccrual"] == 1].copy()

    filings_index = (
        pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
        if BDC_FILINGS_INDEX_FILE.exists()
        else pd.DataFrame()
    )

    recon_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []

    for (cik, accession), grp in flagged.groupby(["cik", "accession_number"], dropna=False):
        first = grp.iloc[0]
        accession_number, xml_path = select_cached_accession(first, filings_index)
        flagged_ids = set(grp["bdc_investment_identifier"].dropna().astype(str))
        aggregate = AggregateEvidence()
        has_lang = False
        pos_df = pd.DataFrame()

        if xml_path:
            try:
                pos_df, aggregate, has_lang = parse_xbrl_evidence(
                    xml_path,
                    flagged_ids,
                    report_date=str(first.get("report_date", "") or ""),
                )
            except Exception as exc:
                logger.warning("Evidence parse failed for %s %s: %s", cik, accession, exc)
                pos_df = pd.DataFrame()

        if not pos_df.empty:
            with_amounts = pos_df.merge(
                grp[[
                    "cik", "entity_name", "report_date", "accession_number",
                    "issuer_name", "bdc_investment_identifier", "fair_value",
                    "cost_value", "nonaccrual_source",
                ]],
                left_on="investment_identifier",
                right_on="bdc_investment_identifier",
                how="left",
            )
            evidence_rows.extend(with_amounts.to_dict("records"))

        evidenced_count = (
            int(pos_df["has_position_evidence"].sum())
            if "has_position_evidence" in pos_df.columns
            else 0
        )
        all_evidenced = len(flagged_ids) > 0 and evidenced_count == len(flagged_ids)
        flagged_fv = float(grp["fair_value"].sum())
        flagged_cost = float(grp["cost_value"].fillna(0).sum())
        aggregate_fv_status = _aggregate_reconciliation_status(
            flagged_fv,
            aggregate.fair_value,
        )
        aggregate_cost_status = _aggregate_reconciliation_status(
            flagged_cost,
            aggregate.cost,
        )
        status = classify_reconciliation(
            flagged_fv=flagged_fv,
            flagged_cost=flagged_cost,
            disclosed_fv=aggregate.fair_value,
            disclosed_cost=aggregate.cost,
            all_positions_evidenced=all_evidenced,
            has_nonaccrual_language=has_lang,
            cache_available=xml_path is not None,
        )

        recon_rows.append({
            "quarter": quarter,
            "report_date": report_date,
            "cik": cik,
            "entity_name": first.get("entity_name", ""),
            "accession_number": accession_number,
            "xbrl_local_path": xml_path or "",
            "flagged_position_count": len(grp),
            "flagged_nonaccrual_fv": flagged_fv,
            "flagged_nonaccrual_cost": flagged_cost,
            "positions_with_direct_evidence": evidenced_count,
            "disclosed_nonaccrual_fv": aggregate.fair_value,
            "disclosed_nonaccrual_cost": aggregate.cost,
            "aggregate_evidence_source": aggregate.source,
            "aggregate_fv_reconciliation_status": aggregate_fv_status,
            "aggregate_cost_reconciliation_status": aggregate_cost_status,
            "aggregate_variance_reason": _aggregate_variance_reason(
                fv_status=aggregate_fv_status,
                cost_status=aggregate_cost_status,
                position_evidence_complete=all_evidenced,
            ),
            "position_evidence_complete": all_evidenced,
            "has_nonaccrual_language": has_lang,
            "status": status,
        })

    recon = pd.DataFrame(recon_rows)
    evidence = pd.DataFrame(evidence_rows)
    out_recon = OUTPUT_DIR / f"nonaccrual_reconciliation_{quarter}.csv"
    out_evidence = OUTPUT_DIR / f"nonaccrual_position_evidence_{quarter}.csv"
    recon.to_csv(out_recon, index=False)
    evidence.to_csv(out_evidence, index=False)

    summary = summarize_chart_validation(population, flagged, recon)
    append_investigation_summary(quarter, summary, out_recon, out_evidence)
    return recon, evidence, summary


def summarize_chart_validation(
    population: pd.DataFrame,
    flagged: pd.DataFrame,
    recon: pd.DataFrame,
) -> dict[str, Any]:
    total_fv = float(population["fair_value"].sum()) if not population.empty else 0.0
    flagged_fv = float(flagged["fair_value"].sum()) if not flagged.empty else 0.0
    passing = {PASS, PASS_POSITION}

    if recon.empty or flagged_fv <= 0:
        return {
            "chart_status": "UNDER_REVIEW",
            "reason": "no flagged rows or no reconciliation rows",
            "total_fv": total_fv,
            "flagged_fv": flagged_fv,
            "nonaccrual_ratio": flagged_fv / total_fv if total_fv else 0,
            "reconciled_fv": 0.0,
            "reconciled_pct": 0.0,
        }

    recon = recon.copy()
    recon["flagged_nonaccrual_fv"] = pd.to_numeric(
        recon["flagged_nonaccrual_fv"], errors="coerce"
    ).fillna(0)
    recon["share"] = recon["flagged_nonaccrual_fv"] / flagged_fv
    large = recon[recon["share"] >= 0.01]
    large_ok = large["status"].isin(passing).all() if not large.empty else True
    reconciled_fv = float(
        recon.loc[recon["status"].isin(passing), "flagged_nonaccrual_fv"].sum()
    )
    reconciled_pct = reconciled_fv / flagged_fv if flagged_fv else 0.0
    chart_ok = bool(large_ok and reconciled_pct >= 0.90)
    return {
        "chart_status": "VALIDATED" if chart_ok else "UNDER_REVIEW",
        "reason": (
            "thresholds met"
            if chart_ok
            else "one-percent contributors or 90% FV threshold not reconciled"
        ),
        "total_fv": total_fv,
        "flagged_fv": flagged_fv,
        "nonaccrual_ratio": flagged_fv / total_fv if total_fv else 0,
        "reconciled_fv": reconciled_fv,
        "reconciled_pct": reconciled_pct,
        "large_contributors": len(large),
        "large_contributors_passing": int(large["status"].isin(passing).sum()),
    }


def append_investigation_summary(
    quarter: str,
    summary: dict[str, Any],
    recon_path: Path,
    evidence_path: Path,
) -> None:
    INVESTIGATION_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    heading = f"## Non-accrual reconciliation - {quarter}"
    text = (
        f"\n\n{heading}\n\n"
        f"Question: validate the BDC direct-lending non-accrual FV used in "
        f"`credit_risk.json` for `{quarter}`.\n\n"
        f"Sources: `private_markets_holdings.csv`, `nonaccrual_flags.csv`, "
        f"`fund_financials.csv`, `bdc_filings_index.csv`, and cached XBRL files.\n\n"
        f"Conclusion: chart status `{summary['chart_status']}`. "
        f"Flagged FV ${summary['flagged_fv']:,.0f} / total FV "
        f"${summary['total_fv']:,.0f} = {summary['nonaccrual_ratio']:.4%}. "
        f"Reconciled FV ${summary['reconciled_fv']:,.0f} "
        f"({summary['reconciled_pct']:.1%}). Reason: {summary['reason']}.\n\n"
        f"Artifacts: `{recon_path.as_posix()}` and `{evidence_path.as_posix()}`.\n\n"
        "Residual uncertainty: aggregate non-accrual totals are only accepted "
        "when parseable from structured XBRL concepts; otherwise direct "
        "position-level evidence is used and unresolved cases remain under review."
    )
    if INVESTIGATION_RESULTS_FILE.exists():
        existing = INVESTIGATION_RESULTS_FILE.read_text(encoding="utf-8")
        changed = False
        while True:
            start = existing.find(heading)
            if start < 0:
                break
            next_start = existing.find("\n## ", start + len(heading))
            if next_start < 0:
                existing = existing[:start].rstrip()
            else:
                existing = existing[:start].rstrip() + "\n\n" + existing[next_start:].lstrip()
            changed = True
        if changed:
            INVESTIGATION_RESULTS_FILE.write_text(existing + text, encoding="utf-8")
            return

    with INVESTIGATION_RESULTS_FILE.open("a", encoding="utf-8") as f:
        f.write(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarter", required=True, help="Quarter label, e.g. 2025q4")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    recon, evidence, summary = run_reconciliation(args.quarter)
    logger.info("Wrote %d reconciliation rows and %d evidence rows",
                len(recon), len(evidence))
    logger.info("Chart status: %s; non-accrual FV ratio %.4f",
                summary["chart_status"], summary["nonaccrual_ratio"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
