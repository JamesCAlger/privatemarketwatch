"""Read-only: labels and scores for the second false-alarm sample (fixed rules, ddc0e92, seed 20261019).

    python scripts/v05_evidence/candidate_rules_falsealarm_score_v2.py <sample.csv> <r4fq.csv>

Labels written by the independent reviewer after reading each row's printed line in the cached filing.
Writes docs/investigations/v05_rule_candidates_falsealarm_2026-10-19_labels.csv and ..._rule4_fq.csv.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidate_rules_falsealarm_score import DOCS, F, R, U, wilson  # noqa: E402

STEM = "v05_rule_candidates_falsealarm_2026-10-19"
L = {}
# rule 1
for i, p in {1: "group_prefix", 2: "group_prefix", 3: "group_prefix", 4: "group_prefix", 5: "instrument_in_name",
             6: "group_prefix", 7: "name_doubled", 8: "footnote_digit_in_name", 9: "industry_in_name",
             10: "section_and_industry_prefix", 12: "section_word_prefix", 13: "member_abbreviation",
             14: "instrument_in_name", 15: "member_typo", 16: "member_typo", 17: "instrument_in_name",
             18: "section_residue_prefix", 19: "instrument_and_sequence_in_name", 20: "member_typo",
             22: "instrument_in_name", 23: "sequence_word_in_name", 24: "instrument_in_name",
             25: "section_residue_prefix", 26: "member_typo", 27: "stale_combined_name", 28: "instrument_in_name",
             29: "member_typo", 30: "industry_in_name"}.items():
    L[i] = (R, p, "")
L[11] = (R, "cosmetic_punctuation", "'Freddys' for printed \"Freddy's\" (cosmetic)")
L[21] = (R, "cosmetic_spacing", "'L V F Holdings' for printed 'LVF Holdings' (cosmetic)")
L[15] = (R, "member_typo", "member 'GPZN', page 'GPNZ' on every row")
L[27] = (R, "stale_combined_name", "current row prints 'NCWS Holdings LP'; published is the prior-period combined name")
# rule 2: all 30 real
for i in range(31, 61):
    L[i] = (R, "proxy_count_not_printed", "")
for i in (32, 34, 35, 41, 47, 50, 52, 54, 56):
    L[i] = (R, "sibling_row_count", "")
for i in (48, 49):
    L[i] = (R, "scale_div1000", "published about printed/1000")
L[44] = (R, "count_from_other_quarter", "page prints 142 Shares; published 534,375 (the 2023 count)")
L[60] = (R, "count_from_other_quarter", "page prints 534,375 Shares; published 142 (the 2025 count)")
L[43] = (R, "labelled_count_not_published", "82,735 Shares printed, none published")
# rule 3: all 30 real
for i in range(61, 91):
    L[i] = (R, "pik_not_published", "")
L[61] = L[62] = (R, "pik_rate_holds_spread", "pik_rate 6.25 = spread; PIK 2.50")
L[63] = (R, "pik_rate_holds_floor", "pik_rate 1.0 = floor")
L[64] = (R, "pik_rate_holds_all_in", "pik_rate 12.16 = all-in; PIK 4.50")
L[82] = (R, "pik_rate_holds_spread", "pik_rate 5.75 = spread; page '6.7% PIK'")
L[89] = (R, "pik_rate_holds_floor", "pik_rate 1.0 = floor; PIK 3.00")
# rule 5 text kinds
for i in range(91, 121):
    L[i] = (R, "filer_says_preferred", "")
L[93] = (U, "preferred_heading_only", "AB 'LP Interests' under the filer's 'U.S. Preferred Stock' heading")
L[103] = L[114] = (R, "filer_says_preferred", "member says Class A Units; values are the Series F Preferred row")
# pik_member_text_only
L.update({
    121: (R, "printed_on_page_not_joined", "visible row prints '(including 275 PIK)'; published 0.75 = floor"),
    122: (R, "printed_on_page_not_joined", "visible row prints '(incl. 3.50 % PIK)'; published 9.25 = spread"),
    123: (U, "page_silent", "member '600 PIK'; visible row prints no rate"),
    124: (F, "member_misattributed", "10.50% PIK belongs to the next row (IMG Blocker preferred); Accelerate common prints none"),
    125: (U, "page_silent", "member '1000 PIK'; visible row prints no rate"),
    126: (R, "printed_on_page_not_joined", "visible row prints 'S + 6.75 % PIK'; none published"),
    127: (F, "member_disagrees_with_page", "page DDTL prints 3.50% PIK = published; member 3.00"),
    128: (U, "page_silent", "member 'including 200 PIK'; visible row prints no rate"),
    129: (F, "member_stale", "member 'S+700 including 150 PIK'; visible row prints 'S + 550 (100 Floor)', no PIK"),
    130: (U, "page_silent", "member 'plus 75 PIK'; visible row prints none"),
})
# units_scale_unclear
L.update({
    131: (U, "hps_units_scale", "HPS 274 vs published 274,000"),
    132: (R, "cost_used_as_count", "Golub prints 1 unit, cost 1,279; published 1,279,000"),
    133: (F, "page_in_thousands", "Blue Owl printed 1,269,969 units in 2023, 1,270 here; published 1,269,969 is right"),
    134: (F, "page_in_thousands", "Blue Owl 2024 prints units in thousands (as #133); published 10,000 consistent with cost 10"),
    135: (U, "hps_units_scale", "HPS 3,528 vs 3,528,000"),
    136: (U, "hps_units_scale", "HPS 2,000 vs 2,000,000"),
    137: (F, "page_in_thousands", "Blue Owl 989 printed, cost 989; published 989,000 consistent with units in thousands"),
    138: (U, "hps_units_scale", "HPS 274 vs 274,000"),
    139: (R, "scale_x1000", "26North prints 400,429 shares at cost 400 (thousands): 400,429,000 is wrong"),
    140: (R, "scale_x1000", "T Series prints full counts (500,000; 1,383,156) beside 250: published 250,000 is wrong"),
})
R4_NOT_PRINTED: set = set()  # all 30 sampled fund-quarters print an industry


def main() -> None:
    s = pd.read_csv(sys.argv[1], dtype=str)
    fq = pd.read_csv(sys.argv[2], dtype=str)
    rows = s[s.stratum != "r4_fq"].copy()
    rows["sample_id"] = rows.sample_id.astype(int)
    rows["review_label"] = rows.sample_id.map(lambda i: L[i][0])
    rows["pattern"] = rows.sample_id.map(lambda i: L[i][1])
    rows["note"] = rows.sample_id.map(lambda i: L[i][2])
    keep = ["sample_id", "stratum", "rule", "kind", "basis", "cik", "fund", "report_date", "accession_number", "row_id",
            "issuer_name", "fair_value", "published", "printed", "review_label", "pattern", "note"]
    rows[keep].to_csv(DOCS / f"{STEM}_labels.csv", index=False)
    fq["industry_printed"] = ~fq.cik.isin(R4_NOT_PRINTED)
    fq["review_label"] = "gap_fillable"
    fq.to_csv(DOCS / f"{STEM}_rule4_fq.csv", index=False)
    print("| stratum | n | real | false | unclear | precision | 95% Wilson |")
    for st, g in rows.groupby("stratum", sort=False):
        k, f, u = (g.review_label == R).sum(), (g.review_label == F).sum(), (g.review_label == U).sum()
        lo, hi = wilson(k, k + f)
        print("| %s | %d | %d | %d | %d | %.3f | %.3f-%.3f |" % (st, len(g), k, f, u, k / (k + f), lo, hi))
    lo, hi = wilson(len(fq), len(fq))
    print("| r4_fq | %d | %d | 0 | 0 | 1.000 | %.3f-%.3f |" % (len(fq), len(fq), lo, hi))


if __name__ == "__main__":
    main()
