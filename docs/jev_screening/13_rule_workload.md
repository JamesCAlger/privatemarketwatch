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

## Reproduction

Isolated script: `scripts/inventory_jev_rule_workload.py`. It uses DuckDB with
1 GB memory, two threads, a 120-second timeout and bounded aggregate output;
checks the input hash before/after; and writes only to the pilot directory.

Artifact: `data/pilot/jev_screening/20261003_shadow/rule_workload_92daab94bfc185cf.json`.
Canonical input: `data/output/row_validation_issues.csv`, SHA-256
`112e7b7004a16071479e86a1987e6d5711ee3de0a350d16940a8bc3c0f4e3d67`.
The report also records the inspected rule code and script hashes. This was an
offline aggregate, not a new builder evaluation, test-suite run or API call.
