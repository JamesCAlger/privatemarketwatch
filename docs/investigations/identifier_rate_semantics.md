<!-- Canonical investigations file (cutover 2026-08-20). Append new entries with a
     dated '## ' heading, the question asked, and the results found; then rebuild
     the index: python scripts/split_investigations.py --reindex -->
# Identifier & rate semantics (Agent A)

## 2026-06-19 - Structured-XBRL-twin coverage for freeform investment_identifier (Agent A anchor budget)

QUESTION: if an "Agent A" enrichment parser splits the freeform BDC
`investment_identifier` string into structured fields, what fraction of rows have an
INDEPENDENT native-XBRL twin for each field to validate the parse against? This sets
how anchored vs blind such a parser is, and therefore how strong its promotion gate
must be.

MEASURED (cache-only, `data/output/bdc_holdings.parquet`, current-period rows only:
`period == report_date`; freeform id present). N = **627,181** rows. Essentially all
are 2022+ XBRL-era (only 122 current-period freeform rows pre-2022 -- pre-XBRL is the
HTML-template path, a separate population).

Per-field structured-twin coverage (field also present as a separately-tagged XBRL
element, independent of the string):

| Field | Twin coverage | Note |
|---|---|---|
| `basis_spread` | 67.8% | also the fixed/floating oracle |
| `principal_amount` | 70.0% | row-level identity anchor |
| `interest_rate` (clean numeric) | 59.3% | +0.3% is freeform text leaking into the column ('1M SOFR + 6.00%') |
| `maturity_date` | 29.2% | |
| `pik_rate` | 7.8% | |
| `reference_rate_type` | 0.0% (213 rows) | NEVER tagged structurally; string-only |

Any checkable rate/maturity twin (numeric interest_rate OR maturity_date): **66.9%**.
So ~33% of rows have no rate/maturity anchor at all. Era split confirms XBRL-era
concentration: interest_rate clean-numeric is 60.2% on 2022+ vs n=122 pre-2022.

KEY FINDING -- the anchor is inversely correlated with where a string parser adds
value. The fields a parser most needs to fix (the wrapper's known failure modes:
`reference_rate_type` invented, `coupon_type` fixed-vs-floating invented, GICS-prefix
split, issuer isolation) are exactly the ~0%-twin fields. The well-anchored fields
(interest_rate 59%, basis_spread 68%) are the ones the deterministic pipeline already
extracts competently. So "cross-check the parse against its XBRL twin" does NOT cover
the high-value-add fields.

USABLE ANCHORS for the unanchored fields are cross-field internal-consistency, not
independent facts:
1. `basis_spread` present (67.8%) => instrument is floating => a reference token must
   exist in the string, and coupon_type=floating. basis_spread ABSENT => fixed => any
   "LIBOR"/"Floating" the parser emits is fabricated (this is exactly the wrapper's
   invented-LIBOR-on-a-fixed-loan bug).
2. `interest_rate` numeric twin (59%) => total = cash + pik arithmetic localizes
   mis-binning (e.g. 11 == 7 + 4).

DESIGN IMPLICATION: the ~33% with no twin is a third of the corpus, not a corner
case -- it is the quarantine / low-confidence / gold-slice population. Stable-but-
unanchored fields (0%-twin) get only a grammar-stability check (same filer+layout =>
same parse), never a truth anchor, so they should stay permanently lower-confidence
and never graduate to "verified" on stability alone.

## 2026-06-19 - Format-signature (cik, shape) clustering probe: TWO REGIMES, naive mask is regime-dependent

