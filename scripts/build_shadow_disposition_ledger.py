"""Shadow disposition ledger -- Step 1 (v1) of the frontier architecture.

See docs/refactoring/frontier_architecture.md, section "Step 1 (v1)".

Purpose
-------
Build a READ-ONLY shadow of the disposition decision (is this source row a
position or an aggregate?) over the existing extracted BDC rows, and diff the
new centralized + conservation logic against what the current pipeline actually
decided. Nothing in the production pipeline is touched; outputs land under
data/output/shadow/ only.

v1 scope
--------
- Only BDC CIKs that have a wrapper config in data/overrides/bdc_xbrl_wrappers/.
- Only current-period rows (period == report_date); comparatives are tagged and
  excluded from the conservation sum.
- Signals are deterministic only (text-aggregate, wrapper aggregate_markers,
  leaf-detail presence). Resolved-issuer arithmetic rollup attribution and
  probabilistic entity resolution are deferred to v2; the per-CIK-quarter signed
  conservation residual is the arbiter in v1.

Outputs (data/output/shadow/)
-----------------------------
- bdc_row_disposition_ledger.csv : one row per current-period wrapped BDC source
  row, with signals, current_disposition, new_disposition, agree.
- bdc_disposition_diff_summary.csv : counts + FV by (current -> new) transition.
- bdc_conservation_residual.csv : per (cik, report_date), the signed residual
  Sum(included FV) - Total Investments, under BOTH current and new disposition.

This is a shadow/diagnostic artifact. It does NOT feed unified_holdings.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import duckdb

from pipeline.config import (
    BDC_HOLDINGS_FILE,
    BDC_HOLDINGS_PARQUET_FILE,
    FUND_FINANCIALS_FILE,
    OUTPUT_DIR,
    OVERRIDES_DIR,
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("shadow_disposition_ledger")

WRAPPER_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"
SHADOW_DIR = OUTPUT_DIR / "shadow"
_CIK_RE = re.compile(r"^\d{10}$")


def _bdc_source() -> str:
    """Prefer parquet (typed, fast); fall back to CSV."""
    if BDC_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{BDC_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{BDC_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def _unified_source() -> str:
    if UNIFIED_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{UNIFIED_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def load_wrapped_ciks() -> list[str]:
    """CIKs that have a per-CIK wrapper config (10-digit filenames only)."""
    ciks = sorted(
        p.stem for p in WRAPPER_DIR.glob("*.json") if _CIK_RE.match(p.stem)
    )
    return ciks


def load_aggregate_markers(ciks: list[str]) -> list[tuple[str, str]]:
    """(cik, lowercased aggregate_marker) pairs from dispatch.aggregate_markers."""
    pairs: list[tuple[str, str]] = []
    for cik in ciks:
        path = WRAPPER_DIR / f"{cik}.json"
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("skip wrapper %s: %s", cik, exc)
            continue
        markers = (cfg.get("dispatch") or {}).get("aggregate_markers") or []
        for m in markers:
            m = str(m).strip().lower()
            if m:
                pairs.append((cik, m))
    return pairs


def build_ledger(con: duckdb.DuckDBPyConnection) -> None:
    bdc = _bdc_source()
    unified = _unified_source()

    # Current-period source rows for wrapped CIKs, with a stable id.
    con.execute(
        f"""
        CREATE TABLE src AS
        SELECT
            md5(
                CAST(cik AS VARCHAR) || '|' || CAST(report_date AS VARCHAR)
                || '|' || COALESCE(dimensions_raw, '')
                || '|' || COALESCE(CAST(fair_value AS VARCHAR), '')
            ) AS source_row_id,
            CAST(cik AS VARCHAR)         AS cik,
            CAST(report_date AS VARCHAR) AS report_date,
            CAST(period AS VARCHAR)      AS period,
            investment_identifier,
            lower(trim(COALESCE(investment_identifier, ''))) AS ident_l,
            dimensions_raw,
            TRY_CAST(fair_value AS DOUBLE) AS fair_value,
            interest_rate, maturity_date, principal_amount, shares_held, cost,
            industry, investment_type, affiliation
        FROM {bdc}
        WHERE CAST(cik AS VARCHAR) IN (SELECT cik FROM wrapped)
          AND CAST(period AS VARCHAR) = CAST(report_date AS VARCHAR)
        """
    )

    # TIGHT anchor: the schedule grand-total ("Total Investments" family).
    # We accept grand-total phrasings but EXCLUDE category/affiliation/cash
    # subtotals (which would give a too-small anchor and manufacture false
    # overshoots), then take the max FV per quarter as the grand total.
    con.execute(
        r"""
        CREATE TABLE target AS
        SELECT cik, report_date, max(fair_value) AS total_fv
        FROM src
        WHERE fair_value IS NOT NULL
          AND (ident_l LIKE 'total %investment%'
               OR ident_l = 'total investment portfolio'
               OR ident_l LIKE 'total portfolio investment%')
          AND NOT regexp_matches(ident_l,
              '(debt|equity|short-?term|affiliat|controll|non-?control|secured|'
              || 'unsecured|clo|collateral|joint venture|cash|warrant|structured|'
              || 'senior|subordinat|first[- ]lien|second[- ]lien|preferred|note|'
              || 'loan|bond|derivative)')
        GROUP BY cik, report_date
        """
    )

    # Anchors from fund_financials (companyfacts -- exact-concept-keyed, verified
    # reliable: BS identity holds 98.8%). This REPLACES the broken
    # bdc_fund_highlights.total_assets (substring-bound, BS identity 4.3%).
    #  - inv_fv  = investments_at_fair_value: the SAME quantity as Sum(positions)
    #              from an independent source -> STRONG tight anchor.
    #  - total_assets: gross assets -> LOOSE bound (positions are a high fraction).
    if FUND_FINANCIALS_FILE.exists():
        con.execute(
            f"""
            CREATE TABLE ffin AS
            SELECT CAST(cik AS VARCHAR) AS cik,
                   CAST(report_date AS VARCHAR) AS report_date,
                   max(TRY_CAST(investments_at_fair_value AS DOUBLE)) AS inv_fv,
                   max(TRY_CAST(total_assets AS DOUBLE)) AS total_assets
            FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
            WHERE source = 'companyfacts'
            GROUP BY 1, 2
            """
        )
    else:
        con.execute("CREATE TABLE ffin (cik VARCHAR, report_date VARCHAR, inv_fv DOUBLE, total_assets DOUBLE)")

    # Production quantity for the gate: sum of UNIFIED fair value per CIK-quarter.
    # This is what production actually published. The gate must reconcile THIS
    # against the anchor -- NOT a sum of matched bdc_holdings source rows, which
    # double-counts wherever unified deduped (e.g. duplicate 10-K/10-K/A filings).
    con.execute(
        f"""
        CREATE TABLE unified_fv AS
        SELECT CAST(cik AS VARCHAR) AS cik,
               CAST(report_date AS VARCHAR) AS report_date,
               sum(TRY_CAST(fair_value AS DOUBLE)) AS unified_fv,
               count(*) AS unified_rows
        FROM {unified}
        WHERE bdc_dimensions_raw IS NOT NULL
          AND CAST(cik AS VARCHAR) IN (SELECT cik FROM wrapped)
        GROUP BY 1, 2
        """
    )

    # Signals + dispositions. Resolution policy is intentionally simple in v1.
    con.execute(
        """
        CREATE TABLE ledger AS
        WITH sig AS (
            SELECT
                s.*,
                (s.ident_l LIKE 'total %'
                 OR s.ident_l = 'total investments'
                 OR s.ident_l LIKE '%subtotal%')                AS is_total,
                (trim(s.ident_l) LIKE '%\\%' ESCAPE '\\')        AS is_pct_row,
                (s.interest_rate IS NOT NULL
                 OR s.maturity_date IS NOT NULL
                 OR s.principal_amount IS NOT NULL
                 OR s.shares_held IS NOT NULL)                  AS has_leaf_detail,
                EXISTS (
                    SELECT 1 FROM markers m
                    WHERE m.cik = s.cik
                      AND s.ident_l LIKE '%' || m.marker || '%'
                )                                               AS wrapper_marker_match
            FROM src s
        ),
        disp AS (
            SELECT
                *,
                (NOT has_leaf_detail AND fair_value IS NOT NULL) AS bare_header,
                (is_total OR is_pct_row)                         AS text_aggregate
            FROM sig
        )
        SELECT
            d.* EXCLUDE (industry, investment_type, affiliation),
            -- Disposition is REUSED from the existing pipeline outcome (a row is
            -- a position iff it survived the full validated rule stack into
            -- unified_holdings). We do NOT recompute disposition here. The cheap
            -- signals below are DIAGNOSTIC FLAGS only -- used to triage where the
            -- independent conservation gate says the existing output does not
            -- reconcile -- never a competing decision.
            CASE WHEN u.bdc_dimensions_raw IS NOT NULL
                 THEN 'include_position' ELSE 'excluded'
            END AS disposition,
            u.issuer_name AS issuer_name,
            (d.text_aggregate OR d.wrapper_marker_match) AS flag_explicit_aggregate
        FROM disp d
        LEFT JOIN (
            SELECT
                CAST(cik AS VARCHAR)         AS cik,
                CAST(report_date AS VARCHAR) AS report_date,
                bdc_dimensions_raw,
                any_value(issuer_name)       AS issuer_name
            FROM """ + unified + """
            WHERE bdc_dimensions_raw IS NOT NULL
            GROUP BY 1, 2, 3
        ) u
          ON u.cik = d.cik
         AND u.report_date = d.report_date
         AND u.bdc_dimensions_raw = d.dimensions_raw
        """
    )

    # Triage flags over the EXISTING output (not decisions):
    #  - leak_candidate: included by the pipeline but looks like an aggregate
    #  - drop_candidate: excluded by the pipeline but has leaf detail
    con.execute(
        """
        ALTER TABLE ledger ADD COLUMN leak_candidate BOOLEAN;
        ALTER TABLE ledger ADD COLUMN drop_candidate BOOLEAN;
        UPDATE ledger SET
            leak_candidate = (disposition = 'include_position'
                              AND (flag_explicit_aggregate OR bare_header)),
            drop_candidate = (disposition = 'excluded' AND has_leaf_detail);
        """
    )


def write_outputs(con: duckdb.DuckDBPyConnection) -> None:
    SHADOW_DIR.mkdir(parents=True, exist_ok=True)

    ledger_path = SHADOW_DIR / "bdc_row_disposition_ledger.csv"
    con.execute(
        f"""
        COPY (
            SELECT
                source_row_id, cik, report_date, period,
                investment_identifier, fair_value,
                has_leaf_detail, is_total, is_pct_row, bare_header,
                wrapper_marker_match, flag_explicit_aggregate,
                disposition, leak_candidate, drop_candidate
            FROM ledger
            ORDER BY cik, report_date, fair_value DESC NULLS LAST
        ) TO '{ledger_path.as_posix()}' (HEADER, DELIMITER ',')
        """
    )

    # Triage breakdown over the EXISTING output (not a competing decision).
    triage_path = SHADOW_DIR / "bdc_triage_summary.csv"
    con.execute(
        f"""
        COPY (
            SELECT
                disposition,
                sum(CASE WHEN leak_candidate THEN 1 ELSE 0 END) AS leak_candidates,
                round(sum(CASE WHEN leak_candidate THEN COALESCE(fair_value,0) ELSE 0 END)/1e6, 1) AS leak_fv_m,
                sum(CASE WHEN drop_candidate THEN 1 ELSE 0 END) AS drop_candidates,
                round(sum(CASE WHEN drop_candidate THEN COALESCE(fair_value,0) ELSE 0 END)/1e6, 1) AS drop_fv_m,
                count(*) AS n_rows
            FROM ledger GROUP BY disposition ORDER BY disposition
        ) TO '{triage_path.as_posix()}' (HEADER, DELIMITER ',')
        """
    )

    # Independent conservation gate over the EXISTING included set, TIERED:
    #  - tight anchor (schedule grand-total): reconcile to +/-0.5%
    #  - loose anchor (total_assets): bound check, band [0.70, 1.05]
    #  - else no_anchor
    con.execute(
        """
        CREATE TABLE residual AS
        WITH src AS (
            SELECT cik, report_date, count(*) AS n_rows,
                   sum(CASE WHEN disposition='include_position' THEN COALESCE(fair_value,0) ELSE 0 END) AS source_included_fv,
                   sum(CASE WHEN disposition='include_position' THEN 1 ELSE 0 END) AS n_included
            FROM ledger GROUP BY cik, report_date
        ),
        sums AS (
            -- sum_included is the PRODUCTION quantity (sum of unified FV), not the
            -- sum of matched source rows. source_included_fv is kept as a
            -- diagnostic; (source_included_fv - sum_included) is the dedup that
            -- unified applied (e.g. duplicate-filing collapse).
            SELECT src.cik, src.report_date, src.n_rows, src.n_included,
                   src.source_included_fv,
                   COALESCE(uf.unified_fv, 0) AS sum_included,
                   uf.unified_rows
            FROM src LEFT JOIN unified_fv uf USING (cik, report_date)
        )
        SELECT
            s.cik, s.report_date, s.sum_included, s.source_included_fv,
            (s.source_included_fv - s.sum_included) AS source_minus_unified,
            s.unified_rows, s.n_rows, s.n_included,
            f.inv_fv          AS companyfacts_inv_fv,   -- STRONG tight anchor
            t.total_fv        AS schedule_total,        -- secondary tight anchor
            f.total_assets    AS total_assets,          -- LOOSE bound anchor
            -- The tight anchor used: companyfacts investments_at_fv if present,
            -- else the schedule grand-total.
            COALESCE(f.inv_fv, t.total_fv) AS tight_anchor,
            CASE WHEN f.inv_fv IS NOT NULL THEN 'companyfacts_fv'
                 WHEN t.total_fv IS NOT NULL THEN 'schedule_total'
                 WHEN f.total_assets IS NOT NULL AND f.total_assets > 0 THEN 'loose_assets'
                 ELSE 'none' END AS anchor_tier,
            -- cross-check where BOTH tight anchors exist (should agree)
            CASE WHEN f.inv_fv IS NOT NULL AND t.total_fv IS NOT NULL AND t.total_fv <> 0
                 THEN round(100.0*(f.inv_fv - t.total_fv)/t.total_fv, 3) END AS anchor_crosscheck_pct,
            CASE WHEN COALESCE(f.inv_fv, t.total_fv) IS NOT NULL AND COALESCE(f.inv_fv, t.total_fv) <> 0
                 THEN round(100.0*(s.sum_included - COALESCE(f.inv_fv, t.total_fv))/COALESCE(f.inv_fv, t.total_fv), 3) END AS tight_residual_pct,
            CASE WHEN f.total_assets IS NOT NULL AND f.total_assets > 0
                 THEN round(s.sum_included/f.total_assets, 4) END AS invested_ratio,
            CASE
                WHEN COALESCE(f.inv_fv, t.total_fv) IS NOT NULL THEN
                    CASE WHEN abs(s.sum_included - COALESCE(f.inv_fv, t.total_fv)) <= 0.005*abs(COALESCE(f.inv_fv, t.total_fv)) THEN 'tight_reconciles'
                         WHEN s.sum_included > COALESCE(f.inv_fv, t.total_fv) THEN 'tight_overshoot_leak'
                         ELSE 'tight_undershoot_missing' END
                WHEN f.total_assets IS NOT NULL AND f.total_assets > 0 THEN
                    CASE WHEN s.sum_included BETWEEN 0.70*f.total_assets AND 1.05*f.total_assets THEN 'loose_ok'
                         WHEN s.sum_included > 1.05*f.total_assets THEN 'loose_overshoot'
                         ELSE 'loose_low' END
                ELSE 'no_anchor'
            END AS gate_status
        FROM sums s
        LEFT JOIN target t USING (cik, report_date)
        LEFT JOIN ffin f USING (cik, report_date)
        """
    )

    resid_path = SHADOW_DIR / "bdc_conservation_residual.csv"
    con.execute(
        f"""
        COPY (
            SELECT cik, report_date, anchor_tier, gate_status, sum_included,
                   source_included_fv, source_minus_unified,
                   companyfacts_inv_fv, schedule_total, tight_anchor,
                   anchor_crosscheck_pct, tight_residual_pct,
                   total_assets, invested_ratio, unified_rows, n_rows, n_included
            FROM residual
            ORDER BY anchor_tier,
                     abs(COALESCE(sum_included - tight_anchor, 0)) DESC
        ) TO '{resid_path.as_posix()}' (HEADER, DELIMITER ',')
        """
    )

    logger.info("wrote %s", ledger_path)
    logger.info("wrote %s", triage_path)
    logger.info("wrote %s", resid_path)


def build_localization(con: duckdb.DuckDBPyConnection) -> None:
    """Localize each non-reconciling tight residual to specific candidate rows.

    Uses STRUCTURE (single-row==gap, issuer-subtotal, excluded-row==shortfall),
    not blind subset-sum. Confirms each quarter by whether removing/adding the
    candidates closes the gate. Read-only over `ledger` and `residual`.
    """
    con.execute(
        """
        CREATE TABLE localization AS
        WITH ov AS (
            SELECT cik, report_date, sum_included, tight_anchor,
                   (sum_included - tight_anchor) AS gap
            FROM residual WHERE gate_status = 'tight_overshoot_leak'
        ),
        un AS (
            SELECT cik, report_date, sum_included, tight_anchor,
                   (tight_anchor - sum_included) AS gap
            FROM residual WHERE gate_status = 'tight_undershoot_missing'
        ),
        -- A: an AGGREGATE-LIKE included row whose FV ~ the whole excess. Must be
        -- aggregate-like (no leaf detail or explicit-aggregate flag) so a real
        -- position equal to the excess by coincidence is not flagged.
        a AS (
            SELECT l.cik, l.report_date, 'overshoot' AS direction, o.gap,
                   l.source_row_id, l.investment_identifier, l.fair_value,
                   l.issuer_name, 'aggregate_row_equals_excess' AS candidate_type
            FROM ledger l JOIN ov o ON l.cik=o.cik AND l.report_date=o.report_date
            WHERE l.disposition='include_position' AND l.fair_value IS NOT NULL
              AND (NOT l.has_leaf_detail OR l.flag_explicit_aggregate)
              AND o.gap > 0 AND abs(l.fair_value - o.gap) <= 0.02*o.gap
        ),
        -- B: an AGGREGATE-LIKE included row whose FV ~ the sum of >=2 DETAILED
        -- children sharing its resolved issuer (a leaked issuer subtotal). The
        -- candidate must itself be aggregate-like; the children must be real
        -- positions (has_leaf_detail). This rejects 2-equal-position groups.
        detail_grp AS (
            SELECT cik, report_date, issuer_name,
                   sum(CASE WHEN has_leaf_detail THEN fair_value ELSE 0 END) AS child_sum,
                   sum(CASE WHEN has_leaf_detail THEN 1 ELSE 0 END) AS n_children
            FROM ledger
            WHERE disposition='include_position' AND fair_value IS NOT NULL
              AND issuer_name IS NOT NULL
            GROUP BY 1,2,3
        ),
        b AS (
            SELECT l.cik, l.report_date, 'overshoot' AS direction, o.gap,
                   l.source_row_id, l.investment_identifier, l.fair_value,
                   l.issuer_name, 'issuer_subtotal' AS candidate_type
            FROM ledger l
            JOIN ov o ON l.cik=o.cik AND l.report_date=o.report_date
            JOIN detail_grp g ON g.cik=l.cik AND g.report_date=l.report_date
                             AND g.issuer_name=l.issuer_name
            WHERE l.disposition='include_position' AND l.fair_value IS NOT NULL
              AND (NOT l.has_leaf_detail OR l.flag_explicit_aggregate)
              AND g.n_children >= 2
              AND abs(l.fair_value - g.child_sum) <= 0.02*l.fair_value
        ),
        -- C: an excluded row WITH leaf detail whose FV ~ the shortfall (a real
        -- position the rules dropped).
        c AS (
            SELECT l.cik, l.report_date, 'undershoot' AS direction, u.gap,
                   l.source_row_id, l.investment_identifier, l.fair_value,
                   l.issuer_name, 'excluded_row_equals_shortfall' AS candidate_type
            FROM ledger l JOIN un u ON l.cik=u.cik AND l.report_date=u.report_date
            WHERE l.disposition='excluded' AND l.fair_value IS NOT NULL
              AND l.has_leaf_detail
              AND u.gap > 0 AND abs(l.fair_value - u.gap) <= 0.02*u.gap
        )
        SELECT DISTINCT * FROM (
            SELECT * FROM a UNION ALL SELECT * FROM b UNION ALL SELECT * FROM c
        )
        """
    )

    # Per-quarter rollup with gap-closure (dedup candidate rows by source_row_id).
    con.execute(
        """
        CREATE TABLE localization_summary AS
        WITH cand AS (
            SELECT DISTINCT cik, report_date, direction, source_row_id, fair_value
            FROM localization
        ),
        agg AS (
            SELECT cik, report_date, any_value(direction) AS direction,
                   count(*) AS n_candidates, sum(fair_value) AS cand_fv
            FROM cand GROUP BY cik, report_date
        ),
        j AS (
            SELECT r.cik, r.report_date, r.gate_status,
                   (r.sum_included - r.tight_anchor) AS signed_gap,
                   a.n_candidates, a.cand_fv, r.sum_included, r.tight_anchor,
                   CASE
                     WHEN r.gate_status='tight_overshoot_leak'
                       THEN abs((r.sum_included - COALESCE(a.cand_fv,0)) - r.tight_anchor) <= 0.005*abs(r.tight_anchor)
                     ELSE
                       abs((r.sum_included + COALESCE(a.cand_fv,0)) - r.tight_anchor) <= 0.005*abs(r.tight_anchor)
                   END AS gap_closes
            FROM residual r LEFT JOIN agg a USING (cik, report_date)
            WHERE r.gate_status IN ('tight_overshoot_leak','tight_undershoot_missing')
        )
        SELECT *,
            CASE
              WHEN gate_status='tight_overshoot_leak'  AND n_candidates IS NULL THEN 'overshoot_unexplained'
              WHEN gate_status='tight_overshoot_leak'  AND gap_closes THEN 'leak_localized'
              WHEN gate_status='tight_overshoot_leak'  THEN 'partial_leak'
              WHEN gate_status='tight_undershoot_missing' AND n_candidates IS NULL THEN 'undershoot_unexplained'
              WHEN gate_status='tight_undershoot_missing' AND gap_closes THEN 'drop_localized'
              ELSE 'partial_drop'
            END AS label
        FROM j
        """
    )

    loc_path = SHADOW_DIR / "bdc_residual_localization.csv"
    con.execute(
        f"""
        COPY (SELECT cik, report_date, direction, gap, candidate_type,
                     source_row_id, issuer_name, fair_value, investment_identifier
              FROM localization ORDER BY direction, gap DESC, fair_value DESC)
        TO '{loc_path.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    sum_path = SHADOW_DIR / "bdc_residual_localization_summary.csv"
    con.execute(
        f"""
        COPY (SELECT cik, report_date, gate_status, label, signed_gap,
                     n_candidates, cand_fv, gap_closes
              FROM localization_summary ORDER BY abs(signed_gap) DESC)
        TO '{sum_path.as_posix()}' (HEADER, DELIMITER ',')
        """
    )
    logger.info("wrote %s", loc_path)
    logger.info("wrote %s", sum_path)

    logger.info("residual localization (non-reconciling tight CIK-quarters):")
    for label, n in con.execute(
        "SELECT label, count(*) FROM localization_summary GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        logger.info("  %-24s : %4d", label, n)


def log_summary(con: duckdb.DuckDBPyConnection) -> None:
    n_rows, n_ciks, n_q = con.execute(
        "SELECT count(*), count(DISTINCT cik), count(DISTINCT cik || report_date) FROM ledger"
    ).fetchone()
    logger.info("ledger: %d rows, %d CIKs, %d CIK-quarters (disposition REUSED from existing pipeline)",
                n_rows, n_ciks, n_q)

    incl, excl = con.execute(
        """
        SELECT sum(CASE WHEN disposition='include_position' THEN 1 ELSE 0 END),
               sum(CASE WHEN disposition='excluded' THEN 1 ELSE 0 END)
        FROM ledger
        """
    ).fetchone()
    logger.info("existing dispositions: %d included, %d excluded", incl, excl)

    leak_n, leak_fv, drop_n = con.execute(
        """
        SELECT sum(CASE WHEN leak_candidate THEN 1 ELSE 0 END),
               round(sum(CASE WHEN leak_candidate THEN COALESCE(fair_value,0) ELSE 0 END)/1e6,1),
               sum(CASE WHEN drop_candidate THEN 1 ELSE 0 END)
        FROM ledger
        """
    ).fetchone()
    logger.info("triage flags over existing output: %d leak-candidates ($%sM included but aggregate-like), "
                "%d drop-candidates (excluded but has leaf detail)", leak_n, leak_fv, drop_n)

    # Tiered conservation gate over the EXISTING included set.
    logger.info("anchor coverage (CIK-quarters):")
    for tier, n in con.execute(
        "SELECT anchor_tier, count(*) FROM residual GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        logger.info("  %-6s : %4d", tier, n)

    logger.info("gate status:")
    for status, n in con.execute(
        "SELECT gate_status, count(*) FROM residual GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        logger.info("  %-24s : %4d", status, n)

    # Tight-anchor validation: median sum/tight should be ~1.0 if well-scoped.
    med = con.execute(
        "SELECT round(median(sum_included/tight_anchor), 4) FROM residual "
        "WHERE tight_anchor IS NOT NULL AND tight_anchor > 0"
    ).fetchone()[0]
    logger.info("tight-anchor validation: median sum_included/tight_anchor = %s (want ~1.0)", med)

    # Cross-check the two independent tight anchors where both exist.
    xc = con.execute(
        "SELECT count(*), round(median(abs(anchor_crosscheck_pct)), 3) FROM residual "
        "WHERE anchor_crosscheck_pct IS NOT NULL"
    ).fetchone()
    logger.info("anchor cross-check (companyfacts_fv vs schedule_total, n=%s): median |diff| = %s%%",
                xc[0], xc[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-ciks", type=int, default=0,
                        help="debug: cap number of wrapped CIKs processed")
    args = parser.parse_args(argv)

    ciks = load_wrapped_ciks()
    if args.limit_ciks:
        ciks = ciks[: args.limit_ciks]
    if not ciks:
        logger.error("no wrapper CIK configs found in %s", WRAPPER_DIR)
        return 1
    logger.info("wrapped CIK cohort: %d CIKs", len(ciks))

    markers = load_aggregate_markers(ciks)
    logger.info("loaded %d aggregate_marker entries", len(markers))

    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped (cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)", [(c,) for c in ciks])
    con.execute("CREATE TABLE markers (cik VARCHAR, marker VARCHAR)")
    if markers:
        con.executemany("INSERT INTO markers VALUES (?, ?)", markers)

    build_ledger(con)
    write_outputs(con)
    build_localization(con)
    log_summary(con)
    return 0


if __name__ == "__main__":
    sys.exit(main())
