"""Enforcement-preview (dry-run): per enforcement-registry rule, which v1 wrapped
CIK-quarters it WOULD gate and the FV/row blast radius -- computed READ-ONLY from the
shadow ledger + coverage tiers, BEFORE any gate is wired.

Nothing here blocks the build or mutates production/registry data; it writes only
data/output/shadow/enforcement_preview.csv. This is the "measure before enforce"
discipline: no rule is promoted to blocking without its dry-run blast radius recorded.

Run: PYTHONPATH=. python scripts/enforcement_preview.py
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import duckdb

from pipeline.config import OUTPUT_DIR, OVERRIDES_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("enforcement_preview")

SHADOW = OUTPUT_DIR / "shadow"
REG_DIR = OVERRIDES_DIR / "enforcement_registry"
LEDGER = SHADOW / "validation_results_ledger.csv"
TIERS = SHADOW / "validation_quality_tiers.csv"


def wrapped_ciks() -> list[str]:
    return sorted(p.stem for p in (OVERRIDES_DIR / "bdc_xbrl_wrappers").glob("*.json")
                  if re.match(r"^\d{10}$", p.stem))


def main(argv: list[str] | None = None) -> int:
    reg = REG_DIR / "enforcement_registry.csv"
    if not LEDGER.exists():
        logger.error("ledger missing: %s (run shadow_validation_runner.py first)", LEDGER)
        return 1
    if not reg.exists():
        logger.error("registry missing: %s", reg)
        return 1

    con = duckdb.connect()
    con.execute(f"CREATE TABLE L AS SELECT * FROM read_csv_auto('{LEDGER.as_posix()}', sample_size=-1)")
    # LIVE registry = the active blocking floor; DORMANT = candidate what-ifs (none can
    # promote until a gold set exists). Union the shared columns so the preview shows both,
    # tagged by source -- the dormant rows are informational, not active gates.
    dorm = REG_DIR / "enforcement_registry_dormant.csv"
    sel = ("rule_id, ledger_engine, ledger_rule, quantity_group, authority_source, "
           "enforcement_state, deminimis_floor_usd")
    parts = [f"SELECT {sel}, 'live' AS registry_source "
             f"FROM read_csv_auto('{reg.as_posix()}', sample_size=-1, all_varchar=true)"]
    if dorm.exists():
        parts.append(f"SELECT {sel}, 'dormant' AS registry_source "
                     f"FROM read_csv_auto('{dorm.as_posix()}', sample_size=-1, all_varchar=true)")
    con.execute("CREATE TABLE R AS " + " UNION ALL ".join(parts))
    w = wrapped_ciks()
    con.execute("CREATE TABLE w(cik VARCHAR)")
    con.executemany("INSERT INTO w VALUES (?)", [(c,) for c in w])
    logger.info("registry rules: %d ; wrapped cohort: %d CIKs",
                con.execute("SELECT count(*) FROM R").fetchone()[0], len(w))

    # ledger flags with a localizability predicate + an FV proxy where the metric carries one
    con.execute(r"""
        CREATE TABLE F AS SELECT *,
            status IN ('fail','warn') AS flagged,
            (regexp_matches(CAST(period AS VARCHAR), '^\d{4}-\d{2}-\d{2}$')
             AND regexp_matches(CAST(cik AS VARCHAR), '^\d{10}$')) AS localizable,
            CASE metric_name WHEN 'affected_fv_m' THEN metric*1e6
                             WHEN 'total_fv_m'   THEN metric*1e6 ELSE NULL END AS fv_usd
        FROM L
    """)
    tiers_ok = TIERS.exists()
    if tiers_ok:
        con.execute(f"""CREATE TABLE T AS
            SELECT CAST(cik AS VARCHAR) cik, CAST(period AS VARCHAR) period, quality_tier
            FROM read_csv_auto('{TIERS.as_posix()}', sample_size=-1)""")

    rules = con.execute("""
        SELECT rule_id, ledger_engine, ledger_rule, enforcement_state, authority_source,
               deminimis_floor_usd, quantity_group
        FROM R WHERE enforcement_state IN ('blocking','candidate')
    """).fetchall()

    rows_out = []
    gated_union: set[tuple[str, str]] = set()
    for rid, eng, rl, state, auth, floor, qty in rules:
        eng_cond = "TRUE" if eng in (None, "*", "") else f"engine = '{eng}'"
        rl_cond = "TRUE" if rl in (None, "*", "") else f"rule_name = '{rl}'"
        floor_v = float(floor) if floor not in (None, "") else None

        con.execute(f"""CREATE OR REPLACE TEMP TABLE M AS
            SELECT cik, period, n_units, fv_usd
            FROM F WHERE flagged AND localizable AND {eng_cond} AND {rl_cond}
              AND cik IN (SELECT cik FROM w)""")
        has_fv = con.execute("SELECT count(*) FROM M WHERE fv_usd IS NOT NULL").fetchone()[0]

        # materiality: impossible -> all; else FV-floor where the ledger carries FV; else presence-only
        if auth == "confirmed_impossible":
            mat, mat_mode = "TRUE", "impossible_all"
        elif has_fv and floor_v is not None:
            mat, mat_mode = f"(fv_usd IS NULL OR fv_usd >= {floor_v})", "fv_floor"
        else:
            mat, mat_mode = "TRUE", "presence_only"

        nflags, ncq, nrows, fv = con.execute(
            f"""SELECT count(*), count(DISTINCT cik||period), sum(COALESCE(n_units,0)),
                       sum(COALESCE(fv_usd,0)) FROM M WHERE {mat}"""
        ).fetchone()

        nverified = 0
        if tiers_ok and ncq:
            nverified = con.execute(f"""
                SELECT count(*) FROM (SELECT DISTINCT cik, period FROM M WHERE {mat}) g
                JOIN T USING (cik, period) WHERE T.quality_tier = 'verified'""").fetchone()[0]

        rows_out.append((rid, state, auth, qty, mat_mode, int(nflags), int(ncq),
                         int(nrows or 0), round((fv or 0) / 1e6, 1), int(nverified)))
        if state == "blocking":
            for c, p in con.execute(f"SELECT DISTINCT cik, period FROM M WHERE {mat}").fetchall():
                gated_union.add((c, p))

    # write per-rule preview
    SHADOW.mkdir(parents=True, exist_ok=True)
    out = SHADOW / "enforcement_preview.csv"
    con.execute("""CREATE TABLE OUT(rule_id VARCHAR, state VARCHAR, authority VARCHAR,
        quantity VARCHAR, materiality_mode VARCHAR, n_flags BIGINT, n_cik_quarters BIGINT,
        n_rows BIGINT, fv_gated_m DOUBLE, n_currently_verified BIGINT)""")
    con.executemany("INSERT INTO OUT VALUES (?,?,?,?,?,?,?,?,?,?)", rows_out)
    con.execute(f"""COPY (SELECT * FROM OUT
        ORDER BY (state='blocking') DESC, n_cik_quarters DESC) TO '{out.as_posix()}' (HEADER, DELIMITER ',')""")
    logger.info("wrote %s (%d rules)", out, len(rows_out))

    # day-one BLOCKING floor blast radius
    total_cq = con.execute("""SELECT count(DISTINCT cik||period) FROM F
        WHERE localizable AND cik IN (SELECT cik FROM w)""").fetchone()[0]
    nfloor = len(gated_union)
    logger.info("=== day-one BLOCKING floor blast radius (wrapped cohort) ===")
    logger.info("  wrapped evaluated cik-quarters         : %d", total_cq)
    logger.info("  gated by >=1 blocking rule             : %d (%.1f%%)",
                nfloor, 100.0 * nfloor / max(total_cq, 1))
    if tiers_ok and gated_union:
        con.execute("CREATE TABLE GU(cik VARCHAR, period VARCHAR)")
        con.executemany("INSERT INTO GU VALUES (?,?)", list(gated_union))
        flip = con.execute("""SELECT count(*) FROM (SELECT DISTINCT cik, period FROM GU) g
            JOIN T USING (cik, period) WHERE T.quality_tier='verified'""").fetchone()[0]
        logger.info("  of those currently 'verified' -> flip  : %d", flip)

    logger.info("per-rule (blocking first):")
    for r in sorted(rows_out, key=lambda x: (x[1] != "blocking", -x[6])):
        logger.info("  %-20s %-9s cq=%-4d rows=%-7d fv=$%-7sM verified_hit=%-3d (%s)",
                    r[0], r[1], r[6], r[7], r[8], r[9], r[4])
    return 0


if __name__ == "__main__":
    sys.exit(main())
