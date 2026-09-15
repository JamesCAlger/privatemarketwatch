"""One holdings population for public headline, instrument and sector totals."""
from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

from pipeline import config
from pipeline.cohort_guard import load_cohort_ciks


def write_public_contributors(con,path,as_of):
    """Retain the exact partition membership used by the public exporters."""
    payload=con.execute("""SELECT to_json(struct_pack(asOf := ?, rows := coalesce(
      list(struct_pack(row_id := row_id,instrument := instrument,sector := sector) ORDER BY row_id),[])))
      FROM public_holdings""",[as_of]).fetchone()[0]
    Path(path).write_text(payload+"\n",encoding="utf-8")


def public_snapshot(con, holdings_file: Path, *, cutoff="9999-12-31", cohort=None,
                    hierarchy=None):
    """Materialize each retained observation once; aggregate its two partitions.

    No sign filter, deduplication, fund overlay or remainder arithmetic is used.
    Decimal sums are retained as exact strings alongside display numbers. Missing
    FV remains missing and counted; malformed nonempty values block the export.
    """
    cohort = sorted(load_cohort_ciks() if cohort is None else cohort)
    if not cohort:
        raise ValueError("Public export requires a nonempty wrapper cohort")
    if hierarchy is None:
        hierarchy = json.loads(config.GICS_HIERARCHY_FILE.read_text(encoding="utf-8-sig"))
    con.execute("CREATE OR REPLACE TEMP TABLE public_sector_map(sub_industry VARCHAR PRIMARY KEY, sector VARCHAR)")
    mapping = sorted((name, item["sector"]) for name, item in hierarchy.items())
    if mapping:
        con.executemany("INSERT INTO public_sector_map VALUES (?,?)", mapping)
    con.execute("""CREATE OR REPLACE TEMP TABLE public_holdings AS
      WITH scoped AS (
        SELECT *, TRY_CAST(substr(report_date,1,10) AS DATE) AS public_date
        FROM read_csv(?,all_varchar=true)
        WHERE lpad(cik,10,'0') IN (SELECT unnest(?))
      ), current_rows AS (
        SELECT * FROM scoped WHERE public_date <= CAST(? AS DATE)
        QUALIFY public_date = max(public_date) OVER ()
      )
      SELECT h.*, TRY_CAST(nullif(trim(fair_value),'') AS DECIMAL(38,12)) AS public_fv,
        coalesce(nullif(trim(index_classification),''),'UNCLASSIFIED') AS classification,
        CASE WHEN index_classification='DIRECT_LENDING' THEN
          CASE WHEN lien_position IN ('First Lien','Second Lien','Subordinated','Unsecured')
            THEN lien_position ELSE 'Other Lending' END
          WHEN index_classification='STRUCTURED_CREDIT' THEN 'Structured'
          WHEN index_classification='PREFERRED_EQUITY' THEN 'Preferred'
          WHEN index_classification='COMMON_EQUITY' THEN 'Common Equity'
          WHEN index_classification='CASH' THEN 'Cash' ELSE 'Other' END AS instrument,
        coalesce(s.sector,'Unknown') AS sector
      FROM current_rows h LEFT JOIN public_sector_map s ON h.gics_sub_industry=s.sub_industry
      """, [str(holdings_file), cohort, cutoff])
    invalid = con.execute("""SELECT count(*) FROM public_holdings
      WHERE nullif(trim(fair_value),'') IS NOT NULL AND public_fv IS NULL""").fetchone()[0]
    if invalid:
        raise ValueError("Public export contains unrepresentable fair value")
    incompatible = con.execute("""SELECT count(*) FROM public_holdings
      WHERE public_fv IS NOT NULL AND upper(coalesce(trim(fair_value_currency),'')) NOT IN ('','USD')
      """).fetchone()[0]
    if incompatible:
        raise ValueError("Public export contains non-USD or unresolved fair value")
    as_of, count, missing, total = con.execute("""SELECT max(public_date),count(*),
      count(*) FILTER(WHERE public_fv IS NULL), coalesce(sum(public_fv),0) FROM public_holdings""").fetchone()
    # GROUPING SETS operates on exactly the same retained observation multiset.
    records = con.execute("""SELECT
      CASE WHEN grouping(instrument)=0 THEN 'instrument'
           WHEN grouping(sector)=0 THEN 'sector' ELSE 'classification' END AS dimension,
      coalesce(instrument,sector,classification) AS bucket,
      coalesce(sum(public_fv),0) AS fv, count(*) AS observations,
      count(*) FILTER(WHERE public_fv IS NULL) AS missing_fv,
      count(DISTINCT cik) AS funds
      FROM public_holdings GROUP BY GROUPING SETS ((instrument),(sector),(classification))
      ORDER BY dimension,fv DESC,bucket""").fetchall()
    partitions = {name: [] for name in ("instrument", "sector", "classification")}
    for dimension, bucket, fv, observations, missing_fv, funds in records:
        partitions[dimension].append(dict(label=bucket,totalFv=float(fv),fairValueExact=str(fv),
            pctOfTotal=float(fv/total) if total else 0.0, positionCount=observations,
            missingFairValueCount=missing_fv, fundCount=funds))
    for dimension, rows in partitions.items():
        if sum((Decimal(r["fairValueExact"]) for r in rows), Decimal(0)) != total:
            raise ValueError("Public partition FV differs from headline: " + dimension)
        if sum(r["positionCount"] for r in rows) != count:
            raise ValueError("Public partition lost or repeated contributors: " + dimension)
    return dict(asOf=str(as_of) if as_of else None, portfolioFv=float(total),
        fairValueExact=str(total), positionCount=count, missingFairValueCount=missing,
        partitions=partitions, publicPartitionDelta="0", basis="cohort_holdings_signed_fair_value")
