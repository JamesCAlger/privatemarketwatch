<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Per-CIK wrapper residual reviews

## 2026-06-04 - Golub bare-name 2024-06-30 wrapper residuals

Question: Do cached raw HTML filings contain additional instrument labels for
the five matched, unclassified bare-name Golub Capital Private Credit Fund
(`0001930087`) rows from 2024-06-30?

Sources used:
- `data/output/bdc_xbrl_wrapper_trial/0001930087/reconciliation_detail.csv`
- Cached XBRL instance:
  `data/raw/filings/bdc_xbrl/1930087/000193008724000045.xml`
- Cached SC TO-I HTML directory:
  `data/raw/filings/sc_toi_html/1930087/`

Findings:
- No cached BDC HTML directory exists for `1930087`, and the relevant
  2024-06-30 accession is cached as XBRL XML only.
- Searching cached SC TO-I HTML for `Amberfield Acquisition`,
  `CHVAC Services`, `Quick Quack`, and `Yorkshire Parent` found no investee
  mentions. The SC TO-I HTML is tender-offer material, not a schedule of
  investments.
- The five residual rows are all matched rows from accession
  `0001930087-24-000045`:
  `Amberfield Acquisition Co.`, `CHVAC Services Investment, LLC`,
  `Quick Quack Car Wash Holdings, LLC 1`,
  `Quick Quack Car Wash Holdings, LLC 2`, and `Yorkshire Parent, Inc.`.
- Raw XBRL contexts `c-497`, `c-498`, `c-499`, `c-502`, and `c-505` contain
  `InvestmentOwnedBalanceShares`, `InvestmentOwnedAtCost`,
  `InvestmentOwnedAtFairValue`, and `InvestmentOwnedPercentOfNetAssets`.
  They do not include an instrument label in the typed
  `InvestmentIdentifierAxis` value.
- Nearby XBRL contexts show richer debt identifiers for the same issuers
  where applicable, such as `Quick Quack Car Wash Holdings, LLC, One stop 1`
  and `Yorkshire Parent, Inc., One stop 1/2/3`. The bare-name rows are
  separate share-bearing rows, not missing debt suffix variants.
- Adjacent aggregate/type contexts indicate equity securities groupings, but
  the position-level typed contexts themselves do not provide common-stock,
  preferred-stock, LP-unit, or LLC-interest text.

Decision:
Do not broaden the Golub wrapper to classify arbitrary bare issuer names as
equity. The rows are already matched and not source blockers; the evidence is
sufficient to treat them as legitimate share-bearing positions in the pipeline,
but not sufficient for a text-only dispatch rule that would generalize safely.

Residual risk:
If rendered 10-Q HTML for `0001930087-24-000045` is later cached, re-check the
schedule table for an explicit security type column. Until then, the safest
status is residual unclassified wrapper coverage, not a wrapper-rule change.

## 2026-06-04 - Oaktree wrapper comparison against cached HTML

Question: Does cached raw HTML for Oaktree Strategic Credit Fund
(`0001872371`) contain source-table evidence that should change the wrapper,
especially for the current promotion-gate residuals?

Sources used:
- Cached BDC HTML/grid files under `data/raw/filings/bdc_html/1872371/`
- Cached SC TO-I HTML directory under `data/raw/filings/sc_toi_html/1872371/`
- Oaktree wrapper trial/oracle outputs under
  `data/output/bdc_xbrl_wrapper_trial/0001872371/`

Findings:
- Cached BDC HTML exists only for early filings:
  `000187237122000005`, `000187237122000009`,
  `000187237122000013`, `000187237122000018`, and
  `000187237123000004`. The later 2024-12-31 through 2026-03-31 quarters
  with promotion-gate `cost_fv_ratio_outliers` do not have cached BDC HTML
  in this workspace.
- Cached SC TO-I HTML did not provide useful schedule-of-investments rows for
  Oaktree; it is tender-offer material, not the BDC holdings table.
- The latest cached BDC HTML (`000187237123000004`) contains a schedule table
  with columns for portfolio company/type of investment, cash interest rate,
  industry, principal, cost, fair value, and notes.
- The HTML table supports the wrapper's instrument-driven format. It contains
  examples such as first lien term loans, first lien revolvers, second lien
  term loans, fixed rate bonds, common units, and explicit issuer rows with
  separate instrument rows.
- The HTML specifically contains `First Lien Delayed Draw Term Loan` rows for
  issuers including `Mesoblast, Inc.` and `PFNY Holdings, LLC`. The initial
  Oaktree wrapper matched first-lien term loans but did not explicitly cover
  delayed-draw term loan wording.
- The HTML also confirms that `Apex Group Treasury LLC` is a private-market
  borrower row with a first lien term loan, so the existing false-positive
  guard that prevents `Treasury` in an issuer name from becoming cash is
  source-supported.

