# How production derives text and class fields (BDC rows)

Scope: the old Python pipeline (`pipeline/`), BDC source rows only, five v0.5 funds.
Read from code on 2026-11-25 in worktree `warehouse-dbt`. No data was read and nothing was run.
Paths are relative to the worktree root. Line numbers are for this checkout.

Abbreviations:
- `SB` = `pipeline/staging_bdc.py` (`_prepare_bdc`, line 698)
- `UH` = `pipeline/unified_holdings.py` (`build_unified_holdings`, line 956)
- `FC` = `pipeline/financial_conventions.py` (`prepare`, line 63; called by `pipeline/financial_finalization.py:13` from UH:1642)
- `HB` = `pipeline/bdc_xbrl_html_bridge.py`
- `CL` = `pipeline/classification.py`
- "member" = the InvestmentIdentifierAxis typed member text = `investment_identifier` from extraction = `bdc_investment_identifier` in holdings. Staging works on `_raw_id` = member after affiliation stripping (SB:1862-1897).
- "field-status artifact" = `BDC_IXBRL_FIELD_STATUS_FILE`, built separately by `HB.extract_bdc_ixbrl_field_status` (HB:1828) from the cached inline-XBRL page. Staging reads it only if the file exists (SB:3318).

## 1. Summary table

| Field | Where set (first, in order) | Input text | Method | Global / per fund | Overwritten later by |
|---|---|---|---|---|---|
| issuer_name | SB:2217-2345 parse; SB:2498-2570 bridges, bad-name fix; SB:2934 name normalise; SB:3257-3282 casing vote | member (`_raw_id`) | ordered CASE of regex/segment rules; wrapper `staging.hierarchy_extract` regex; exact-key bridge tables | global parser plus per-fund regex (Ares, Apollo) | row corrections (UH:1532); promoted rules (UH:1554); `issuer_from_identifier` (UH:1561); `issuer_name_strip_re` (UH:1569); global split (UH:1577) |
| instrument_description | SB:2346-2468; bridges SB:2498-2546 | member | same CASE as issuer; remainder of the member | global plus per fund | row corrections; promoted rules; strip-to-instrument (UH:1569); `instrument_description_strip_re` (UH:1571); global split (UH:1577) |
| asset_category | SB:2737-2741 keyword CASE; SB:2769-2784 co-invest; SB:2798-2832 cash; SB:2835-2840 unclassed fix | XBRL InvestmentType member name, instrument_description, member; numeric presence | keyword lists, then field heuristic | global plus wrapper lists (`equity_instrument_labels`, `cash_identifiers`, `par_tagged_as_units`) | printed sections equity tranches (UH:1529); row corrections; promoted B2 |
| issuer_category | SB:2743-2755; SB:2779-2782 | issuer_name | keyword ("asset management" within 30 chars, "senior loan program") | global | row corrections |
| index_classification | UH:1224-1243 + 1361 (CL:469-545) | issuer_name + instrument_description; asset_category; issuer_category | keyword CASE | global | stabilise (UH:1519); restore (UH:1520); printed sections (UH:1529); row corrections; fund-strategy corrections (UH:1535); promoted B2 `classification_fix`; unclassified cache (UH:1623) |
| exposure_type | UH:1233 (CL:575-592) | same text; categories | keyword CASE | global | stabilise; row corrections; promoted B2; unclassified cache |
| asset_class | UH:1234 (CL:595-648) | same text; categories | keyword CASE | global | stabilise; restore; printed sections; row corrections; fund strategy; RE override (UH:1539); promoted B2; unclassified cache |
| lien_position | SB:3193 blank; iXBRL overlay SB:3335 (HB:1347-1353); UH:1239 + 1364 keyword | issuer+instrument+member; printed section heading (overlay) | keyword CASE first, overlay value as fallback; kept only if DIRECT_LENDING | global; HPS `lien_from_identifier` | restore (UH:1520); printed sections null (UH:1529); row corrections + re-derive; lien cache (UH:1616); `lien_from_identifier` (UH:1620) |
| instrument_type | SB:3194 blank; UH:1242 + 1366 | issuer+instrument+member | keyword CASE (instrument_classification.py:31-49) | global | row corrections + re-derive (UH:2476-2530) |
| coupon_type | SB:2844-2852 tags; SB:3007-3017 text | member (spread/rate text, "floating/sofr/prime" words) | rule on tag presence, then regex | global | iXBRL overlay Fixed (HB:1432-1443); row corrections |
| reference_rate_type | SB:2983-2993 | XBRL tag text; member; report_date | tag, else regex on member, else date guess if spread tagged | global; overlay uses per-fund codes/columns | html section bridge (SB:3309); iXBRL overlay fill/replace/withdraw (HB:1347-1431); row corrections |
| reference_rate_source | SB:2994-3006 | provenance of above | labels | global | HB:728, HB:1360, 1381, 1388, 1422, 1431; row corrections |
| basis_spread | SB:2967-2972 | tag; member | tag rescale; regex `<bench> + n` | global | iXBRL overlay fixed-coupon null / cash+PIK sum (HB:1399-1418, 1448-1463); Agent A corrections (disabled); row corrections; promoted rules; FC margin_from_pik (FC:315) |
| basis_spread_source | SB:2973-2976 | provenance | labels | global | `identifier_spread_corrections` (disabled). Not updated by the overlay or FC |
| basis_spread_kind | FC:316 | none | `coalesce(nullif(x,''),'unresolved')` | global | nothing; no producer sets it |
| interest_rate (identifier_text) | SB:2903-2914, 2955-2966 | member | regex: "Fixed interest rate n%", "Floor rate n%", "Interest Rate n%" | global | overlay `from_spread_tag` (HB:1416); whole-coupon mark (affects kind); row corrections; promoted; FC all-in conversion (FC:279-302) |
| pik_rate_source | SB:3141-3143 | provenance | tag, else `identifier_text` | global | not updated by any later step |
| maturity_date_source | SB:3063-3070 | provenance | tag / printed_page / identifier_text | global | HB:723 `html_section_bridge`; HB:1360 `ixbrl_field_status` |
| maturity_precision | FC:268-275 | `maturity_precision` column, src_facts raw, source label | rules | global | row corrections can set it before FC |
| extracted_industry | SB:3190-3191 (printed rows / `_hier_industry` only); overlay heading SB:3335 (HB:1326-1346); LLM lookup UH:1489-1515 | printed heading above row; member (some filers); LLM output | heading reader; regex; cached GPT-4o-mini extraction | global; Apollo `industry_from_identifier_re`; HPS/Apollo `printed_industry_labels` | row corrections (UH:1532); `_apply_printed_industry` cleanup/withdraw/fill (UH:571-668) |
| gics_sub_industry | SB:3192 blank; GICS name cache UH:1606 | issuer_name, filed name, canonical_name | cached LLM label by normalised company name | global | printed industry map (UH:1610); HPS carry-back (UH:1613); RE-fund remap (UH:1630) |
| gics_sector | FC:327, 332 | gics_sub_industry | lookup in `gics_hierarchy.json` | global | nothing after |
| nonaccrual_footnote | extraction bdc_filings.py:1189-1204 | XBRL footnote text linked to the row's facts | regex classifier | global | row corrections (UH:2440-2451) |
| nonaccrual_dimension | bdc_filings.py:1173-1176, 1204 | investment_type, affiliation, dimensions_raw (incl. member text) | substring "nonaccrual" after stripping non-alphanumerics | global | none |
| nonaccrual_status | FC:325-326 | the two flags | rule | global | none |
| is_subsidiary | SB:3169-3170; recomputed in `accounting_scope.annotate` (accounting_scope.py:50) | dimensions_raw (axis names, member segments, appended detached label) | scope expression | global plus wrapper keys (BCRED JV labels, HPS detached schedules) | promoted B2 `layer_exclusion` selects on it; annotate recomputes |
| accounting_record_class | accounting_scope.py:51-55 | accounting_scope_id | rule | global plus same wrapper keys | none |

