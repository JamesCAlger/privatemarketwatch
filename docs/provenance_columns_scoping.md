# Provenance Columns for VALUE Claims -- Scoping Report (2026-08-21)

**Scope: BDC XBRL rows, post-2022, wrapper cohort.** This matches the v1
product scope (AGENTS.md): the public site ships only the ~70 unlisted-BDC
cohort, and BDC XBRL coverage is strongest from 2022 onward. N-PORT and
pre-XBRL HTML template extraction are out of scope (section 7 records the
one-line facts about them so this narrowing is an informed one).

This scopes step 1 of the approved auditability chain: provenance columns ->
deterministic re-verifier -> shadow-ledger routing with reason codes
(extraction-wrong / provenance-wrong / parser-drift / amended) -> annotated
iXBRL overlay viewer of the real filing. Section 8 additionally scopes the
step-3 routing design (lanes, agents, gates) agreed 2026-08-22. It is a
scoping report, not an implementation sign-off; nothing here has been
changed in code.

---

## 1. The single in-scope path and its one real gap

Every value claim in scope originates as an XBRL fact in a cached filing under
`data/raw/filings/bdc_xbrl/{cik}/*.xml`. The raw files retain everything the
chain needs -- fact `id`, `contextRef`, `unitRef`, `decimals`, concept QNames,
dimension segments -- and the cached BDC filings are confirmed iXBRL, so the
facts are DOM nodes in the real filing: `accession + contextRef + concept`
locates the `ix:nonFraction` node for the overlay viewer directly.

What the extractor keeps vs drops:

| Source ref | Captured in extractor | Survives to bdc_holdings.csv | Survives to unified |
|---|---|---|---|
| accession_number | yes | yes | yes (`accession_number`) |
| contextRef | yes -- `_context_id`, `bdc_filings.py:814` | **NO -- dropped in `_deduplicate_bdc_holdings()`** | no |
| fact `id` attribute | never read (fact loop `bdc_filings.py:748-796` ignores `id`; the nonaccrual footnote path builds a `fact_id_to_ctx` map at :891-897, so the machinery exists) | no | no |
| concept QName | lossy -- `CONCEPT_MAP` (`bdc_filings.py:44-88`) collapses many concepts to one column; only `interest_rate_concept` is kept | partially | no |
| `decimals` | read and used by `_normalize_mixed_decimals_monetary_facts()` (:573-622) for silent scale correction, then discarded | no | no |
| dimension path | yes | yes (`dimensions_raw`) | yes (`bdc_dimensions_raw`) |
| investment identifier (axis member) | yes | yes | yes (`bdc_investment_identifier`) |
| filing file path | not stored (derivable: accession -> cache dir, same resolution `source_anchor_verify.py` already does) | no | no |
| merged-context audit | -- | yes (`dedupe_context_count`, `dedupe_conflict_fields`, `dedupe_axis_split`) | **no -- dropped in staging** |

**Two drop points:**
1. `bdc_filings.py::_deduplicate_bdc_holdings()` -- loses `_context_id`.
   This is THE gap; everything else is secondary.
2. `pipeline/staging_bdc.py` Phase C final SELECT (~:2583-2648) -- drops
   anything not explicitly listed (this is where the `dedupe_*` audit columns
   and the industry/investment_type/affiliation axis members die).

**Why contextRef is the right anchor:** a schedule-of-investments row is one
investment-axis context; all its facts share it. Fact ids are not needed --
contextRef + concept identifies the fact, and per-field concepts are required
anyway because CONCEPT_MAP is many-to-one (the re-verifier must know whether
`principal_amount` came from FaceAmount or PrincipalAmount to re-read the
right fact).

**Existing precedent to copy:** `pipeline/bdc_position_pik.py`
(PIK_EVIDENCE_COLUMNS, :26-31) already retains `concept`, `context_id`,
`decimals`, `unit` per fact. The pattern is proven; it just never made it
into the main holdings extractor.

### 1.1 The one HTML remnant that stays in scope