Decision:
Add a narrow Oaktree wrapper rule/test for `First Lien Delayed Draw Term Loan`
as a debt position leaf. Do not add any broad bare-name or HTML-total rule.
The cached HTML cannot validate the current 2024-2026 cost/FV outlier soft
diagnostics because those periods' BDC HTML files are not cached.

Validation:
- `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001872371.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json` passed.
- `pytest tests/test_bdc_xbrl_wrapper.py -k oaktree_strategic_credit -q`
  passed: 11 passed, 120 deselected.
- `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001872371 --compare-baseline --fresh-bdc-staging`
  passed source blocking checks: 13 pass, `remaining_blocking_rows=0`,
  `remaining_wrapper_blocking_rows=0`.
- `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001872371 --promotion-gate`
  remains `review_required` with zero blocking delta, due only to
  `cost_fv_ratio_outliers` in 2024-12-31, 2025-03-31, 2025-06-30,
  2025-09-30, and 2026-03-31.

Residual risk:
The delayed-draw rule is source-supported, but the HTML cache is too old to
resolve the later cost/FV soft diagnostics. Those still require XBRL/source
fact review or a later cached rendered filing, not a wrapper-broadening change.

## 2026-06-05 - North Haven wrapper comparison against cached HTML

Question: Do North Haven Private Income Fund LLC (`0001851322`) source HTML
tables classify old bare-name rows by instrument type that is lost during XBRL
tagging?

Sources used:
- Cached BDC HTML/grid files under `data/raw/filings/bdc_html/1851322/`
- North Haven wrapper trial/oracle outputs under
  `data/output/bdc_xbrl_wrapper_trial/0001851322/`

Findings:
- Cached 2022 rendered HTML/grid files include schedule rows grouped under
  visible instrument section headers. The headers include `First Lien Debt`,
  `Second Lien Debt`, `Preferred Equity`, and `Common Equity`.
- Example 2022 debt schedule rows have issuer-only company names in the table
  body, while the surrounding table section supplies the instrument class.
- Example 2022 equity schedule rows similarly sit below `Preferred Equity` and
  `Common Equity` sections, with acquisition-date/share fields in the columns.
- The old XBRL typed `InvestmentIdentifierAxis` values often retain only the
  issuer label, so the instrument section context is not available in the
  identifier text consumed by the wrapper.
- Later 2025 and 2026 inline HTML/XBRL identifiers often include explicit
  hierarchy text such as `Investment First Lien Debt` or
  `Investment Common Equity`, which the wrapper already handles directly.

Decision:
Classify old bare issuer-name rows with entity-name signals as
`mixed_position_leaf`, not as debt or equity. This fixes the leaf/aggregate
problem supported by source HTML without inventing an instrument family that
the typed XBRL identifier no longer carries. Short labels without entity-name
signals remain unclassified.

Validation:
- `python -m jsonschema -i data/overrides/bdc_xbrl_wrappers/0001851322.json schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`
  passed.
- `pytest tests/test_bdc_xbrl_wrapper.py -q` passed: 142 passed, 2 existing
  regex warnings.
- `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001851322 --compare-baseline --fresh-bdc-staging`
  improved to 10 pass / 3 fail across 13 quarters with zero remaining hard
  blockers and wrapper classification coverage of 3,033 / 3,144 candidates.
- `python -m pipeline.bdc_xbrl_wrapper_oracle --cik 0001851322 --promotion-gate`
  remains `reject`. It improves blockers by 3 rows and $51.609 million FV, but
  current final unified artifacts still miss two eligible 2025-12 common-equity
  source rows and soft diagnostics remain unaccepted.

Residual risk:
The HTML evidence supports treating the old bare-name rows as position leaves,
but it does not recover instrument family from the XBRL identifier. A more
precise debt/equity assignment would require a table-aware HTML extractor or
field-aware classification using independent source columns, not a broader
text-only wrapper catch-all.

## 2026-06-05 - Monroe wrapper economic-reality residual review

Question: Beyond the `review_required` promotion verdict for Monroe Capital
Income Plus Corp (`0001742313`), are there wrapper or parser fixes needed to
make final output better match economic reality?

Sources used:
- Monroe wrapper trial/oracle outputs under
  `data/output/bdc_xbrl_wrapper_trial/0001742313/`
- Current final holdings in `data/output/private_markets_holdings.csv`
- Cached Monroe rendered HTML under `data/raw/filings/bdc_html/1742313/`

Findings:
- Source/output reconciliation is clean for matched rows: no matched-row
  field mismatches were present in the trial detail.
