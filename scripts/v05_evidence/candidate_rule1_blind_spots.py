"""Read-only: where rule 1 (issuer_name_differs_from_page) cannot see, per fund-quarter (2026-10-18).

    python scripts/v05_evidence/candidate_rule1_blind_spots.py <out.csv>

For each fund in the main checkout's docs/investigations/v05_readings/accepted_sandboxes.json it loads the
published rows from that fund's accepted sandbox (pipeline.candidate_rules.load_fund_rows), runs rule 1 so
its working table _cr_names exists, and counts per report_date:
  rows            published rows with an issuer name (what rule 1 reads)
  no_printed_row  rows the page reader did not join (no printed_row): page test impossible
  not_comparable  printed row joined but no name cell left (row starts with an instrument, or the lead
                  cells are labels/headings): page test impossible, only the shape fallback runs
  blind_share     (no_printed_row + not_comparable) / rows
Nothing is written except the output CSV. DuckDB memory 3GB, one fund at a time.
"""
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

WT = Path(__file__).resolve().parents[2]
MAIN = WT.parents[2] if WT.parent.name == "worktrees" else WT
sys.path.insert(0, str(WT))
from pipeline import candidate_rules as cr  # noqa: E402


def main() -> None:
    out_csv = Path(sys.argv[1])
    registry = json.loads((MAIN / "docs/investigations/v05_readings/accepted_sandboxes.json").read_text(encoding="utf-8"))
    parts = []
    for cik, entry in registry.items():
        out = MAIN / "scratch/fund_sandbox" / entry["label"] / "output"
        if not (out / "private_markets_holdings.parquet").exists():
            print("missing sandbox", cik, entry["label"], flush=True)
            continue
        con = duckdb.connect()
        con.execute("SET memory_limit='3GB'")
        con.execute("SET threads=4")
        cr.load_fund_rows(con, out, cik)
        cr.issuer_name_differs_from_page(con)
        name = con.execute(f"""SELECT any_value(entity_name) FROM read_parquet('{(out / "private_markets_holdings.parquet").as_posix()}')
                               WHERE lpad(CAST(cik AS VARCHAR),10,'0') = '{cik}'""").fetchone()[0]
        df = con.execute("""
            SELECT cik, report_date, count(*) AS rows,
                   count(*) FILTER (WHERE printed_row IS NULL) AS no_printed_row,
                   count(*) FILTER (WHERE printed_row IS NOT NULL AND NOT comparable) AS not_comparable,
                   sum(abs(coalesce(fair_value, 0))) AS abs_fv,
                   sum(abs(coalesce(fair_value, 0))) FILTER (WHERE printed_row IS NULL OR NOT comparable) AS abs_fv_blind
            FROM _cr_names GROUP BY 1, 2 ORDER BY 2""").fetchdf()
        df.insert(1, "fund", name)
        df.insert(2, "label", entry["label"])
        df["blind_share"] = (df.no_printed_row + df.not_comparable) / df.rows
        df["fv_blind_share"] = df.abs_fv_blind.fillna(0) / df.abs_fv.where(df.abs_fv > 0)
        parts.append(df)
        print("%s %-6s quarters=%d rows=%d blind=%d" % (cik, entry["label"], len(df), df.rows.sum(),
                                                       (df.no_printed_row + df.not_comparable).sum()), flush=True)
        con.close()
    res = pd.concat(parts, ignore_index=True)
    res.to_csv(out_csv, index=False)
    print("wrote", out_csv, len(res))


if __name__ == "__main__":
    main()
