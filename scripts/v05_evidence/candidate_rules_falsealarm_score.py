"""Read-only: attach the reviewer's labels to the false-alarm sample and score each rule (2026-10-18).

    python scripts/v05_evidence/candidate_rules_falsealarm_score.py <sample.csv> <r4fq.csv>

The labels below were written by an independent reviewer after reading each sampled row's printed line
in the cached filing (candidate_rules_falsealarm_sample.py evidence, page_line.py, the raw table rows).
Writes, in docs/investigations/: v05_rule_candidates_falsealarm_2026-10-18_labels.csv (row labels),
..._rule4_fq.csv (fund-quarter labels) and prints the precision table.
"""
import math
import sys
from pathlib import Path

import pandas as pd

WT = Path(__file__).resolve().parents[2]
DOCS = WT / "docs/investigations"
STEM = "v05_rule_candidates_falsealarm_2026-10-18"
R, F, U = "real_error", "false_alarm", "unclear"

LABELS = {
    # rule 1 issuer_name_differs_from_page
    1: (R, "group_prefix", "page row prints 'VCI Intermediate TopCo 3 LLC' under group heading 'Valor'"),
    2: (R, "group_prefix", "group heading row 'Vantive', entity row 'Spruce Bidco II Inc.'"),
    3: (R, "instrument_in_name", "instrument 'Extended Series C Warrants' appended to the issuer"),
    4: (R, "group_prefix", "'EG Group' heading + 'EG Group Limited'"),
    5: (R, "group_prefix", "'McGraw Hill' heading + 'McGraw-Hill Education, Inc.'"),
    6: (R, "group_prefix", "'JPW' heading + 'JPW Industries Holding Corporation'"),
    7: (F, "member_carries_fuller_legal_name", "page prints 'IMA Financial Group', member adds 'LLC'; published name is the legal name"),
    8: (R, "group_prefix", "'Protein for Pets' heading + 'Protein For Pets Opco, LLC'"),
    9: (R, "footnote_digit_in_name", "'Kaseya, Inc.4': footnote 4 glued to the name"),
    10: (R, "group_prefix", "'KLO Holdings, LLC' heading + '1244311 B.C. Ltd.'"),
    11: (F, "printed_row_starts_at_industry_cell", "New Mountain prints 'Sierra Enterprises, LLC' then 'Food & Beverage'; joined row lost the company cell"),
    12: (R, "industry_in_name", "', Diversified Consumer Services' appended"),
    13: (R, "industry_in_name", "'Commercial Services & Supplies' appended"),
    14: (F, "page_spelling_variant", "this row prints 'ClearCapital', sibling rows print 'Clear Capital'"),
    15: (R, "instrument_as_issuer", "issuer published as 'CLO Notes'; page issuer is 'Rockford Tower CLO 2024-1'"),
    16: (R, "member_typo", "member 'USA Debunk', page 'USA Debusk'"),
    17: (F, "printed_row_starts_at_industry_cell", "New Mountain: 'Coyote Buyer, LLC' printed before 'Specialty Chemicals & Materials'"),
    18: (F, "printed_row_starts_at_industry_cell", "New Mountain: 'Foundational Education Group, Inc.' printed before 'Education'"),
    19: (R, "instrument_in_name", "', Private asset-backed investment' appended"),
    20: (R, "industry_in_name", "industry appended (joined printed row is also the next issuer's)"),
    21: (F, "printed_row_starts_at_industry_cell", "New Mountain: 'Tahoe Finco, LLC' printed before 'Information Technology'"),
    22: (R, "industry_in_name", "'Commercial Services & Supplies' appended"),
    23: (U, "page_and_member_name_differ", "current row prints 'FineLine Systems', member and prior period 'Fineline Technologies, Inc.' (rename?)"),
    24: (F, "printed_row_misjoined", "joined row is Movati; page prints 'Southpaw AP Buyer, LLC' = published"),
    25: (R, "industry_in_name", "'Environmental, Maintenance and Security Services' prefixed"),
    26: (R, "member_names_other_entity", "equity row prints 'Wildcat Parent LP'; published 'Wildcat BuyerCo, Inc.' (the borrower)"),
    27: (F, "page_spelling_variant", "this row prints 'Ascend Partners', sibling rows 'Ascend Partner'"),
    28: (R, "instrument_in_name", "'First lien senior secured revolving loan' appended"),
    29: (R, "industry_in_name", "'Commercial Services & Supplies' appended"),
    30: (F, "printed_row_starts_at_industry_cell", "New Mountain: 'Sierra Enterprises, LLC' printed before 'Food & Beverage'"),
    # rule 2 unit_count_differs_from_row_text
    31: (R, "proxy_count_not_printed", "177,076 published, row prints 8,824"),
    32: (R, "labelled_count_not_published", "row prints 423,728 units, none published"),
    33: (R, "sibling_row_count", "770 is the Class A preferred units' count; row prints 770,423"),
    34: (F, "member_up_to_count", "published 3,223,122 = page count; member says 'up to 3,280,444' (warrant)"),
    35: (U, "scale_undecidable", "page prints '4' in Principal/Share column of an in-thousands schedule; 4,000 may be right"),
    36: (R, "proxy_count_not_printed", "3 published, row prints 2,670"),
    37: (R, "proxy_count_not_printed", "46,363 published, row prints 238"),
    38: (R, "proxy_count_not_printed", "25,739 published, row prints 527,226"),
    39: (R, "proxy_count_not_printed", "44,535 published, row prints 1,195,880"),
    40: (R, "proxy_count_not_printed", "235,740 published, row prints 11,786"),
    41: (R, "scale_x1000", "400,429,000 published, row prints 400,429"),
    42: (R, "sibling_row_count", "817,194 is the Series A units' count; row prints 129,822"),
    43: (R, "sibling_row_count", "6,667 is the B-2 warrants' count; row prints 11,911"),
    44: (R, "sibling_row_count", "907,499 is the common stock's count; preferred row prints 3,719"),
    45: (R, "sibling_row_count", "129,822 is the preferred count; units row prints 817,194"),
    46: (R, "proxy_count_not_printed", "318,631 published, row prints 11,786"),
    47: (R, "proxy_count_not_printed", "244 published, row prints 173,048 units"),
    48: (R, "proxy_count_not_printed", "4,648,653 published, row prints 6,047,390"),
    49: (R, "sibling_row_count", "1,251 is Class A's count; Class B row prints 17,221"),
    50: (U, "scale_undecidable", "HPS 'Par Amount/Units' 6,312 vs published 6,312,000: units scale not stated on the row"),
    51: (R, "sibling_row_count", "15,636 is Class A's count; Class B row prints 833,140"),
    52: (R, "labelled_count_not_published", "row prints 38,889 Shares, none published"),
    53: (R, "sibling_row_count", "1,041 is the Class Z units' count, put on the Blocker Note row"),
    54: (U, "scale_undecidable", "HPS 2,000 vs published 2,000,000 (same as #50)"),
    55: (R, "sibling_row_count", "2,766 is Additional A's count; Additional B row prints 147,380"),
    56: (R, "scale_x1000", "400,429,000 published, row prints 400,429"),
    57: (U, "member_names_other_row", "member says FS WhiteWater, FV and date are the RPC ABC row (320,487); 221 is FS WhiteWater's count"),
    58: (R, "sibling_row_count", "116 is the preferred stock's count; Equity Unit row prints 1,176"),
    59: (R, "proxy_count_not_printed", "1,105 published, row prints 1,251"),
    60: (F, "digit_in_issuer_name", "'Holdings 1 LLC Class B Interests' read as a count of 1; published 1,237 = page"),
    # rule 3 pik_printed_not_published
    61: (R, "pik_not_published", "8.00% PIK on preferred units"),
    62: (R, "pik_not_published", "11.64% (4.50% PIK)"),
    63: (R, "pik_not_published", "11.00% PIK on preferred shares"),
    64: (R, "pik_not_published", "13.65% (3.25% PIK)"),
    65: (R, "pik_not_published", "8.00% PIK on Class A units"),
    66: (R, "pik_not_published", "SOFR + 6.0% PIK"),
    67: (R, "pik_not_published", "15.00% PIK"),
    68: (F, "member_disagrees_with_page", "member says 3.00% PIK; page DDTL row prints 3.50% PIK = published"),
    69: (R, "pik_not_published", "11.00% PIK on preferred"),
    70: (R, "pik_not_published", "including 50 PIK"),
    71: (F, "member_disagrees_with_page", "member says (5.00% PIK); page DDTL row prints no PIK (the term loan does)"),
    72: (R, "pik_rate_holds_all_in", "pik_rate 9.65 = all-in coupon; PIK is 4.25"),
    73: (R, "pik_not_published", "14.50% PIK"),
    74: (R, "pik_not_published", "S+450 PIK"),
    75: (R, "pik_not_published", "0.25% PIK"),
    76: (R, "pik_rate_holds_floor", "pik_rate 1.0 = floor; PIK margin 5.00"),
    77: (R, "pik_not_published", "E + 1000 PIK"),
    78: (R, "pik_not_published", "9.75% PIK"),
    79: (F, "filer_tag_rounding", "published 3.8 vs printed 3.83 (kind pik_value_rounding): filer tag precision, not a build error"),
    80: (R, "pik_not_published", "including 50 PIK"),
    81: (R, "pik_not_published", "SOFR+1260 PIK"),
    82: (R, "pik_not_published", "SOFR + 6.0% PIK"),
    83: (R, "pik_not_published", "(2.75% PIK)"),
    84: (R, "pik_not_published", "11.47% PIK"),
    85: (U, "member_says_pik_page_silent", "member '(plus 75 PIK)'; visible row prints no PIK"),
    86: (R, "pik_rate_holds_floor", "pik_rate 2.5 = floor; PIK margin 8.00"),
    87: (R, "pik_not_published", "13.75% PIK"),
    88: (R, "pik_rate_holds_floor", "pik_rate 1.0 = floor; PIK 3.00"),
    89: (R, "pik_rate_holds_floor", "pik_rate 2.5 = floor; PIK margin 6.50"),
    90: (R, "pik_not_published", "10.15% PIK"),
}
# rule 5 text kinds: all preferred-by-the-filer published as common except #96
for i in range(91, 121):
    LABELS[i] = (R, "filer_says_preferred", "")
