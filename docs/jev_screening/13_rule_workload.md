# Where wider screening could help

Date: 2026-10-04. Read-only inventory within the already reserved 16 funds.
No additional flags were selected for investigation or sent to Jev.

## Current-period opportunity

The latest flagged holdings period for these funds is Q1 2026. Selected rules:

| Rule | Trigger | Existing action | Issue rows | Funds |
|---|---|---|---:|---:|
| X02 | Credit position missing rate and spread | Review | 539 | 15 |
| C107 | Negative cost | Review | 510 | 9 |
| C104 | Zero fair value | Track only | 448 | 8 |
| X08 | Positive FV below 5% of positive cost | Track only | 18 | 5 |
| C103 | Residual negative FV | Review | 11 | 2 |
| X03 | Fund exposure with maturity | Track only | 6 | 5 |
| X07 | Non-equity FV above 10x cost | Review | 4 | 1 |
| C202 | Issuer name shorter than three characters | Review | 1 | 1 |
| C404 | Negative percentage of net assets | Track only | 1 | 1 |

These are recorded issue rows, not distinct B1 investigations, eligible bundles,
true errors or estimated savings. Latest flagged period is derived from the issue
artifact; it does not independently establish the latest available holdings.
The selected funds are a development sample, not representative of all v1 funds.

## Priorities and trade-offs

1. **Keep C107 as the review-efficiency test.** There is meaningful recorded
   volume and an existing cost/FV evidence contract. Missing identity, inherited
   section scope and proxy-cost lineage remain real reasons to use B1. Compare
   against deterministic source matching before attributing savings to Jev.
2. **C104 is the strongest measured wider-coverage opportunity here.** It has
   substantially more current issue rows than X08 and can reuse FV evidence.
   But a disclosed zero only answers whether extraction matches the source; it
   does not prove the position's classification, completeness or economic status.
   Source dashes, comparative columns and missing facts need explicit handling.
3. **Retain X08 as a useful error-control family.** Both cost and FV must be
   independently sourced. The existing natural sample contains known unit errors,
   which the builder correctly blocks. Low current volume limits absolute benefit
   in this sample; screening would add coverage rather than remove existing jobs.
4. **Do not prioritise X02 solely by volume.** Establishing that a rate is absent
   requires rate columns, legends, footnotes, instrument classification and often
   unfunded/non-income status. Absence from a short excerpt is insufficient.
   This needs a separate evidence contract, not an extra output field in a
   cost/FV bundle. It is marked moderate evidence, not weak.
5. **Defer the smaller families.** X07 shares monetary evidence but also requires
   asset-class evidence. X03 requires instrument/fund classification; C404 needs
   the disclosed percentage and denominator/sign context. Reusing an amount
   comparison alone would answer the wrong question.

Historical false-positive rates in rule comments were not used as current error
prevalence estimates. Known high-error or strong-evidence rules remain B1 work.

## Historical artifact limitations

Across all included datasets and historical periods, the inventory contains
45,522 issue rows over 187 fund-periods. Of these, 14,818 have no `row_id`;
24,058 distinct position keys can be counted among rows with an identifier.
These totals must not be presented as review jobs or model-ready positions.

In particular, AGG01 contributes 13,078 suspected aggregate/header
issues, all without `row_id` or reporting date. Its adapter carries a separate `row_key`, but that
is not a certified join to current holdings. It is not a cheap expansion target
until snapshot lineage and the row mapping are established. Large historical
flag volume can reflect artifact semantics rather than a large current queue.

## Position overlap changes the workload interpretation

An additional read-only join groups exact Q1-2026 row IDs within this artifact:

| Position set | Positions | Other review/block issue already present | No other review/block issue |
|---|---:|---:|---:|
| C104 zero FV | 448 | 204 | 244 |
| X08 low FV/cost | 18 | 12 | 6 |
| C107 negative cost | 510 | 416 | 94 |

For C104/X08, "other" means any recorded REVIEW or BLOCK_VERIFIED issue. For C107,
it excludes C107 itself. C104 and X08 are mutually exclusive here. Their combined
466 positions contain 216 already needing review and 250 with only tracking
issues. Seventy-three positions have both C104 and C107. Of the 94 positions with
no review/block issue other than C107, ten also have a C104 tracking flag.

This limits what clearing one flag can save. Even clearing every C107 suspicion
would leave another review/block issue on 416 positions. It might shorten their
investigations, but cannot remove the entire position review. At most 94 positions
in this artifact could lose their sole recorded review issue through C107 alone;
that is an upper bound on positions, not measured avoided B1 jobs. Newly screening
C104/X08 potentially introduces investigation work for 250 positions that have
only tracking flags, plus additional questions on the 216 already reviewed.

The practical next measurement is marginal review time per flag and grouped
investigation, including whether one source lookup settles several issues. It
is not enough to multiply model clearance counts by the cost of a whole B1 job.
The shadow router's complete-member requirement remains necessary: a cleared
weak flag cannot erase another unresolved member.

