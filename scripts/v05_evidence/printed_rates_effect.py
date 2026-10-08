"""Read-only: what the printed-page reading changed, per fund, against a sandbox built before it.

    python scripts/v05_evidence/printed_rates_effect.py <label> <label before> [last quarter to compare, default 2026-03-31]

Rows are matched by filing, report date and source context. Counts are published rows up to the
last quarter named; fair value is unchanged by construction and is checked.
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
FUNDS = {"0001803498": "BCRED", "0001812554": "Blue Owl", "0001287750": "Ares", "0001838126": "HPS", "0001837532": "Apollo"}
label, before = sys.argv[1], sys.argv[2]
last = sys.argv[3] if len(sys.argv) > 3 else "2026-03-31"


def holdings(name):
    path = (REPO / "scratch/fund_sandbox" / name / "output/private_markets_holdings.parquet").as_posix()
    return f"""(SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, accession_number, CAST(report_date AS VARCHAR)[:10] AS q, src_context_id,
        nullif(trim(CAST(reference_rate_type AS VARCHAR)),'') AS ref, coalesce(CAST(reference_rate_source AS VARCHAR),'') AS src,
        TRY_CAST(basis_spread AS DOUBLE) AS spread, TRY_CAST(interest_rate AS DOUBLE) AS rate, TRY_CAST(pik_rate AS DOUBLE) AS pik,
        coalesce(CAST(coupon_type AS VARCHAR),'') AS coupon, coalesce(CAST(src_transforms AS VARCHAR),'') AS events,
        coalesce(CAST(corrected_fields AS VARCHAR),'') AS corrected, TRY_CAST(fair_value AS DOUBLE) AS fv,
        CAST(issuer_name AS VARCHAR) AS issuer, CAST(lien_position AS VARCHAR) AS lien, CAST(maturity_date AS VARCHAR) AS maturity
        FROM read_parquet('{path}') WHERE coalesce(accounting_record_class,'')<>'underlying_schedule'
          AND CAST(report_date AS VARCHAR)[:10] <= '{last}')"""


con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
con.execute(f"CREATE TEMP TABLE j AS SELECT a.*, b.ref AS ref0, b.src AS src0, b.spread AS spread0, b.rate AS rate0, b.coupon AS coupon0, b.fv AS fv0, "
            f"b.lien AS lien0, b.maturity AS maturity0, b.issuer AS issuer0 "
            f"FROM {holdings(label)} a JOIN {holdings(before)} b USING (cik, accession_number, q, src_context_id)")
there = con.execute(f"SELECT count(*) FROM {holdings(before)}").fetchone()[0]
print("rows matched %d of %d in %s; fair value differs on %d" % (
    con.execute("SELECT count(*) FROM j").fetchone()[0], there, before,
    con.execute("SELECT count(*) FROM j WHERE fv IS DISTINCT FROM fv0").fetchone()[0]))
measures = [
    ("reference rate: a date guess replaced by the printed code", "src0 LIKE 'inferred_%' AND src='ixbrl_field_status' AND ref IS DISTINCT FROM ref0"),
    ("reference rate: one read from the label replaced by the printed code", "src0='identifier_text' AND src='ixbrl_field_status' AND ref IS DISTINCT FROM ref0"),
    ("reference rate: a date guess withdrawn (page prints none)", "src0 LIKE 'inferred_%' AND ref IS NULL AND ref0 IS NOT NULL"),
    ("reference rate: filled where nothing was published", "ref0 IS NULL AND ref IS NOT NULL"),
    ("reference rate: other change", "ref IS DISTINCT FROM ref0 AND NOT (src0 LIKE 'inferred_%' OR src0='identifier_text' OR ref0 IS NULL)"),
    ("spread: a fixed coupon no longer published as a spread", "events LIKE '%basis_spread:fixed_coupon%'"),
    ("rate: published from that spread tag", "events LIKE '%interest_rate:from_spread_tag%'"),
    ("spread: cash plus PIK published as the total margin", "events LIKE '%basis_spread:cash_plus_pik_margin%' AND spread IS DISTINCT FROM spread0"),
    ("coupon type: Floating to Fixed", "coupon='Fixed' AND coupon0='Floating'"),
    ("coupon type: blank to Fixed", "coupon='Fixed' AND coupon0=''"),
    ("row corrections: spread or rate set from the printed line", "(spread IS DISTINCT FROM spread0 OR rate IS DISTINCT FROM rate0) AND (corrected LIKE '%basis_spread%' OR corrected LIKE '%interest_rate%')"),
    ("lien position changed", "lien IS DISTINCT FROM lien0"),
    ("maturity date changed", "maturity IS DISTINCT FROM maturity0"),
    ("issuer name changed", "issuer IS DISTINCT FROM issuer0"),
]
print("change | " + " | ".join(FUNDS.values()) + " | $M")
for name, where in measures:
    counts = dict(con.execute(f"SELECT cik, count(*) FROM j WHERE {where} GROUP BY 1").fetchall())
    total = con.execute(f"SELECT round(coalesce(sum(fv),0)/1e6,0) FROM j WHERE {where}").fetchone()[0]
    print("   %s | %s | %s" % (name, " | ".join(str(counts.get(c, 0)) for c in FUNDS), total))
