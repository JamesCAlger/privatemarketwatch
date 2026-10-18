"""Read-only: sample of the rule-1 rows added by 02311c2 (narrowed 'printed elsewhere' pass), seed 20261020.

    python scripts/v05_evidence/candidate_rules_falsealarm_sample_v3.py <rows_before.csv> <evidence_out.txt>

<rows_before.csv> is the rows CSV as of ddc0e92 (git show ddc0e92:docs/investigations/...rows.csv). New rows
= rule-1 rows in the current rows CSV whose (row_id, report_date) were not flagged before. 20 drawn, at most
5 per fund. Writes <out>.sample.csv and page-line evidence.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidate_rules_falsealarm_sample as v1  # noqa: E402

RULE = "issuer_name_differs_from_page"


def main() -> None:
    before = pd.read_csv(sys.argv[1], dtype=str)
    out_txt = Path(sys.argv[2])
    now = pd.read_csv(v1.DOCS / "v05_rule_candidates_2026-10-17_rows.csv", dtype=str)
    old = set(zip(before[before.rule == RULE].row_id, before[before.rule == RULE].report_date))
    new = now[(now.rule == RULE) & [k not in old for k in zip(now.row_id, now.report_date)]]
    print("new rule-1 rows:", len(new), "funds:", new.cik.nunique())
    print(new.groupby(["fund", "kind"]).size().to_string())
    v1.SEED, v1.N, v1.CAP = 20261020, 20, 5
    s = v1.stratified(new, "cik").assign(stratum="r1_new")
    s.insert(0, "sample_id", range(1, len(s) + 1))
    s.to_csv(out_txt.with_suffix(".sample.csv"), index=False)
    new.to_csv(out_txt.with_suffix(".new_rows.csv"), index=False)
    with out_txt.open("w", encoding="ascii", errors="replace") as fh:
        for r in s.itertuples():
            fh.write("=== #%d %s %s | %s %s %s | %s\n" % (r.sample_id, r.kind, r.basis, r.fund, r.report_date,
                                                      r.accession_number, r.issuer_name))
            fh.write("  instr=%r FV=%s printed=%r\n" % (r.instrument_description, r.fair_value, r.printed))
            fh.write("  printed_row=%r\n" % str(r.printed_row)[:260])
            fh.write("  member=%r\n" % str(r.member)[:220])
            for line in v1.probe(r):
                fh.write(line[:520] + "\n")


if __name__ == "__main__":
    main()
