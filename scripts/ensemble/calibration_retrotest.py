"""Retro-test candidate rule calibrations against ens2 B1 adjudications.

For each high-FP weak rule, re-evaluates the OLD predicate and each NEW
candidate predicate on current unified holdings, per adjudicated ens2 flag
group (cik, report_date, rule). A group is SUPPRESSED by a candidate when the
old predicate fires >=1 row but the new predicate fires 0 rows for that
CIK-quarter.

Scoring per candidate:
  fa_suppressed / fa_groups     -> false alarms removed (higher is better)
  real_lost / real_groups       -> adjudicated real errors lost (lower is better)
  rows_old -> rows_new          -> full-dataset flag-volume delta (BDC rows)

CAVEATS (report honestly):
  - B1 verdicts are per flag GROUP, not per row. real_error means ">=1 real
    row in the group"; suppressing a real group may drop mostly-FA rows plus
    the real one. Treat real_lost as a hard loss anyway (conservative).
  - Holdings have drifted since the queue was built; groups where the old
    predicate no longer fires are counted as irreproducible and excluded.

Read-only over holdings; writes calibration_retrotest.csv to the batch dir.
ASCII only. No network.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.config import (  # noqa: E402
    FUND_FINANCIALS_FILE,
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
)

BATCH = Path("data/output/ensemble/ens2")
VERDICTS = Path("data/output/review_queue/verdicts")
DECIDED = {"real_error", "false_alarm"}

# Keyword screen for unfunded-commitment style positions (extends the X06
# list with 'revolv' to cover revolver/revolving).
_KW = ("revolv", "delayed draw", "unfunded", "undrawn", "commitment",
       "letter of credit", "credit facility")
_TEXT = ("lower(COALESCE(CAST(issuer_name AS VARCHAR), '') || ' ' || "
         "COALESCE(CAST(instrument_description AS VARCHAR), '') || ' ' || "
         "COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''))")
KW_SQL = "(" + " OR ".join(f"{_TEXT} LIKE '%{k}%'" for k in _KW) + ")"

FV = "TRY_CAST(fair_value AS DOUBLE)"
COST = "TRY_CAST(cost AS DOUBLE)"
PCT = "TRY_CAST(pct_of_net_assets AS DOUBLE)"
SH = "TRY_CAST(shares_held AS DOUBLE)"
PRIN = "TRY_CAST(principal_amount AS DOUBLE)"

# Row-level rules: rule -> {variant_name: row predicate SQL}. 'old' required.
ROW_RULES: dict[str, dict[str, str]] = {
    "C103": {
        "old": f"{FV} < 0",
        "excl_negcost": f"{FV} < 0 AND NOT COALESCE({COST} < 0, FALSE)",
        "excl_kw": f"{FV} < 0 AND NOT {KW_SQL}",
        "excl_both": (f"{FV} < 0 AND NOT COALESCE({COST} < 0, FALSE) "
                      f"AND NOT {KW_SQL}"),
        "both_keepcash": (f"{FV} < 0 AND (COALESCE(CAST(asset_class AS VARCHAR), '') = 'CASH' "
                          f"OR (NOT COALESCE({COST} < 0, FALSE) AND NOT {KW_SQL}))"),
    },
    "C104": {
        "old": f"{FV} = 0",
        "substance": (f"{FV} = 0 AND (COALESCE({SH}, 0) > 0 "
                      f"OR COALESCE({PRIN}, 0) > 0 OR COALESCE({COST}, 0) > 0)"),
        # segment exclusion: worthless equity/warrants and unfunded commitments
        # are the legitimate-zero classes; zero FV on a funded debt row is the
        # suspicious residual.
        "nonequity_nokw": (
            f"{FV} = 0 "
            "AND COALESCE(CAST(asset_class AS VARCHAR), '') <> 'PRIVATE_EQUITY' "
            "AND COALESCE(CAST(index_classification AS VARCHAR), '') "
            "    NOT IN ('COMMON_EQUITY', 'PREFERRED_EQUITY') "
            f"AND NOT {KW_SQL} "
            f"AND {_TEXT} NOT LIKE '%warrant%'"
        ),
        # column-shift twin (Navistar signature): a zero-FV row whose COST
        # equals another same-quarter same-issuer row's FAIR VALUE -- the
        # broken duplicate of a correctly-extracted row.
        "shift_twin": (
            f"{FV} = 0 AND COALESCE({COST}, 0) > 0 AND EXISTS ("
            "  SELECT 1 FROM h h2"
            "  WHERE h2.cik10 = h.cik10 AND h2.rdate = h.rdate"
            "    AND h2.issuer_name = h.issuer_name"
            f"   AND ABS(TRY_CAST(h2.fair_value AS DOUBLE) - {COST})"
            f"        <= GREATEST(1.0, 0.0001 * {COST}))"
        ),
    },
    "C107": {
        "old": f"{COST} < 0",
        "excl_negfv": f"{COST} < 0 AND NOT COALESCE({FV} < 0, FALSE)",
        "excl_kw": f"{COST} < 0 AND NOT {KW_SQL}",
        "excl_both": (f"{COST} < 0 AND NOT COALESCE({FV} < 0, FALSE) "
                      f"AND NOT {KW_SQL}"),
    },
    "C404": {
        "old": f"{PCT} < 0",
        "excl_negfv": f"{PCT} < 0 AND NOT COALESCE({FV} < 0, FALSE)",
    },
    # weak engine fmt_* rules: violation predicates among present values;
    # gate approximated as source='bdc' (weak_base is dim-filtered BDC rows).
    "fmt_cost": {
        "old": (f"NOT ({COST} IS NOT NULL AND {COST} BETWEEN 0 AND 3e9) "
                "AND trim(COALESCE(CAST(cost AS VARCHAR), '')) <> ''"),
        "allow_neg": (f"NOT ({COST} IS NOT NULL AND {COST} BETWEEN -3e9 AND 3e9) "
                      "AND trim(COALESCE(CAST(cost AS VARCHAR), '')) <> ''"),
    },
    "fmt_pct_of_net_assets": {
        "old": (f"NOT ({PCT} IS NOT NULL AND {PCT} BETWEEN 0 AND 100) "
                "AND trim(COALESCE(CAST(pct_of_net_assets AS VARCHAR), '')) <> ''"),
        "allow_neg": (f"NOT ({PCT} IS NOT NULL AND {PCT} BETWEEN -100 AND 100) "
                      "AND trim(COALESCE(CAST(pct_of_net_assets AS VARCHAR), '')) <> ''"),
    },
    "pct_position_concentration": {
        "old": f"pct_of_net_assets IS NOT NULL AND NOT ({PCT} BETWEEN 0 AND 25)",
        "pos_only": f"pct_of_net_assets IS NOT NULL AND {PCT} > 25",
    },
}

# Aggregate rule PCT01: variant -> pct_sum threshold.
PCT01_THRESHOLDS = {"old": 200.0, "t225": 225.0, "t235": 235.0, "t250": 250.0}


def _unified_rel() -> str:
    if UNIFIED_HOLDINGS_PARQUET_FILE.exists():
        return f"read_parquet('{UNIFIED_HOLDINGS_PARQUET_FILE.as_posix()}')"
    return f"read_csv_auto('{UNIFIED_HOLDINGS_FILE.as_posix()}', sample_size=-1)"


def load_groups() -> list[dict]:
    """Adjudicated ens2 flag groups for target rules."""
    targets = set(ROW_RULES) | {"PCT01"}
    with open(BATCH / "review_ids.csv", newline="", encoding="utf-8") as fh:
        meta = list(csv.DictReader(fh))
    groups = []
    for m in meta:
        if m["rule_name"] not in targets:
            continue
        p = VERDICTS / f"{m['review_id']}.json"
        if not p.exists():
            continue
        try:
            v = json.load(open(p, encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        verdict = (v.get("verdict") or "").strip().lower()
        if verdict not in DECIDED:
            continue
        groups.append({
            "rule": m["rule_name"],
            "cik": m["cik"].zfill(10),
            "report_date": m["report_date"],
            "verdict": verdict,
        })
    return groups


def main() -> int:
    groups = load_groups()
    print(f"adjudicated target groups: {len(groups)} "
          f"(real={sum(1 for g in groups if g['verdict'] == 'real_error')}, "
          f"fa={sum(1 for g in groups if g['verdict'] == 'false_alarm')})")

    con = duckdb.connect()
    con.execute(
        f"""
        CREATE TABLE h AS
        SELECT LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik10,
               CAST(report_date AS VARCHAR) AS rdate,
               source, asset_class, index_classification, issuer_name,
               instrument_description,
               bdc_investment_identifier, fair_value, cost, principal_amount,
               shares_held, pct_of_net_assets
        FROM {_unified_rel()}
        WHERE lower(CAST(source AS VARCHAR)) = 'bdc'
        """
    )
    n = con.execute("SELECT count(*) FROM h").fetchone()[0]
    print(f"holdings BDC rows: {n}")

    out_rows = []

    # --- row-level rules ---------------------------------------------------
    for rule, variants in ROW_RULES.items():
        gsub = [g for g in groups if g["rule"] == rule]
        if not gsub:
            print(f"\n{rule}: no adjudicated groups, skipping")
            continue
        # per (cik, rdate) fire counts for every variant in one pass
        exprs = ", ".join(
            f"SUM(CASE WHEN {sql} THEN 1 ELSE 0 END) AS n_{name}"
            for name, sql in variants.items()
        )
        per_cq = {
            (r[0], r[1]): dict(zip(variants.keys(), r[2:]))
            for r in con.execute(
                f"SELECT cik10, rdate, {exprs} FROM h GROUP BY cik10, rdate"
            ).fetchall()
        }
        totals = con.execute(
            f"SELECT {exprs} FROM h"
        ).fetchone()
        totals = dict(zip(variants.keys(), totals))

        print(f"\n=== {rule} ===  total rows firing: "
              + ", ".join(f"{k}={totals[k]}" for k in variants))
        repro = [g for g in gsub
                 if per_cq.get((g["cik"], g["report_date"]), {}).get("old", 0) > 0]
        n_irr = len(gsub) - len(repro)
        fa = [g for g in repro if g["verdict"] == "false_alarm"]
        real = [g for g in repro if g["verdict"] == "real_error"]
        print(f"  groups: {len(gsub)} adjudicated, {n_irr} irreproducible, "
              f"{len(fa)} FA / {len(real)} real reproducible")
        for name in variants:
            if name == "old":
                continue
            fa_sup = sum(1 for g in fa
                         if per_cq[(g["cik"], g["report_date"])][name] == 0)
            real_lost = sum(1 for g in real
                            if per_cq[(g["cik"], g["report_date"])][name] == 0)
            print(f"  {name:14s} FA suppressed {fa_sup}/{len(fa)}, "
                  f"real lost {real_lost}/{len(real)}, "
                  f"rows {totals['old']} -> {totals[name]}")
            out_rows.append({
                "rule": rule, "variant": name,
                "fa_groups": len(fa), "fa_suppressed": fa_sup,
                "real_groups": len(real), "real_lost": real_lost,
                "irreproducible": n_irr,
                "rows_old": totals["old"], "rows_new": totals[name],
            })

    # --- C404 NAV-consistency (implied-NAV cross-check) ----------------------
    # B1 decided these flags by recomputing FV / net_assets * 100 and checking
    # it against the printed pct. Reproduce that deterministically: implied NAV
    # per CIK-quarter = median(FV / pct * 100) over materially-sized rows, then
    # flag negative pct only when it is INCONSISTENT with FV * implied NAV.
    gsub = [g for g in groups if g["rule"] == "C404"]
    if gsub:
        con.execute(
            f"""
            CREATE TABLE nav AS
            SELECT cik10, rdate,
                   MEDIAN({FV} / NULLIF({PCT}, 0) * 100) AS nav_est
            FROM h
            WHERE ABS({PCT}) >= 0.5 AND {FV} IS NOT NULL
            GROUP BY cik10, rdate
            HAVING COUNT(*) >= 5
            """
        )
        variants = {}
        for name, tol in (("nav_tol006", 0.06), ("nav_tol015", 0.15)):
            variants[name] = (
                f"{PCT} < 0 AND (nav_est IS NULL OR nav_est <= 0 OR "
                f"ABS({PCT} - ({FV} / nav_est * 100)) "
                f"> GREATEST({tol}, 0.5 * ABS({FV} / nav_est * 100)))"
            )
        # sign inconsistency: negative pct is only anomalous when the row's FV
        # is non-negative AND the fund's NAV is not negative (negative-NAV
        # quarters legitimately print negative pct on positive-FV rows).
        variants["sign_incons"] = (
            f"{PCT} < 0 AND COALESCE({FV} >= 0, TRUE) "
            "AND COALESCE(nav_est >= 0, TRUE)"
        )
        variants["old"] = f"{PCT} < 0"
        exprs = ", ".join(
            f"SUM(CASE WHEN {sql} THEN 1 ELSE 0 END) AS n_{name}"
            for name, sql in variants.items()
        )
        per_cq = {
            (r[0], r[1]): dict(zip(variants.keys(), r[2:]))
            for r in con.execute(
                f"""
                SELECT j.cik10, j.rdate, {exprs}
                FROM (SELECT h.*, nav.nav_est FROM h
                      LEFT JOIN nav ON nav.cik10 = h.cik10 AND nav.rdate = h.rdate) j
                GROUP BY j.cik10, j.rdate
                """
            ).fetchall()
        }
        totals = con.execute(
            f"""
            SELECT {exprs}
            FROM (SELECT h.*, nav.nav_est FROM h
                  LEFT JOIN nav ON nav.cik10 = h.cik10 AND nav.rdate = h.rdate) j
            """
        ).fetchone()
        totals = dict(zip(variants.keys(), totals))
        print(f"\n=== C404 nav-consistency ===  total rows firing: "
              + ", ".join(f"{k}={totals[k]}" for k in variants))
        repro = [g for g in gsub
                 if per_cq.get((g["cik"], g["report_date"]), {}).get("old", 0) > 0]
        fa = [g for g in repro if g["verdict"] == "false_alarm"]
        real = [g for g in repro if g["verdict"] == "real_error"]
        print(f"  groups: {len(gsub)} adjudicated, {len(gsub) - len(repro)} "
              f"irreproducible, {len(fa)} FA / {len(real)} real reproducible")
        for name in variants:
            if name == "old":
                continue
            fa_sup = sum(1 for g in fa
                         if per_cq[(g["cik"], g["report_date"])][name] == 0)
            real_lost = sum(1 for g in real
                            if per_cq[(g["cik"], g["report_date"])][name] == 0)
            print(f"  {name:14s} FA suppressed {fa_sup}/{len(fa)}, "
                  f"real lost {real_lost}/{len(real)}, "
                  f"rows {totals['old']} -> {totals[name]}")
            out_rows.append({
                "rule": "C404", "variant": name,
                "fa_groups": len(fa), "fa_suppressed": fa_sup,
                "real_groups": len(real), "real_lost": real_lost,
                "irreproducible": len(gsub) - len(repro),
                "rows_old": totals["old"], "rows_new": totals[name],
            })

    # --- PCT01 (aggregate) ---------------------------------------------------
    gsub = [g for g in groups if g["rule"] == "PCT01"]
    if gsub:
        per_cq = {
            (r[0], r[1]): r[2]
            for r in con.execute(
                f"""
                SELECT cik10, rdate, SUM({PCT}) AS pct_sum
                FROM h
                WHERE {PCT} IS NOT NULL AND {PCT} != 0
                GROUP BY cik10, rdate
                HAVING COUNT(*) >= 5
                """
            ).fetchall()
        }
        all_sums = list(per_cq.values())
        print(f"\n=== PCT01 ===  cik-quarters with pct_sum: {len(all_sums)}")
        repro = [g for g in gsub
                 if per_cq.get((g["cik"], g["report_date"]), 0)
                 and per_cq[(g["cik"], g["report_date"])] > PCT01_THRESHOLDS["old"]]
        n_irr = len(gsub) - len(repro)
        fa = [g for g in repro if g["verdict"] == "false_alarm"]
        real = [g for g in repro if g["verdict"] == "real_error"]
        print(f"  groups: {len(gsub)} adjudicated, {n_irr} irreproducible, "
              f"{len(fa)} FA / {len(real)} real reproducible")
        for g in repro:
            g["_sum"] = per_cq[(g["cik"], g["report_date"])]
        print("  adjudicated sums: "
              + "; ".join(f"{g['verdict'][:4]}={g['_sum']:.1f}" for g in
                          sorted(repro, key=lambda x: x["_sum"])))
        for name, thr in PCT01_THRESHOLDS.items():
            if name == "old":
                continue
            fa_sup = sum(1 for g in fa if g["_sum"] <= thr)
            real_lost = sum(1 for g in real if g["_sum"] <= thr)
            n_flag = sum(1 for s in all_sums if s > thr)
            n_old = sum(1 for s in all_sums if s > PCT01_THRESHOLDS["old"])
            print(f"  {name:14s} FA suppressed {fa_sup}/{len(fa)}, "
                  f"real lost {real_lost}/{len(real)}, "
                  f"cik-qtrs {n_old} -> {n_flag}")
            out_rows.append({
                "rule": "PCT01", "variant": name,
                "fa_groups": len(fa), "fa_suppressed": fa_sup,
                "real_groups": len(real), "real_lost": real_lost,
                "irreproducible": n_irr,
                "rows_old": n_old, "rows_new": n_flag,
            })

        # NAV-anchored variant: compare extracted pct_sum to the fund's own
        # net assets (fund_financials.csv). expected_sum = total_FV/NAV*100;
        # flag when extracted sum exceeds expected by > tol points. Fallback
        # to the >200 threshold when no NAV is available.
        con.execute(
            f"""
            CREATE TABLE ff AS
            SELECT LPAD(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik10,
                   CAST(report_date AS VARCHAR) AS rdate,
                   MEDIAN(TRY_CAST(net_assets AS DOUBLE)) AS nav,
                   MEDIAN(TRY_CAST(investments_at_fair_value AS DOUBLE)) AS ioafv
            FROM read_csv_auto('{FUND_FINANCIALS_FILE.as_posix()}', sample_size=-1)
            WHERE TRY_CAST(net_assets AS DOUBLE) > 0
            GROUP BY 1, 2
            """
        )
        # Two anchors: 'expected' = extracted total_FV / NAV (CIRCULAR -- a
        # leaked row inflates both sides); 'indep' = companyfacts
        # investments_at_fair_value / NAV (independent of extraction).
        anchored = {
            (r[0], r[1]): {"pct_sum": r[2], "expected": r[3], "indep": r[4]}
            for r in con.execute(
                f"""
                WITH agg AS (
                    SELECT cik10, rdate,
                           SUM({PCT}) AS pct_sum,
                           SUM({FV}) AS total_fv
                    FROM h
                    WHERE {PCT} IS NOT NULL AND {PCT} != 0
                    GROUP BY cik10, rdate
                    HAVING COUNT(*) >= 5
                )
                SELECT a.cik10, a.rdate, a.pct_sum,
                       CASE WHEN ff.nav > 0 THEN a.total_fv / ff.nav * 100 END AS expected,
                       CASE WHEN ff.nav > 0 AND ff.ioafv > 0
                            THEN ff.ioafv / ff.nav * 100 END AS indep
                FROM agg a LEFT JOIN ff ON ff.cik10 = a.cik10 AND ff.rdate = a.rdate
                """
            ).fetchall()
        }
        n_with_nav = sum(1 for v in anchored.values() if v["expected"] is not None)
        n_with_ind = sum(1 for v in anchored.values() if v["indep"] is not None)
        print(f"  NAV anchor coverage: {n_with_nav}/{len(anchored)} cik-quarters "
              f"(independent IOAFV anchor: {n_with_ind})")
        for g in repro:
            a = anchored.get((g["cik"], g["report_date"]))
            g["_exp"] = a["expected"] if a else None
            g["_ind"] = a["indep"] if a else None
        print("  adjudicated sum / circular-expected / independent-expected: "
              + "; ".join(
                  f"{g['verdict'][:4]}={g['_sum']:.1f}/"
                  + (f"{g['_exp']:.1f}" if g["_exp"] is not None else "noNAV") + "/"
                  + (f"{g['_ind']:.1f}" if g["_ind"] is not None else "noIOAFV")
                  for g in sorted(repro, key=lambda x: x["_sum"])))
        for name, key, tol in (("anchored_d10", "_exp", 10.0),
                               ("anchored_d15", "_exp", 15.0),
                               ("indep_d10", "_ind", 10.0),
                               ("indep_d15", "_ind", 15.0)):
            akey = "expected" if key == "_exp" else "indep"

            def fires(sums, exp, t=tol):
                if exp is None:
                    return sums > 200.0
                return (sums - exp) > t
            fa_sup = sum(1 for g in fa if not fires(g["_sum"], g[key]))
            real_lost = sum(1 for g in real if not fires(g["_sum"], g[key]))
            n_flag = sum(1 for v in anchored.values()
                         if fires(v["pct_sum"], v[akey]))
            print(f"  {name:14s} FA suppressed {fa_sup}/{len(fa)}, "
                  f"real lost {real_lost}/{len(real)}, "
                  f"cik-qtrs {n_old} -> {n_flag}")
            out_rows.append({
                "rule": "PCT01", "variant": name,
                "fa_groups": len(fa), "fa_suppressed": fa_sup,
                "real_groups": len(real), "real_lost": real_lost,
                "irreproducible": n_irr,
                "rows_old": n_old, "rows_new": n_flag,
            })

    out = BATCH / "calibration_retrotest.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
