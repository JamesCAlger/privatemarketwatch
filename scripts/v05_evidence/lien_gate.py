"""Read-only: the lien reconciliation gate of the printed-page artifact, tier by tier, for one fund.

    python scripts/v05_evidence/lien_gate.py <label> <cik> [quarter]

Re-reads each filing's page and compares, per lien tier, the fair value of the page rows that carry
the tier with the reference the gate uses: the page's own section totals where it prints them,
else the filed breakdown (bdc_lien_breakdown.csv). A tier passes within 5 pct or 5M. One failing
tier withholds lien for the whole filing. The page sum is also shown for published rows only.
"""
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import bdc_xbrl_html_bridge as b  # noqa: E402

label, cik = sys.argv[1], sys.argv[2].zfill(10)
only = sys.argv[3] if len(sys.argv) > 3 else None
S = (REPO / "scratch/fund_sandbox" / label / "output").as_posix()
con = duckdb.connect()
con.execute("SET memory_limit='3GB'")
flat = con.execute(f"""SELECT CAST(accession_number AS VARCHAR), CAST(report_date AS VARCHAR)[:10], CAST(investment_identifier AS VARCHAR), TRY_CAST(fair_value AS DOUBLE)
    FROM read_csv('{S}/bdc_holdings.csv', header=true, all_varchar=true, sample_size=-1)
    WHERE lpad(cik,10,'0')='{cik}' AND CAST(period AS VARCHAR)[:10]=CAST(report_date AS VARCHAR)[:10]""").fetchall()
published = {(r[0], b._raw_id_lower(r[1])) for r in con.execute(f"""SELECT CAST(report_date AS VARCHAR)[:10], CAST(bdc_investment_identifier AS VARCHAR)
    FROM read_parquet('{S}/private_markets_holdings.parquet')
    WHERE lpad(CAST(cik AS VARCHAR),10,'0')='{cik}' AND coalesce(accounting_record_class,'')<>'underlying_schedule'""").fetchall()}
lien = con.execute(f"""SELECT DISTINCT lpad(cik,10,'0') AS cik, report_date, lien_tier, grain, TRY_CAST(fair_value AS DOUBLE) AS fair_value
    FROM read_csv('{S}/bdc_lien_breakdown.csv', header=true, all_varchar=true, sample_size=-1) WHERE lpad(cik,10,'0')='{cik}'""").df()
filed = b.filed_lien_subtotals(lien)
filings = sorted({(r[1], r[0]) for r in flat})
print("quarter | reference | tier | page rows | page sum $M | published rows only $M | reference $M | difference $M | tier")
for quarter, accession in filings:
    if only and quarter != only:
        continue
    fv = {b._raw_id_lower(r[2]): (r[3] or 0.0) for r in flat if r[0] == accession}
    prop = b.propose_field_bridges_from_ixbrl(cik=cik, accession_number=accession, report_date=quarter)
    printed = prop.get("printed_lien_totals") or {}
    reference = printed or filed.get((cik, quarter), {})
    sums, pub, count = {}, {}, {}
    for bridge in prop.get("bridges") or []:
        tier = bridge.get("lien_position")
        if not tier:
            continue
        value = fv.get(bridge["raw_id_lower"], 0.0)
        sums[tier] = sums.get(tier, 0.0) + value
        count[tier] = count.get(tier, 0) + 1
        if (quarter, bridge["raw_id_lower"]) in published:
            pub[tier] = pub.get(tier, 0.0) + value
    for tier in sorted(set(sums) | set(reference)):
        ref = reference.get(tier)
        diff = None if ref is None else sums.get(tier, 0.0) - ref
        verdict = "" if ref is None else "ok" if abs(diff) <= max(5e6, 0.05 * abs(ref)) else "FAIL"
        print("   %s | %s | %s | %d | %.1f | %.1f | %s | %s | %s" % (
            quarter, "page totals" if printed else "filed breakdown" if reference else "none", tier, count.get(tier, 0),
            sums.get(tier, 0.0) / 1e6, pub.get(tier, 0.0) / 1e6, "-" if ref is None else "%.1f" % (ref / 1e6),
            "-" if diff is None else "%.1f" % (diff / 1e6), verdict))