QUESTION (falsification test for the Agent-A design): does masking the freeform
`investment_identifier` to a structural shape (rates->%, m/d/y and ISO dates->D,
other numbers->#, word-runs->W, punctuation/delimiters preserved) cluster tightly
within a CIK, so a grammar-per-(cik, shape)-variant is viable?

METHOD: vectorized DuckDB regexp mask, current-period rows. Two high-volume CIKs.

RESULT -- it splits cleanly into two filer REGIMES that need different signature
strategies:

1. DELIMITED regime. Golub Capital BDC (1476765), 23,971 rows, rate-embedding=0%.
   43 distinct shapes; largest 55.6%; **2 shapes cover 80%, 5 cover 95%.** Strings
   are clean delimited records ("CG Group Holdings, LLC, One stop 1" => `W , W , W`;
   pipe variant "Issuer | type | Non-Affiliated Issuer" => `W , W | W | W -W`).
   Within a shape the segment semantics are constant. (cik, shape) clusters TIGHTLY
   and the punctuation skeleton is the right signature. These filers are also the
   well-ANCHORED ones (rates/maturity tagged structurally, not in the string).

2. FLATTENED-CONCATENATION regime. Antares Strategic Credit Fund (1993402), 10,007
   rows, rate-embedding=67%. **178 distinct shapes; largest 23.6%; 9 shapes for 80%,
   40 for 95%; 42-77 distinct shapes PER quarter.** The identifier is a concatenation
   of XBRL dimension members with NO reliable delimiter ("Investments -
   non-controlled/non-affiliated Secured Debt <GICS industry> <Issuer> Asset Type
   First Lien <ref> + <spread>% <ref>% ... <maturity>"). The naive punctuation mask
   OVER-FRAGMENTS, and the fragmentation is largely ARTIFACTUAL, from 3 causes:
   (a) variable rate-leg COUNT ("% W % W D" vs "% W % W % W D" = +1 PIK leg) -> same
       grammar, different shape;
   (b) field-internal commas in GICS names ("Electronic Equipment, Instruments and
       Components") inject a spurious comma-delimiter into the shape;
   (c) dash-ENCODING noise: "Investments - non" (spaced hyphen) vs "Investments(en-dash)non"
       render as different shapes; the en-dash also shows as a cp1252 mojibake char
       in the cached data (a real source data-quality artifact).
   True grammar count is small (~4: debt-with-rate-legs, revolver/DDTL "Commitment
   Type...Expiration", "Equity Investments", aggregate/total rows). The 178 is noise.

KEY FINDING: the regime split lines up exactly with the anchor-availability split
above. The 0%-rate filers are delimited + well-anchored (easy on every axis); the
50-67%-rate filers (Antares, MidCap 54%, Bain 55%, Crescent 63%) are flattened +
weakly-anchored (hard on every axis). Agent A is most needed precisely where the
naive signature fails and the structured twin is absent.

DESIGN CONSEQUENCE: (cik, shape) is viable but the A0 deterministic signature must be
REGIME-AWARE and NORMALIZED, not a raw character mask:
- detect regime per filer cheaply (rate-embedding %, delimiter density, presence of
  keyword anchors like "Asset Type"/"Commitment Type"/"non-controlled");
- delimited filers: punctuation skeleton (works as-is);
- flattened filers: segment on KEYWORD anchors, not punctuation; normalize out the
  artifacts -- collapse repeated rate-legs to a single quantifier (`%+`), strip
  dash/encoding variants, protect field-internal commas in known GICS names.
Most of Agent A's value/risk is in this A0 signature engineering: a naive signature
buries the agent under a 178-shape tail; a normalized regime-aware one hands it ~4-10
grammars per filer. Probe was a throwaway (scripts/tmp_format_signature_probe.py,
removed); reproduce from this spec.

VALIDATION (same day): ran the keyword-anchored signature on Antares (1993402) to
test whether it collapses the 178 punctuation-shapes. Signature = ordered sequence
of section-anchor keywords present (AFFIL [non-controlled/affiliated stem],
SECDEBT, EQUITY, SUBORD, ASSETTYPE ["asset type"], COMMIT ["commitment type"],
COMMITEXP ["commitment expiration"], REFRATE [sofr/libor/prime/reference rate],
RATE [%], MAT [m/d/y]); rate-legs and dates reduced to ONE token each (kills the
leg-count blowup); punctuation/commas/dashes ignored (kills the other two artifacts).

RESULT -- DECISIVE collapse: **178 -> 23 distinct signatures; 2 cover 80%, 3 cover
90%, 5 cover 95%** (Golub-grade tightness, now on the hard filer). The top signatures
are semantic grammars:
- `AFFIL SECDEBT ASSETTYPE REFRATE RATE MAT` 65.7% (rate-bearing first/second-lien debt)
- `AFFIL COMMIT COMMITEXP MAT` 22.4% (revolver / delayed-draw; commitment + expiration)
- `AFFIL EQUITY ASSETTYPE` 3.3% (equity)
- `AFFIL SECDEBT` 2.3% (issuer/rate ABSENT after a GICS industry => GICS-industry
  SUBTOTAL / section-header => leaked-aggregate candidate, flagged for free)
- `(none)` 1.9% mostly a typeless secured-debt partial; also caught 1 junk row whose
  identifier is the Excel error text "Retrieving data. Wait a few seconds..." -- a
  single $0-FV corrupt cell, immaterial (1 row, 1 CIK across the whole dataset), but
  surfaced by the signature with zero extra work.
The keyword regex matched AFFIL straight through the `�` dash-mojibake, confirming
robustness to the encoding noise that fractured the naive mask.

CONCLUSION: (cik, keyword-signature) is the right A0 key for the flattened regime;
(cik, punctuation-shape) for the delimited regime. Both yield ~2-5 grammars covering
80%+, i.e. inside the bounded-bundle budget. The Agent-A premise survives the
falsification on the HARD filer. Remaining A0 build work is the per-regime detector +
the flattened anchor vocabulary (the SECDEBT-with-no-issuer => aggregate signal is a
bonus output feeding the leaked-aggregate flag). Probe was a throwaway
(scripts/tmp_keyword_signature_probe.py, removed); reproduce from the anchor list above.

GENERALIZATION TEST (same day): ran the Antares-tuned 11-anchor vocabulary, unchanged,
against the other 3 flattened filers (MidCap 1278752, Bain 1655050, Crescent 1633336).
Diagnostic = distinct-sig count, cover80, the (none) share, and whether rate-embedding
rows got a RATE-bearing signature.

| filer | rows | sigs | cover80 | largest | (none) | rate-rows RATE-captured |
|---|---|---|---|---|---|---|
| Antares (baseline) | 10,007 | 23 | 2 | 65.7% | 1.9% | 100% |
| MidCap | 9,893 | 15 | 3 | 49.0% | 30.9% | 100% |
| Bain | 9,557 | 20 | 5 | 28.9% | 15.6% | 100% |
| Crescent | 8,326 | 6 | 2 | 61.9% (just "RATE") | 21.7% | 100% |

TWO SEPARATE CONCLUSIONS (do not conflate):
1. TIGHTNESS GENERALIZES. Every filer clusters to <=5 sigs for 80% coverage. The
   (cik, keyword-signature) STRUCTURE is sound everywhere. And RATE-capture is 100%
   for all four -- the %/date detectors are universal, so the highest-value, zero-twin
   field (the rate) is robustly located regardless of filer dialect.
2. THE SHARED VOCABULARY DOES NOT GENERALIZE. The Antares anchor set fits Antares
   (1.9% none) but degrades on the others, because each filer has its own keyword
   DIALECT:
   - lien/instrument marker: "Asset Type" (Antares) vs "Investment Type" (MidCap,
     Crescent) vs inline "First Lien Senior Secured Loan" (Bain). I only keyed "asset
     type".
   - asset category: "Secured Debt" (Antares/MidCap) vs "Debt Investments" (Crescent)
     vs "Senior Secured Loan" (Bain). I only keyed "secured debt".
   - affiliation: inline prefix (Antares) vs a section HEADER not on the row (MidCap)
     vs absent.
   - encoding corruption breaks literal anchors: Crescent writes "Investment(mojibake)Type",
     so even an "investment type" literal would miss -> Crescent degenerates to a
     vocabulary-less "RATE"-only signature on 62% of rows.
   Result: MidCap 30.9% / Bain 15.6% / Crescent 21.7% land in (none), and Crescent's
   dominant signature carries no structure. NOTE: the user's canonical example
   ("Automotive Crowne Automotive Vari-Form Group, LLC First Lien Secured Debt 11.00%
   (7.00% Cash plus 4.00% PIK...") is a MidCap row -> sig "SECDEBT RATE MAT" (no AFFIL,
   no REFRATE since it is fixed) -- correctly typed, confirming the signature reads the
   semantics right when the keyword is in-vocabulary.

DESIGN CONSEQUENCE (this resolves the open question): the anchor vocabulary is
PER-FILER config, NOT a shared global list -- exactly AGENTS.md Layer-2 ("per-CIK
corrections as audited config, not growing global keyword lists"). So:
- A0 (global): regime detector + punctuation-shape for delimited filers + a STARTER
  anchor set + the (none)/degenerate-signature share as the "vocabulary not yet
  learned" trigger.
- A2 (agent, per flattened filer, ONE TIME): induce that filer's anchor dialect from a
  sample -- what marks lien, what marks category, is affiliation inline or a header,
  what encoding variants appear -- and emit it as per-CIK anchor config. THIS is the
  agent's highest-value task, not row-by-row splitting.
- After induction: deterministic signature + parse + drift-watch, agent only on drift.
The flattened cohort is the ~30-40 rate-embedding filers (>=20% '%'-embedding). Each
needs a one-time, bounded anchor-induction bundle. The (none)/degenerate share is the
measurable per-filer trigger and, later, the coverage KPI. Probe was a throwaway
(scripts/tmp_keyword_sig_generalize.py, removed); reproduce from the table above.

## 2026-06-20 - Why text-spread disagrees with the XBRL basis_spread tag (Agent A gold conflicts)

QUESTION: on the basis_spread gold conflicts where the freeform identifier text says one
spread (e.g. 5.0%) but the tagged XBRL basis_spread says another (e.g. 5.5%), is it a
genuine filer data-input error? Pulled the EXACT rows (cik+report_date+fair_value+full
identifier prefix) with all structured rate fields. Two distinct mechanisms:

1. GENUINE FILER TEXT-vs-TAG INCONSISTENCY (the real disagreements). The schedule-of-
   investments TEXT states a precise contractual margin; the XBRL InvestmentBasisSpread
   tag carries a DIFFERENT, usually ROUNDED number. Gold confirms the TEXT is correct
   (TRUE matches A) where determinable:
   - A001 MidCap "L+525" (=5.25%)  vs tag 5.35%   (+10bps; not round -> keying error)
   - A005 Bain "SOFR Spread 6.60%" vs tag 6.00%   (-60bps; rounded to whole)
   - A006 Bain "SOFR Spread 8.75%" vs tag 9.00%   (+25bps; AND its int_rate tag 14.5% vs
          text 13.91% -- the filer rounded BOTH spread and rate)
   - A007 Antares "S + 5.25%"      vs tag 5.50%   (+25bps)
   - A008 Antares "S + 5.50%"      vs tag 5.00%   (-50bps)
   Tags cluster on round numbers (5.00/5.50/6.00/9.00) while the text is precise
   (5.25/6.60/8.75). On A007/A008 the interest_rate tag AGREES with text -- only the
   spread tag is off -> isolated spread mis-tag, not a whole-row error. So YES: a genuine
   filer-side inconsistency between their own SOI table and their XBRL tagging (rounding
   or mis-key in the structured tag; the human-readable table is the precise source).

2. NOT a value error -- XBRL basis_spread stored on inconsistent SCALE (A002, A004).
   text "SOFR+575" and tag both 5.75 -- but the tag is stored as PERCENT (5.75), not the
   usual decimal (0.0535). text and tag AGREE; the overlay conflict-detector (_agree
   assumes decimal -> 5.75*100=575) FALSELY flagged them. MidCap and Crescent both have
   mixed decimal/percent basis_spread storage. This inflates the 834 conflict count.

IMPLICATIONS:
- Validates Agent A for spread: A reads the precise text correctly; the XBRL basis_spread
  tag is the LESS reliable source (filers round/mis-key it). gold basis_spread A 100% /
  XBRL 33%.
- Challenges the default provenance precedence (structured XBRL > A-parse) FOR SPREAD
  specifically: the freeform text is more precise than the tag here. Blank-only stays the
  safe default, but A-spread is at least as good and a future override is defensible on a
  larger gold.
- Fix the conflict detector's decimal-vs-percent scale handling before trusting the
  conflict count (mechanism 2 is pure false-positive).

## 2026-06-20 - CORRECTION to the above: all-in reconciliation REVERSES it (tag, not text)

The prior entry concluded the freeform TEXT spread is precise and the XBRL basis_spread
tag is the rounded/erroneous one (A 100% / XBRL 33% on the gold). Cross-checking against
the ALL-IN interest rate overturns that.

METHOD: for a floating loan above its floor, all_in_cash = SOFR + spread, so
implied_SOFR = all_in - pik - spread. Benchmark SOFR = filer-quarter MEDIAN implied SOFR
over its floating decimal-scale loans. That median matched PUBLISHED 3M term SOFR
(2023Q2 5.20, 2024Q2 5.42, 2024Q3 4.95, 2025Q2 4.33) -> a valid independent benchmark.

RESULT (4 checkable conflict rows; TAG reconciles, TEXT is the outlier):
- A005: SOFR 5.20; text 6.60->implied 4.53 (off .67) vs tag 6.00->5.13 (off .07) -> TAG
- A006: SOFR 5.20; text 8.75->5.75 (off .55) vs tag 9.00->5.50 (off .30) -> TAG (but its
  all-in is itself disputed: text 13.91 vs tag 14.50; on the text all-in A006 flips to text)
- A007: SOFR 5.42; text 5.25->5.72 (off .30) vs tag 5.50->5.47 (off .05) -> TAG
- A008: SOFR 4.74; text 5.50->4.09 (off .65) vs tag 5.00->4.59 (off .15) -> TAG

INTERPRETATION: these rows are INTERNALLY INCONSISTENT in the filing -- the stated spread
and stated all-in do not reconcile at period SOFR. The XBRL (spread tag + rate tag) pair
reconciles; the TEXT spread is the figure that does not add up. So the prior "text precise /
tag rounded" claim is WITHDRAWN. The text spreads differ from tags in BOTH directions
(no systematic offset), i.e. the text spread is noisier, not consistently higher/lower.
The gold "A correct" labels on these rows are soft: the human read the spread NUMBER without
checking it reconciles to the all-in.

CONSEQUENCES:
- The real validator for spread is ALL-IN RECONCILIATION (spread + SOFR ~= all_in), not a
  text-vs-tag value comparison. Add it as a hard gate invariant; it is stronger than
  cross-twin agreement and caught what the gold missed.
- A's spread is NOT unambiguously better than the XBRL tag (possibly worse on conflicts);
  the earlier "merge A spread / prefer text over XBRL for spread" recommendation is WITHDRAWN.
- Circularity caveat: the benchmark is tag-derived, but it (a) matches published SOFR and
  (b) is dominated by non-conflict rows where text==tag, so a conflict row's tag-implied
  falling on the median means its tag looks like a normal loan and its text spread is the
  outlier. Not purely circular, but a fully independent SOFR series would make it airtight.

## 2026-06-21 - Twin (structured) vs identifier (text) disagreements: who is right, and where to resolve

Question: the A3 held-out gate hard-failed grammars on twin-comparison invariants (parsed
identifier value vs the structured XBRL twin). Are those FAILs real grammar defects, or is the
twin the unreliable side? And where should "which value wins" be decided?

Worked example (Investcorp ICMB 0001578348, Axiom Global, traced through the RAW iXBRL across
filings): ONE investee (single InvestmentIdentifierAxis member) -- NOT two positions, NOT a
transform collapse. Its maturity was AMENDED 10/1/2026 -> 10/2/2028 in Q3 2024. The filer
updated the structured `us-gaap:InvestmentMaturityDate` fact immediately (2024-09-30 context =
2028-10-02) but left the free-text member DESCRIPTOR stale at "Maturity Date 10/01/2026" for ~2
quarters (it caught up to 2028 by the 2025-03-31 filing). Our pipeline carried both: identifier
(descriptor) = 2026, structured twin = 2028. The current-period TWIN was correct; the grammar
read a STALE descriptor.

Longitudinal adjudication (convergence test: when parsed != twin at period T, which value do the
two sources agree on at another period for that investee?), over 472 maturity disagreements / 38
cohort filers:
- TWIN correct (struct corroborated, descriptor stale): 47.5%
- IDENTIFIER correct (twin mis-tagged): 12.1%
- AMBIGUOUS (neither corroborated): 30.9%
- BOTH (genuine change across periods): 9.5%
- Among one-side-corroborated (n=281): structured/twin correct ~80%, identifier ~20%.

So neither source is categorically authoritative: descriptors go stale after amendments
(~80% of adjudicable cases), but the twin is mis-tagged ~20% of the time. Consistent with the
2026-06-20 spread finding (the XBRL tag, not the text, was usually right on spread conflicts).

RETRACTED: an earlier "51% twin false-negative rate" estimate. Its heuristic ("parsed value
present in the identifier string => grammar correct") conflated descriptor-agreement with
correctness; Axiom is the counterexample (descriptor present but stale). Not a valid metric.
`position_id` is NOT usable as a cross-period adjudication key here: 100% NULL on the 133,547
BDC maturity-bearing rows in private_markets_holdings.csv (it nulls exactly when the identifier
format changes across periods -- the stale-descriptor case). That absence of a deterministic key
reinforces routing this to Agent B's source-context/longitudinal evidence-gathering.

Decision (architecture): twin-vs-text resolution is an Agent B per-row VALUE adjudication
(B_and_C "Class 2 within-row: decide which field / whether real"), not an Agent A promotion
gate. Implemented:
- `pipeline/identifier_held_out.py`: the held-out gate now gates ONLY on self-contained
  invariants (`sum_identity`); `pct_agree`/`date_agree` (twin comparisons) are tracked as an
  advisory `twin_agreement_pct` per quarter and no longer fail the gate.
- `scripts/shadow_agent_a_engine.py`: new `agentA_maturity_vs_xbrl` ledger flag (joins the
  existing `agentA_spread_vs_xbrl`) so B receives the maturity disagreement.
- "No structured value -> use text" is the deterministic default and is largely already in place
  via the identifier text-enrichment that fills null maturity/reference fields.
- Re-gate of the 2025-12-31 cohort (55 staged proposals): 35 PASS / 20 FAIL -> 38 PASS / 17 FAIL.
  3 FAIL->PASS (0001653384 Runway, 0001832148 SLR HC, 0001905824 PIMCO -- pure twin-disagreement
  fails); 0 PASS->FAIL regressions; remaining 17 FAILs are real (3 regime, 8 completeness,
  6 none-share). Investcorp correctly STAYS FAIL on a genuine none-share issue, so the gate is
  not over-relaxed.

Caveats: adjudication is maturities only (floating rates reset each period -> no convergence
test). Investee matching across periods used a regex-stripped identifier key (imperfect ->
inflated the 31% ambiguous), so 80/20 is directional, not exact. Tests:
tests/test_identifier_held_out.py (twin-advisory regression). 27 Agent A held-out/rate/shadow
tests pass.

## 2026-06-23 - Why the 8 Agent A "completeness" FAILs fail: 0% encoding, ~84% regex/sampling, ~16% scope-out

Question: of the 8 staged-FAIL CIKs the A3 held-out gate failed on grammar COMPLETENESS
(2025-12-31 batch), how many are fixable by separator/encoding NORMALIZATION (a harness fix)
vs need real grammar/sampling work? Tested deterministically: reproduced the gate's per-quarter
completeness (sig==dom; all required_fields extract), isolated the exact UNPARSED rows in each
CIK's worst quarter, then measured (a) recovery under layered normalization (dash/encoding
unify, percent-unglue, hyphen-unglue, whitespace), and (b) whether the coupon VALUE actually
appears in the identifier string (interest_rate/basis_spread twin value or a "REF +spread"
token present) -- a regex can only extract a rate that is in the string.

Findings (worst quarter per CIK; unparsed rows):
- ENCODING/SEPARATOR-driven: 0 of 8. Normalization recovered 0% on every CIK. The earlier
  Goldman "glued %1st vs spaced % 1st / hyphen vs em-dash" cosmetic difference is real but is
  NOT what breaks completeness.
- RATE-IN-STRING but layout missed (regex+sampling fix): ~209 of 249 unparsed rows (~84%).
  5 CIKs ~100% regex-fixable (Goldman 0001772704 50/50, Silver Point 0001646614 62/65,
  SLR 0001418076 9/9, Phillip Street 0001948368 38/38, Great Elm 0001675033 45/45); 2 small-n
  MIXED (FIDUS 0001513363 2/3, Silver Capital 0001674760 3/6).
- RATE-NOT-IN-STRING (lives in XBRL twin only -> scope OUT of a flattened string-grammar's
  denominator; not Agent A's job): ~40 of 249 (~16%), almost all Star Mountain 0001786835
  (33/33; identifiers are industry+instrument-type only, e.g. "Aerospace Defense First Lien
  Senior Secured Term Loan Non-Affiliate Investments", no coupon in the string).

Root cause of the dominant (regex-fixable) bucket, from full-string inspection (Goldman
2023-12-31): the real position line is PREFIXED by a hierarchy breadcrumb carrying NAV
percentages, e.g. "Investment Debt Investments - 204.80% United States - 197.87% 1st
Lien/Senior Secured Debt [em-dash] 195.60% CFS Management, LLC ... Interest Rate 11.86%
Reference Rate and Spread S +6.25 (Incl. 0.75% PIK) Maturity 07/01/24" (ti=0.1186, ts=0.0625
confirm the coupon IS present and well-labeled). The grammar misses it because its extractors
are not robust to (1) a prepended breadcrumb with leading >100% NAV percentages, and (2) spread
variants "S +6.25" vs "S + 6.25" and the "(Incl. X% PIK)" parenthetical. These breadcrumb-
prefixed rows exist in the failing quarter but the head-3-per-era sampling never showed them to
the worker.

Implication for remediation of the 8:
- Normalization/encoding harness fix clears NONE of them. Do not pursue it for this batch.
- ~5 (+2 partial) need LABEL-ANCHORED extractors (anchor on "Interest Rate"/"Reference Rate and
  Spread"/"Maturity", skip any leading breadcrumb; tolerate glued/spaced spread + PIK
  parenthetical) AND within-quarter SHAPE-diverse sampling so the worker actually sees the
  breadcrumb-prefixed variant (era-stratification alone was already on and did not surface it).
- 1 (Star Mountain) is a SCOPE/denominator fix: its identifiers carry no coupon, so they should
  not count against a flattened string-grammar; route to the structured-twin path, not re-induction.
Method: read-only diagnostic over bdc_holdings.parquet + staged proposal grammar/anchors
(temp script, deleted). Production untouched.

## 2026-07-20 - XBRL linkbase-layer evidence: rate-concept fingerprints, presentation labels, calc arcs, domain-default anchors

**Question.** Can XBRL linkbase-layer metadata (concept QNames, presentation
labels/preferred-label roles, calculation arcs, definition-linkbase domain
defaults) improve (a) per-filer interest-rate convention adjudication
(cash leg vs all-in) and (b) subtotal-leakage detection?

**Data.** (1) One streaming pass over all 2,977 cached BDC instance XMLs
(17.1 GB, 234 CIKs, zero network) -> `linkbase_analysis/rate_tag_fingerprint_by_accession.csv`
and `fv_dimension_buckets_by_accession.csv`. (2) All 25 SEC BDC dataset zips
(2022q4-2026_06, new /files/datastandardsinnovation/ path; the old
/structureddata/ path is dead) -> `dataset_rate_semantics.csv` (SEC's own
soi.tsv flattening), `dataset_cal_rate_arcs.csv`, `dataset_pre_rate_labels.csv`.

**Findings - rate convention.**
- The us-gaap SOI taxonomy has three position-rate elements. 34 of 192 dataset
  CIKs use `InvestmentInterestRatePaidInCash` (47,283 facts in the instance
  cache); 22 tag bare+cash+PIK on the same contexts.
- The extractor's CONCEPT_MAP substring fallthrough stored PaidInCash values
  in `interest_rate` with provenance discarded; 293 filings have MIXED
  winners (bare in some contexts, PaidInCash in others) -> a single per-CIK
  convention is ill-posed for those filers; migration needs per-row provenance.
- Arithmetic sum proof (bare == cash + PIK within context): WhiteHorse 589/594
  -> bare is all-in (resolved its ceiling_conflict unknown). Great Elm 76/90
  but 26/103 ordering violations from its ~4% cash-won contexts -> left
  unknown (s0_s1_conflict), needs per-row treatment.
- Concept misuse exists (2/34): Main Street labels PaidInCash "PIK Rate";
  First Eagle labels PaidInCash generically and PaidInKind as "PIK loan
  concentration". QName evidence therefore requires a presentation-label
  guard; label-contradicted CIKs abstain.
- BlackRock TCP/DLC/PCF label bare "Total Coupon" and PaidInCash/PIK
  "Spread Cash"/"Spread PIK" (spreads, not rates); stored column is 85-95%
  all-in totals with 5-15% spread contamination. The classifier's blanket
  cash_leg for these three would mis-normalize the majority -> mixed flag.
- Format eras dated from soi.tsv: Stellus SCIC cash-only tagging through
  2024-09-30 (bare appears 2024-12-31), Stellus PC BDC bare from 2024-09-30,
  StepStone bare-only -> dual (2024q4-2025q3) -> cash-only from 2025-12-31.
  Monroe pair: stable mixed tagging, no era flip.
- Calc arcs: CION declares InvestmentInterestRate = PaidInCash + PaidInKind
  (+ coupon components) in 15 filings (filer-signed all-in); VLL/WTI family
  declares the same for InvestmentInterestRateDuringPeriod.

**Findings - subtotal leakage / anchors.**
- The dimensionless (no-member) InvestmentOwnedAtFairValue fact is the
  filer-declared portfolio total (XBRL domain-default semantics). 90% of
  accession-periods with >=20 positions carry one; only 2.5% are ambiguous
  (multiple candidates).
- Ares check: unified holdings reconcile to this anchor within 0.07-0.39%
  while raw bdc_holdings is +17% -> the anchor detects the cleanup the
  pipeline already performs. Corpus-wide vs private_markets_holdings: 52%
  within 0.5%, 23% beyond 10% -- confounded by index-facing exclusions, and
  companyfacts_fv already serves as the production anchor. NOT wired as a
  gate; artifact retained as an anchor-candidate source for the existing
  consensus-tier machinery.
- Presentation linkbase cannot flag member-level subtotals (labels attach to
  concepts, not typed-member values), so it does not replace the aggregate
  keyword filters.

**Integration (validated, value-preserving).**
- `scripts/scan_rate_tag_fingerprint.py`, `scripts/analyze_bdc_dataset_linkbase.py`,
  `scripts/build_s0_convention_signal.py` -> `linkbase_analysis/s0_convention_signal.csv`.
- rate_convention.py S0 signal (basis `tag_fingerprint`): 4 unknowns resolved
  (Gladstone, Stellus x2 cash_leg; WhiteHorse all_in), Fidus medium->high,
  0 convictions overturned, 9 mixed_tag_semantics flags. Numeric signals
  block S0; phrasing-only disagreement is non-blocking (the sum test measures
  the same printed decomposition the phrase regex infers from).
- bdc_filings.py now records `interest_rate_concept` ('bare'|'paid_in_cash')
  per row (empty until an accession is (re)parsed; backfill needs a full
  re-extraction from cache).