The XBRL->HTML section bridge (`pipeline/bdc_xbrl_html_bridge.py`) overlays
maturity/reference_rate/lien onto BDC XBRL rows in staging (join
~`staging_bdc.py:1485-1494`; overlay ~:2725). Bridge entries carry full
coordinates (`html_sha256`, `table_index`, `row_index`, `cell_indices`;
BRIDGE_TABLE_COLUMNS :30-51) but the coordinates are dropped at overlay -- a
unified row today cannot tell you a field came from the bridge rather than
XBRL. Those up-to-3 fields need a field-level override ref or their
provenance claims would silently point at the wrong source. No new parser is
needed to verify them: `source_anchor_verify.py` already resolves accession
-> cached filing and re-parses with the same `_extract_tables()` coordinate
system used by the evidence CLI.

---

## 2. Which columns can carry provenance, and what "provenance" means per class

Decision (2026-08-22): provenance columns are integrated INTO the production
CSV (in-table, appended to `UNIFIED_COLUMNS`), not a sidecar. Extraction
anchors are immutable build outputs and belong with the rows; verification
STATE (re-verifier verdicts, reason codes, timestamps) evolves between builds
and belongs in the shadow ledger, never in this artifact.

### 2.1 Two precedents already in the schema -- generalize, don't invent

- **Per-field pathway enums already exist for 4 fields:**
  `interest_rate_source`, `basis_spread_source`, `reference_rate_source`,
  `maturity_date_source` (`staging_bdc.py:2456-2497,2550-2559`), with values
  `xbrl_field` / `identifier_text` / `inferred_post_libor` /
  `inferred_pre_libor` / `''`.
- **A transform that records itself already exists:** the FX conversion
  publishes `principal_amount_usd` alongside `principal_fx_rate_to_usd` and
  `principal_fx_status` -- value, transform parameter, and status in-table.

### 2.2 Column classification (all 112 columns)

**Class A -- fact-anchored numerics** (anchor = contextRef + concept;
pointer-verifiable against the filing): `fair_value`, `cost`,
`principal_amount`, `shares_held`, `pct_of_net_assets`,
`bdc_unrealized_gain_loss`, the `*_currency` columns (unitRefs), and
`interest_rate` / `basis_spread` / `pik_rate` / `maturity_date` WHEN their
`*_source` is `xbrl_field`.

**Class B -- text-anchored** (anchor = the `bdc_investment_identifier`
string, already in-table, plus a parse-rule id from the per-CIK identifier
grammar): `issuer_name`, `instrument_description` (both parsed from the
identifier), and the four rate/date fields WHEN `*_source` is
`identifier_text`. Verifiable against a text span + grammar rule, not a
filing cell.

**Class C -- derived, no filing anchor** (provenance = a derivation record;
can never be "source-verified"): `cost` when the cost-proxy fill fired
(FIRST_VALUE of fair_value across quarters -- cross-row), `shares_held` when
the power-of-10 fix fired (group-median inference -- cross-row),
`reference_rate_type` when `inferred_*` (spread presence + LIBOR-cessation
date), `coupon_type` when text-inferred (`staging_bdc.py:2498-2506`),
`principal_amount_usd` (FX; already self-documenting), `extracted_industry`
(LLM-populated -- never pointer-verifiable, gold-set only).

**Class D -- semantic claims** (owner decision, standing: rule + gold-set
audited, NOT pointer provenance): `asset_category`, `issuer_category`,
`index_classification`, `exposure_type`, `asset_class`, `gics_sub_industry`,
`lien_position`, `instrument_type`, `is_subsidiary`, `jv_subsidiary`.

**Class E -- identity/evidence columns** (they ARE provenance or pipeline
joins; no provenance needed): `source`, `cik`, `entity_name`,
`accession_number`, dates, `bdc_dimensions_raw`, `bdc_investment_identifier`,
`nonaccrual_*`, `row_id`, `position_key`, `position_id`, `entity_id`,
`canonical_name`.

### 2.3 Transforms: anchor alone is insufficient

Published values are frequently NOT the anchored raw value. The provenance
payload per value field is a triple -- **pathway, anchor, transform** -- and
the verification rule is:

    published == apply(transform_chain, raw_anchored_value)

with transform codes drawn from a small versioned registry. Transforms that
actually fire today:

| Transform | Where | Note |
|---|---|---|
| `rate_x100` / `rate_div100` | `staging_bdc.py:2450-2453` (and spread :2461-2464, pik :2507-2510, pct :2441-2443) | PER-ROW THRESHOLD HEURISTIC: `<=0.50 -> x100`, `>=50 -> /100`, else identity. Which branch fired is invisible today. Known-imperfect: see the :2657 comment (20-50bps PIK wrongly x100'd). |
| `bps_div100` + parse rule | identifier-text rates (`_text_*` from `_raw_id`) | The "Fixed + 1600" -> 16.00 class. The CCS Medical defect (1.6 vs 16.0) was a bug in exactly this transform. |
| `decimals_rescale:10^k` | `bdc_filings.py::_normalize_mixed_decimals_monetary_facts` (:573-622) | Silent extractor-side scale correction when filers misuse `decimals`. |
| `date_parse:<fmt>` / month->last_day | `staging_bdc.py:2515-2549` | Identifier-text maturity parsing with 1950/2099 guards. |
| `pow10_shares:k` | `with_shares_fix` CTE | Cross-row group-median inference -> Class C. |
| `cost_proxy_fv` | `with_cost` CTE | Cross-quarter FIRST_VALUE fill -> Class C. |
| `fx:<ccy>:<rate>` | principal USD conversion | Already recorded in-table. |

**iXBRL display scale needs NO column:** cached instance XML values are
already fully expanded (the filer's `scale=3` lives on the `ix:nonFraction`
display node; displayed 58,702 = instance 58,702,000). The overlay viewer
reads scale/format off the DOM node it highlights. Only PIPELINE-side value
changes (the rows above) need recording.

**Measurement by-product:** recording which rescale branch fired per row
yields the first dataset that can measure the threshold heuristic's error
rate against the rate-convention gold set (the mixed_tag_semantics problem).

### 2.4 The columns to add

1. **Extend the `*_source` enum pattern** to the remaining anchored value
   fields (it already covers 4). Pathway per field as plain SQL-groupable
   enums; new enum values where needed (e.g. `derived_proxy`, `bridge`,
   `b2_corrected`).
2. `src_context_id` -- the row's XBRL contextRef (one per row; Class-A facts
   share the row's context). Primary anchor for re-verifier + overlay viewer.
3. `src_facts` -- compact JSON `{field: {concept, raw, xform: [...]}}`, only
   where non-trivial (concept ambiguous under the many-to-one CONCEPT_MAP,
   raw != published, or Class-C derivation method). `raw` = value as
   extracted from the instance BEFORE pipeline transforms. Storing `raw`
   makes verification two-tier: a CHEAP check (re-derive published from
   raw + declared transforms; no filing access; can run on every rebuild)
   and a FULL check (re-read the filing; confirm raw matches the fact at
   context+concept). Subsumes the earlier `src_concepts` +
   `src_scale_adjusted` proposals.
4. `src_context_count` -- carry-through of `dedupe_context_count` (>1 =
   merged contexts, anchor is primary-of-N; `dedupe_conflict_fields` rides
   along or folds in).
5. `src_field_overrides` -- `{field: "bridge:<html_sha256_8>:t<T>:r<R>"}` for
   bridge-overlaid fields.
6. `corrected_fields` -- JSON list of fields modified by promoted B2
   corrections. Corrections apply INSIDE `build_unified_holdings()`
   (`unified_holdings.py:1347-1360`) before the write, so a corrected row's
   published value legitimately DISAGREES with its anchor. Without the
   marker the re-verifier misroutes every applied correction as
   extraction-wrong. Ship WITH the provenance columns, not later.

NOT proposed: fact ids (contextRef+concept suffices), filing path (derivable
from accession), per-fact decimals (subsumed by `src_facts.xform`), display
scale (see 2.3).

**Verified-FV accounting rule:** Class-C derived values are EXCLUDED from any
"verified FV" numerator and counted as their own bucket -- "correctly derived
by our own rule" is a different claim than "matches the filing". Class-D
columns never enter pointer verification at all.

**Partial population is deliberate and honest.** Provenance is populated for
cohort CIKs x post-2022 accessions only; `src_*` stays empty elsewhere.
Verification, B2 fleets, and the public product are all cohort-scoped, so
empty provenance outside the cohort is a documented known-empty region
(schemas.md), not a defect. The shadow ledger must treat "no provenance" as
its own state -- distinct from unverified-with-anchor.

Size impact at cohort scope is negligible relative to the 546MB CSV; the
parquet companion picks the columns up automatically
(`unified_holdings.py:1425-1426`).

---

## 3. Touched modules

| Module | Change |
|---|---|
| `pipeline/bdc_filings.py` | Keep `_context_id` through `_deduplicate_bdc_holdings()`; record per-field concepts + raw-as-extracted values + `decimals_rescale` transform events (feeds `src_facts`). Changes the bdc_holdings.csv schema. |
| `pipeline/staging_bdc.py` | Phase C SELECT (+ the 4 empty-frame constructors at :408/:435/:454/:1670) gains the new columns; the rate/pct rescale CASEs (:2441-2512) and identifier-text parse branches record which transform fired into `src_facts`; `*_source` enums extended to the remaining value fields; bridge overlay records `src_field_overrides`. |
| `pipeline/unified_holdings.py` CTEs | `with_cost` / `with_shares_fix` record `cost_proxy_fv` / `pow10_shares` derivation events (Class C) into `src_facts` and flip the field's `*_source` to `derived_proxy`. |
| `pipeline/unified_holdings.py` | Append new columns to `UNIFIED_COLUMNS` (:54-111); UNION and empty-frame paths pick them up via the constant; surface `corrected_fields` from the B2 apply step. N-PORT staging emits the columns as empty (union is by explicit column list from the constant, so both source preps must emit every column). |
| `pipeline/position_matching.py` / `pipeline/gics_classification.py` | No code change IF columns are added to `UNIFIED_COLUMNS` -- both enforce/reorder to that constant (:2416-2421, :735-739). Columns added OUTSIDE the constant are silently dropped here. |
| `tests/test_unified_holdings.py` | Exact-schema assertion at :1330 (`list(result.columns) == UNIFIED_COLUMNS`) plus staging fixture tests break by design; update alongside. |
| `pipeline/source_anchor_verify.py` | No change now; becomes a consumer of the columns at the re-verifier step. |
| `docs/reference/schemas.md` | Document the new columns and the known-empty region (out-of-cohort / pre-2022 rows). |

Tolerant (no change needed): all export modules and `scripts/diff_outputs.py`
(DuckDB `read_csv_auto`/`all_varchar`, schema-agnostic); `validate_holdings.py`,
`pik_status.py`, `index_returns.py` (pandas reads without column pinning);
B2 `dispatch_preflight.py` staging (`SELECT *` from the parquet -- analyst
workers automatically see the new columns in their per-CIK CSV, which is a
feature: workers can cite `src_context_id` in diagnoses). No DuckDB
`columns=`/`types=` pinning exists anywhere on the unified CSV.

**row_id is safe:** computed as the final build step
(`unified_holdings.py:1437-1470`) from the natural key in
`position_id_registry.py:58-148` (cik | source | report_date | rawid |
principal | shares, + dims/lot disambiguation). New columns do not change
existing row_ids **as long as none are added to the natural key -- do not add
provenance fields to the key.**

---

## 4. Migration risks

1. **bdc_holdings.csv backfill -- now cohort-sized.** `src_context_id` was
   dropped before that artifact, so populating it requires re-parsing cached
   filings (cache-only, no network). Under this scope that means cohort CIKs
   x post-2022 accessions -- a fraction of the 2,775 cached filings across
   425 BDCs (exact count is a one-line DuckDB query over bdc_holdings.csv at
   implementation time). The extraction supports `--ciks`, so a cohort-scoped
   re-extraction is the natural mechanism. A sidecar backfill (re-parse
   emitting a context_id join table keyed on cik/accession/identifier/dims)
   was considered and rejected: the join key is exactly the fields whose
   collisions the dedup logic exists to resolve, so ambiguous joins would
   need that logic replicated.
2. **Value-drift conflation.** The provenance re-extraction must be a
   values-identical change: run `python scripts/diff_outputs.py --semantic`
   and require ZERO semantic deltas (new columns only). Cohort-only
   re-extraction sharpens this gate -- any drift discovered mid-migration is
   confined to cohort CIKs and easy to adjudicate. If the extractor has
   drifted since the last bdc_holdings build, separate that drift from the
   provenance change before proceeding. Baseline governance per AGENTS.md:
   refresh `data/snapshots/baseline/` only after the semantic diff is
   documented.
3. **The silent-drop trap.** `position_matching.py` and
   `gics_classification.py` reorder to `UNIFIED_COLUMNS`; a column added to
   the frame but not the constant survives the build and then vanishes when
   those consumers rewrite the CSV. All additions go in the constant, in one
   commit with the staging changes.
4. **Correction/provenance disagreement** (section 2, `corrected_fields`):
   without the marker, the re-verifier misroutes every applied B2 correction
   as extraction-wrong.
5. **Merged-context rows.** `src_context_count > 1` rows have a primary-of-N
   anchor; the re-verifier contract must define what "verified" means there
   (suggest: the anchor verifies the surviving context's facts; listed
   conflict fields are excluded from verified status).
6. **HTML bridge sha mismatch.** Bridge entries pin `html_sha256`; the
   `src_field_overrides` refs inherit that pin. If a cached filing file is
   ever re-fetched/normalized, refs go stale -- the re-verifier should treat
   sha mismatch as provenance-wrong (reason code), not extraction-wrong.
7. **Test schema assertions** break by design (section 3); the pytest write
   guard (conftest) is unaffected -- rebuilds happen outside pytest.

---

## 5. Public-FV tripwire (decision needed before shadow routing lands)

Verified in code: the homepage headline is `portfolioFv` in
`portfolio_characteristics.json`, computed in
`pipeline/export/index_exports.py:774-791` as a straight
`GROUP BY index_classification` SUM of `fair_value` over ALL rows of
`private_markets_holdings.csv` at the as-of quarter, filtered to the unlisted
cohort (`_unlisted_bdc_filter_sql`) -- deliberately the exact sum of the
rounded classification buckets so headline + instrument donut reconcile to
the dollar (AGENTS.md v1 reconciliation contract; the industry donut must
stay on the same basis). Note the headline was already cohort-scoped, so this
report's scope narrowing changes nothing here -- but it does mean every row
in the headline is a row that COULD carry an anchor once the cohort
re-extraction lands, making the basis question unavoidable.

When shadow-ledger routing gives rows verified/unverified status, there are
exactly two coherent options, and the choice must be explicit:

- **(A) Keep the all-rows headline; publish verified-FV share as a quality
  metric alongside.** No public number moves; matches the existing
  `verified_fv >= 70` acceptance-gate framing; frontend "explains data status
  through metrics," per AGENTS.md. Recommended.
- **(B) Switch the headline to verified-rows-only.** Then the instrument
  donut, industry donut, AND per-fund pages must all switch on the same
  filter in the same release, or the exact-reconciliation contract breaks.
  Public FV would drop by the unverified share and move as verification
  progresses.

Do not let a shadow-routing implementation change the headline basis
implicitly. The one-line guard: the export query above gains either no filter
(A) or the same filter everywhere (B) -- never a mix. If (A), "no provenance"
rows (out-of-cohort never occurs here, but pre-2022 cohort history does)
count toward the headline like any other row and simply cap the verified
share.

---

## 6. Suggested implementation order

1. Cheap passthroughs first -- no re-extraction, populated from data that
   already exists: `src_context_count` (+ conflict fields) from
   bdc_holdings.csv; `src_field_overrides` from the bridge overlay step;
   transform recording in staging (`rate_x100`/`rate_div100` branch,
   identifier-text parse rules, `cost_proxy_fv`, `pow10_shares`) -- these
   fire during the unified build, so a `--unified` rebuild populates them
   without touching the extractor.
2. `bdc_filings.py` provenance capture (`src_context_id` + per-field
   concepts/raw values/`decimals_rescale` events for `src_facts`) +
   cohort-scoped, cache-only re-extraction under the zero-semantic-delta
   gate (risks 1/2).
3. `corrected_fields` from the B2 apply step; extend `*_source` enums to the
   remaining value fields.
4. Then the deterministic re-verifier consuming the columns: cheap tier
   (raw + declared transforms -> published; every rebuild) and full tier
   (`source_anchor_verify`-style filing re-read of every anchored row).

---

## 7. Out of scope (recorded so the narrowing is informed)

- **N-PORT** (interval/tender funds; not in v1): already carries the best
  cross-ref of any path -- `accession_number` + `nport_holding_id` survive
  to unified (`staging_nport.py:217,299`) and all 26 raw SEC dataset ZIPs
  (2019q4-2026q1) are cached under `data/raw/sec_datasets/nport_quarterly/`,
  so structured cross-refs are fully offline-verifiable. Only gap if ever
  needed: `sec_dataset_quarter` exists in nport_holdings.csv but is dropped
  in staging (amended filings can land in a later dataset quarter).
- **Pre-XBRL HTML template extraction** (`pipeline/html_extract.py` ->
  `html_extraction_holdings.csv`): NOT merged into unified holdings at all
  today -- no code imports the artifact downstream, so it contributes zero
  rows to the public product. If it is ever merged, coordinates (table/row/
  cell) are all known inside `extract_filing()` (:453/:499/:560-567) and are
  discarded at the record-dict construction (:504-531); the fix is cheap and
  the parser already matches `source_anchor_verify.py`.

---

## 8. Shadow-ledger routing: lanes, agents, and gates (step-3 scoping, agreed 2026-08-22)

Owner decisions folded in: mismatched rows route to agent lanes INCLUDING a
code-repair lane for parser drift (fix the parser ONCE, never per-row
overrides); amendments/restatements are deferred (get the original filings in
order first); lanes get descriptive names, not B-numbers (B1/B2 are already
overloaded -- they also name position-matching tiers); the existing Codex
worker plumbing is reused across all lanes.

### 8.1 The ledger is field-level

A row can have `fair_value` verified and `interest_rate` mismatched. Ledger
rows are keyed `(row_id, field)`, carrying: reason code, the re-verifier
evidence that produced it (tier, raw, declared xform, re-read value), the
build id of the unified artifact it was computed against, and current
routing state. Verification STATE lives here and only here -- never in
private_markets_holdings.csv (section 2). Reason-code enum reserves
`amended` from day one (costs nothing, avoids a schema migration); until the
amendments lane exists, amendment-caused mismatches land in the triage
residue and double as free measurement of how common that class is.

**Dedup against existing queues is mandatory:** before packet building, join
ledger rows against the source-reconciliation residual packets and any open
B2 verdict/correction state. A row must not be remediated twice because it
appears in both the old blocker pool (14,878 actionable) and the new ledger.

### 8.2 Triage is deterministic code first; agents get the residue

Most reason codes fall out of re-verifier evidence mechanically:

- cheap-tier fail + full-tier pass -> transform/registry drift;
- published still matches the filing on re-read but declared raw/xform is
  stale -> ANCHOR STALENESS (extractor improved; re-stamp provenance, no
  code change) -- distinguished from REGRESSION (published no longer matches
  the filing -> code fix). This split is what keeps the code-repair lane
  from "fixing" improvements;
- witness/sha mismatch -> provenance-wrong;
- clean anchor mismatch, healthy parse, no correction marker ->
  extraction-wrong;
- `corrected_fields` hit -> not a defect; verify against the correction
  audit trail instead.

Only what deterministic triage cannot classify goes to the adjudicator
agent. This preserves the standing doctrine (agents on validation residuals
only) and keeps the validation layer independent: reason codes must be
re-derivable from ledger evidence, and every lane's output is re-checked
gate-side by machinery the authoring agent does not control.

### 8.3 Lanes, permissions, gates

| Lane | Nature | Reads | Writes | Gated by | Dispatch unit |
|---|---|---|---|---|---|
| `provenance_triage` | deterministic module | ledger + re-verifier evidence | reason codes | re-derivable from evidence | -- (every rebuild) |
| `ledger-error-classifier` | agent, read-only | ledger, cached filings, holdings CSV | reason-code verdict leaves | gate-side re-derivation | per residue packet |
| `anchor-leaf-author` | agent | + corrections dir conventions | re-anchor leaves | `source_anchor_verify` refusal matrix (cell, witnesses, scale) | per CIK-quarter-mechanism |
| `correction-leaf-author` (today's B2, unchanged) | agent | as today | correction leaves / escalations | validator + B3 gate + magnitude gates | per CIK-quarter-mechanism |
| `parser-patch-author` | agent, isolated git worktree | pipeline/, tests/, cached filings | CODE + regression test | tests green + predicted-delta-only rebuild + OPERATOR MERGE | one packet per drift fingerprint |

Parser-repair acceptance contract (the lane's gate is sharper than any
confidence score because the blast radius is pre-declared): the packet is a
drift fingerprint (field, transform/parse rule, extractor version range,
affected row_id set from the ledger). Acceptance requires (1) a
failing-then-passing regression test reproducing the drift on a real cached
filing; (2) focused + full pytest green; (3) rebuild shows EXACTLY the
fingerprint's rows changing in the predicted direction, nothing else
(semantic diff). Escalate, do not fix, when the change would move rows
outside the fingerprint set -- that is a recalibration decision (e.g. the
<=0.50 rate threshold), owner-level, not a drift fix. The operator remains
the merge gate; the rebuild happens operator-side after merge.

Filer-error subcase (anchor-repair lane): when the source document itself is
wrong, there is nothing to repair -- the output is an escalation leaf
documenting the filer error (candidate for derived_value / known-limitations
treatment), never a fabricated anchor. The SAV worker canary demonstrated
workers make this call honestly (2 clean escalations, 0 fabrications).

### 8.4 Names (convention: `...-classifier` = verdict/read-only, `...-author` = gated artifact/write)

Owner-decided convention (2026-08-22, detail in
`docs/agent_family_architecture.md`): classifier-family lanes end in
`-classifier`; fixer-family lanes end in `-author`, with `-leaf-author`
for data fixers and `-patch-author` for code fixers. Deterministic modules
take neither suffix, so a suffixed name always means an agent lane.
**Names CHOSEN 2026-08-22 (the first option per lane below):**
`provenance_triage`, `ledger-error-classifier`, `anchor-leaf-author`,
`correction-leaf-author`, `parser-patch-author`. Alternatives retained for
the record.

- **Triage module (not an agent, no suffix):** `provenance_triage` |
  `ledger_triage` | `reason_code_triage`
- **Adjudicator agent:** `ledger-error-classifier` |
  `mismatch-classifier` | `reason-code-classifier` |
  `ledger-residue-classifier`
- **Anchor-repair agent:** `anchor-leaf-author` |
  `source-anchor-author` | `re-anchor-leaf-author` |
  `provenance-anchor-author`
- **Data-repair agent (existing B2):** `correction-leaf-author` |
  `holdings-correction-author` | `data-correction-author` (keep the
  `agent_b2` tooling paths as-is; rename is cosmetic/prompt-level, the
  scripts and dirs carry too much history to churn)
- **Parser-repair agent:** `parser-patch-author` |
  `parser-fix-author` | `extractor-patch-author` | `drift-patch-author`

### 8.5 Shared plumbing (owner assumption confirmed, one extension needed)

All agent lanes reuse the existing Codex worker harness: dispatcher +
WorkerHome lifecycle (`run_codex_worker.ps1`, auth re-copy, waste scrub),
ADMIN-shell dispatch (UAC lesson), packet manifests + prompt building
(`dispatch_preflight` pattern), leaf validation at intake (BOM strip,
escalation siblings), trace harvest, cohort guard at the dispatch chokepoint,
and the escalation-leaf convention across every lane. Differences are
confined to per-lane GRANT PROFILES (read-only vs corrections-dir write vs
worktree) and per-lane VERIFIERS at intake/gate.

The one genuine extension is the parser-repair lane: workers need an
isolated git worktree with write access to `pipeline/` + `tests/` and the
ability to run pytest -- none of which the B2 harness grants today. Note the
pytest conftest guard already blocks writes to `data/output/` from within
tests, which composes well: a parser-repair worker structurally cannot touch
production artifacts even with code-write grants. Everything else about its
lifecycle (dispatch, manifest, trace harvest, admin shell) is unchanged.

### 8.6 Agent-family design intent (see docs/agent_family_architecture.md)

The lanes above group into two families -- CLASSIFIER agents (triage
residue adjudication; verdict leaves, read-only, gate-side re-derivation)
and FIXER agents (anchor repair, data repair, parser repair; gated
artifacts, write grants, deterministic verifiers) -- with fixer split into
data and code sub-species. The family layer is DESIGN INTENT, not a
prerequisite project (owner decision 2026-08-22): nothing in this section
depends on it; the first new lanes are built ad hoc on the existing worker
harness, and the family contracts are EXTRACTED once a second new lane per
family is running. Every lane in this section is built against the
convergence checklist in `docs/agent_family_architecture.md` (verdict-or-
artifact output, first-class escalation sibling, gate outside the agent's
write reach, per-lane grant profile, re-derivable evidence) so later
unification is trivial. Grants and evidence visibility never port through
the family layer -- scaffolding only.

### 8.7 Deferred: amendments/restatements

Deferred by owner decision until original filings verify cleanly. The
design does not corner us: anchors are accession-scoped and accessions are
immutable, so an anchor is inherently an as-filed claim; amendment handling
(supersession detection, latest-knowledge vs as-filed policy, re-extraction
flow) is purely additive later. Reserved now: the `amended` enum value
(8.1). Known cost of deferral: amendment-caused mismatches burn adjudicator
cycles in the residue bucket -- bounded, measurable, and the measurement
itself prices the future lane.