LABELS[94] = LABELS[95] = LABELS[104] = LABELS[110] = LABELS[114] = LABELS[117] = LABELS[118] = LABELS[119] = (
    R, "filer_says_preferred", "Convertible Preference Shares")
LABELS[96] = (U, "preferred_heading_lp_interest", "row 'LP Interests' sits under the filer's 'U.S. Preferred Stock' heading")
LABELS[102] = (R, "filer_says_preferred", "member text names Class A Units but the row's values are Lucidworks Series F Preferred")

# rule 4 fund-quarters: is the industry printed on the page for the flagged rows?
R4_NOT_PRINTED = {"0002049733"}  # Blackstone Private Real Estate Credit: asset-type headings only (CMBS, RMBS, loans by property)
R4_NOTE = {
    "0002037804": "industry cell printed under each company (e.g. 'Software', 'Business Services'); build reads none",
    "0001925531": "industry cell printed under each company (e.g. 'Business Services'); build reads none",
    "0001766037": "industry cell printed under each company (e.g. 'Food & Beverage'); build reads none",
    "0001742313": "industry section headings printed ('Capital Equipment', 'Wholesale', 'FIRE: Real Estate')",
    "0001786108": "industry headings printed; extracted_industry partly holds section headings ('Warrant Investments- United States')",
    "0001825384": "industry section headings printed ('Insurance', 'Capital Markets')",
    "0001838126": "industry section headings printed ('Oil, Gas and Coal', 'Travel and Leisure')",
    "0001989817": "industry section headings printed ('Automobiles and Parts', 'Industrial Metals and Mining')",
    "0001837532": "industry section headings printed ('Leisure Products', 'Specialty Retail')",
    "0001634452": "industry printed on every row ('Software & Tech Services', 'Consumer Non-Cyclical')",
    "0002049733": "no industry printed: CMBS / RMBS / mezzanine headings, loans named by property address",
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def main() -> None:
    sample = pd.read_csv(sys.argv[1], dtype=str)
    r4fq = pd.read_csv(sys.argv[2], dtype=str)
    rows = sample[sample.stratum != "r4_fq"].copy()
    rows["sample_id"] = rows.sample_id.astype(int)
    rows["review_label"] = rows.sample_id.map(lambda i: LABELS[i][0])
    rows["pattern"] = rows.sample_id.map(lambda i: LABELS[i][1])
    rows["note"] = rows.sample_id.map(lambda i: LABELS[i][2])
    keep = ["sample_id", "stratum", "rule", "kind", "basis", "cik", "fund", "report_date", "accession_number", "row_id",
            "issuer_name", "fair_value", "published", "printed", "review_label", "pattern", "note"]
    rows[keep].to_csv(DOCS / f"{STEM}_labels.csv", index=False)
    r4fq["industry_printed"] = ~r4fq.cik.isin(R4_NOT_PRINTED)
    r4fq["review_label"] = r4fq.industry_printed.map({True: "gap_fillable", False: "coverage_limit"})
    r4fq["note"] = r4fq.cik.map(R4_NOTE)
    r4fq.to_csv(DOCS / f"{STEM}_rule4_fq.csv", index=False)

    allrows = pd.read_csv(DOCS / "v05_rule_candidates_2026-10-17_rows.csv", dtype=str, usecols=["rule", "kind", "cik"])
    print("| stratum | n | real | false | unclear | precision real/(real+false) | 95% Wilson | real/n | row-weighted |")
    for st, g in rows.groupby("stratum", sort=False):
        k, f, u = (g.review_label == R).sum(), (g.review_label == F).sum(), (g.review_label == U).sum()
        lo, hi = wilson(k, k + f)
        pool = allrows[allrows.rule == g.rule.iloc[0]]
        if st == "r5_text":
            pool = pool[pool.kind.isin(["text_says_preferred", "text_and_rate"])]
        w = pool.cik.value_counts()
        g = g.assign(w=g.cik.map(w) / g.cik.map(g.cik.value_counts()))
        dec = g[g.review_label != U]
        rw = (dec.w * (dec.review_label == R)).sum() / dec.w.sum()
        print("| %s | %d | %d | %d | %d | %.3f | %.3f-%.3f | %.3f | %.3f |" % (st, len(g), k, f, u, k / (k + f), lo, hi, k / len(g), rw))
    k = int(r4fq.industry_printed.sum())
    lo, hi = wilson(k, len(r4fq))
    print("| r4_fq | %d | gap %d | limit %d | - | %.3f | %.3f-%.3f | - | - |" % (len(r4fq), k, len(r4fq) - k, k / len(r4fq), lo, hi))
    print()
    print(rows[rows.review_label != R].groupby(["stratum", "review_label", "pattern"]).size().to_string())
    print()
    print(rows[rows.review_label == R].groupby(["stratum", "pattern"]).size().to_string())
    print()
    print(rows.groupby(["stratum", "basis", "review_label"]).size().to_string())


if __name__ == "__main__":
    main()
