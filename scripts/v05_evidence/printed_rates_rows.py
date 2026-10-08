"""Read-only: the rows behind a fund's printed-page findings.

    python scripts/v05_evidence/printed_rates_rows.py <label> <cik> [reference|spread] [max rows]

Published loan rows whose reference rate differs from the confirmed printed code, or whose spread
differs from the printed total margin by more than 0.011, with the tagged values beside them.
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
label, cik = sys.argv[1], sys.argv[2].zfill(10)
kind = sys.argv[3] if len(sys.argv) > 3 else "spread"
limit = int(sys.argv[4]) if len(sys.argv) > 4 else 60
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
KEY = "lower(trim(regexp_replace(regexp_replace(CAST(h.bdc_dimensions_raw AS VARCHAR),'^[^=]*=',''),'[ ]+',' ','g')))"
J = f"""(SELECT *, CAST(report_date AS VARCHAR)[:10] AS q FROM read_parquet('{S}/private_markets_holdings.parquet')
        WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{cik}' AND coalesce(accounting_record_class,'')<>'underlying_schedule') h
    JOIN (SELECT * FROM read_csv('{S}/bdc_ixbrl_field_status.csv', header=true, all_varchar=true, sample_size=-1)
        WHERE cik='{cik}' AND period_role='current') f
      ON f.accession_number=h.accession_number AND f.report_date=h.q AND f.raw_id_lower={KEY}"""
if kind == "reference":
    where = """f.reference_rate_status='value' AND nullif(trim(CAST(h.reference_rate_type AS VARCHAR)),'') IS NOT NULL
        AND upper(trim(f.reference_rate_type)) <> upper(trim(CAST(h.reference_rate_type AS VARCHAR)))"""
else:
    where = "abs(TRY_CAST(h.basis_spread AS DOUBLE)-TRY_CAST(f.printed_margin AS DOUBLE))>0.011"
print("quarter | accession | published ref (source) | printed ref | spread | printed margin | pik | rate | $M | transforms | identifier")
for r in con.execute(f"""SELECT h.q, h.accession_number, coalesce(CAST(h.reference_rate_type AS VARCHAR),'')||' ('||coalesce(CAST(h.reference_rate_source AS VARCHAR),'')||')',
        f.reference_rate_type, round(TRY_CAST(h.basis_spread AS DOUBLE),3), f.printed_margin, round(TRY_CAST(h.pik_rate AS DOUBLE),3),
        round(TRY_CAST(h.interest_rate AS DOUBLE),3), round(TRY_CAST(h.fair_value AS DOUBLE)/1e6,1), coalesce(CAST(h.src_transforms AS VARCHAR),'')[:60],
        CAST(h.bdc_investment_identifier AS VARCHAR)[:110]
    FROM {J} WHERE {where} ORDER BY h.q, 11 LIMIT {limit}""").fetchall():
    print("   " + " | ".join(str(v) for v in r))
if kind == "spread":
    print("spread disagreements where spread + pik = printed margin: rows | of")
    print("   %s | %s" % con.execute(f"""SELECT count(*) FILTER (WHERE abs(TRY_CAST(h.basis_spread AS DOUBLE)+TRY_CAST(h.pik_rate AS DOUBLE)-TRY_CAST(f.printed_margin AS DOUBLE))<=0.011), count(*)
        FROM {J} WHERE {where}""").fetchone())
