"""Read-only probe: how much FV does a bounded tail census cover, and under which
denominator? Informs the tail-threshold tuning. No writes anywhere.
"""
from __future__ import annotations
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parents[2]
UNIFIED = ROOT / "data" / "output" / "private_markets_holdings.parquet"
WRAPPER_DIR = ROOT / "data" / "overrides" / "bdc_xbrl_wrappers"
PERIOD_START = "2022-10-01"

ciks = [p.stem for p in WRAPPER_DIR.glob("*.json") if p.stem.isdigit() and len(p.stem) == 10]
cik_list = ",".join(f"'{c}'" for c in ciks)
con = duckdb.connect(); con.execute("PRAGMA threads=4")

con.execute(f"""
CREATE TEMP VIEW base AS
SELECT lpad(cast(cast(cik AS BIGINT) AS VARCHAR),10,'0') AS cik,
       report_date,
       try_cast(fair_value AS DOUBLE) AS fv,
       abs(try_cast(fair_value AS DOUBLE)) AS afv,
       issuer_name, bdc_investment_identifier
FROM read_parquet('{UNIFIED.as_posix()}')
WHERE upper(source) LIKE 'BDC%' AND report_date >= '{PERIOD_START}'
  AND lpad(cast(cast(cik AS BIGINT) AS VARCHAR),10,'0') IN ({cik_list})
  AND try_cast(fair_value AS DOUBLE) IS NOT NULL
""")

# as-of snapshot = each fund's latest report_date
con.execute("""
CREATE TEMP VIEW snap AS
SELECT b.* FROM base b
JOIN (SELECT cik, max(report_date) md FROM base GROUP BY cik) m
  ON b.cik = m.cik AND b.report_date = m.md
""")

def curve(view, label):
    tot = con.execute(f"SELECT sum(afv) FROM {view}").fetchone()[0]
    n = con.execute(f"SELECT count(*) FROM {view}").fetchone()[0]
    print(f"\n=== {label}: {n:,} position-quarters, sum|FV|=${tot/1e9:.1f}B ===")
    print(f"{'K':>6} {'cum$B':>9} {'%ofFV':>7} {'minFVm':>9}")
    rows = con.execute(f"""
        WITH r AS (SELECT afv, row_number() OVER (ORDER BY afv DESC) rk,
                          sum(afv) OVER (ORDER BY afv DESC) cum FROM {view})
        SELECT rk, cum, afv FROM r
        WHERE rk IN (50,100,150,200,300,500,1000,2000) ORDER BY rk
    """).fetchall()
    for rk, cum, afv in rows:
        print(f"{rk:>6} {cum/1e9:>9.1f} {100*cum/tot:>6.1f}% {afv/1e6:>9.1f}")
    # distinct instruments in top-300
    dd = con.execute(f"""
        WITH r AS (SELECT *, row_number() OVER (ORDER BY afv DESC) rk FROM {view})
        SELECT count(*) tot, count(DISTINCT cik||'|'||lower(coalesce(bdc_investment_identifier,issuer_name))) dist
        FROM r WHERE rk <= 300
    """).fetchone()
    print(f"  top-300: {dd[0]} position-quarters -> {dd[1]} distinct instruments")

curve("base", "ALL-HISTORY (2022Q4+, pooled across quarters)")
curve("snap", "AS-OF SNAPSHOT (each fund's latest filed quarter)")

# snapshot date spread
print("\n=== snapshot report_date spread ===")
for d, c, fv in con.execute("""
    SELECT report_date, count(DISTINCT cik) nfund, sum(afv) fv
    FROM snap GROUP BY report_date ORDER BY report_date DESC LIMIT 8
""").fetchall():
    print(f"  {d}: {c} funds  ${fv/1e9:.1f}B")
