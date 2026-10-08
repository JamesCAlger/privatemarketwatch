"""Read-only: each fund's printed reference rate and margin against the published rows.

    python scripts/v05_evidence/printed_rates_check.py <label> [before label] [cik ...]

Per fund (default: the five v0.5 funds), published rows only:
1. what the page reader made of the printed column, current-period rows;
2. published reference rate against the printed code (rows the reader confirmed), by where the
   published value came from;
3. published spread against the printed total margin, and the commonest disagreements;
4. with a second label: rows whose reference rate, spread, coupon type or rate differs from it.
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
FUNDS = {"0001803498": "BCRED", "0001812554": "Blue Owl", "0001287750": "Ares", "0001838126": "HPS", "0001837532": "Apollo"}
label = sys.argv[1]
rest = sys.argv[2:]
before = rest[0] if rest and not rest[0].isdigit() else None
ciks = [a.zfill(10) for a in rest if a.isdigit()] or list(FUNDS)


def out(name):
    return (REPO / "scratch/fund_sandbox" / name / "output").as_posix()


def show(rows):
    for r in rows:
        print("   " + " | ".join(str(v) for v in r))


S = out(label)
con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
KEY = "lower(trim(regexp_replace(regexp_replace(CAST(h.bdc_dimensions_raw AS VARCHAR),'^[^=]*=',''),'[ ]+',' ','g')))"
for cik in ciks:
    print("\n===== %s %s (%s)" % (FUNDS.get(cik, ""), cik, label))
    H = f"""(SELECT *, CAST(report_date AS VARCHAR)[:10] AS q FROM read_parquet('{S}/private_markets_holdings.parquet')
        WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{cik}' AND coalesce(accounting_record_class,'')<>'underlying_schedule')"""
    F = f"""(SELECT * FROM read_csv('{S}/bdc_ixbrl_field_status.csv', header=true, all_varchar=true, sample_size=-1)
        WHERE cik='{cik}' AND period_role='current')"""
    J = f"{H} h JOIN {F} f ON f.accession_number=h.accession_number AND f.report_date=h.q AND f.raw_id_lower={KEY}"
    print("1. printed column: status | rows | margin read")
    show(con.execute(f"SELECT reference_rate_status, count(*), count(*) FILTER (WHERE nullif(trim(printed_margin),'') IS NOT NULL) FROM {F} GROUP BY 1 ORDER BY 2 DESC").fetchall())
    print("2. confirmed printed code against published: published source | printed | published | rows | $M")
    show(con.execute(f"""SELECT coalesce(nullif(CAST(h.reference_rate_source AS VARCHAR),''),'(none)'), f.reference_rate_type,
            coalesce(nullif(trim(CAST(h.reference_rate_type AS VARCHAR)),''),'(none)'), count(*), round(sum(TRY_CAST(h.fair_value AS DOUBLE))/1e6,0)
        FROM {J} WHERE f.reference_rate_status='value'
          AND upper(trim(f.reference_rate_type)) IS DISTINCT FROM upper(nullif(trim(CAST(h.reference_rate_type AS VARCHAR)),''))
        GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 25""").fetchall())
    r = con.execute(f"""SELECT count(*), count(*) FILTER (WHERE upper(trim(f.reference_rate_type)) = upper(trim(CAST(h.reference_rate_type AS VARCHAR)))),
            count(*) FILTER (WHERE nullif(trim(CAST(h.reference_rate_type AS VARCHAR)),'') IS NULL)
        FROM {J} WHERE f.reference_rate_status='value'""").fetchone()
    print("   compared %s | agree %s | nothing published %s | disagree %s" % (r[0], r[1], r[2], r[0] - r[1] - r[2]))
    print("   printed 'no reference rate' on a row that publishes one: source | published | coupon type | rows | $M")
    show(con.execute(f"""SELECT coalesce(nullif(CAST(h.reference_rate_source AS VARCHAR),''),'(none)'), h.reference_rate_type, h.coupon_type, count(*),
            round(sum(TRY_CAST(h.fair_value AS DOUBLE))/1e6,0)
        FROM {J} WHERE f.reference_rate_status='not_applicable' AND nullif(trim(CAST(h.reference_rate_type AS VARCHAR)),'') IS NOT NULL
        GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 10""").fetchall())
    r = con.execute(f"""SELECT count(*), count(*) FILTER (WHERE abs(TRY_CAST(h.basis_spread AS DOUBLE)-TRY_CAST(f.printed_margin AS DOUBLE))<=0.011),
            count(*) FILTER (WHERE TRY_CAST(h.basis_spread AS DOUBLE) IS NULL)
        FROM {J} WHERE TRY_CAST(f.printed_margin AS DOUBLE) IS NOT NULL""").fetchone()
    print("3. printed margin read %s | spread agrees %s | no spread published %s | disagree %s" % (r[0], r[1], r[2], r[0] - r[1] - r[2]))
    print("   disagreements: quarters | published spread | printed | pik rate | rows | $M | example")
    show(con.execute(f"""SELECT min(h.q)||'..'||max(h.q), round(TRY_CAST(h.basis_spread AS DOUBLE),3), TRY_CAST(f.printed_margin AS DOUBLE), round(TRY_CAST(h.pik_rate AS DOUBLE),3),
            count(*), round(sum(TRY_CAST(h.fair_value AS DOUBLE))/1e6,0), any_value(CAST(h.bdc_investment_identifier AS VARCHAR)[:45])
        FROM {J} WHERE abs(TRY_CAST(h.basis_spread AS DOUBLE)-TRY_CAST(f.printed_margin AS DOUBLE))>0.011
        GROUP BY 2,3,4 ORDER BY 5 DESC LIMIT 15""").fetchall())
    show(con.execute(f"""SELECT 'by quarter', h.q, count(*) FROM {J} WHERE abs(TRY_CAST(h.basis_spread AS DOUBLE)-TRY_CAST(f.printed_margin AS DOUBLE))>0.011 GROUP BY 2 ORDER BY 2""").fetchall())
    if before:
        B = out(before)
        print("4. against %s: field | changed | filled from blank | value replaced | emptied | rows here | rows there" % before)
        for field in ("reference_rate_type", "basis_spread", "coupon_type", "interest_rate", "pik_rate", "fair_value"):
            show([(field,) + con.execute(f"""WITH a AS (SELECT accession_number, q, src_context_id, nullif(trim(CAST({field} AS VARCHAR)),'') AS v FROM {H}),
                b AS (SELECT accession_number, CAST(report_date AS VARCHAR)[:10] AS q, src_context_id, nullif(trim(CAST({field} AS VARCHAR)),'') AS v
                      FROM read_parquet('{B}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{cik}'
                        AND coalesce(accounting_record_class,'')<>'underlying_schedule')
                SELECT count(*) FILTER (WHERE a.v IS DISTINCT FROM b.v AND NOT coalesce(TRY_CAST(a.v AS DOUBLE)=TRY_CAST(b.v AS DOUBLE),false)),
                    count(*) FILTER (WHERE b.v IS NULL AND a.v IS NOT NULL),
                    count(*) FILTER (WHERE b.v IS NOT NULL AND a.v IS NOT NULL AND a.v<>b.v AND NOT coalesce(TRY_CAST(a.v AS DOUBLE)=TRY_CAST(b.v AS DOUBLE),false)),
                    count(*) FILTER (WHERE b.v IS NOT NULL AND a.v IS NULL), (SELECT count(*) FROM a), (SELECT count(*) FROM b)
                FROM a FULL JOIN b USING (accession_number, q, src_context_id)""").fetchone()])
        print("   reference rate changes: before | after | rows | $M")
        show(con.execute(f"""SELECT coalesce(nullif(trim(CAST(b.reference_rate_type AS VARCHAR)),''),'(none)'), coalesce(nullif(trim(CAST(a.reference_rate_type AS VARCHAR)),''),'(none)'),
                count(*), round(sum(TRY_CAST(a.fair_value AS DOUBLE))/1e6,0)
            FROM {H} a JOIN (SELECT accession_number, CAST(report_date AS VARCHAR)[:10] AS q, src_context_id, reference_rate_type
                FROM read_parquet('{B}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{cik}') b USING (accession_number, q, src_context_id)
            WHERE nullif(trim(CAST(a.reference_rate_type AS VARCHAR)),'') IS DISTINCT FROM nullif(trim(CAST(b.reference_rate_type AS VARCHAR)),'')
            GROUP BY 1,2 ORDER BY 3 DESC LIMIT 25""").fetchall())