## 2. Field details

### 2.1 Member text before parsing
- Extraction `_parse_xbrl_contexts` (bdc_filings.py:550-686). `investment_identifier` = typed member text of any dimension whose local name contains `investmentidentifier` or `investmentcompany` (bdc_filings.py:169, 605-607). Falls back to a company axis member, NexPoint/explicit-member tables, or a cash-axis member (638-674).
- Same function keeps explicit members: `industry` (axis name contains `industr`), `investment_type` (`investmenttype`/`investmentinstrument`), `affiliation`. These are raw local names, for example `FirstLienSeniorSecuredMember`, not humanised (bdc_filings.py:616-626, 517-529).
- `dimensions_raw` = `axis=value|axis=value`; the typed member text is inside it (bdc_filings.py:603, 682).
- Wrapper `source_encodings.relabelled_contexts` renames listed contexts' member text in one filing (page_labelled_contexts.py:189-232, called at bdc_filings.py:698-703). Blue Owl lists about 200 contexts for 0001812554-26-000027.
- Staging Phase A strips affiliation prefixes/suffixes from the member (SB:1862-1897; regexes bdc_identifier.py:224-283), for example `" | Non-Affiliated Issuer"`.

### 2.2 issuer_name and instrument_description
Order of the CASE in SB Phase B (first match wins):
1. Printed-row declaration (`source_encodings.printed_rows_without_context`; none of the five use it).
2. Wrapper `staging.strategy = hierarchy_extract` (SB:1383-1456): `regexp_extract(clean_member, hierarchy_issuer_re / hierarchy_instrument_re, 1)` when `hierarchy_condition_extra` matches. Used by Ares and Apollo.
3. Pipe formats (SB:2155-2212, 2230, 2352-2381): 2 segments -> issuer seg1, instrument seg2; 3+ segments with affiliation tag last; legal-suffix tests; default 3+ -> issuer seg3 ("SLR").
4. Leaf-guard, MSD, industry-prefix, percent-prefix (PennantPark, Saratoga, Goldman) branches (SB:2235-2342, 2382-2460). None of the five's wrappers opt into these; the industry-prefix branch is global (`_INDUSTRY_LABELS`, CL:11).
5. No `" - "` in member: issuer = whole member, instrument = `''` (SB:2142, 2462).
6. Default: issuer = first `" - "` segment, instrument = rest, leading amount stripped (SB:2464-2467).

Then:
- Exact-key bridges: `staging.issuer_bridges` and HTML-section bridges (SB:2498-2546). Keys are cik + report_date (+ accession) + lower member.
- Bad-name fix (SB:2553-2570): a generic or letterless name with entity words in the member becomes the whole member; otherwise the row is dropped.
- `_sql_normalize_name` (CL:651-667) at SB:2934; casing vote per CIK (SB:3257-3282).
- At the tail of UH, after classification and corrections:
  - `_issuer_from_identifier` (UH:2116-2147), wrapper `dispatch.issuer_from_identifier`. None of the five.
  - `_strip_issuer_names` (UH:2150-2183), wrapper `dispatch.issuer_name_strip_re`; with `issuer_name_strip_to_instrument` the removed text fills a blank instrument or is prefixed to it.
  - `_strip_instrument_text` (UH:2186-2207), wrapper `instrument_description_strip_re` (+ `_may_empty`).
  - Global split `issuer_instrument_split.split_issuer_instrument` (issuer_instrument_split.py:68-140), on (data/reference/issuer_instrument_split.json `enabled: true`). Cuts at the first `", "` or `" - "` followed by an instrument phrase.

