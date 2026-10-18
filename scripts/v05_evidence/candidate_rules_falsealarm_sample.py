"""Read-only: draw the false-alarm review sample for the five candidate rules (2026-10-18).

    python scripts/v05_evidence/candidate_rules_falsealarm_sample.py <evidence_out.txt>

Reads docs/investigations/v05_rule_candidates_2026-10-17_rows.csv in this checkout. Per rule, 30 rows
at random (seed 20261018), no fund supplying more than 6. Rule 5 is sampled from its text kinds only
(owner 2026-10-18: the rate-only part is dropped). Rule 4 is sampled at fund-quarter level (30
fund-quarters, no fund more than 6), three flagged rows each. Writes the sample CSV next to the rows
CSV and, for each sampled row, the page lines around the issuer name (main checkout's cached filing,
via fund_gate.page_text) to the evidence file. Reviewer labels are added by hand afterwards.
"""
import re
import sys
from pathlib import Path

import pandas as pd

WT = Path(__file__).resolve().parents[2]
MAIN = WT.parents[2] if WT.parent.name == "worktrees" else WT
sys.path.insert(0, str(MAIN / "scripts/v05_evidence"))
from fund_gate import normalise, page_text  # noqa: E402

SEED = 20261018
N, CAP = 30, 6
DOCS = WT / "docs/investigations"


def stratified(df: pd.DataFrame, key: str) -> pd.DataFrame:
    shuffled = df.sample(frac=1.0, random_state=SEED)
    taken, counts = [], {}
    for idx, k in zip(shuffled.index, shuffled[key]):
        if counts.get(k, 0) >= CAP:
            continue
        counts[k] = counts.get(k, 0) + 1
        taken.append(idx)
        if len(taken) == N:
            break
    return df.loc[taken]


def windows(cik: str, acc: str, phrase: str, before: int, after: int, limit: int = 2) -> list[str]:
    text = page_text(cik, acc)
    if text is None:
        return ["(filing not cached)"]
    p = normalise(phrase)
    out = []
    for m in re.finditer(re.escape(p), text, flags=re.I):
        w = text[m.start(): m.start() + 200]
        if re.search(r"\d{4}-\d{2}-\d{2} 0\d{9}", w) or "Member" in w[:160]:
            continue
        out.append(text[max(0, m.start() - before): m.start() + after])
        if len(out) >= limit:
            break
    return out


def probe(row, before=80, after=320, limit=2) -> list[str]:
    cik = str(row.cik).zfill(10)
    name = str(row.issuer_name or "")
    tries = [name]
    words = re.sub(r"[^A-Za-z0-9&' ]+", " ", name).split()
    if len(words) > 2:
        tries.append(" ".join(words[:2]))
    if isinstance(row.printed, str) and row.printed and row.rule == "issuer_name_differs_from_page":
        tries.append(row.printed.split(" | ")[0])
    res = []
    for t in tries:
        if len(t) < 4:
            continue
        w = windows(cik, row.accession_number, t, before, after, limit)
        res.append("  phrase=%r hits=%d" % (t, len(w)))
        res.extend("    ..." + x for x in w)
        if w and t == name:
            break
    return res


def main() -> None:
    out_txt = Path(sys.argv[1])
    rows = pd.read_csv(DOCS / "v05_rule_candidates_2026-10-17_rows.csv", dtype=str)
    rows["fq"] = rows["cik"] + "|" + rows["report_date"]
    picks = []
    for rule in ["issuer_name_differs_from_page", "unit_count_differs_from_row_text", "pik_printed_not_published"]:
        picks.append(stratified(rows[rows.rule == rule], "cik").assign(stratum=rule))
    r5 = rows[rows.rule == "preferred_published_as_common"]
    picks.append(stratified(r5[r5.kind.isin(["text_says_preferred", "text_and_rate"])], "cik").assign(stratum="r5_text"))
    sample = pd.concat(picks)
    # rule 4: fund-quarters
    r4 = rows[rows.rule == "industry_not_published"]
    fq = r4.groupby(["cik", "fund", "report_date", "accession_number"]).size().reset_index(name="n_flagged")
    fq_s = stratified(fq, "cik")
    r4_rows = []
    for _, q in fq_s.iterrows():
        sub = r4[(r4.cik == q.cik) & (r4.report_date == q.report_date)].sample(n=min(3, q.n_flagged), random_state=SEED)
        r4_rows.append(sub.assign(stratum="r4_fq"))
    sample = pd.concat([sample] + r4_rows)
    sample.insert(0, "sample_id", range(1, len(sample) + 1))
    sample.drop(columns=["fq"]).to_csv(out_txt.with_suffix(".sample.csv"), index=False)
    fq_s.to_csv(out_txt.with_suffix(".r4fq.csv"), index=False)
    with out_txt.open("w", encoding="ascii", errors="replace") as fh:
        for r in sample.itertuples():
            before = 600 if r.stratum == "r4_fq" else 80
            fh.write("=== #%d %s %s | %s %s %s | %s\n" % (r.sample_id, r.stratum, r.kind, r.fund, r.report_date,
                                                       r.accession_number, r.issuer_name))
            fh.write("  instr=%r published=%r printed=%r FV=%s\n" % (r.instrument_description, r.published, r.printed,
                                                                   r.fair_value))
            fh.write("  printed_row=%r\n" % (str(r.printed_row)[:300]))
            fh.write("  member=%r\n" % (str(r.member)[:300]))
            for line in probe(r, before=before):
                fh.write(line[:1100] + "\n")
            print("done", r.sample_id, flush=True)


if __name__ == "__main__":
    main()
