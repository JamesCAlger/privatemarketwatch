"""Quantify dimension-axis duplicate positions that survive Stage-D dedup.

A position can appear under two iXBRL dimension axes (e.g. affiliation vs industry)
with the SAME (cik, accession, report_date, fair_value) but DIVERGENT issuer_name /
instrument_description because the wrapper parsed each axis differently -- so the
Stage-D dedup key (issuer+instrument+principal+shares) does not match and both
copies survive (e.g. WDE TorcSill protective advance, FV 2,858,752).

Detection: within (cik, accession, report_date, round(fair_value)) groups of >=2
BDC rows, flag groups where >=2 rows share a DISTINCTIVE issuer token (generic SOI
words dropped). The shared token discriminates real same-position dupes from
distinct positions that merely collide on fair value.

Read-only, cache-only. Prints counts + FV-at-risk + examples.
"""

from __future__ import annotations

import re
from collections import Counter

import duckdb

H = "data/output/private_markets_holdings.csv"
_GENERIC = {
    "investments", "investment", "united", "states", "debt", "securities", "senior",
    "secured", "first", "second", "third", "lien", "term", "loan", "loans", "delayed",
    "draw", "revolving", "revolver", "type", "portfolio", "fund", "subordinated",
    "common", "stock", "preferred", "equity", "units", "unit", "the", "inc", "llc",
    "ltd", "lp", "corp", "co", "and", "of", "clo", "structured", "finance", "notes",
    "note", "company", "holdings", "group", "warrants", "warrant", "controlled",
    "affiliated", "non", "energy", "equipment", "services", "acquisition", "date",
    "maturity", "net", "assets", "floor", "pik", "inc.", "prime", "sofr", "libor",
}


def _tokens(s: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z0-9]+", s or "")
            if t.lower() not in _GENERIC and len(t) > 2 and not t.isdigit()}


def main() -> int:
    con = duckdb.connect()
    # candidate groups: same cik/accession/report_date/fv with >=2 BDC rows
    cand = con.execute(f"""
        WITH b AS (
            SELECT lpad(CAST(cik AS VARCHAR),10,'0') cik, accession_number acc,
                   CAST(report_date AS VARCHAR) rd,
                   round(TRY_CAST(fair_value AS DOUBLE), 0) fv,
                   issuer_name, instrument_description, bdc_investment_identifier id,
                   interest_rate, pik_rate
            FROM read_csv_auto('{H}', sample_size=-1)
            WHERE lower(CAST(source AS VARCHAR)) = 'bdc'
              AND abs(TRY_CAST(fair_value AS DOUBLE)) > 1000
        )
        SELECT * FROM b
        WHERE (cik, acc, rd, fv) IN (
            SELECT cik, acc, rd, fv FROM b GROUP BY 1,2,3,4 HAVING count(*) >= 2
        )
        ORDER BY cik, acc, rd, fv
    """).df()
    print(f"candidate rows (in >=2-row same cik/acc/rd/fv groups): {len(cand)}")

    groups: dict = {}
    for r in cand.to_dict("records"):
        groups.setdefault((r["cik"], r["acc"], r["rd"], r["fv"]), []).append(r)

    dup_groups = []
    for key, rows in groups.items():
        # shared distinctive token across >=2 rows?
        tok_count = Counter()
        per_row = [_tokens(f"{x['issuer_name']} {x['id']}") for x in rows]
        for ts in per_row:
            for t in ts:
                tok_count[t] += 1
        shared = {t for t, c in tok_count.items() if c >= 2}
        if shared:
            dup_groups.append((key, rows, shared))

    n_groups = len(dup_groups)
    n_extra_rows = sum(len(rows) - 1 for _, rows, _ in dup_groups)
    fv_at_risk = sum((len(rows) - 1) * abs(key[3]) for key, rows, _ in dup_groups)
    # how many flagged groups also have divergent rate attribution (ir vs pik)
    attr_conflict = 0
    for _, rows, _ in dup_groups:
        irs = {("ir" if (x["interest_rate"] == x["interest_rate"]) else "") +
               ("pik" if (x["pik_rate"] == x["pik_rate"]) else "") for x in rows}
        if len(irs) > 1:
            attr_conflict += 1

    print(f"\n=== dimension-axis dup groups (shared issuer token) ===")
    print(f"  groups:            {n_groups}")
    print(f"  over-counted rows: {n_extra_rows}")
    print(f"  FV at risk (over-counted): ${fv_at_risk:,.0f}")
    print(f"  groups w/ divergent ir-vs-pik attribution: {attr_conflict}")
    print(f"  (groups with NO shared token = likely distinct, not flagged: {len(groups) - n_groups})")

    print("\n=== examples ===")
    for key, rows, shared in dup_groups[:5]:
        print(f"cik {key[0]} acc {key[1]} {key[2]} fv ${key[3]:,.0f}  shared={sorted(shared)[:3]}")
        for x in rows:
            print(f"   ir={x['interest_rate']} pik={x['pik_rate']} | {str(x['issuer_name'])[:75]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