Per fund:
- BCRED (0001803498): no `staging` block, so the generic parser. Member `Issuer N | Non-Affiliated Issuer` -> suffix stripped -> no pipe, no dash -> issuer = whole text, instrument blank. `Issuer N | Emerald JV LP` -> two_pipe -> instrument = `Emerald JV LP`, then `instrument_description_strip_re` + `may_empty` blanks it. `issuer_name_strip_re` removes JV labels and a trailing 1-2 digit row number.
- Blue Owl (0001812554): generic parser; members `Issuer | Instrument [| affiliation]` -> two_pipe. `issuer_name_strip_re` (long instrument-word list after a comma) + `issuer_name_strip_to_instrument: true`.
- Ares (0001287750): `staging.hierarchy_extract`; issuer = text before the last `", "` or `" | "` segment, instrument = that last segment, only when it contains an instrument word (loan, notes, units, stock, shares, interests, ...). `identifier_format` `", "` also puts Ares in single-child rollup detection (SB:2024-2060) and the raw-member position key (SB:3197-3203). `issuer_name_strip_re` + `to_instrument` for names without a comma; `instrument_description_strip_re` removes a doubled "First lien senior secured loan".
- HPS (0001838126): generic parser. `issuer_name_strip_re` = trailing ` \d{1,2}`.
- Apollo (0001837532): `staging.hierarchy_extract`; issuer = text after an optional industry label (`MSD_INDUSTRY_LABELS` placeholder + `extra_industry_labels`) and before "Investment Type"/"Security Type"/a lien-type phrase; instrument = from the lien-type phrase to the end, so it keeps "Reference Rate and Spread ... Interest Rate ... Maturity Date ..." text. `issuer_name_strip_re` removes a leading brand word where the legal name follows (lookahead list).

### 2.3 asset_category
SB:890 builds `CL._sql_classify_bdc_asset` (CL:411-466). Order:
1. `investment_type` member (lowercased CamelCase local name): fund keywords -> FUND; loan keywords -> LOAN; `equity|stock|shares|warrant` substring -> EQUITY_COMMON.
2. `instrument_description`, then the member: loan keywords (CL:139-148) -> LOAN; fund keywords or `\bfunds?\b` -> FUND; `preferred` -> EQUITY_PREFERRED; equity keywords (CL:150-157) or `series [a-f]` -> EQUITY_COMMON.
3. Wrapper `equity_instrument_labels` exact match on the whole instrument text (source_encodings.py:379-392) -> EQUITY_COMMON. Blue Owl: "LLC interest", "Investment partnership".
4. Numeric heuristic: interest rate, spread or principal present -> LOAN; shares -> EQUITY_COMMON; else OTHER.

Then:
- Named co-invest (CL:548-572, SB:2769-2784): FUND rows whose issuer has a company marker plus co-invest/LP-interest words -> EQUITY_PREFERRED/EQUITY_COMMON, issuer_category CORPORATE.
- Cash (SB:2798-2832): money-market keywords, wrapper `non_private_markers`/`cash_identifiers`, or a `CashAndCashEquivalents` axis -> CASH if the text names a cash vehicle; otherwise the row is dropped.
- `par_tagged_as_units` mode `listed_rows_without_instrument` (HPS, filing 0001628280-26-033248): EQUITY_COMMON rows with a count, no principal, no instrument text and no equity word -> LOAN (SB:917, 2839; source_encodings.py:497-526).
- Later: `printed_sections` sets EQUITY_COMMON only under a wrapper `equity_re` heading (printed_sections.py:143-145); BCRED declares no `equity_re`. Row corrections may set it (UH:2217). No other step re-derives it.

### 2.4 issuer_category
SB:2743-2755: FUND if asset_category FUND, or equity/OTHER and issuer name contains "asset management" in its first 30 characters or "senior loan program" (CL:216-222, SB:1590-1606); else CORPORATE. Co-invest step forces CORPORATE. GOVERNMENT only comes from N-PORT. Row corrections may set it.

### 2.5 index_classification, exposure_type, asset_class
Computed once at the BDC/N-PORT union (UH:1224-1243) on `_combined_fund_text = lower(issuer_name) || ' ' || lower(instrument_description)` plus asset_category, issuer_category (`nport_asset_cat` is blank on BDC rows).
- index (CL:523-545): CASH category -> CASH; CLO keywords (`"clo "`, `" clo,"`, `"clo/"`, "subordinated note", ...) -> STRUCTURED_CREDIT; cash keywords -> CASH; LOAN + CORPORATE -> DIRECT_LENDING; real-estate keywords -> DIRECT_REAL_ESTATE; preferred/common + CORPORATE -> PREFERRED_EQUITY/COMMON_EQUITY; FUND rows by keyword counts (credit vs PE signals); else UNCLASSIFIED.
- exposure (CL:585-592): LIQUID / FUND / DIRECT.
- asset_class (CL:629-648): CASH / REAL_ESTATE / STRUCTURED_CREDIT / PRIVATE_CREDIT / PRIVATE_EQUITY / HEDGE_FUND / OTHER.
- Same SELECT nulls principal fields for equity and fund classes (UH:1346-1360) and keeps lien only for DIRECT_LENDING (UH:1364).

Later writers, in order:
1. `_stabilize_classification` (UH:220-334): per cik + source + normalised issuer + instrument + asset_category + issuer_category, the majority value wins where it has at least twice the quarters of the runner-up. All three fields.
2. `_restore_deterministic_classification_rules` (UH:337-405): rows with a CLO keyword or a "bdc" fund name get index/asset_class/lien recomputed.
3. `apply_structured_sections` (printed_sections.py:113-162): opted-in funds (BCRED: `dispatch.structured_credit_sections`, `structured_re = ^structured finance obligations`). Each current-period FV fact's contextRef is assigned the last top-level heading above it on the cached page; under the structured heading -> index STRUCTURED_CREDIT, asset_class STRUCTURED_CREDIT, lien null.
4. Row corrections (UH:2290-2473): index, exposure, asset_class, asset_category, issuer_category are correctable fields (UH:2211-2251).
5. Fund-strategy correction candidates (UH:1779-1817; `proposed_index_classification`, `proposed_asset_class`).
6. RE-strategy override sets asset_class REAL_ESTATE for funds marked REAL_ESTATE (UH:1824-1887).
7. Promoted B2 corrections and investigator rules (UH:1545-1556; `agent_b2_appliers.apply_classification_fix`, agent_b2_appliers.py:253-277).
8. `_apply_unclassified_cache` (UH:801-945): UNCLASSIFIED rows only, keyed by normalised issuer name, from `unclassified_review_cache.csv` (agent verdicts).

