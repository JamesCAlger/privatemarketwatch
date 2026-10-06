"""Write the v0.5 standing dispositions from a sandbox ledger.

    python scripts/v05_evidence/make_dispositions.py <sandbox label> [--write]

Each spec below is one decision recorded in docs/investigations/v05_decision_log.md. For `as_filed` and
`not_applicable` the fund-quarters are taken from the ledger's unresolved findings for that rule, so an
entry names exactly the quarters that were looked at. Nothing is written without --write.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import finding_dispositions as fd  # noqa: E402

label = sys.argv[1]
BCRED, OWL, ARES, HPS, APOLLO = "0001803498", "0001812554", "0001287750", "0001838126", "0001837532"
WHO, WHEN = "agent, owner permission given in session 2026-10-06", "2026-10-06"
S = "python scripts/v05_evidence/"
ALLQ = ["%d-%s" % (y, md) for y in range(2022, 2027) for md in ("03-31", "06-30", "09-30", "12-31")]
# Blue Owl: from 2024-12-31 undrawn lines come from the commitments table, which files no cost.
OWL_PROXY = {q for q in ALLQ if q >= "2024-12-31"}

# id, class, engine, rule, funds or None (all funds in the ledger with that rule), skip {(cik, quarter)}, supersede, statement, evidence, rerun
SPECS = [
    ("DS-001", "informational", "nonaccrual", "nonaccrual_flag", "*", set(), False,
     "The rule reports that a loan is on non-accrual. That is a credit fact about the loan, not a data defect.",
     [("code", "scripts/shadow_adapter.py _nonaccrual_select: 'Non-accrual evidence -- a PRESENCE signal, not a pass/fail check. "
               "Non-accrual is a credit-risk fact, not a data defect, so it is ingested as a weak warn'.")],
     "grep -n 'PRESENCE signal' scripts/shadow_adapter.py"),
    ("DS-002", "informational", "provenance_reverify", "text_pathway", "*", set(), False,
     "The rule records that a value was read from the row text rather than from a tag. It names a pathway, not an error.",
     [("code", "scripts/shadow_adapter.py: 'weak/warn = informational states'; PROV_WEAK_WARN lists text_pathway."),
      ("query", "Sandbox five10, Apollo: affected fair value 0.0M in all 12 fund-quarters.")],
     S + "family.py five10 text_pathway"),
    ("DS-003", "not_applicable", "fund_financials", "F28", None, set(), False,
     "Fund-level figures exist for these quarters but the cache holds no position schedule before the fund's first "
     "structured filing, so there are no holdings to compare.",
     [("query", "Published holdings start at 2022-09-30 for Ares and BCRED and at 2023-03-31 for Blue Owl, HPS and Apollo "
                "(sandbox five10). The Ares row dated 2026-04-27 is a fund-level fact after the last schedule."),
      ("query", "Whether earlier schedules exist on EDGAR was not checked: downloads are not permitted in this run.")],
     S + "ffval.py five10 F28"),
    ("DS-004", "as_filed", "row_validation", "C107", [OWL, HPS], {(OWL, q) for q in OWL_PROXY}, False,
     "Negative cost on undrawn revolvers and delayed draws, filed net of fees.",
     [("query", "Sandbox five12: Blue Owl to 2024-09-30, 717 negative-cost rows, cost a filed fact on every one, all with "
                "fair value at or below zero. HPS 1,328 rows, cost a filed fact on every one, 1,181 with fair value at or "
                "below zero; identifiers carry no instrument wording.")],
     S + "negcost.py five12"),
    ("DS-004A", "as_filed", "row_validation", "C107", [APOLLO], set(), True,
     "Negative cost on undrawn revolvers and delayed draws, printed in the schedule. Two reviewer verdicts called these "
     "real errors; the lines they quote show the negative cost in the filing.",
     [("filing", "Apollo 10-Q for 2025-09-30, schedule lines: 'MRO Holdings, Inc. | First Lien Secured Debt - Revolver | "
                 "S + 450, 0.50 % Floor | 5/5/2032 | -- | ( 802 ) | ( 213 )' and 'TITAN BW BORROWER L.P. | Revolver | -- | "
                 "( 327 ) | ( 336 )': par blank, cost and value negative. Published cost for the Titan revolver is -327,000."),
      ("query", "Sandbox five12: 998 of 1,039 negative-cost rows carry a filed cost fact; 41 carry a labelled proxy.")],
     S + "negcost.py five12"),
    ("DS-004B", "not_applicable", "row_validation", "C107", [OWL], {(OWL, q) for q in ALLQ if q not in OWL_PROXY}, True,
     "From 2024-12-31 Blue Owl files undrawn lines in its commitments table with a fair value and no cost. The published "
     "cost on those rows is the pipeline's labelled proxy (cost_source first_observed_fv_proxy), not a filed figure, so a "
     "test of filed cost does not apply. The reviewers' point stands: the filing gives no cost for these rows.",
     [("filing", "0001812554-26-000027 context c-925 (Ministry Brands revolving loan): InvestmentCompanyFinancialCommitment"
                 "ToInvesteeFutureAmount, InvestmentCompanyFinancialSupportToInvesteeContractuallyRequiredAmount and "
                 "InvestmentOwnedFairValueNetOfUnamortizedFees = -4083000; no InvestmentOwnedAtCost fact."),
      ("query", "Sandbox five12: 508 such rows in six quarters, cost -64.9M in total, every one with fair value at or below "
                "zero. Published total equals the filed total in all six quarters with these rows included.")],
     S + "owl_commit.py five12"),
    ("DS-005", "as_filed", "row_validation", "X06", [BCRED, OWL, ARES, HPS, APOLLO], set(), False,
     "Principal far above fair value on partly drawn commitments (principal is the commitment) and on loans the fund has "
     "marked down, as filed.",
     [("query", "Sandbox five10, rows the rule flags: HPS 258 rows, 163 with fair value under 2 pct of principal and 160 with cost "
                "at or below zero, largest value 4.3M (Severin Acquisition 1: value 4.26M, cost 3.65M, commitment 63.0M). "
                "BCRED Material Holdings 2: value 4.2M, cost 57.1M, principal 60.6M (a markdown). Ares Eckler Industries: value "
                "1.5M, cost 25.5M, principal 28.8M. Apollo Mitel Networks: value 0.25M, cost 3.2M, principal 3.2M."),
      ("filing", "Ares 2022-09-30 (0001287750-22-000052): Senior Direct Lending Program subordinated certificates, printed "
                 "schedule line '269,806.0 1,121.0 1,121.0' and tag InvestmentOwnedBalancePrincipalAmount = 269806000000. "
                 "The principal is wrong in the filing itself; no filed alternative exists. See DS-022.")],
     S + "issue_shape.py five10 X06 3"),
    ("DS-006", "as_filed", "row_validation", "X02", [BCRED, OWL, HPS], set(), True,
     "Credit rows with no rate and no spread because no rate or spread fact is tagged for them: undrawn lines, non-accrual "
     "loans, and loans whose only rate tag is a PIK rate (published in pik_rate). Reviewer verdicts for these funds cite "
     "rows that are now populated or whose only tag is the PIK one.",
     [("filing", "Blue Owl 0001812554-26-000027: AAM Series 1.1 Rail (context c-608) carries InvestmentInterestRatePaidInKind "
                 "0.12 and no other rate fact; the schedule has Ref. Rate, Cash and PIK columns and no all-in rate. ABB/Con-cise "
                 "Optical, cited by the reviewer, now publishes its spread of 7.5. HPS 0001628280-26-033248 context c-922 "
                 "(Daphne S.P.A.): InvestmentInterestRatePaidInKind 0.0675 only; the printed line shows 'E + 6.75 %' and 8.75 %. "
                 "BCRED 0001803498-24-000044 context c-1374 (WHCG Purchaser III, Inc.): cost and value facts only; AI Altius "
                 "Bidco, cited by the reviewer, is no longer flagged."),
      ("query", "Sandbox five9: Blue Owl 1,908 rows, 1,634 with fair value at or below zero, 247 PIK only. HPS 1,366 rows, "
                "1,084 at or below zero, 130 PIK only. BCRED 3 rows."),
      ("query", "Limit: for HPS and Blue Owl the printed schedule shows a margin or coupon on PIK loans that the tags do "
                "not carry as a spread or rate. The published fields follow the tags.")],
     S + "norate2.py five12"),
    ("DS-006A", "as_filed", "row_validation", "X02", [ARES], set(), True,
     "Credit rows with no rate and no spread because the filing prints and tags none: loans on non-accrual and undrawn "
     "lines. The rows the reviewers cited now publish a rate (PIK-only coupons, decision D-018; rates joined from a "
     "neighbouring context, decision D-020).",
     [("filing", "Ares 10-Q for 2025-06-30 (0001287750-25-000038), printed lines with no coupon and footnote (9): 'Pathway Vet "
                 "Alliance LLC and Jedi Group Holdings LLC ... Second lien senior secured loan 03/2020 06/2028 78.6 75.5 51.1 "
                 "(2)(9)'; 'Florida Food Products, LLC ... Second lien senior secured loan 10/2021 10/2029 71.8 69.5 47.4 "
                 "(2)(9)'; 'Continental Acquisition Holdings, Inc. ... First lien senior secured loan 01/2021 07/2028 39.3 36.8 "
                 "22.8 (2)(9)'."),
      ("query", "Sandbox five13: 14 to 30 funded loans a quarter carry no rate fact; fair value is well below principal on "
                "most (2025-06-30: 25 rows, 377M). Only those three issuers were read on the printed page.")],
     S + "orphan_rates.py five14 1287750 2025-06-30"),
    ("DS-006B", "as_filed", "row_validation", "X02", [APOLLO], set(), False,
     "One loan is filed with no rate in its tags or its row text.",
     [("filing", "Apollo 10-Q for 2025-03-31 and 2025-06-30: 'Aerospace & Defense Spirit Aerosystems Spirit Aerosystems, Inc. "
                 "Investment Type First Lien Secured Debt - Term Loan Maturity Date 6/30/2025', fair value 47.75M; no "
                 "InvestmentInterestRate or spread fact on its context.")],
     S + "flagged.py five14 X02 1837532 2025-03-31"),
    ("DS-012", "as_filed", "row_validation", "X01", [ARES, HPS], set(), False,
     "Equity units printed with a coupon. The rate is filed; the filer names the instrument units, not preferred.",
     [("filing", "Ares 10-Q for 2024-03-31: 'LJP Purchaser, Inc. and LJP Topco, LP ... Class A units 8.00 % PIK 09/2022 "
                 "5,098,000 5.8 6.4'. Ares 10-Q for 2025-03-31: SM Wellness 'Series D units 8.00 % PIK 03/2023 1,127 1.3 1.8'. "
                 "HPS filings for 2025-03-31 to 2025-09-30: 'OneTeam Partners, LLC - Class D Units 8.00 % 8.00 %'."),
      ("query", "Ares Redwood Services Series D units (60.5M, 2024-03-31) carries a tagged rate of 8.0; its printed line was "
                "not found by text search. HPS relabels the same position 'Preferred Units' from 2025-12-31; those two "
                "quarters are corrected to preferred equity (decision D-021).")],
     S + "equity_with_rate.py five14"),
    ("DS-007", "as_filed", "row_validation", "C103", [HPS, APOLLO], set(), False,
     "Small negative fair values on undrawn lines whose identifier does not name the instrument.",
     [("query", "Sandbox five4: HPS 16 rows, 10 with cost exactly zero, 1.24M in total, largest 0.28M (Femur Buyer Inc 2: value "
                "-49,000, cost 0, no principal). Apollo 62 rows across the period, 60 named revolver or delayed draw.")],
     S + "unfunded.py five10"),
    ("DS-008", "as_filed", "weak", "maturity_not_past", [APOLLO], set(), True,
     "One loan, Heubach Holdings USA LLC, is filed with a maturity of 4/30/2024 in six later filings.",
     [("filing", "Apollo Debt Solutions 10-Q and 10-K filings for 2024-06-30 to 2025-09-30: the position's identifier reads "
                 "'... Maturity Date 4/30/2024' and the tagged maturity is 2024-04-30 (maturity_date_source xbrl_field); fair "
                 "value 0.2M to 0.8M.")],
     S + "weakrows.py five10 1837532"),
    ("DS-010", "as_filed", "oracle", "B01", [APOLLO], set(), True,
     "Position contexts with no fair value fact: undrawn lines with nothing filed, and a few positions the filer tagged "
     "under two spellings.",
     [("query", "Sandbox five5: 32 to 64 such contexts a quarter; about half named revolver or delayed draw; at most 4 carry "
                "units and 3 a principal."),
      ("filing", "2026-03-31 (0001193125-26-215667): the reviewer's verdict rested on the published total being 3,272 below "
                 "the printed 'Total Investments before Cash Equivalents $ 25,426,426 $ 25,149,083'. That gap was two "
                 "delayed-draw lines tagged with the wrong sign (Rocket Youth, printed 1,884, tagged -1,884; SavATree, "
                 "printed ( 248 ), tagged 248), corrected in decision D-021. Published now equals the printed total in all "
                 "13 quarters (sandbox five14).")],
     S + "b01.py five10 1837532"),
    ("DS-011", "as_filed", "oracle", "C04", [HPS, OWL], set(), False,
     "Equity rows filed without a unit count.",
     [("query", "Sandbox five10: HPS 345 of 367 equity rows carry units overall (22 without, 27M); Blue Owl 615 of 673 (58 "
                "without, 682M, mostly fund interests filed with a principal). The fund-quarters below are those under 70 pct.")],
     S + "ident_c04.py five10"),
    ("DS-013", "as_filed", "provenance_reverify", "merged_context_excluded", [ARES], set(), False,
     "Rows the filer tagged across several contexts under the issuer names alone; the pipeline assembles them.",
     [("query", "Sandbox ares3: Expereo USA, Inc. and Ristretto Bidco B.V., 60.2M at 2025-03-31 and 61.0M at 2025-06-30, built "
                "from four contexts (cost, fair value and principal filled); Rawlings Sporting Goods loan at 2024-12-31 "
                "(rate filled)."),
      ("query", "2023-12-31 and 2025-09-30: rates joined from a neighbouring rate-only context under decision D-020 (Apex "
                "Service Partners c-1205 to c-1206; Flexera c-164 to c-165; Sunk Rock c-1474 to c-1475).")],
     S + "orphan_pairs.py five13 1287750"),
    ("DS-014", "as_filed", "row_validation", "FX01", [APOLLO], set(), False,
     "One loan's principal has no dollar equivalent because the filing names its currency as KPW, for which no rate exists.",
     [("query", "Apollo 2024-06-30, Delivery Hero Finco Germany: principal 195,000,000,000 with document unit KPW; later "
                "filings give KRW and convert (about 148M). The data contract lists this case and says the later filing does "
                "not certify the earlier one.")],
     S + "weakrows.py five10 1837532"),
    ("DS-015", "as_filed", "provenance_reverify", "financial_convention_unresolved", [ARES, APOLLO], set(), False,
     "Rows whose filed rate is below their PIK rate. The filed rate cannot be the all-in coupon, and the all-in coupon "
     "cannot be derived, so the published rate is left empty.",
     [("query", "Sandbox five8: 13 Ares rows (194.2M) and 2 Apollo rows (124.9M), e.g. Ares NMC Skincare 2023-12-31 filed 1.0 "
                "with PIK 11.44; Apollo Paymentsense filed 0.125 with PIK 6.25.")],
     S + "rate_kind_test2.py five10"),
    ("DS-016", "not_applicable", "row_validation", "SRC_BDC01", [ARES, OWL, APOLLO], set(), False,
     "Source rows the reconciliation reads as missing positions are issuer-level or subtotal rows, not positions.",
     [("query", "Ares: 'Visual Edge Technology, Inc.' 70.5M at 2026-03-31 equals its six published positions (14.4 + 7.8 + "
                "34.4 + 2.5 + 9.9 + 1.5), which are named 'Visual Edge Technology, Inc., VEIT, LLC, and VEIT Topco, LLC'; "
                "'Olympia ... Asclepius Hodlings LLC' is a misspelt issuer group. Apollo: 'Total Pharmaceuticals' and "
                "'Insurance First Lien Secured Debt - Revolver'. Blue Owl: 'Blue Owl Cross-Strategy Opportunities LLC (BOCSO)' "
                "and 'Notorious Topco, LLC (dba Beauty Industry Group)' issuer rows."),
      ("query", "Published totals equal filed totals in these fund-quarters (sandbox five6), so no position is missing.")],
     S + "issues2.py five10 SRC_BDC01 1287750"),
    ("DS-017", "not_applicable", "source_recon", "blocking_source_position_like_parser_mismatch", [ARES, OWL], set(), False,
     "The same issuer-level source rows as DS-016, reported by the reconciliation's second engine.",
     [("query", "Ares 'Olympia Acquisition, Inc., Olympia TopCo, L.P. and Asclepius Hodlings LLC' 48.6M, 44.7M, 37.5M "
                "(2022-09-30 to 2023-03-31); Blue Owl BOCSO 303.9M and 24.8M at 2025-12-31, 378.0M and 24.7M at 2026-03-31. "
                "Published totals equal filed totals in those quarters.")],
     S + "recstatus2.py five10 1287750 position_like_parser_mismatch"),
    ("DS-027", "not_applicable", "row_validation", "SRC_BDC01", [BCRED], set(), False,
     "The source rows read as missing positions are footnote figures tagged on an issuer's name, excluded by rule.",
     [("filing", "0001803498-24-000044 footnote: '$ 54.2 million of the cost and $ 35.6 million of fair value of WHCG Purchaser "
                 "III, Inc. is considered to be on non-accrual status'. Context c-1374 carries only that cost and fair value; "
                 "c-4046 carries the JV's share (3.3M cost, 2.2M fair value) the same way. The schedule positions are "
                 "contexts c-352 and c-353."),
      ("query", "Sandbox five15: with the two rows excluded the published total equals the filed total at 2024-06-30.")],
     S + "bcred_footnote_rows.py five14"),
    ("DS-028", "not_applicable", "source_recon", "blocking_source_position_like_parser_mismatch", [BCRED], set(), False,
     "The same footnote rows as DS-027, reported by the reconciliation's second engine.",
     [("filing", "See DS-027: 0001803498-24-000044 contexts c-1374 and c-4046, footnote figures for WHCG Purchaser III, Inc.")],
     S + "bcred_footnote_rows.py five14"),
    ("DS-018", "as_filed", "row_validation", "SRC_BDC02", [ARES], set(), False,
     "Eight positions restored by rule: their cost and fair value are filed on the issuer-name axis, so they have no "
     "source row on the position context.",
     [("filing", "0001287750-25-000020 contexts c-1033, c-1491, c-1679, c-1699 and 0001287750-25-000038 contexts c-1171, "
                 "c-1590, c-1729, c-1750 carry InvestmentOwnedAtCost and InvestmentOwnedAtFairValue under "
                 "InvestmentIssuerNameAxis; totals 94.3M and 33.2M, the fund's shortfall in those quarters.")],
     S + "ares_nofv.py five10 2025-03-31"),
    ("DS-019", "as_filed", "provenance_reverify", "anchor_missing", [ARES], set(), False,
     "The same eight restored positions as DS-018: the value context is not the position's own, so the re-verifier finds "
     "no anchor.",
     [("filing", "See DS-018: values are on the issuer-name-axis contexts of 0001287750-25-000020 and 0001287750-25-000038.")],
     S + "ares_nofv.py five10 2025-03-31"),
    ("DS-020", "as_filed", "identity", "pct_of_net_assets_identity", [BCRED, OWL], set(), False,
     "One to five rows a quarter, out of several hundred, carry a filed percent that disagrees with their fair value. "
     "The published percent is the tagged fact.",
     [("filing", "BCRED 0001803498-23-000012, RoadOne Inc, context i8f6a38cb858548e3a3e7799099e66ff5_I20230331: percent "
                 "tagged 0.07 (7 pct) on a 1.1M position in a 23.1B fund. Blue Owl 2023-06-30, Spotless Brands first lien "
                 "loan: tagged 0.9 on 53.5M of 6.69B net assets (0.80)."),
      ("query", "Sandbox five11: failing rows per quarter 1, 3, 3, 3, 1 of 735 to 961 (BCRED) and 1 to 5 of 283 to 405 "
                "(Blue Owl); the median implied net assets match the filed figure within 0.7 pct in every quarter.")],
     S + "ident_left.py five11"),
    ("DS-021", "as_filed", "identity", "income_identity", [HPS, OWL], set(), False,
     "Net investment income is filed after fee waivers and expense support; the expenses field holds the gross figure.",
     [("filing", "HPS 10-Q, three months to 2022-06-30: income 37,750,000, InvestmentCompanyExpenseAfterReductionOfFeeWaiver"
                 "AndReimbursement 4,097,000, net investment income 33,653,000; gross expenses 16,022,000, so the gap is "
                 "11,925,000. To 2022-09-30: 83,118,000 less 19,958,000 is 63,160,000. Blue Owl 10-Q to 2022-03-31: "
                 "InvestmentCompanyExpenseOffsetArrangement 4,062,000, the gap to the dollar."),
      ("query", "HPS 2022-03-31 and 2022-12-31 have no net-expense fact for the quarter; the same waiver is assumed.")],
     S + "waivers.py 1838126 2022"),
    ("DS-022", "as_filed", "weak", "fmt_principal_amount", [ARES], set(), False,
     "Senior Direct Lending Program certificates at 2022-09-30 are filed with a principal of 269,806,000,000 against a "
     "cost and value of 1,121,000,000. The filing is wrong and offers no other figure, so the filed number stands.",
     [("filing", "0001287750-22-000052 context id76f5ace86324911921d72b1dbdc0154_I20220930: InvestmentOwnedBalancePrincipal"
                 "Amount = 269806000000; printed schedule line '12/2036 269,806.0 1,121.0 1,121.0'. Other quarters file a "
                 "principal equal or close to cost (2022-12-31: 1,274,100,000).")],
     S + "filing_grep.py 1287750 000128775022000052 html \"Subordinated certificates\" 6 260"),
    ("DS-023", "as_filed", "weak", "fmt_principal_amount_usd", [ARES], set(), False,
     "The dollar principal of the same row as DS-022.",
     [("filing", "See DS-022: 0001287750-22-000052, principal tagged and printed as 269,806.0 (millions).")],
     S + "sdlp.py five11"),
    ("DS-024", "not_applicable", "row_validation", "PP03", [OWL], set(), False,
     "One small equity row a quarter is the current-period fact; its unit count was rescaled to the scale of earlier "
     "filings, which makes it equal the prior-period fact the check compares with.",
     [("query", "Blue Owl 2024-12-31, Gloves Holdings LP Interest: published row is context c-1174 (period 2024-12-31, "
                "value 118,000, cost 100,000, units filed 1,000,000 and published 1,000 by the shares normalisation); the "
                "prior-period context c-1947 files 1,000 units. Same row at 2023-06-30 and 2024-06-30; Hercules Buyer "
                "Common Units at 2023-12-31.")],
     S + "row.py five11 1812554 2024-12-31 \"Gloves Holdings, LP\" 4"),
    ("DS-025", "not_applicable", "row_validation", "SRC_BDC03", [APOLLO], set(), False,
     "Two rows are published from the printed schedule, not the tag, because the tag has the wrong sign. A comparison "
     "with the tag is expected to disagree on them.",
     [("filing", "0001193125-26-215667: Rocket Youth Brands Holdco LLC delayed draw, printed '2,047 2,013 1,884', tag "
                 "InvestmentOwnedAtFairValue = -1884000 (context C_7b0eb0f5-42c5-465b-a014-838550129a62); SAVATREE CI delayed "
                 "draw, printed '- ( 44 ) ( 248 )', tagged 248. Issuer subtotals 11,000 and 16,538 and the industry total "
                 "1,162,031 agree with the printed figures.")],
     S + "apollo_industry_totals.py five14 000119312526215667 2026-03-31"),
    ("DS-026", "not_applicable", "source_recon", "blocking_fair_value_disagreement", [APOLLO], set(), False,
     "The same two corrected rows as DS-025, reported by the reconciliation's second engine.",
     [("filing", "See DS-025: 0001193125-26-215667, Rocket Youth and SavATree delayed-draw lines; printed values 1,884 and "
                 "( 248 ) against tags of -1,884 and 248.")],
     S + "apollo_industry_rows.py five13 000119312526215667 2026-03-31 \"Diversified Consumer Services\""),
]
# A finding already closed by a disposition stays in scope, so regenerating keeps its entry.
RESOLVED = {"adjudicated_false_alarm", "remediated_promoted", "resolved_upstream", "gone_unadjudicated"}
csv.field_size_limit(10**9)
quarters = defaultdict(set)
with open(REPO / "scratch/fund_sandbox" / label / "findings_ledger.csv", newline="", encoding="utf-8-sig") as fh:
    for row in csv.DictReader(fh):
        if row["state"] not in RESOLVED and row["report_date"][:10] >= "2022-01-01":
            quarters[(row["engine"], row["rule_name"], row["cik"].zfill(10))].add(row["report_date"][:10])
entries = []
for did, kind, engine, rule, funds, skip, supersede, statement, evidence, rerun in SPECS:
    base = {"disposition_id": did, "class": kind, "engine": engine, "rule_name": rule, "statement": statement,
            "evidence": [{"source": s, "quote": q} for s, q in evidence], "rerun": rerun, "decided_by": WHO, "decided_on": WHEN}
    if supersede:
        base["supersedes_real_error_verdict"] = True
    if funds == "*":
        entries.append({**base, "ciks": ["*"], "quarters": ["all"]})
        continue
    ciks = funds or sorted({c for (e, r, c) in quarters if e == engine and r == rule})
    covered = {c: sorted(q for q in quarters.get((engine, rule, c), ()) if (c, q) not in skip) for c in ciks}
    covered = {c: q for c, q in covered.items() if q}
    if not covered:
        print("no open findings for", did, engine, rule)
        continue
    for i, (cik, qs) in enumerate(sorted(covered.items())):
        entries.append({**base, "disposition_id": "%s-%s" % (did, cik[-7:]), "ciks": [cik], "quarters": qs})
for entry in entries:
    problems = fd.validate(entry)
    assert not problems, (entry["disposition_id"], problems)
print("entries:", len(entries), "| fund-quarters named:", sum(len(e["quarters"]) for e in entries if e["quarters"] != ["all"]))
for entry in entries:
    print("  %-16s %-14s %-48s %s %s" % (entry["disposition_id"], entry["class"], entry["engine"] + "/" + entry["rule_name"],
                                         entry["ciks"][0], "all" if entry["quarters"] == ["all"] else len(entry["quarters"])))
if "--write" in sys.argv:
    target = REPO / "data/overrides/finding_dispositions/v05_2026-10-06.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"dispositions": entries}, indent=1) + "\n", encoding="utf-8")
    assert len(fd.load(target.parent)) >= len(entries)
    print("wrote", target.relative_to(REPO))
