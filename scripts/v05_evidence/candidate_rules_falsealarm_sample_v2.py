"""Read-only: second false-alarm sample, on the rules as fixed in ddc0e92 (2026-10-19 seed).

    python scripts/v05_evidence/candidate_rules_falsealarm_sample_v2.py <evidence_out.txt>

Same method as candidate_rules_falsealarm_sample.py: seed 20261019, no fund more than 6 rows per
stratum. Strata: 30 finding rows per rule 1/2/3/5 (rule 2 without units_scale_unclear, rule 3 without
pik_member_text_only), 10 rows each of those two weaker kinds, and 30 rule-4 fund-quarters (3 rows
read each). Writes <out>.sample.csv, <out>.r4fq.csv and the page-line evidence file.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidate_rules_falsealarm_sample as v1  # noqa: E402

v1.SEED = 20261019


def strat(df, n):
    old = v1.N
    v1.N = n
    try:
        return v1.stratified(df, "cik")
    finally:
        v1.N = old


def main() -> None:
    out_txt = Path(sys.argv[1])
    rows = pd.read_csv(v1.DOCS / "v05_rule_candidates_2026-10-17_rows.csv", dtype=str)
    weak = {"units_scale_unclear", "pik_member_text_only"}
    picks = []
    for rule in ["issuer_name_differs_from_page", "unit_count_differs_from_row_text", "pik_printed_not_published",
                 "preferred_published_as_common"]:
        d = rows[(rows.rule == rule) & ~rows.kind.isin(weak)]
        picks.append(strat(d, 30).assign(stratum=rule))
    for k in sorted(weak):
        picks.append(strat(rows[rows.kind == k], 10).assign(stratum=k))
    sample = pd.concat(picks)
    r4 = rows[rows.rule == "industry_not_published"]
    fq = r4.groupby(["cik", "fund", "report_date", "accession_number"]).size().reset_index(name="n_flagged")
    fq_s = strat(fq, 30)
    r4_rows = [r4[(r4.cik == q.cik) & (r4.report_date == q.report_date)].sample(n=min(3, q.n_flagged), random_state=v1.SEED)
               .assign(stratum="r4_fq") for _, q in fq_s.iterrows()]
    sample = pd.concat([sample] + r4_rows)
    sample.insert(0, "sample_id", range(1, len(sample) + 1))
    sample.to_csv(out_txt.with_suffix(".sample.csv"), index=False)
    fq_s.to_csv(out_txt.with_suffix(".r4fq.csv"), index=False)
    with out_txt.open("w", encoding="ascii", errors="replace") as fh:
        for r in sample.itertuples():
            if r.stratum == "r4_fq":
                continue
            fh.write("=== #%d %s %s %s | %s %s %s | %s\n" % (r.sample_id, r.stratum, r.kind, r.basis, r.fund, r.report_date,
                                                         r.accession_number, r.issuer_name))
            fh.write("  instr=%r published=%r printed=%r FV=%s\n" % (r.instrument_description, r.published, r.printed, r.fair_value))
            fh.write("  printed_row=%r\n" % (str(r.printed_row)[:300]))
            fh.write("  member=%r\n" % (str(r.member)[:300]))
            for line in v1.probe(r):
                fh.write(line[:700] + "\n")
            print("done", r.sample_id, flush=True)


if __name__ == "__main__":
    main()