### 2.6 lien_position
- Staging sets `''` (SB:3193). The iXBRL overlay may fill it blank-only from `lien_position` with `lien_status = value` (HB:1347-1353).
- The artifact's lien: printed section heading (`_SECTION_PATTERNS`, HB:198-219) classified by `classify_lien`; if the page has no lien sections, the row's printed cells are scanned with the same keywords (HB:1645-1650). Cleared when one member prints on two rows with different tiers (HB:1723-1724). Downgraded to `validation_needed` (not applied) when the tier's rows do not sum to the filer's lien subtotal within max(5M, 5 pct) (HB:1107-1113, 1135-1138, 1165-1192).
- Union step (UH:1239): `COALESCE(keyword lien, staged lien)`. Keywords (lien_classification.py:46-105) on issuer+instrument and on the member: second lien > unsecured/subordinat/mezzanine > first lien/senior secured/unitranche/one stop/... Kept only for DIRECT_LENDING (UH:1364).
- Then: restore step recomputes from keywords only for restored rows (UH:387-391); printed sections null for structured rows; row corrections (explicit value or re-derived from corrected text, UH:2476-2530); `lien_cache.csv` by normalised issuer+instrument text, DIRECT_LENDING blanks only (lien_classification.py:245-318); `dispatch.lien_from_identifier` (UH:2092-2113), LOAN blanks only. HPS: `{"First Lien": "^(?i:trugreen limited partnership)$"}`.

### 2.7 instrument_type
Staging `''` (SB:3194). Union step (UH:1242): keyword CASE on issuer+instrument and member: delayed draw/ddtl -> "Delayed Draw Term Loan"; revolver/revolving -> "Revolver"; unitranche; term loan (instrument_classification.py:25-49). All rows, not only loans. Row corrections may set it or re-derive it from corrected text (UH:2505-2517). Global.

### 2.8 coupon_type
1. SB:2844-2852: tagged spread -> Floating; else tagged rate -> Fixed; else `''`.
2. SB:3007-3017: Fixed + text spread -> Floating; keep non-blank; text spread -> Floating; text rate and the member names `variable|floating|sofr|libor|prime` -> Floating; text rate -> Fixed.
3. iXBRL overlay (HB:1432-1443): `reference_rate_status = not_applicable`, row has interest_rate or pik_rate (or the spread was moved to the rate), asset_category LOAN, and (coupon and reference rate both blank, or the reference rate was just withdrawn and coupon is Floating) -> Fixed.
4. Row corrections.

### 2.9 reference_rate_type and reference_rate_source
1. Extraction: concept local name containing `investmentreferencerateandspread` -> stored as the raw fact text, not parsed (bdc_filings.py:97, 1106-1107).
2. SB:2983-3006: tag text; else member regex `\bsofr\b`, `\blibor\b`, `\bprime\b`, `S + d`, `L + d`, `E + d` (SB:2859-2867); else, if a spread is tagged and the member does not name euribor/sonia/eur/gbp/sterling, `SOFR` for report_date >= 2023-07-01 and `LIBOR` before. Source: `printed_page`, `xbrl_field`, `identifier_text`, `inferred_post_libor` / `inferred_pre_libor`.
3. HTML section bridge overlay, blank only, source `html_section_bridge` (HB:651-730).
4. iXBRL overlay (HB:1347-1431):
   - blank-only fill from a `value` status, source `ixbrl_field_status`;
   - funds with `reference_rate_columns` (all five): a printed code replaces an inferred or identifier_text value that differs; an inferred value the page confirms is relabelled `ixbrl_field_status`;
   - `not_applicable` status withdraws an inferred value (unless spread and rate tags disagree);
   - `unspecified` status (Ares `unspecified_reference_labels: "Base Rate"`) withdraws inferred and identifier_text values.
   - The artifact's value: `field_status` (HB:563-636). For a named column only that column is read; `_filer_leading_code`, `_extract_reference_rate` (HB:99-112) and `_benchmark_from_code` (HB:134-149) map the cell, filer codes first (`reference_rate_codes`, dated "to/from" codes, source_encodings.py:214-249).
5. Row corrections (reference_rate_type, reference_rate_source correctable).

Per fund `reference_rate_columns` / codes: BCRED "Reference Rate and Spread" (S=SONIA, C=CDOR, CA=CORRA, ...); Blue Owl "Interest", "Ref. Rate" (SR=SOFR, SA=SONIA, C dated CDOR/CORRA, ...); Ares "Reference" (CDOR, NIBOR, BBSY, BKBM, TONA) + "Base Rate" unspecified; HPS "Reference Rate and Spread" (SN=SONIA, dated C, B, ...); Apollo "Interest Rate" (C=CORRA, BBSW).

### 2.10 basis_spread, basis_spread_source, basis_spread_kind
1. SB:2967-2976: tag (`<=0.50` x100, `>=50` /100, negative -> null); else member regex `(SOFR|LIBOR|PRIME|EURIBOR|SONIA|CORRA)\s*\+\s*n` or `\b[SLE]\s*\+\s*n`, values >= 25 divided by 100 (SB:2894-2902). Source `printed_page` / `xbrl_field` / `identifier_text`.
2. iXBRL overlay (HB:1399-1418): named-column fund, `not_applicable`, LOAN, spread > 0 and equal to the rate (or no rate): spread nulled (`basis_spread:fixed_coupon`); with no rate the spread becomes interest_rate (`interest_rate:from_spread_tag`).
3. iXBRL overlay (HB:1448-1463): funds with `printed_margin_reading` (Blue Owl, Apollo): spread = spread + pik where the printed margin equals that sum (`basis_spread:cash_plus_pik_margin`). Printed margin read by `printed_margin` (HB:436-466).
4. Agent A spread overrides: `APPLY_IDENTIFIER_SPREAD_OVERRIDES = False` (identifier_spread_corrections.py:22-23).
5. Row corrections; promoted rate rescale / source-anchored values.
6. FC `margin_from_pik` (FC:177-179, 204, 315): funds with `pik_only_tag_reading` containing `margin` (Blue Owl, HPS), LOAN, reference rate known, no rate and no spread, pik > 0 -> basis_spread = pik.
- `basis_spread_kind`: FC:316 only, `'unresolved'` unless already set. No module sets it (grep: only FC, financial_validation.py, output_schemas.py).