- The cost/FV diagnostic rows are source-passed-through economics, not wrapper
  value drift. Examples include deeply marked-down debt (`First Brands Group`)
  and low-cost equity/preferred positions with large fair values
  (`Witkoff/Monroe 700 JV LLC`).
- Cached rendered HTML for Monroe confirms the early Witkoff preferred-units
  row is reported in a thousands-denominated schedule with very small cost
  and larger fair value. That supports preserving the source economics rather
  than multiplying the cost by 1,000.
- The remaining `family_vs_asset_category_disagreement` rows are not safe
  wrapper fixes. Warrant rows are intentionally grouped by downstream output
  as common equity exposure. The few equity-labeled rows with loan-like
  principal/cost facts are filer-label inconsistencies that need source/fact
  review before changing output classification.
- Low position-continuity flags are mostly identifier-format churn: due-date
  phrases disappear, pipe-delimited issuer/instrument layout appears in
  2025-12-31, and tranche labels move before/after the instrument family.
  This affects position matching quality, but a broad text strip could merge
  separate senior/junior or numbered tranches.

Decision:
No additional Monroe wrapper classification change is supported by the current
evidence. Do not edit output CSVs by hand. The next fixable production item is
not a value correction; it is a tested position-key normalization enhancement
that can preserve tranche identity while reconciling Monroe's format churn.

Residual risk:
The cost/FV outlier gate remains a useful review flag. It should not be waived
as "clean" without documenting the economic mechanism, but the reviewed rows do
not currently justify a parser-scale correction.

## 2026-06-05 - Ares Core Infrastructure cached HTML wrapper check

Question: After adding the Ares Core Infrastructure Fund (`0002031750`) wrapper,
does cached rendered HTML support any additional safe wrapper or parser fixes?

Sources used:
- Cached rendered HTML:
  `data/raw/filings/bdc_html/2031750/000203175026000015.html`
- Ares wrapper trial outputs under
  `data/output/bdc_xbrl_wrapper_trial/0002031750/`
- Current final holdings in `data/output/private_markets_holdings.csv`

Findings:
- The cached annual HTML contains 104 parsed tables. No same-directory
  `.grids.json` file was present.
- Tables 50-52 show `First lien senior secured loans` and
  `Senior subordinated loans` as section/category labels and show separate
  `Total ... loans` rows. This supports treating the bare labels as aggregate
  rows, not position-level holdings.
- Table 53 shows Meade Pipeline and Redwood Meade Midstream as common-equity
  positions with cost/share fields. The XBRL source also has explicit
  `, Common equity` rows with the same fair values; the bare issuer-only rows
  are FV-only duplicates and should remain dropped by the wrapper trial.
- Table 54 confirms First American U.S. Treasury Sweep rows are cash
  equivalents. Treasury Bill rows likewise remain non-private-market rows, not
  index positions.
- Table 58 restates a 2024 Denali Equity Holdings row as `Class A units`, which
  is useful source context. It is not same-accession evidence for accepting a
  static bridge on older XBRL rows, and later Denali issuer-only rows are
  FV-only diagnostics beside explicit equity rows.
- A direct bare-issuer search found no matches in the cached SC TO-I HTML
  files. The only bare-name matches were in the 2025-12 annual BDC HTML.
- The direct HTML pass found Denali, Meade, and Redwood in an underlying
  projects summary table; Denali under `Other equity`; Meade and Redwood under
  `Common equity`; and Meade/Redwood again in a company-level roll-forward
  table. `AEJV SPV LP Membership Interest` was not present in cached HTML.
- The existing HTML-section bridge proposal tool can propose same-accession
  2025-12 bridges for bare Meade and Redwood as `Common Equity`, but those
  fair values already exist on explicit `, Common equity` XBRL rows. The tool
  rejected the small bare Denali diagnostic row because no HTML row matched its
  fair value.

Decision:
No additional Ares production wrapper change is supported by the cached HTML.
The current wrapper cleanup should be kept: cash rows are excluded, bare loan
section labels are aggregates, and FV-only bare equity duplicates remain
unclassified/dropped when explicit equity rows carry the position economics.

Residual risk:
Older bare Denali rows may be equity positions, but a broad text-only Denali
leaf rule would overclassify later diagnostic rows. A safer improvement would
require same-accession HTML/grid evidence or a field-aware bridge that can
distinguish the issuer-only position row from FV-only diagnostics.

## 2026-06-05 - Barings Private Credit wrapper residual closeout

Question: After adding the Barings Private Credit Corp (`0001859919`) wrapper,
are any remaining source-reconciliation blockers mechanically fixable?

Sources used:
- Wrapper trial outputs under
  `data/output/bdc_xbrl_wrapper_trial/0001859919/`
- Cached BDC holdings in `data/output/bdc_holdings.parquet`
- Barings trial unified holdings in
  `data/output/bdc_xbrl_wrapper_trial/0001859919/unified_trial/private_markets_holdings.0001859919.csv`

