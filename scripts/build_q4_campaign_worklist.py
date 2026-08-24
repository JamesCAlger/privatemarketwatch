"""Build the Q4 2025 B-agent campaign worklist.

Two-part campaign (run Part A first; its fixes cascade into Part B):

  Part A: aggregate_header name adjudication scoped to Q4 2025.
          Every fail/warn aggregate_header ledger name (AGGREGATE_HEADER +
          JV_SUBSIDIARY) joined into 2025-12-31 unified holdings rows on
          lower(trim(issuer_name)) -- the same key the shadow runner uses
          for agg_header localization. Names with no Q4 footprint are
          reported but not queued.

  Part B: all Q4 2025 review-queue items (blocker + review lanes),
          annotated with dispatch tier, likely B2 remediation lane,
          wrapper/verdict/bundle existence, sorted in dispatch order.

Read-only on production artifacts; writes only _q4_campaign_* files under
data/output/review_queue/.

Usage: python scripts/build_q4_campaign_worklist.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "output"
QDIR = OUT / "review_queue"
LEDGER = OUT / "shadow" / "validation_results_ledger.csv"
HOLDINGS = OUT / "private_markets_holdings.csv"
QUEUE = QDIR / "review_queue.csv"
WRAPPER_DIR = ROOT / "data" / "overrides" / "bdc_xbrl_wrappers"

Q4 = "2025-12-31"

# Dispatch tiers (blocker lane; review lane is always tier 4, runs last).
TIER_BY_ENGINE = {
    "conservation": 0,
    "html_extract": 0,
    "gav_recon": 0,
    "cross_source": 0,
    "source_recon": 1,
    "identity": 2,
    "row_validation": 2,
    "oracle": 3,
    "agentA": 3,
    "fund_financials": 3,
    "derivative_role": 3,
}

# Likely B2 remediation lane by engine (B1 adjudication is universal; this
# only routes the *fix* if the verdict is real_error).
LANE_BY_ENGINE = {
    "source_recon": "wrapper_parser",
    "agentA": "wrapper_grammar",
    "conservation": "wrapper_aggregate_or_global",
    "html_extract": "wrapper_aggregate_or_global",
    "aggregate_header": "wrapper_aggregate_or_global",
    "gav_recon": "anchor_side",
    "cross_source": "anchor_side",
    "identity": "global_logic",
    "oracle": "varies_adjudicate_first",
    "fund_financials": "income_extraction",
    "derivative_role": "classification",
    "row_validation": "wrapper_or_global",
    "weak": "precision_measurement",
    "validation_rules": "precision_measurement",
    "nonaccrual": "precision_measurement",
    "fund_strategy": "precision_measurement",
    "classification": "precision_measurement",
}


def main() -> int:
    for p in (LEDGER, HOLDINGS, QUEUE):
        if not p.exists():
            print(f"ERROR: missing {p}")
            return 1

    wrappers = {p.stem for p in WRAPPER_DIR.glob("*.json")}
    verdicts = {p.stem for p in (QDIR / "verdicts").glob("*.json")}
    bundles = {p.stem for p in (QDIR / "review_bundles").glob("*.json")}
    print(f"wrappers={len(wrappers)} verdicts={len(verdicts)} bundles={len(bundles)}")

    con = duckdb.connect()

    # ---------------- Part A: aggregate names x Q4 holdings ----------------
    print("Part A: loading aggregate_header ledger names ...")
    con.execute(
        f"""
        CREATE TABLE agg_names AS
        SELECT lower(trim(cik)) AS name_key,
               rule_name,
               src_confidence,
               confidence,
               TRY_CAST(n_units AS INTEGER) AS ledger_units_allq,
               TRY_CAST(metric AS DOUBLE) AS ledger_fv_m_allq
        FROM read_csv_auto('{LEDGER.as_posix()}', sample_size=-1)
        WHERE engine = 'aggregate_header' AND status IN ('fail', 'warn')
        """
    )
    n_names = con.execute("SELECT count(*) FROM agg_names").fetchone()[0]
    print(f"  {n_names} flagged names (all quarters)")

    print("Part A: joining into Q4 holdings (this reads the 560MB CSV once) ...")
    con.execute(
        f"""
        CREATE TABLE q4_rows AS
        SELECT lpad(CAST(cik AS VARCHAR), 10, '0') AS cik,
               entity_name,
               lower(trim(issuer_name)) AS name_key,
               TRY_CAST(fair_value AS DOUBLE) AS fair_value,
               COALESCE(CAST(is_subsidiary AS VARCHAR), '') AS is_subsidiary,
               COALESCE(CAST(jv_subsidiary AS VARCHAR), '') AS jv_subsidiary
        FROM read_csv_auto('{HOLDINGS.as_posix()}', sample_size=-1)
        WHERE CAST(report_date AS VARCHAR) = '{Q4}'
        """
    )
    n_q4 = con.execute("SELECT count(*) FROM q4_rows").fetchone()[0]
    print(f"  {n_q4} Q4 holdings rows")

    part_a = con.execute(
        """
        SELECT a.rule_name,
               a.name_key,
               r.cik,
               any_value(r.entity_name) AS entity_name,
               count(*) AS q4_rows,
               round(sum(r.fair_value) / 1e6, 3) AS q4_fv_m,
               sum(CASE WHEN lower(r.is_subsidiary) IN ('true','1') THEN 1 ELSE 0 END)
                   AS q4_rows_marked_subsidiary,
               sum(CASE WHEN r.jv_subsidiary NOT IN ('', 'None') THEN 1 ELSE 0 END)
                   AS q4_rows_marked_jv,
               any_value(a.src_confidence) AS src_confidence,
               any_value(a.ledger_units_allq) AS ledger_units_allq,
               any_value(a.ledger_fv_m_allq) AS ledger_fv_m_allq
        FROM agg_names a
        JOIN q4_rows r ON r.name_key = a.name_key
        GROUP BY a.rule_name, a.name_key, r.cik
        ORDER BY q4_fv_m DESC NULLS LAST
        """
    ).fetchall()
    cols_a = [d[0] for d in con.description]

    path_a = QDIR / "_q4_campaign_partA_aggregate_names.csv"
    with open(path_a, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols_a + ["wrapper_exists"])
        for row in part_a:
            rec = dict(zip(cols_a, row))
            w.writerow(list(row) + [rec["cik"] in wrappers])
    print(f"  Part A worklist: {len(part_a)} (rule, name, cik) groups -> {path_a.name}")

    unmatched = con.execute(
        """
        SELECT a.rule_name, count(*) AS names_no_q4_footprint
        FROM agg_names a
        LEFT JOIN (SELECT DISTINCT name_key FROM q4_rows) q ON q.name_key = a.name_key
        WHERE q.name_key IS NULL
        GROUP BY a.rule_name
        """
    ).fetchall()

    # ---------------- Part B: Q4 queue items annotated ----------------
    print("Part B: annotating Q4 queue items ...")
    con.execute(
        f"""
        CREATE TABLE q4_items AS
        SELECT * FROM read_csv_auto('{QUEUE.as_posix()}', sample_size=-1, all_varchar=true)
        WHERE report_date = '{Q4}'
        """
    )
    items = con.execute("SELECT * FROM q4_items").fetchall()
    cols_b = [d[0] for d in con.description]

    out_rows = []
    for row in items:
        rec = dict(zip(cols_b, row))
        engine = rec["engine"]
        tier = 4 if rec["lane"] == "review" else TIER_BY_ENGINE.get(engine, 3)
        lane2 = LANE_BY_ENGINE.get(engine, "varies_adjudicate_first")
        fv = 0.0
        try:
            fv = float(rec["fv_at_risk_m"] or 0.0)
        except ValueError:
            pass
        out_rows.append(
            (
                tier,
                -fv,
                rec["review_id"],
                rec["lane"],
                rec["engine"],
                rec["rule_name"],
                rec["cik"],
                rec["unit_label"],
                rec["mechanism"],
                rec["n_units"],
                rec["fv_at_risk_m"],
                lane2,
                rec["cik"] in wrappers,
                rec["review_id"] in verdicts,
                rec["review_id"] in bundles,
            )
        )
    out_rows.sort(key=lambda t: (t[0], t[1]))

    path_b = QDIR / "_q4_campaign_partB_items.csv"
    with open(path_b, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "dispatch_tier",
                "neg_fv_sort",
                "review_id",
                "lane",
                "engine",
                "rule_name",
                "cik",
                "unit_label",
                "mechanism",
                "n_units",
                "fv_at_risk_m",
                "likely_b2_lane",
                "wrapper_exists",
                "verdict_exists",
                "bundle_exists",
            ]
        )
        w.writerows(out_rows)
    print(f"  Part B worklist: {len(out_rows)} items -> {path_b.name}")

    # ---------------- Summary ----------------
    print()
    print("=== Part A summary (aggregate names with Q4 2025 footprint) ===")
    for rule in ("AGGREGATE_HEADER", "JV_SUBSIDIARY"):
        groups = [dict(zip(cols_a, r)) for r in part_a if r[0] == rule]
        names = {g["name_key"] for g in groups}
        ciks = {g["cik"] for g in groups}
        fv = sum(g["q4_fv_m"] or 0.0 for g in groups)
        rows = sum(g["q4_rows"] for g in groups)
        print(
            f"  {rule}: {len(names)} names, {len(ciks)} CIKs, "
            f"{len(groups)} (name,cik) groups, {rows} Q4 rows, {fv:,.0f} FV_m"
        )
    for rule, n in unmatched:
        print(f"  {rule}: {n} flagged names with NO Q4 footprint (not queued)")

    print()
    print("=== Part B summary (Q4 queue items by dispatch tier) ===")
    from collections import Counter

    tier_ct = Counter((r[0], r[3]) for r in out_rows)
    for (tier, lane), n in sorted(tier_ct.items()):
        print(f"  tier {tier} ({lane}): {n} items")
    done = sum(1 for r in out_rows if r[13])
    print(f"  items with existing verdict: {done}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
