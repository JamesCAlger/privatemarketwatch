# Owner review: the proposed rate-column rules (text slice R), 2026-11-26

For the owner to decide. Source: `baseline_text_rates_phase2_2026-11-26.md` section 10 (verdicts after fix round 1,
commit fd9381b5) and `baseline_text_rates_agent_run_2026-11-26.md` (the agent's proposals). Nothing is accepted,
applied or published until the owner answers.

"Accepted by a check" means consistent with the filer's own tags, its footnote legend or public rate series. It does
not mean a value is correct. No page was read by a person. Production's values were not used.

## Where the proposals stand

| | Accepted by a check | Partly | Needs the owner | Contradicted | Unstable |
|---|---:|---:|---:|---:|---:|
| Columns (31) | 26 | - | 4 | 0 | 1 |
| Shapes (284; 56 more have no number) | 116 (98,069 positions) | 29 (1,264) | 71 (5,866) | 5 (6,220) | 7 (98) |
| Codes (134) | 66 (32,993 positions) | - | 59 | 6 | 3 |

Number readings accepted by a check, by kind: spread 86 (51,808 positions), all-in rate 17 (43,512), PIK rate 41
(5,487), PIK spread 9, fixed rate 7. Floors: none (no filer tags a floor).

## Decisions, with the controller's recommendation

Each is one decision for a class of proposals, not per row. "Positions" counts position cells the decision would let
the pipeline read.

| # | Question | Positions | Recommendation | If wrong |
|---|---|---:|---|---|
| 1 | A code that spells out its own rate ("SOFR", "LIBOR", "Euribor", "CORRA", "SONIA", "CDOR" in Ares' "Reference" column; "SONIA" in Apollo's; "NIBOR", "BBSY", "BKBM", "TONA", "SORA", "CIBOR") has no legend entry because it needs none. Accept it as that rate, as a general rule? | about 13,700 | Yes. General rule: a code equal to a rate's own name is that rate | None seen |
| 2 | A fund's legend defines a code in some filings and not others (Blue Owl "SR = SOFR" in one filing; the code is used in 15). Carry a fund's legend entry to its other filings where no filing contradicts it? | about 4,750 | Yes, with the rule: the filing's own legend first; else the fund's legend from the nearest filing; a filing that gives two names decides nothing | A code that changed meaning in a quarter with no legend is read under the old name |
| 3 | A code whose legend changes over time (HPS "B": BBSW to 2024-09-30, BBSY from 2025; HPS "C": CDOR to 2025-03-31, CORRA from 2026-03-31; Blue Owl "C"; Apollo "T"). Read each filing by its own legend, and the filings that list both names as undecided? | about 170 | Yes. This is decision 2's rule applied; the agent's single answer (the latest name) is rejected for these | Transition quarters stay empty for these codes |
| 4 | Single-letter codes with no legend in the fund at all, read by common usage (Blue Owl "L" = LIBOR 278, "P" = PRIME; BCRED and Apollo rare ones) | about 330 | Accept L, P, E, S where the fund's own cells or another of its columns use the letter consistently; list the rest (N, K, T, B, BB, ST, SA, CA with under 5 rows) as unread | A wrong common-usage reading on a few dozen rows |
| 5 | Floors. The text says "#% Floor"; no filer tags a floor, so no check exists (37 readings, plus the floor in Apollo's main shape) | about 7,300 | Accept on the wording: the number directly before the word "Floor" is the floor. Mark the field's source as "printed, unchecked" | A floor read from a shape where "Floor" means something else; none seen |
| 6 | Apollo's main shape "S+#, #% Floor" and its code "S = SOFR" show as contradicted. The cause is 5 rows (of 6,214) where the filer's all-in rate tag holds the spread or the floor. The spread equals its tag on 6,195 of 6,197 rows and the legend defines S as SOFR in 15 filings | 6,214 | Accept the spread reading and S = SOFR. Record the 5 rows as the filer's tag errors (they are already known: 2 are row corrections) | None seen |
| 7 | Rare shapes: 71 shapes with under 5 rows each, too few for any check (about 140 positions; the two large "needs owner" shapes are Blue Owl's share-of-net-assets columns, not rates) | about 140 | Accept a rare shape only where the same shape is accepted by a check in another column of the same fund; leave the rest unread, counted under a ceiling | About 100 positions stay without a printed rate reading |
| 8 | Columns no tag can confirm: Ares "Reference", Blue Owl "Ref. Rate" (two table types) hold reference-rate codes | 17,300 | Accept. The cells are codes only ("SOFR (Q)", "S+") | None seen |
| 9 | Ares "Coupon" as the all-in rate: 89.995% of its tags are all-in rate tags, just under the 90% bar; the rest are PIK tags on wholly-PIK loans (the filer tags that coupon under the PIK concept) | 15,233 | Accept as the all-in rate | None seen |
| 10 | Blue Owl group header "Interest" over "Ref. Rate / Cash / PIK": the two runs said "rate terms" and "spread" | 1,416 | "Rate terms". It only labels the group; the three leaf columns have their own rules | None |
| 11 | Unstable shapes (the two runs differ), 98 positions: a bare "#%" in a reference-rate-and-spread column (66: a fixed rate, or a spread with no code); Blue Owl "#% (#% PIK)" (7); Apollo "#% Cash plus #% PIK" (2), which production also reads two ways; Apollo "S+# PIK" (4); a dash (19, no value) | 98 | Leave unread and listed. Take them up with the class slice, where "this row is a loan with no reference rate" can be known | 79 positions without a printed reading |
| 12 | Blue Owl "SR + 0.0725": a spread printed as a fraction (7.25%), 2 rows | 2 | Leave unread; add a "fraction" reading only if more appear | None |
| 13 | Texts that are not rates: "Base Rate", "CAD Base Rate" (name no benchmark), "Equity plus", "Variable" | about 400 | Store "Base Rate" as printed with no benchmark; the others are not codes | None |

## A separate finding, not a rule: BCRED 2022-09-30

In filing 0001803498-22-000021, printed rows 826 to 835, each interest-rate tag sits on the row it is printed on but
belongs to the investment of the row above. The filed layer places it correctly; the filer's tagging is off by one.
For 9 positions the tagged rate (which the spine and production both read) is the neighbour's rate. Recommendation:
record as the filer's error; correct the 9 from the printed cell once the printed all-in rule is accepted (a rule
"the printed all-in rate wins over the tag in this table of this filing", evidence the ten rows). Not checked on the
page by a person.

## What no decision here settles

- Which dollar rate a code is. The level check separates currency blocs from mid-2023 and prime from everything else;
  it cannot tell SOFR from fed funds or the LIBOR proxy, and it is blind in 2022. A code's meaning rests on the
  legend, on the rate naming itself, or on the owner.
- Blue Owl and Apollo get almost no arithmetic check: Blue Owl prints no all-in rate and Apollo tags five.
- The checks judge a rule. They do not find a row whose printed text is itself wrong.

## After the owner answers

Accepted rules go into each fund's wrapper copy (`reading_rules`), the pipeline reads the fields from them with the
rule named on every value, and the comparison with production and the count of unread rates now read are produced.
Proposals not accepted stay unread and counted.

## Added after the change-only review of fd9381b5 (2026-11-26)

The review reproduced every count and confirmed decision 6's reading: Apollo's main shape and "S = SOFR" are marked
contradicted only by the floor identity, which on Apollo can never pass (it runs only where an all-in tag exists, and
Apollo's 8 such rows all carry a faulty tag). Two more things the owner should know before accepting:

- What "accepted" tests. Every accepted number reading rests on one check: the printed number equals the filer's
  tag. That settles WHICH number is the spread, the rate or the PIK. It does not settle the finer label where two
  labels share one tag: "fixed rate" against "all-in rate" (both compared with the interest-rate tag), and "PIK
  spread" against "PIK rate" (both compared with the PIK tag). Those labels rest on the wording and the agent.
- On nearly all compared rows the tag sits in the very cell being read. So the check shows the rule picks the number
  the filer itself tagged; it is not a second, independent source.

To fix with the next build (not blocking the decisions): the floor identity must not contradict a proposal where it
can only ever run on faulty tags; evidence must not be pooled across upper- and lower-case variants of a shape (one
accepted Apollo reading shows 27 compared rows where its own count is 15; it passes alone at 15 of 15); a stale
comment in the legend model.