### 2.11 interest_rate with source `identifier_text`
See section 3.2.

### 2.12 pik_rate_source
SB:3141-3143: `xbrl_field` if a PIK tag >= 0; `identifier_text` if no tag and the member matches `(\d+\.?\d*)%\s*PIK` or `+PIK (Fixed) Interest Rate n%` (SB:2915-2921). No `printed_page` branch. Not updated by the /100 boundary fix (SB:3237-3251), `whole_coupon_pik` (whole_coupon_pik.py:146), promoted rules or corrections.

### 2.13 maturity_date_source and maturity_precision
- SB:3026-3070: valid tag (1950 <= date, year < 2099) -> `xbrl_field` (or `printed_page`); tag present but invalid -> blank date; else member/instrument text `M/D/YY(YY) Maturity`, `Maturity|Due [Date] M/D/YY`, then month forms `due M/YYYY`, `Maturity/Dissolution Date M/YYYY` (last day of month), source `identifier_text` (SB:2868-2893).
- Overlays fill blanks: `html_section_bridge` (HB:720-724), `ixbrl_field_status` (HB:1347-1360). The artifact maturity must be after report_date (HB:639-648).
- Row corrections may set `maturity_date` and `maturity_precision`; the source column is not correctable, so it keeps its earlier label.
- FC:268-275 precision: explicit `maturity_precision`; else `src_facts.maturity_date.r` pattern (YYYY-MM -> month, YYYY -> year, full -> day); else `day` only when source in (`xbrl_field`, `nport`, `printed_page`) and the date parses; else `unknown`. `maturity_status` FC:320-324.

### 2.14 extracted_industry, gics_sub_industry, gics_sector
Order:
1. SB:3190-3191: printed-row declaration, else `_hier_industry` (only for wrappers with `identifier_parser.type = hierarchical_pct`; none of the five). The XBRL industry axis member (`industry` column) is loaded (SB:729) but not used for this field.
2. iXBRL overlay (HB:1326-1346): the heading printed above the row (artifact column `gics_sector` with `sector_status = value`; it holds the heading text, not a GICS sector). Heading = last lone non-numeric, non-total row (HB:1603-1611), lone "Interest" ignored. Rejected when it matches `_NOT_AN_INDUSTRY_RE` (HB:1200-1207) or one heading covers over half of a filing's rows (>= 20 rows). Blank-only.
3. UH:1489-1515: blank rows filled from `identifier_extraction_lookup.csv`, keyed by member text. That cache is written by `pipeline/identifier_extraction.py` from GPT-4o-mini output (identifier_extraction.py:1-13, 248).
4. Row corrections may set it (UH:2226).
5. `_apply_gics_cache` (UH:508-535 -> gics_classification.py:668-772): gics_sub_industry from `company_gics_cache.csv` (LLM labels) by normalised issuer name, then the filed name, then canonical_name. Overwrites the column.
6. `_apply_printed_industry` (UH:571-668): strips a trailing "Interest Rate ..." tail; fills blanks from `dispatch.industry_from_identifier_re` (Apollo), rare unmapped catches (< 20 rows) refused; maps labels to GICS (alias table, exact GICS name, label cache, wrapper `industry_label_gics`); in a filing where >= 20 labelled rows and under half map, unmapped labels are blanked except wrapper `printed_industry_labels` (HPS ICB list; Apollo "Asset Backed Securities", "Financing", "Special Purpose Entity"); mapped labels replace gics_sub_industry.
7. `_carry_back_gics_industry` (UH:683-761): HPS only (`gics_industry_carry_back: through 2025-09-30`): earlier quarters take the GICS mapping of the company's single later printed GICS industry.
8. `_apply_re_fund_gics_overrides` (UH:1630, map UH:1895-1907): RE-strategy funds only.
9. FC:327, 332: `gics_sector` = parent sector of gics_sub_industry from `gics_hierarchy.json`.

### 2.15 Non-accrual
- `nonaccrual_dimension` (nonaccrual_evidence.py:164-173): investment context whose `investment_type + affiliation + dimensions_raw`, lowercased with non-alphanumerics removed, contains `nonaccrual`.
- `nonaccrual_footnote` (bdc_filings.py:1179-1198; nonaccrual_evidence.py:129-154, 176-206): XBRL footnote linked by arc to any fact of the context; text must match `non-accrual`, not exclusion/negation, not a structural or count footnote, any "as of <date>" must equal report_date, and must match a positive phrase (`placed on non-accrual`, `non-accrual status`, ...). The printed footnote marker on the HTML page is not read.
- OR-merged across duplicate contexts (bdc_filings.py:1395-1405). Staging casts to boolean (SB:3166-3167). Row corrections may set `nonaccrual_footnote` (UH:2440-2451).
- `nonaccrual_status` (FC:325-326): `nonaccrual` if either flag; else keeps `accrual_confirmed`/`not_applicable` if present; else `unknown`. No module sets `accrual_confirmed` (grep), so the output is `nonaccrual` or `unknown`.

