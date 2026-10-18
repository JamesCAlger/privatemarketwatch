"""Read-only: labels for the 20-row sample of rule-1 rows added by 02311c2 (seed 20261020).

    python scripts/v05_evidence/candidate_rules_falsealarm_score_v3.py <sample.csv>

Writes docs/investigations/v05_rule_candidates_falsealarm_2026-10-20_rule1_new_labels.csv.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidate_rules_falsealarm_score import DOCS, F, R, wilson  # noqa: E402

TAG = "filer_fact_under_other_member"  # the page row is where the published FV is printed; the member names another company
CONT = "continuation_row_not_stopped"  # printed row is a later tranche whose first cell is an instrument the stop list misses
L = {
    1: (R, TAG, "values are Zendesk revolver (11/22/2028); member 'Visionary Buyer LLC | Zendesk, Inc.' published as Visionary"),
    2: (R, TAG, "published FV 193 is Excelitas's row; Dwyer revolver prints FV 240"),
    3: (R, TAG, "values (11.98%, 11/25/2025, 4,100,950) are AmerCareRoyal's; member says West Dermatology"),
    4: (F, CONT, "'Structured Secured Note - Class B' row under Perimeter Master Note Business Trust"),
    5: (F, CONT, "'Member interest (100.00% interest)' row under Ivy Hill Asset Management"),
    6: (R, "stale_member_name", "FV 6.8 is PCG-TAC-CV, LP (fka PCG-Ares Sidecar Investment II); published as PCG-Ares Sidecar Investment"),
    7: (R, TAG, "published FV 4,513 is Pregis TopCo's row; Plastipak prints 3,234"),
    8: (F, CONT, "'12,832 Class C' row under Raptor US Buyer II Corp."),
    9: (R, TAG, "member terms (11.99%, S + 8.00%, 12/31/26) and FV 12,375 are AQ Helios's row; published as AI Titan"),
    10: (R, TAG, "'TricorBraun Holdings, Inc. 2' FV 11,800 is Trident TPI's row; no second TricorBraun row prints 11,800"),
    11: (F, CONT, "'Structured Secured Note - Class E' row under Perimeter Master Note Business Trust"),
    12: (R, TAG, "FV 390 is LEP Pequod Holdings LP (Common); LEP McLarens prints LP Units 118"),
    13: (R, TAG, "FV 883 is a 1375 Owner LLC row; published as 1375 Mezz LLC"),
    14: (R, TAG, "FV 41,367.7 is Hyperion Refinance's row; Keystone prints 51,790.1 / 3,882.6"),
    15: (R, TAG, "member terms and FV 4,941 are Great Lakes Dental Partners' row; published as GrapeTree"),
    16: (R, TAG, "values are Webster Equity Partners III-A DDTL; member carries 'Visionary Buyer LLC |' in front"),
    17: (R, TAG, "member terms and FV 1,891 are New Era Technology's row; published as MRI Software"),
    18: (R, TAG, "member terms (S + 4.75%, 04/18/2033) and FV -12 are Bridgepointe's row; published as Appfire"),
    19: (F, CONT, "'12,832 Class E' row under Raptor US Buyer II Corp."),
    20: (R, TAG, "'IG Investments Holdings, LLC 2' FV 29,685 is Inmar, Inc.'s row"),
}


def main() -> None:
    s = pd.read_csv(sys.argv[1], dtype=str)
    s["sample_id"] = s.sample_id.astype(int)
    for c, k in (("review_label", 0), ("pattern", 1), ("note", 2)):
        s[c] = s.sample_id.map(lambda i: L[i][k])
    keep = ["sample_id", "kind", "basis", "cik", "fund", "report_date", "accession_number", "row_id", "issuer_name",
            "fair_value", "printed", "review_label", "pattern", "note"]
    s[keep].to_csv(DOCS / "v05_rule_candidates_falsealarm_2026-10-20_rule1_new_labels.csv", index=False)
    k, f = (s.review_label == R).sum(), (s.review_label == F).sum()
    lo, hi = wilson(k, k + f)
    print("real %d false %d precision %.3f wilson %.3f-%.3f" % (k, f, k / (k + f), lo, hi))
    print(s.groupby(["review_label", "pattern", "fund"]).size().to_string())


if __name__ == "__main__":
    main()