These overlaps omit issues without row IDs and fund-wide findings that cannot
be allocated to a position. They do not reproduce the production queue/grouping
logic, establish materiality or prove that every REVIEW action becomes a B1 job.
No issue disposition was changed.

## Why X02 needs a separate evidence contract

Three already-selected Crescent positions also carry X02. Their exact source
contexts contain cost, FV and percentage-of-net-assets facts, but no principal
or rate facts. The visible rows have a dash in the principal area. Their note 5
says the position **or a portion** is an unfunded commitment and that no interest
is earned on the unfunded portion. It also refers to the commitments note.

Those observations do not establish that the entire position is unfunded or that
the filing contains no applicable rate. A short excerpt with no rate tag cannot
certify absence. The pilot assigns no X02 labels; the separate blocking identity
issue also remains. See [the three-case investigation](16_missing_issuer_mechanism.md).

A future X02 bundle would need:

| Evidence | Required distinction | Trade-off |
|---|---|---|
| Published rate fields and provenance | Missing versus zero; rate, spread and cash/PIK terms as actually stored | More fields are needed, but changing rate conventions is outside screening |
| Original rate/principal columns and inline facts | Blank, untagged dash, explicitly tagged zero and numeric value | Missing tags cannot become invented zeros |
| Funding status and commitment notes | Entirely undrawn versus partly funded | An unfunded-portion note alone cannot waive a rate question |
| Instrument identity and classification | Revolver, term loan, DDTL or misclassified equity | Same borrower does not mean the same instrument |
| Applicable rate legends and targeted note references | Benchmark/spread terms versus current income/accrual status | More context may be necessary, but follow references needed for the question rather than every filing cross-reference |
| Explicit evidence of disclosure coverage | Source omits a rate versus retrieval omitted the relevant disclosure | Hard absence questions require B1 when coverage is not established |

This keeps C104 the better bounded next coverage family: it reuses a narrow FV
comparison. X02 may eventually add more semantic value for Jev, but its higher
flag count does not make its bundle simpler or its clearance safer.

Raw inventory: `rate_context_inventory_0788a87fa395c099.json` in the pilot root,
produced offline by `scripts/review_jev_rate_contexts.py`. It covers only the same
three existing positions in two cached filings, with no new calls or natural
case selection. It is not a full filing search or an independent absence audit.

## Reproduction

Isolated script: `scripts/inventory_jev_rule_workload.py`. It uses DuckDB with
1 GB memory, two threads, a 120-second timeout and bounded aggregate output;
checks the input hash before/after; and writes only to the pilot directory.

Original inventory: `data/pilot/jev_screening/20261003_shadow/rule_workload_92daab94bfc185cf.json`.
Updated inventory with overlap counts: `rule_workload_07cfcaabee4d805b.json` in the same directory.
Canonical input: `data/output/row_validation_issues.csv`, SHA-256
`112e7b7004a16071479e86a1987e6d5711ee3de0a350d16940a8bc3c0f4e3d67`.
The report also records the inspected rule code and script hashes. This was an
offline aggregate, not a new builder evaluation, test-suite run or API call.

## 2026-10-04: actual review-group membership and queue identity

The 67 frozen flags belong to 33 fund/period/rule groups containing 1,063 current issue rows: C107 44 selected of 919 rows in 18 groups; X08 19 of 30 in 11 groups; C104 4 of 114 in four groups. Twelve groups are fully selected; nine are also entirely evidence-ready before size, policy, model or audit checks. These are population-coverage counts, not completed reviews.

A native join to queue CIK/report_date finds none of the 33 groups. The ledger casts inferred timestamps to strings such as `2026-03-31 00:00:00`, while `pipeline/review_queue.py` localizes only exact YYYY-MM-DD strings. Existing affected queue rows have blank CIK/report_date. The review-ID input includes the blank localized date rather than raw period, producing repeated IDs across quarters.

A diagnostic-only join using unit_label and normalized period locates all 18 C107 groups, with n_units matching all current issue counts. Six review IDs repeat across 16 of those 18 entries. X08/C104 have no matched queue entries in these sampled groups; their tracking-only statuses do not imply current B1 jobs. Date normalization here does not certify a parent link or repair existing IDs, bundles, verdicts or locks.

Only three queued C107 groups are fully selected: the three Ares single-row groups. All three currently exceed the ordinary runner's size cap. Other queued groups retain unselected members. Optional compact encoding remains unvalidated with the model. Thus these data do not demonstrate a fully screened current B1 job, even before independent audit is required.

Before any queue integration: normalize and validate the ledger's date contract, require unique review IDs across periods, account for every parent member, and assess migration of existing IDs/verdicts/locks. Do not silently relabel existing records or reuse a verdict through an ambiguous ID. Production changes remain prohibited in this session.

Artifact: review_group_profile_cc98b0808f2e7934.json. Inputs are hashed; queue timestamp 2026-09-30 19:24:52 UTC, issues timestamp 2026-09-30 17:34:23 UTC. Read-only diagnostic on the same 11 funds, no new model calls. Earlier strict-join report review_group_profile_1af497f03efcc785.json is retained as the initial observation.