### 2.16 is_subsidiary and accounting_record_class
- Before parsing, `tag_detached_schedules` (source_encodings.py:631-683, called SB:799-802) appends ` | <label>` to `dimensions_raw` for contexts after the first context-number gap >= 200 in a filing. HPS: `detached_schedule_labels: "joint venture schedule"`.
- Staging scope (SB:2124-2129, accounting_scope.py:15-29): underlying if any axis name matches `nonconsolidatedsubsidiar|equitymethodinvestmentequitymethodinvesteenameaxis`, or `reporting_suffix_expression` (source_encodings.py:541-608) finds a wrapper label among the later `dimensions_raw` segments, a `legal_entity_members` axis member, or (BCRED legacy) the JV label inside the member text by regex. `is_subsidiary` = 0 for `|parent` scope, else 1 (SB:3169-3170).
- `accounting_scope.annotate` (accounting_scope.py:32-56), run in `prepare_artifact` after FC, recomputes scope from `bdc_dimensions_raw` and the current `is_subsidiary`, rewrites `is_subsidiary`, and sets `accounting_record_class` = `parent_schedule` / `unresolved_underlying_schedule` / `underlying_schedule`.
- BCRED keys: `legal_entity_members` (BCREDEmeraldJVLPMember, BCREDVerdeliteJVLPMember), `reporting_entity_suffixes`, `reporting_entity_identifier_suffixes` ("Emerald JV LP", "Verdelite JV LP"). HPS: `detached_schedule_labels`. Blue Owl, Ares, Apollo: none of these keys (global axis test only).

## 3. Specific answers

### 3.1 asset_category = LOAN and the "PIK is the whole coupon" reading
asset_category = LOAN (SB:2737-2741, CL:411-466), first match wins:
1. InvestmentType member name contains a loan keyword. The member is CamelCase without spaces, so only one-word keywords can match (`subordinated`, `mezzanine`, `unitranche`, `revolving`, `revolver`); fund and equity tests run before and after it.
2. instrument_description contains a loan keyword (CL:139-148: first lien, second lien, term loan, senior secured, secured debt, revolving, delayed draw, subordinated, unitranche, ...).
3. Same keywords in the member.
4. No equity/fund/preferred keyword in 2-3, no wrapper equity label, and the row has a nonzero tagged interest rate, spread or principal.
5. HPS listed filing: EQUITY_COMMON with count-as-par -> LOAN (SB:2839).

PIK readings in FC (all at FC:168-237):
- `pik_is_coupon` (FC:171-176): cik in `pik_only_tag_reading` containing `coupon` (Blue Owl, Ares, HPS, Apollo; not BCRED) AND asset_category = LOAN AND (cik not in the `margin` set OR (lower(coupon_type) = 'fixed' AND reference_rate_type blank)).
- `pik_is_margin` (FC:177-179): cik in the `margin` set (Blue Owl, HPS) AND LOAN AND reference_rate_type non-blank.
- `rate_kind = 'all_in'` from PIK alone (FC:235-236): `pik_is_coupon` AND no reported rate AND no spread AND pik > 0. Then `interest_rate = pik` (FC:280), src_transforms `interest_rate:pik_only` (FC:311).
- `margin_from_pik` (FC:204): `pik_is_margin` AND no rate AND no spread AND pik > 0 -> basis_spread = pik (FC:315).

Where "the page prints a fixed coupon with no reference rate" is tested:
- Not in FC itself. FC reads `coupon_type = 'Fixed'` and a blank `reference_rate_type`, set earlier.
- The page test is `HB.field_status` for `reference_rate_type` (HB:583-603): for a fund with `reference_rate_columns`, find header cells whose normalised label is in that list (HB:427-433, 585-586); if every such cell is empty or `N/A` (`_NOT_APPLICABLE_RE`, HB:470), and no cell starts with a filer code (shifted-column rescue, HB:593-600), and `_extract_reference_rate` finds no benchmark anywhere in the row (HB:99-112), and no cell is a bare code like `SR +` (HB:472) -> status `not_applicable`.
- Input text: the colspan-expanded cell texts of the inline-XBRL `<tr>` whose InvestmentOwnedAtFairValue fact has the row's current-period context (HB:1571-1643), with the header row map from the last detected header row (HB:495-512, 1579-1582).
- Consumers: the overlay sets coupon_type Fixed for LOAN rows with a rate or PIK (HB:1432-1443), withdraws an inferred reference rate (HB:1419-1422), and moves/nulls a spread that is the coupon (HB:1399-1418). A member printed on two rows with different readings is downgraded to `validation_needed` (HB:1717-1718).
- A tagged spread on such a row: staging set coupon Floating and inferred SOFR/LIBOR; the overlay withdraws the guess and, because `withdrawn & coupon_type = Floating`, sets Fixed.

Related, HPS only: `pik_margin_reading: whole_coupon` (whole_coupon_pik.py:104-163). Reads the artifact's `printed_row` text for `<bench> + m PIK c %` forms; on LOAN rows whose rate tag equals the printed coupon, pik_rate := interest_rate and `pik_rate:whole_coupon_printed` is added; FC then reads `all_in` (FC:217). Three contexts are excluded in the wrapper.

### 3.2 How `interest_rate_source = 'identifier_text'` rows get their rate
1. Only when no rate fact was extracted (`_ir IS NULL`) (SB:2959, 2965). A tagged rate always wins.
2. `_text_interest_rate` (SB:2905-2914), first match on the member text (`_raw_id`, not instrument_description):
   - `(?i)\bFixed\s+interest\s+rate\s+(\d+\.?\d*)%`
   - `(?i)\bFloor\s+rate\s+(\d+\.?\d*)%`
   - `(?i)\bInterest\s+Rate\s+(\d+\.?\d*)%`, skipped if the member contains `+PIK (Fixed) Interest Rate`.
3. Apollo label "... Interest Rate 13.00% PIK Maturity Date 9/24/2033":
   - interest_rate = 13.00, source `identifier_text`.
   - pik_rate: if no PIK fact, `(\d+\.?\d*)%\s*PIK` -> 13.00, source `identifier_text` (SB:2916-2921).
   - coupon_type: Fixed unless the member also has a spread text (`S + n`) or names sofr/libor/prime/variable/floating (SB:3007-3017).
   - maturity 2033-09-24, source `identifier_text`.