Findings:
- The apparent pipeline-only residuals were not true source absences. Matching
  current-period source facts existed for the Eclipse, Skyvault, Biolam, and
  Coastal Marina examples.
- The residuals came from duplicate dimension-path variants. The source
  reconciliation layer collapsed one source variant as
  `collapsed_duplicate_dimension_path`, matched the canonical variant, but
  still reported the corresponding unmatched output variant as
  `extra_in_pipeline`.
- A source-reconciliation change now suppresses only those output extras whose
  collapsed source duplicate matches on same CIK/report/accession, fair value,
  and an exact identifier/dimension/wrapper key, and only when the canonical
  source row has already reconciled.
- Barings hard blockers are now zero in both trial-unified and fresh cached
  staging oracle runs.
- The corrected trial promotion gate is `review_required`, not `reject`.
  Remaining reasons are cost/FV outliers in every quarter and exclusion-risk
  rows in 2023-06-30 and 2024-09-30.
- Cost/FV outliers are specific position economics, mostly Amalfi warrant rows
  with about $4k cost and six-to-seven-figure fair value, plus one negative-FV
  Marmoutier loan row. These should remain review flags, not parser fixes,
  without source-filing confirmation.
- The exclusion-risk rows are instrument-only holdings labels,
  `First Lien Senior Secured Term Loan` and `Subordinated Term Loan`, with
  cost, fair value, and principal facts but no issuer. The wrapper marks them
  aggregate-like; removing or reclassifying them would require human source
  review because the row identity is not position-level enough for index use.

Decision:
No additional Barings wrapper classification change is supported by the current
evidence. Hard source-reconciliation blockers are fixed. The remaining oracle
failures are review gates for economically unusual rows or instrument-only rows
that lack enough issuer evidence for an automated position-level correction.

Residual risk:
The output still includes two instrument-only rows in trial holdings. They may
be filer omissions, parser omissions, or aggregate leakage. Treat them as human
review items rather than broadening wrapper rules.

## 2026-06-05 - MidCap Financial wrapper residual closeout

Question: After adding the MidCap Financial Investment Corp (`0001278752`)
wrapper, are any remaining source-reconciliation blockers mechanically fixable?

Sources used:
- Wrapper trial outputs under
  `data/output/bdc_xbrl_wrapper_trial/0001278752/`
- Cached BDC holdings in `data/output/bdc_holdings.parquet`
- MidCap trial unified holdings in
  `data/output/bdc_xbrl_wrapper_trial/0001278752/unified_trial/private_markets_holdings.0001278752.csv`

Findings:
- The first MidCap wrapper pass reduced fresh-staging residual blockers from
  611 to 207 rows by documenting old `Controlled Investments` /
  `Non-Controlled/Non-Affiliated Investments` hierarchy rows, instrument-only
  subtotals, cash-equivalent totals, and explicit modern position leaves.
- A broad `treasury` non-private-market marker was unsafe. It removed real
  `G Treasury SS LLC` private-credit loan rows from the trial output. The
  marker was replaced with narrower government-security strings, and the
  corrected trial retained the G Treasury revolver, delayed-draw, and term-loan
  rows.
- The remaining hard `wrapper_blockers_remaining` rows were seven
  `mixed_total_rollup` source totals (`Total Consumer Services`,
  `Total Diversified Investment Vehicles, Banking, Finance, Real Estate`,
  `Total Healthcare & Pharmaceuticals`, and `Total Software`). Source
  reconciliation already treats `*_rollup` dispositions as documented rollups;
  the oracle hard-blocker predicate was updated to match that contract.
- Final trial oracle residuals are 191 rows with zero
  `remaining_wrapper_blocking_rows`: 184 `unclassified_signature` rows and
  seven `total_rollup_no_child_tie` rows.
- The unclassified rows are mostly industry-plus-issuer labels with fair value
  and cost but no instrument/rate/maturity evidence in the identifier. Several
  examples are borrower-like, so treating all such rows as aggregate would risk
  deleting real positions.
- The seven total-rollup rows are source-table totals without a same-key child
  tie in the oracle. They are documented as rollups but should remain review
  items unless a source-table coordinate reconciliation mechanism is added.

Decision:
No additional MidCap wrapper classification is supported by the current cached
evidence. The remaining issues require human source-table review or a stronger
independent reconciliation mechanism; broadening the wrapper would either hide
potential real positions or over-suppress borrower-like rows.

Residual risk:
Some industry-plus-issuer rows may be real positions whose instrument data is
outside the XBRL identifier text. Conversely, some may be issuer subtotals
beside explicit child tranches. Without source-table coordinate evidence, the
safe status is review-required rather than automated suppression.

