"""Read-only: Blue Owl's printed reference-rate column against the published rows.

    python scripts/v05_evidence/owl_ref_rate.py <label> [before label]

1. status of the printed column in the sandbox's field-status artifact, by quarter;
2. agreement between the printed code and a reference rate the row already had from another source;
3. loan rows with a PIK rate and no filed rate: how each was resolved;
4. with a second label: rows whose reference rate, spread or rate differs from that sandbox;
5. the rows still unresolved, by what the printed column held.
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
CIK = "0001812554"


def out(label):
    return (REPO / "scratch/fund_sandbox" / label / "output").as_posix()


S = out(sys.argv[1])
con = duckdb.connect()
H = f"""(SELECT *, CAST(report_date AS VARCHAR)[:10] AS q FROM read_parquet('{S}/private_markets_holdings.parquet')
    WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{CIK}' AND coalesce(accounting_record_class,'')<>'underlying_schedule')"""
F = f"""(SELECT * FROM read_csv('{S}/bdc_ixbrl_field_status.csv', header=true, all_varchar=true, sample_size=-1)
    WHERE cik='{CIK}' AND period_role='current')"""

print("1. printed column, current-period rows: quarter | value | blank | validation_needed | other")
for r in con.execute(f"""SELECT report_date, count(*) FILTER (WHERE reference_rate_status='value'), count(*) FILTER (WHERE reference_rate_status='blank'),
        count(*) FILTER (WHERE reference_rate_status='validation_needed'), count(*) FILTER (WHERE reference_rate_status NOT IN ('value','blank','validation_needed'))
    FROM {F} GROUP BY 1 ORDER BY 1""").fetchall():
    print("   " + " | ".join(str(v) for v in r))

print("2. rows whose reference rate came from another source: printed code | published | rows")
for r in con.execute(f"""SELECT f.reference_rate_type, h.reference_rate_type, count(*)
    FROM {H} h JOIN {F} f ON f.accession_number=h.accession_number AND f.report_date=h.q
        AND f.raw_id_lower=lower(trim(regexp_replace(regexp_replace(CAST(h.bdc_dimensions_raw AS VARCHAR),'^[^=]*=',''),'[ ]+',' ','g')))
    WHERE f.reference_rate_status='value' AND coalesce(h.reference_rate_source,'')<>'ixbrl_field_status'
      AND nullif(trim(CAST(h.reference_rate_type AS VARCHAR)),'') IS NOT NULL
    GROUP BY 1,2 ORDER BY 3 DESC""").fetchall():
    print("   " + " | ".join(str(v) for v in r))

print("3. loan rows with a PIK rate and no filed rate: reference | source | spread from PIK | coupon from PIK | rows | $M")
for r in con.execute(f"""SELECT coalesce(nullif(trim(CAST(reference_rate_type AS VARCHAR)),''),'(none)'), coalesce(nullif(CAST(reference_rate_source AS VARCHAR),''),'(none)'),
        coalesce(CAST(src_transforms AS VARCHAR),'') LIKE '%basis_spread:pik_margin%', coalesce(CAST(src_transforms AS VARCHAR),'') LIKE '%interest_rate:pik_only%',
        count(*), round(sum(TRY_CAST(fair_value AS DOUBLE))/1e6,1)
    FROM {H} WHERE asset_category='LOAN' AND TRY_CAST(pik_rate AS DOUBLE)>0 AND TRY_CAST(interest_rate_reported AS DOUBLE) IS NULL
      AND (TRY_CAST(basis_spread AS DOUBLE) IS NULL OR coalesce(CAST(src_transforms AS VARCHAR),'') LIKE '%basis_spread:pik_margin%')
    GROUP BY 1,2,3,4 ORDER BY 5 DESC""").fetchall():
    print("   " + " | ".join(str(v) for v in r))

print("5. PIK-only loan rows with no spread, by what the printed column held: status | coupon published | rows | $M | largest")
for r in con.execute(f"""SELECT coalesce(f.reference_rate_status,'(row not found on the page)'), TRY_CAST(h.interest_rate AS DOUBLE) IS NOT NULL, count(*), round(sum(TRY_CAST(h.fair_value AS DOUBLE))/1e6,1),
        arg_max(CAST(h.bdc_investment_identifier AS VARCHAR)[:50], TRY_CAST(h.fair_value AS DOUBLE))
    FROM {H} h LEFT JOIN {F} f ON f.accession_number=h.accession_number AND f.report_date=h.q
        AND f.raw_id_lower=lower(trim(regexp_replace(regexp_replace(CAST(h.bdc_dimensions_raw AS VARCHAR),'^[^=]*=',''),'[ ]+',' ','g')))
    WHERE h.asset_category='LOAN' AND TRY_CAST(h.pik_rate AS DOUBLE)>0 AND TRY_CAST(h.interest_rate_reported AS DOUBLE) IS NULL
      AND TRY_CAST(h.basis_spread AS DOUBLE) IS NULL GROUP BY 1,2 ORDER BY 3 DESC""").fetchall():
    print("   " + " | ".join(str(v) for v in r))

if len(sys.argv) > 2:
    B = out(sys.argv[2])
    print("4. against %s: field | rows changed | filled from blank | value replaced | emptied" % sys.argv[2])
    for field in ("reference_rate_type", "basis_spread", "interest_rate", "pik_rate", "fair_value", "coupon_type", "asset_category"):
        r = con.execute(f"""WITH a AS (SELECT accession_number, q, src_context_id, nullif(trim(CAST({field} AS VARCHAR)),'') AS v FROM {H}),
            b AS (SELECT accession_number, CAST(report_date AS VARCHAR)[:10] AS q, src_context_id, nullif(trim(CAST({field} AS VARCHAR)),'') AS v
                  FROM read_parquet('{B}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{CIK}'
                    AND coalesce(accounting_record_class,'')<>'underlying_schedule')
            SELECT count(*) FILTER (WHERE a.v IS DISTINCT FROM b.v AND NOT coalesce(TRY_CAST(a.v AS DOUBLE)=TRY_CAST(b.v AS DOUBLE),false)),
                count(*) FILTER (WHERE b.v IS NULL AND a.v IS NOT NULL),
                count(*) FILTER (WHERE b.v IS NOT NULL AND a.v IS NOT NULL AND a.v<>b.v AND NOT (TRY_CAST(a.v AS DOUBLE) IS NOT NULL AND TRY_CAST(a.v AS DOUBLE)=TRY_CAST(b.v AS DOUBLE))),
                count(*) FILTER (WHERE b.v IS NOT NULL AND a.v IS NULL), count(*), (SELECT count(*) FROM a), (SELECT count(*) FROM b)
            FROM a FULL JOIN b USING (accession_number, q, src_context_id)""").fetchone()
        print("   %s | %s | %s | %s | %s   (joined %s, this %s, that %s)" % ((field,) + tuple(r)))
    print("6. coupon_type changes by class: class | rows")
    for r in con.execute(f"""SELECT a.asset_category, count(*) FROM {H} a JOIN (SELECT accession_number, CAST(report_date AS VARCHAR)[:10] AS q, src_context_id, coupon_type
            FROM read_parquet('{B}/private_markets_holdings.parquet') WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{CIK}') b USING (accession_number, q, src_context_id)
        WHERE a.coupon_type IS DISTINCT FROM b.coupon_type GROUP BY 1 ORDER BY 2 DESC""").fetchall():
        print("   " + " | ".join(str(v) for v in r))