4. Overlays may then change the row (HB:1399-1443) as in 3.1.
5. FC (FC:214-237): `rate_concept` is blank for a text rate (no `src_facts.interest_rate` entry), so:
   - no PIK and no PIK word in member/instrument -> `all_in`;
   - else Apollo's wrapper `filed_rate_reading: all_in` -> `all_in` unless pik > rate + 0.01. For the example: pik 13 = rate 13 -> `all_in`, interest_rate 13.00, interest_rate_cash 0 (FC:279-284).
   - Blue Owl has no `filed_rate_reading`; a text rate with a PIK there stays `unresolved` and interest_rate becomes null (FC:302, 314).
6. `interest_rate_reported` keeps the text value (FC:301).

### 3.3 reference_rate_type and basis_spread when not tagged
- reference_rate_type: member regex (SOFR/LIBOR/PRIME words, `S/L/E + digit`), else a date-based guess when a spread tag exists, then replaced/confirmed/withdrawn by the printed reference-rate column for the five funds (details 2.9). No basis-spread text is used to pick the benchmark except through `S/L/E +`.
- basis_spread: member regex `<benchmark word> + n` or `[SLE] + n`, n >= 25 read as basis points (SB:2897-2902). Not read from instrument_description separately (Apollo's instrument text is part of the member anyway). Not read from the printed page except: the cash+PIK sum (Blue Owl, Apollo) and the spread-is-coupon null (HB:1399-1463), and FC's PIK-as-margin (Blue Owl, HPS).

## 4. Dependency order (as run)
1. Extraction: member text, explicit members, dimensions_raw, rate/maturity/reference-rate facts, non-accrual flags (bdc_filings.py). Wrapper `relabelled_contexts` rename members.
2. SB Phase A: detached-schedule label appended (HPS); affiliation stripping; aggregate/rollup row filters keyed on member text.
3. SB Phase B: issuer_name, instrument_description (wrapper `staging` regex for Ares, Apollo); bridges; bad-name fix; affiliation dedup keyed on issuer+instrument text; `is_subsidiary` scope.
4. SB Phase C: asset_category (needs instrument_description, member, investment_type, numeric presence) -> issuer_category (needs asset_category, issuer_name) -> co-invest re-class -> cash re-class/drop -> unclassed LOAN fix -> coupon_type (tags) -> text rate/spread/reference/maturity/PIK -> interest_rate, basis_spread, reference_rate_type (inference needs spread + report_date), coupon_type (text), pik_rate, maturity -> issuer casing.
5. Staging overlays: HTML bridge (maturity, reference rate) -> iXBRL overlay (industry heading, maturity, reference rate, lien; fixed-coupon reading needs asset_category LOAN + rates; cash+PIK spread) -> whole-coupon PIK (needs asset_category LOAN, rate, pik, spread; HPS) -> Agent A spreads (off).
6. UH union: dedup keyed on issuer+instrument text -> index_classification (needs asset_category, issuer_category, text) -> exposure_type, asset_class -> lien (keyword, else overlay; kept only if DIRECT_LENDING) -> instrument_type -> principal nulled by index class.
7. extracted_industry from LLM lookup (blanks).
8. Stabilisation (keys include asset_category, issuer_category) -> deterministic restore.
9. Printed sections (BCRED structured credit).
10. Row corrections (+ instrument_type/lien re-derive from corrected text).
11. Fund-strategy corrections -> RE asset_class override.
12. Promoted B2 corrections and investigator rules.
13. Issuer/instrument text cleanup: issuer_from_identifier -> issuer_name_strip_re (+ to_instrument) -> instrument_description_strip_re -> global split.
14. Entity resolution -> GICS name cache -> printed industry mapping (needs extracted_industry, index_classification) -> HPS carry-back.
15. Lien cache (needs index DIRECT_LENDING, issuer+instrument text) -> lien_from_identifier (needs asset_category LOAN).
16. Unclassified cache (needs index UNCLASSIFIED, issuer name) -> RE-fund GICS remap.
17. FC: rate kind (needs asset_category, coupon_type, reference_rate_type, member/instrument PIK words, wrapper readings) -> interest_rate, interest_rate_cash, basis_spread (PIK margin), basis_spread_kind, maturity_precision/status, nonaccrual_status, gics_sector (needs gics_sub_industry).
18. accounting_scope.annotate: is_subsidiary recomputed, accounting_record_class.

## 5. Fund-specific drivers (wrapper keys that touch these fields)
- BCRED: `dispatch.issuer_name_strip_re`, `instrument_description_strip_re`, `instrument_description_strip_may_empty`, `structured_credit_sections`; `source_encodings.filed_rate_reading` (all_in), `reference_rate_columns`, `reference_rate_codes`, `legal_entity_members`, `reporting_entity_suffixes`, `reporting_entity_identifier_suffixes`, `cash_identifiers`, `par_tagged_as_units` (rows_within_twice_cost).
- Blue Owl: `dispatch.issuer_name_strip_re`, `issuer_name_strip_to_instrument`; `source_encodings.pik_only_tag_reading` (coupon, margin), `printed_margin_reading` (cash_plus_pik), `reference_rate_columns`, `reference_rate_codes`, `equity_instrument_labels`, `relabelled_contexts`, `par_tagged_as_units`, `units_tagged_as_par`. No `filed_rate_reading`.
- Ares: `staging` (hierarchy_extract regexes), `identifier_format`; `dispatch.issuer_name_strip_re`, `issuer_name_strip_to_instrument`, `instrument_description_strip_re`; `source_encodings.filed_rate_reading`, `pik_only_tag_reading` (coupon), `reference_rate_columns`, `reference_rate_codes`, `unspecified_reference_labels`, `rate_only_contexts`, `par_tagged_as_units` (rated_rows_near_cost).
- HPS: `dispatch.issuer_name_strip_re`, `lien_from_identifier`; `source_encodings.filed_rate_reading`, `pik_only_tag_reading` (coupon, margin), `pik_margin_reading` (whole_coupon + 3 exclusions), `reference_rate_columns`, `reference_rate_codes`, `detached_schedule_labels`, `gics_industry_carry_back`, `printed_industry_labels`, `par_tagged_as_units` (incl. listed_rows_without_instrument).
- Apollo: `staging` (hierarchy_extract regexes, `extra_industry_labels`); `dispatch.issuer_name_strip_re`, `industry_from_identifier_re`; `source_encodings.filed_rate_reading`, `pik_only_tag_reading` (coupon), `printed_margin_reading`, `reference_rate_columns`, `reference_rate_codes`, `printed_industry_labels`, `cash_identifiers`.
- `canonical_strip_re`, `prefix_rules`, `leaf_markers_by_family`, `category_marker_re`, `flat_schedule` feed position keys and row dispositions (bdc_xbrl_wrapper.py:298-384), not the text fields above.
- Global for all five: index_classification, exposure_type, asset_class, instrument_type, issuer_category, coupon_type rules, non-accrual flags, text regexes for rate/spread/maturity/reference rate.

## 6. Observations (fragile or order-dependent; not fixed)
1. Principal fields are nulled by the index class at the union (UH:1346-1360). Later class changes (stabilise, restore, printed sections, corrections, B2, unclassified cache) do not restore or re-null them.
2. lien_position is nulled for non-DIRECT_LENDING at the union (UH:1364). A later change to DIRECT_LENDING does not bring the keyword or overlay lien back, except the lien cache fill (DIRECT_LENDING blanks) and `lien_from_identifier` (LOAN blanks).
3. The restore step recomputes lien from keywords only (UH:387-391), dropping an overlay (printed section) lien on restored rows.
4. Keyword lien wins over the reconciled printed-section lien (UH:1239 COALESCE order).
5. asset_category and issuer_category are never re-derived after an index_classification correction or B2 class fix; the two can disagree.
6. Classification runs on text before the issuer/instrument strips and global split (UH:1560-1578). Combined-text keywords are mostly unaffected; the lien cache key (issuer+instrument after strips) can differ from the key the cache was built on.
7. `investment_type` is matched as a CamelCase local name (bdc_filings.py:616-624, SB:2728); multi-word loan keywords ("first lien", "senior secured") cannot match there; `contains(_lower_type,'equity')` matches any member name containing "equity".
8. Keywords are plain substrings (`contains`), so they match inside longer words and names: `common` matches "Commonwealth", `shares`/`units` match any name containing them, and `income`/`yield`/`senior` count as credit-fund signals wherever they appear. `"clo "` needs a trailing space, so "CLO" at the end of a name does not match. `\bprime\b` on the member makes "Prime ..." company names PRIME and Floating; the overlay withdraws that only for named-column funds when the page prints a code, N/A or "Base Rate".
9. "Floor rate n%" in the member is read as interest_rate (SB:2908-2909).
10. A text-read rate takes the fund's `filed_rate_reading` (FC:228-229) although that reading was reviewed for the tag. A label like "Interest Rate 8.50% + 4.50% PIK" (hypothetical) would publish 8.50 as all-in.
11. Text pik_rate uses the first `n% PIK` in the member; on Apollo's "Interest Rate 13.00% PIK" the same 13.00 becomes both rate and PIK.
12. Source labels are not updated when values move: `basis_spread_source` after fixed-coupon null, cash+PIK sum or PIK-as-margin; `interest_rate_source` after `from_spread_tag`; `pik_rate_source` after whole-coupon PIK and the /100 boundary fix; `maturity_date_source` after a maturity correction.
13. `basis_spread_kind` has no producer; it is always `unresolved`.
14. `maturity_precision` is `unknown` for full dates from `identifier_text`, `ixbrl_field_status` and `html_section_bridge` (FC:274 lists only xbrl_field, nport, printed_page), so their `maturity_status` is `unresolved`.
15. The reference-rate tag is stored as raw fact text with no parsing (bdc_filings.py:1106-1107).
16. The date-based reference-rate guess uses report_date, not the loan's origination; a tagged spread on a fixed-rate row produces a guess that only the page overlay removes.
17. `nonaccrual_dimension` searches `dimensions_raw`, which includes the member text, so a member containing "non-accrual" in any form sets the flag.
18. `nonaccrual_status` can only be `nonaccrual` or `unknown`; no step writes `accrual_confirmed`.
19. extracted_industry precedence: iXBRL heading, then LLM lookup, then wrapper member regex (Apollo) only on blanks. The LLM value beats the wrapper regex. A corrected extracted_industry (UH:1532) can be blanked later by the weak-filing withdrawal (UH:636-656) if it does not map.
20. `gics_sub_industry` from the name cache is keyed by issuer name across funds; a mapped printed heading replaces it, an unmapped one leaves the name label in place.
21. The XBRL industry axis member is extracted but not used for extracted_industry.
22. `is_subsidiary` for HPS depends on context-number gaps (>= 200) in the filing software's numbering (source_encodings.py:615, 631-683).
23. Several steps key on `issuer_name`/`instrument_description` text to drop rows (SB affiliation dedup, UH dim-path dedup, cross-source dedup), so parser changes can change row counts.
24. Iteration over cache CSVs and wrapper globs is sorted; order-sensitive tie-breaks are documented in code (UH:857-881, HB:1314-1318).
25. `_reclassify_named_fund_positions` (SB:643) has no caller in `pipeline/` or `scripts/`.

## 7. Not determined
- Which of the five file an InvestmentType axis member, and its local names.
- Whether any of the five tag `...ReferenceRateAndSpread...` and in what text form.
- The real member formats per fund and period (for example whether BCRED members ever carry `" - "` instrument text). Data was not read.
- Contents and coverage for these funds of: `identifier_extraction_lookup.csv`, `company_gics_cache.csv`, `lien_cache.csv`, `unclassified_review_cache.csv`, `row_corrections.csv`, `row_corrections_by_context.csv`, promoted B2 corrections and investigator rules, fund-strategy correction candidates, HTML-section bridge files.
- Whether the field-status artifact is current for every filing of the five; staging silently skips the overlay if the file is missing.
- The GICS alias table details inside `pipeline/gics_mapping.py` (not read in full).
- `pipeline/printed_rows.py` (printed rows without context) was not read in detail; none of the five wrappers declare it.
