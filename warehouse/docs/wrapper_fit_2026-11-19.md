# Do the current wrappers fit a rule table? Two read-only checks

Date: 2026-11-19. Scope: the five v0.5 funds. Nothing was built or changed. Sources: the wrapper
files in `data/overrides/bdc_xbrl_wrappers/` as committed 2026-11-11, the filed layer
(`warehouse/data/filed/`, parser version 3) and today's holdings through `fact_observation`.

Agreement with production is reported throughout. It shows the two agree, not that either is right.

## 1. Reading declarations mapped to the rule shape

Rule shape: filer, valid from, valid to, selector, target, action and parameter, evidence, status.

The `source_encodings` section (plus Ares's `identifier_format`) holds 55 declarations across the
five funds.

| Fit | Declarations | Entries inside them |
|---|---|---|
| Direct: a filer-wide named reading, column name or vocabulary | 45 | about 130 |
| Scoped to whole filings (a list of accessions) | 3, plus one value inside HPS `par_tagged_as_units` | 5 filings |
| Needs its own procedure in code | 2, plus the rule half of HPS `pik_margin_reading` | 3 |
| Row-level: names one filing and one context | 6 | 284 |

### Direct

| Key | Funds | Becomes |
|---|---|---|
| `filed_rate_reading: all_in` | BCRED, Ares, HPS, Apollo | convention on `interest_rate` |
| `principal_usd_reference: fred_h10` | all five | should be a global default, not five filer rules |
| `foreign_unit_values: reported_in_usd` | BCRED, HPS, Apollo | no conversion for rows in a foreign unit |
| `pik_only_tag_reading: coupon / margin` | Blue Owl, Ares, HPS, Apollo | rule with a feature selector: rows that carry only a PIK tag |
| `printed_margin_reading: cash_plus_pik` | Blue Owl, Apollo | convention on the printed margin |
| `cost_in_two_units: foreign_is_par` | Apollo | convention on cost |
| `par_tagged_as_units: <row mode>` | all five, three different modes | rule whose selector is a test on values (par close to cost) |
| `reference_rate_columns` | all five | source rule: which printed column |
| `reference_rate_codes` | all five | vocabulary; HPS and Blue Owl entries carry dates |
| `unspecified_reference_labels`, `equity_instrument_labels`, `printed_industry_labels` | Ares; Blue Owl; HPS, Apollo | vocabulary |
| `legal_entity_members` | BCRED | scope rule with a structural selector (axis member) |
| `reporting_entity_suffixes` (two keys) | BCRED | scope rule with a text selector |
| `cash_identifiers` | BCRED, Apollo | tag `is_cash` by exact identifier |
| `detached_schedule_labels` | HPS | structure: the JV schedule's label |
| `identifier_format` | Ares | source rule: parts of the identifier text |

### Scoped to whole filings

`units_tagged_as_par` (Blue Owl, 1 filing), `bracketed_unsigned_values` (Apollo, 3 filings), one
accession inside HPS `par_tagged_as_units`. These fit as rules whose valid range is one report date.

### Needs a procedure

`rate_only_contexts: adopt_adjacent` (Ares), `gics_industry_carry_back: through 2025-09-30` (HPS),
`pik_margin_reading: whole_coupon` (HPS). Each names a code path that does more than convert a value.

### Row-level

| Key | Fund | Entries | Kind |
|---|---|---|---|
| `relabelled_contexts` | Blue Owl | 201 | correction |
| `untagged_values` | Apollo, Ares, BCRED | 57, 6, 1 | correction (adds a value the filing printed but did not tag) |
| `pik_margin_reading` "not ..." entries | HPS | 3 | exception to a rule |
| `rate_verification_anchors` | Ares | 16 | evidence, not a change |

These belong in the corrections store. Context ids change every filing, so none carries forward.
Why Blue Owl needs 201 relabelled contexts was not examined.

### What does not fit, and gaps

1. **No dates.** Only `reference_rate_codes` (HPS, Blue Owl) and `gics_industry_carry_back` carry a
   date. Every other declaration applies to all 14 to 16 quarters by default. Whether each is true
   for all of them was not checked.
2. **No evidence** on any declaration except Ares's anchors.
3. **Named readings are code paths.** The five funds use 14 distinct named values (`all_in`,
   `fred_h10`, `reported_in_usd`, `coupon`, `margin`, `cash_plus_pik`, `adopt_adjacent`,
   `foreign_is_par`, `rows_near_cost`, `rows_within_twice_cost`, `rated_rows_near_cost`,
   `listed_rows_without_instrument`, `whole_coupon`, carry back). That is the starting size of the
   closed transform list.
4. **`par_tagged_as_units` row modes decide from the size of the number** (par close to cost).
   Three variants across five funds. This is the unsafe kind of rule and should be reviewed, not
   just ported.
5. **Blue Owl has no `filed_rate_reading`.** What production assumes for it was not checked.
6. **The file's `version` field is not maintained** (BCRED says 2 after 16 commits).

## 2. Apollo: can the filing's structure replace the name patterns?

Apollo (0001837532), all parsed filings that holdings use (2023-03-31 to 2026-03-31).

### Row roles: yes

Rule tested, with no Apollo-specific input: a context is a position when it has exactly one member,
on the investment identifier axis; its date is the filing's period end; it has a fair value; and it
has at least one term fact (principal, shares, rate, spread, PIK rate or maturity).

| Contexts with a fair value | Count | In holdings |
|---|---|---|
| Identifier axis, period end, with a term fact | 7,234 | 7,234 |
| Identifier axis, period end, no term fact | 1,421 | 12 |
| Identifier axis, earlier date (comparatives) | 7,479 | 0 |
| Other axes (industry, type, affiliation, level), period end | about 3,700 | 0 |

- The rule agrees with production on 8,643 of 8,655 period-end identifier contexts.
- The 1,409 it excludes are industry and issuer rollups ("Aerospace & Defense",
  "Transportation Infrastructure GSI"). The text markers in the wrapper match only 19 of them; the
  rest are caught today by `no_prefix_is_aggregate`. They occur only up to 2025-03-31; later
  filings put rollups on other axes.
- The 12 differences: 6 money-market cash lines (need the cash rule) and 6 real positions whose
  term tags are missing (already covered by `untagged_values`).
- Replaces: `aggregate_markers` (7 values), `no_prefix_is_aggregate`, `category_marker_re`.
- Caution: one fund. The profile pilot found filers (Fidelity, Onex, NexPoint) whose subtotal rows
  carry cost and percent; whether they also carry term facts is not known.

### Debt or equity: mostly

| Facts on the row | Rows | Production class |
|---|---|---|
| Principal, no shares | 6,079 | 6,061 loan, 11 cash, 7 equity |
| Shares | 231 | 230 equity or fund, 1 loan |
| Neither | 988 | 981 loan, 7 cash |

Structure gives debt or equity for 86 pct of rows and agrees with production on 99.7 pct of those.
The other 14 pct, and every finer class (common or preferred, warrant, lien), still need text.
`leaf_markers_by_family` and `fallback_family_patterns` (47 values) shrink to a vocabulary; they do
not disappear.

### Issuer name and industry: not yet

- The issuer name is exactly one printed cell on 4,258 of 7,298 rows (58 pct). For the rest the
  issuer sits on a row above, or the name needs stripping.
- No position context carries an industry member. Industry is in the identifier text or in the
  printed headings.
- Both depend on knowing the headings above a printed row. The filed layer does not compute that.
- Not replaceable today: `issuer_name_strip_re`, `canonical_strip_re`,
  `industry_from_identifier_re`, the three `staging` hierarchy expressions, `extra_industry_labels`.
  `issuer_name_strip_re` is a hand-kept list of issuer names, so it is name-pinned.

### Other

- `non_private_markers` (7 values) stay, as the cash vocabulary.
- One cached filing (10-Q for 2026-09-30, 784 identifier contexts) is not in holdings.

## Conclusions

1. The reading declarations are in usable shape: 45 of 55 map directly. The missing parts are dates
   and evidence, not structure.
2. 284 row-level entries sit in the wrappers and should move to the corrections store.
3. For Apollo, structure replaces the role patterns almost exactly and the family patterns in part.
4. The remaining patterns all wait on one thing: the heading path of a printed row. That is the
   next measurement, and it needs a small addition to the filed layer or a dbt model.
