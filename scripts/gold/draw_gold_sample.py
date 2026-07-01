"""Draw the first stratified gold-set sample for the v1 BDC cohort.

READ-ONLY w.r.t. data/output and frontend. Writes ONLY to data/gold/samples/.
All heavy work stays in DuckDB (Poisson PPS is vectorized via a deterministic
hash, so there is no large fetch and no row-wise pandas). The drawn frame is
small (a few hundred units) and is the only thing pulled into Python.

Strata (see data/gold/labeler_protocol.md):
  tail_census    -- the top-K positions by |FV| (certainty, pi=1) + top CIK-qtrs
  pps_body       -- Poisson PPS on |FV| over the non-tail body (HT estimator)
  surfaced_flag  -- panel flags with surface != '' (precision population)
  suppressed_flag-- panel flags that are suppressed (recall / FN population)
  silent_bulk    -- positions in no-strong-anchor CIK-qtrs carrying no flag

Usage:
  python scripts/gold/draw_gold_sample.py            # default sizes
  python scripts/gold/draw_gold_sample.py --k-tail 120 --n-pps 80 ...
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
UNIFIED_PARQUET = ROOT / "data" / "output" / "private_markets_holdings.parquet"
FUND_FIN = ROOT / "data" / "output" / "fund_financials.csv"
LEDGER = ROOT / "data" / "output" / "shadow" / "validation_results_ledger.csv"
COVERAGE_GAPS = ROOT / "data" / "output" / "shadow" / "validation_coverage_gaps.csv"
WRAPPER_DIR = ROOT / "data" / "overrides" / "bdc_xbrl_wrappers"
PUBLISHED_MANIFEST = ROOT / "data" / "overrides" / "wrapper_cohorts" / "v2_70_gate_verified_wrapper_manifest.json"
OUT_DIR = ROOT / "data" / "gold" / "samples"

SEED = 20260616          # frozen; deterministic draw
PERIOD_START = "2022-10-01"
DRAW_ID = "batch1"


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT)
        ).decode().strip()
    except Exception:
        return "unknown"


def cohort_ciks() -> list[str]:
    ciks = []
    for p in sorted(WRAPPER_DIR.glob("*.json")):
        stem = p.stem
        if stem.isdigit() and len(stem) == 10:
            ciks.append(stem)
    return ciks


def published_ciks() -> set[str]:
    try:
        data = json.loads(PUBLISHED_MANIFEST.read_text())
    except Exception:
        return set()
    out = set()
    items = data if isinstance(data, list) else data.get("ciks") or data.get("entries") or []
    for it in items:
        c = it if isinstance(it, str) else (it.get("cik") if isinstance(it, dict) else None)
        if c:
            out.add(str(c).zfill(10))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2025-12-31", help="as-of date for the FV-error snapshot; each fund's latest filing on/before this date (default Q4 2025)")
    ap.add_argument("--k-tail", type=int, default=200, help="top-K positions by |FV| in the tail census (over the as-of snapshot)")
    ap.add_argument("--n-tail-cikq", type=int, default=25, help="top CIK-quarters by total FV for rollup labels (over the as-of snapshot)")
    ap.add_argument("--n-pps", type=int, default=100, help="target Poisson-PPS body sample size (over the as-of snapshot)")
    ap.add_argument("--n-surfaced", type=int, default=40)
    ap.add_argument("--n-suppressed", type=int, default=40)
    ap.add_argument("--n-silent", type=int, default=40)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ciks = cohort_ciks()
    pub = published_ciks()
    sha = git_sha()
    print(f"[draw] cohort CIKs={len(ciks)} published={len(pub)} pipeline_version={sha}", flush=True)

    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    cik_list = ",".join(f"'{c}'" for c in ciks)

    # ---- Base cohort/period BDC positions, normalized keys -------------------
    con.execute(f"""
        CREATE TEMP VIEW base AS
        SELECT
            lpad(cast(cast(cik AS BIGINT) AS VARCHAR), 10, '0')        AS cik,
            report_date,
            accession_number                                           AS accession,
            issuer_name,
            bdc_investment_identifier,
            instrument_description,
            try_cast(fair_value AS DOUBLE)        AS fair_value,
            try_cast(cost AS DOUBLE)             AS cost,
            try_cast(pct_of_net_assets AS DOUBLE) AS pct_of_net_assets,
            index_classification, lien_position,
            cast(position_id AS VARCHAR)  AS position_id,
            cast(position_key AS VARCHAR) AS position_key,
            coalesce(cast(position_id AS VARCHAR), cast(position_key AS VARCHAR),
                     cast(cik AS VARCHAR) || '|' || cast(report_date AS VARCHAR) || '|' ||
                     coalesce(bdc_investment_identifier, issuer_name, '') || '|' ||
                     coalesce(fair_value, ''))                         AS uid
        FROM read_parquet('{UNIFIED_PARQUET.as_posix()}')
        WHERE upper(source) LIKE 'BDC%'
          AND report_date >= '{PERIOD_START}'
          AND lpad(cast(cast(cik AS BIGINT) AS VARCHAR), 10, '0') IN ({cik_list})
          AND try_cast(fair_value AS DOUBLE) IS NOT NULL
    """)
    n_base = con.execute("SELECT count(*) FROM base").fetchone()[0]
    total_fv = con.execute("SELECT sum(abs(fair_value)) FROM base").fetchone()[0] or 0.0
    print(f"[draw] base positions={n_base:,} sum|FV|=${total_fv/1e9:.1f}B (all-history)", flush=True)

    # ---- As-of snapshot = each fund's latest filing on/before --as-of --------
    # The FV-error strata (tail + body) are drawn from the snapshot so the
    # dollar-weighted estimate targets the PUBLISHED as-of cohort FV (default Q4
    # 2025), not a multi-quarter cumulative base or the bleeding edge. (Silent-bulk
    # + flags stay all-history on purpose.)
    con.execute(f"""
        CREATE TEMP VIEW snap AS
        SELECT b.* FROM base b
        JOIN (SELECT cik, max(report_date) md FROM base
              WHERE report_date <= '{args.as_of}' GROUP BY cik) m
          ON b.cik = m.cik AND b.report_date = m.md
    """)
    n_snap = con.execute("SELECT count(*) FROM snap").fetchone()[0]
    snap_fv = con.execute("SELECT sum(abs(fair_value)) FROM snap").fetchone()[0] or 0.0
    snap_dates = con.execute(
        "SELECT count(DISTINCT cik), count(DISTINCT report_date) FROM snap").fetchone()
    print(f"[draw] as-of {args.as_of} snapshot: funds={snap_dates[0]} "
          f"positions={n_snap:,} sum|FV|=${snap_fv/1e9:.1f}B "
          f"({snap_dates[1]} distinct report_dates)", flush=True)

    # ---- Stratum: tail census (top-K snapshot positions by |FV|) -------------
    con.execute(f"""
        CREATE TEMP VIEW tail AS
        SELECT *, row_number() OVER (ORDER BY abs(fair_value) DESC, uid) AS rk
        FROM snap QUALIFY rk <= {args.k_tail}
    """)
    tail_min_fv, tail_cov = con.execute(
        "SELECT min(abs(fair_value)), sum(abs(fair_value)) FROM tail"
    ).fetchone()
    print(f"[draw] tail_census K={args.k_tail} min|FV|=${(tail_min_fv or 0)/1e6:.1f}M "
          f"snapshot_coverage={100*(tail_cov or 0)/snap_fv:.1f}%", flush=True)

    # ---- Stratum: PPS body (Poisson, deterministic hash) ---------------------
    # pi_i = min(1, n * size_i / total_size_body); include if u(uid) < pi_i.
    con.execute(f"""
        CREATE TEMP VIEW body AS
        SELECT b.*, abs(b.fair_value) AS size
        FROM snap b
        WHERE b.uid NOT IN (SELECT uid FROM tail)
    """)
    body_total = con.execute("SELECT sum(size) FROM body").fetchone()[0] or 1.0
    con.execute(f"""
        CREATE TEMP VIEW pps AS
        SELECT * FROM (
            SELECT *,
                least(1.0, {args.n_pps} * size / {body_total}) AS pi,
                (hash(uid || '|pps|{SEED}') % 1000000000) / 1000000000.0 AS u
            FROM body
        ) WHERE u < pi
    """)
    n_pps = con.execute("SELECT count(*) FROM pps").fetchone()[0]
    print(f"[draw] pps_body realized n={n_pps} (target {args.n_pps})", flush=True)

    # ---- Stratum: tail CIK-quarters (rollup labels) --------------------------
    # Rank by total position FV; carry the independent companyfacts anchor as a
    # CANDIDATE only (human confirms from source).
    con.execute(f"""
        CREATE TEMP VIEW cikq AS
        WITH agg AS (
            SELECT cik, report_date,
                   any_value(accession) AS accession,
                   count(*)             AS pipeline_position_count,
                   sum(fair_value)      AS pipeline_sum_fv
            FROM snap GROUP BY cik, report_date
        ),
        ff AS (
            SELECT lpad(cast(try_cast(cik AS BIGINT) AS VARCHAR),10,'0') AS cik,
                   report_date,
                   any_value(try_cast(investments_at_fair_value AS DOUBLE)) AS ff_inv_fv
            FROM read_csv_auto('{FUND_FIN.as_posix()}', header=true, all_varchar=true)
            WHERE try_cast(cik AS BIGINT) IS NOT NULL
            GROUP BY 1,2
        )
        SELECT a.*, f.ff_inv_fv AS candidate_total_fv,
               row_number() OVER (ORDER BY a.pipeline_sum_fv DESC) AS rk
        FROM agg a LEFT JOIN ff f USING (cik, report_date)
        QUALIFY rk <= {args.n_tail_cikq}
    """)
    n_cikq = con.execute("SELECT count(*) FROM cikq").fetchone()[0]
    print(f"[draw] tail CIK-quarters={n_cikq}", flush=True)

    # ---- accession resolver for flag units (cik, report_date) -> accession ---
    con.execute("""
        CREATE TEMP VIEW acc_map AS
        SELECT cik, report_date, any_value(accession) AS accession
        FROM base GROUP BY cik, report_date
    """)

    # ---- Stratum: surfaced & suppressed flags (from the panel ledger) --------
    con.execute(f"""
        CREATE TEMP VIEW ledger AS
        SELECT
            lpad(cast(try_cast(cik AS BIGINT) AS VARCHAR),10,'0') AS cik,
            engine, rule_name, tier, enforcement,
            period_kind, period, status, metric, metric_name,
            coalesce(confidence,'') AS confidence,
            coalesce(surface,'')    AS surface
        FROM read_csv_auto('{LEDGER.as_posix()}', header=true, all_varchar=true)
        WHERE lower(status) NOT IN ('pass','skip')
          AND try_cast(cik AS BIGINT) IS NOT NULL
          AND lpad(cast(try_cast(cik AS BIGINT) AS VARCHAR),10,'0') IN ({cik_list})
    """)
    # surfaced = precision population
    con.execute(f"""
        CREATE TEMP VIEW surfaced AS
        SELECT l.*, m.accession,
               (hash(l.cik || l.rule_name || l.period || '|surf|{SEED}') % 1000000000)/1e9 AS u
        FROM ledger l
        LEFT JOIN acc_map m
          ON l.cik = m.cik AND l.period = m.report_date
        WHERE lower(surface) = 'true'
        QUALIFY row_number() OVER (
            ORDER BY (hash(l.cik || l.rule_name || l.period || '|surf|{SEED}') % 1000000000)/1e9
        ) <= {args.n_surfaced}
    """)
    n_surf = con.execute("SELECT count(*) FROM surfaced").fetchone()[0]
    # suppressed = recall / FN population, oversample by confidence class
    con.execute(f"""
        CREATE TEMP VIEW suppressed AS
        SELECT l.*, m.accession,
               (hash(l.cik || l.rule_name || l.period || '|supp|{SEED}') % 1000000000)/1e9 AS u
        FROM ledger l
        LEFT JOIN acc_map m
          ON l.cik = m.cik AND l.period = m.report_date
        WHERE lower(surface) = 'false'
        QUALIFY row_number() OVER (
            PARTITION BY l.confidence
            ORDER BY (hash(l.cik || l.rule_name || l.period || '|supp|{SEED}') % 1000000000)/1e9
        ) <= {max(1, args.n_suppressed // 3)}
    """)
    n_supp = con.execute("SELECT count(*) FROM suppressed").fetchone()[0]
    print(f"[draw] surfaced_flag={n_surf} suppressed_flag={n_supp}", flush=True)

    # ---- Stratum: silent-bulk (no-strong-anchor CIK-qtrs, no flag fired) -----
    con.execute(f"""
        CREATE TEMP VIEW gaps AS
        SELECT lpad(cast(try_cast(cik AS BIGINT) AS VARCHAR),10,'0') AS cik, period
        FROM read_csv_auto('{COVERAGE_GAPS.as_posix()}', header=true, all_varchar=true)
        WHERE try_cast(cik AS BIGINT) IS NOT NULL
    """)
    con.execute(f"""
        CREATE TEMP VIEW silent AS
        SELECT b.*,
               (hash(b.uid || '|silent|{SEED}') % 1000000000)/1e9 AS u
        FROM base b
        JOIN gaps g ON b.cik = g.cik AND b.report_date = g.period
        WHERE b.uid NOT IN (SELECT uid FROM tail)
          AND b.uid NOT IN (SELECT uid FROM pps)
        QUALIFY row_number() OVER (
            ORDER BY (hash(b.uid || '|silent|{SEED}') % 1000000000)/1e9
        ) <= {args.n_silent}
    """)
    n_silent = con.execute("SELECT count(*) FROM silent").fetchone()[0]
    silent_N = con.execute("""
        SELECT count(*) FROM base b
        JOIN gaps g ON b.cik=g.cik AND b.report_date=g.period
    """).fetchone()[0]
    print(f"[draw] silent_bulk={n_silent} (from N={silent_N})", flush=True)

    # ---- Assemble the frame --------------------------------------------------
    frame: list[dict] = []

    def pos_row(r, stratum, pi):
        return {
            "unit_type": "position", "stratum": stratum, "draw_id": DRAW_ID,
            "cik": r["cik"], "report_date": r["report_date"], "accession": r["accession"],
            "source_identifier": r["bdc_investment_identifier"] or r["issuer_name"],
            "issuer_name": r["issuer_name"],
            "unit_uid": r["position_id"] or r["position_key"],
            "pi": pi, "design_weight": (1.0 / pi) if pi else None,
            "in_published_cohort": r["cik"] in pub,
            "pipeline": {
                "fair_value": r["fair_value"], "cost": r["cost"],
                "pct_of_net_assets": r["pct_of_net_assets"],
                "index_classification": r["index_classification"],
                "lien_position": r["lien_position"],
            },
        }

    for r in con.execute("SELECT * FROM tail").fetchdf().to_dict("records"):
        frame.append(pos_row(r, "tail_census", 1.0))
    for r in con.execute("SELECT * FROM pps").fetchdf().to_dict("records"):
        frame.append(pos_row(r, "pps_body", float(r["pi"])))
    silent_pi = (args.n_silent / silent_N) if silent_N else None
    for r in con.execute("SELECT * FROM silent").fetchdf().to_dict("records"):
        frame.append(pos_row(r, "silent_bulk", silent_pi))

    for r in con.execute("SELECT * FROM cikq").fetchdf().to_dict("records"):
        frame.append({
            "unit_type": "cik_quarter", "stratum": "tail_census", "draw_id": DRAW_ID,
            "cik": r["cik"], "report_date": r["report_date"], "accession": r["accession"],
            "pi": 1.0, "design_weight": 1.0, "in_published_cohort": r["cik"] in pub,
            "pipeline": {
                "position_count": int(r["pipeline_position_count"]),
                "sum_fair_value": r["pipeline_sum_fv"],
            },
            "candidate_total_fv": r["candidate_total_fv"],
        })

    for view, stratum in (("surfaced", "surfaced_flag"), ("suppressed", "suppressed_flag")):
        for r in con.execute(f"SELECT * FROM {view}").fetchdf().to_dict("records"):
            frame.append({
                "unit_type": "flag", "stratum": stratum, "draw_id": DRAW_ID,
                "cik": r["cik"], "report_date": r.get("period"), "period": r["period"],
                "accession": r.get("accession"), "in_published_cohort": r["cik"] in pub,
                "flag": {
                    "engine": r["engine"], "rule_name": r["rule_name"], "tier": r["tier"],
                    "enforcement": r["enforcement"], "status": r["status"],
                    "metric": r["metric"], "metric_name": r["metric_name"],
                    "confidence": r["confidence"], "surface": r["surface"],
                },
            })

    # ---- Write frame + manifest ---------------------------------------------
    frame_path = OUT_DIR / f"sample_frame_{DRAW_ID}.jsonl"
    with frame_path.open("w", encoding="ascii") as fh:
        for row in frame:
            fh.write(json.dumps(row, default=str) + "\n")

    by_stratum: dict[str, int] = {}
    for row in frame:
        by_stratum[row["stratum"] + "/" + row["unit_type"]] = by_stratum.get(
            row["stratum"] + "/" + row["unit_type"], 0) + 1

    manifest = {
        "draw_id": DRAW_ID, "seed": SEED, "pipeline_version": sha,
        "period_start": PERIOD_START, "as_of": args.as_of,
        "cohort_ciks": len(ciks), "published_ciks": len(pub),
        "framing": (f"FV-error strata (tail_census, pps_body) drawn from the AS-OF "
                    f"SNAPSHOT = each fund's latest filing on/before {args.as_of}; "
                    f"silent_bulk and flag strata are all-history."),
        "base_positions": int(n_base), "base_sum_abs_fv": float(total_fv),
        "snapshot_positions": int(n_snap), "snapshot_sum_abs_fv": float(snap_fv),
        "params": vars(args),
        "tail_min_abs_fv": float(tail_min_fv or 0),
        "tail_snapshot_coverage_pct": float(100 * (tail_cov or 0) / snap_fv) if snap_fv else None,
        "pps_body_total_size": float(body_total),
        "silent_population_N": int(silent_N),
        "counts_by_stratum_unit": by_stratum,
        "total_units": len(frame),
        "estimators": {
            "tail_census": "certainty (pi=1); exact contribution",
            "pps_body": "Horvitz-Thompson, weight=1/pi, pi=min(1,n*size/total)",
            "silent_bulk": "SRS within no-anchor positions, pi=n/N",
            "surfaced_flag": "precision = confirmed_error / labeled; Wilson CI",
            "suppressed_flag": "FN rate = confirmed_error / labeled; Wilson CI; oversampled by confidence",
        },
    }
    manifest_path = OUT_DIR / f"sample_manifest_{DRAW_ID}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="ascii")

    print(f"[draw] wrote {len(frame)} units -> {frame_path.relative_to(ROOT)}")
    print(f"[draw] manifest -> {manifest_path.relative_to(ROOT)}")
    for k in sorted(by_stratum):
        print(f"         {k:32s} {by_stratum[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
