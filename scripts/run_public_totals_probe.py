"""E5: cache-only public totals and partition deltas; no frontend writes."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb
from pipeline.config import GICS_HIERARCHY_FILE, WRAPPER_COHORT_MANIFEST_FILE
from pipeline.programme.core import atomic_json, now, read_json, sha
from pipeline.programme.runner import candidate_path, heavy_lock
from scripts.run_context_cohort_inventory import literal

HOLDINGS = ROOT / "data/output/private_markets_holdings.csv"
PUBLIC = ROOT / "frontend/public/data"


def run(output, quarter):
    started = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    paths = [Path(__file__), HOLDINGS, WRAPPER_COHORT_MANIFEST_FILE, GICS_HIERARCHY_FILE,
             PUBLIC / "portfolio_characteristics.json", PUBLIC / "gics_sector_breakdown.json"]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    ciks = sorted({str(r["cik"]).zfill(10) for r in read_json(WRAPPER_COHORT_MANIFEST_FILE)["entries"]})
    if len(ciks) != 70:
        raise ValueError("E5 expects the authoritative 70-fund wrapper cohort")
    hierarchy = read_json(GICS_HIERARCHY_FILE)
    mapping = sorted((name, item["sector"]) for name, item in hierarchy.items())
    atomic_json(output / "request.json", dict(experiment="E5", started_utc=now(), quarter=quarter,
        input_sha256=hashes, memory_limit=None, timeout_seconds=None))
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        con.execute("CREATE TABLE sectors(sub_industry VARCHAR PRIMARY KEY,sector VARCHAR)")
        con.executemany("INSERT INTO sectors VALUES (?,?)", mapping)
        con.execute("""CREATE TABLE h AS SELECT h.* FROM read_csv(?,all_varchar=true) h
          WHERE lpad(cik,10,'0') IN (SELECT unnest(?)) AND substr(report_date,1,10)=?""", [str(HOLDINGS), ciks, quarter])
        invalid = con.execute("""SELECT count(*) FROM h WHERE nullif(fair_value,'') IS NOT NULL
          AND TRY_CAST(fair_value AS DECIMAL(38,12)) IS NULL""").fetchone()[0]
        if invalid:
            raise ValueError("Unrepresentable fair value; cannot silently exclude it")
        con.execute("""CREATE TABLE partitioned AS SELECT h.row_id,
          TRY_CAST(h.fair_value AS DECIMAL(38,12)) AS fv,
          CASE WHEN index_classification='DIRECT_LENDING' THEN
            CASE WHEN lien_position IN ('First Lien','Second Lien','Subordinated','Unsecured')
              THEN lien_position ELSE 'Other Lending' END
            WHEN index_classification='STRUCTURED_CREDIT' THEN 'Structured'
            WHEN index_classification='PREFERRED_EQUITY' THEN 'Preferred'
            WHEN index_classification='COMMON_EQUITY' THEN 'Common Equity'
            WHEN index_classification='CASH' THEN 'Cash' ELSE 'Other' END AS instrument,
          coalesce(s.sector,'Unknown') AS sector
          FROM h LEFT JOIN sectors s ON h.gics_sub_industry=s.sub_industry""")
        rows, missing, signed, positive, negative, zero = con.execute("""SELECT count(*),
          count(*) FILTER(WHERE fv IS NULL),sum(fv),sum(fv) FILTER(WHERE fv>0),
          count(*) FILTER(WHERE fv<0),count(*) FILTER(WHERE fv=0) FROM partitioned""").fetchone()
        buckets = []
        for dimension in ("instrument", "sector"):
            groups = con.execute(f"SELECT {dimension},sum(fv),count(*),count(*) FILTER(WHERE fv IS NULL) FROM partitioned GROUP BY 1 ORDER BY 1").fetchall()
            if sum((g[1] or Decimal(0) for g in groups), Decimal(0)) != signed or sum(g[2] for g in groups) != rows:
                raise ValueError("Public partition does not conserve signed FV and rows")
            buckets.extend(dict(dimension=dimension,bucket=name,signed_fv=str(fv or 0),rows=n,missing_fv=missing_count)
                           for name,fv,n,missing_count in groups)
        con.execute("COPY partitioned TO " + literal(output / "contributors.parquet") + " (FORMAT PARQUET)")
    with (output / "partitions.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(buckets[0]))
        writer.writeheader(); writer.writerows(buckets)
    published = read_json(PUBLIC / "portfolio_characteristics.json")
    published_sectors = read_json(PUBLIC / "gics_sector_breakdown.json")
    headline = Decimal(str(published["portfolioFv"]))
    sector_totals = {r["sector"]:Decimal(str(r["totalFv"])) for r in published_sectors}
    new_sectors = {r["bucket"]:Decimal(r["signed_fv"]) for r in buckets if r["dimension"] == "sector"}
    deltas = {name: str(new_sectors.get(name,Decimal(0))-sector_totals.get(name,Decimal(0)))
              for name in sorted(new_sectors.keys() | sector_totals.keys())}
    for relative, expected in hashes.items():
        if sha(ROOT / relative) != expected:
            raise ValueError("E5 input changed: " + relative)
    atomic_json(output / "summary.json", dict(experiment="E5", completed_utc=now(), quarter=quarter,
        elapsed_seconds=time.monotonic()-started, cohort_funds=70, rows=rows, missing_fv_rows=missing,
        negative_fv_rows=negative, zero_fv_rows=zero, signed_fv=str(signed), positive_only_fv=str(positive),
        removal_of_positive_filter_delta=str(signed-positive), published_headline=str(headline),
        published_as_of=published.get("asOf"), signed_minus_published=str(signed-headline),
        published_sector_total=str(sum(sector_totals.values())), sector_deltas=deltas,
        public_partition_delta="0", contributor_membership="Each retained row occurs once in each CASE/GICS partition; no dedup or filtering",
        sector_basis="Existing position gics_sub_industry mapped through versioned hierarchy; missing/unknown stay Unknown. No fund overlay or automatic instrument-to-sector fallback."))
    atomic_json(output / "complete.json", {p.name:sha(p) for p in output.iterdir() if p.is_file()})
    print("E5 complete: signed FV=" + str(signed) + "; published delta=" + str(signed-headline), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--quarter", default="2026-03-31")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / "scratch"):
        parser.error("E5 outputs must be under scratch/")
    with heavy_lock(candidate_path("t1-runtime-20260910-v5")):
        run(output, args.quarter)


if __name__ == "__main__":
    main()
