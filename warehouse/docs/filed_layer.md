# Filed layer: spec (step 2 of the data-model redesign)

Status: written 2026-11-18 by the agent on the owner's "keep going"; the owner is reviewing in parallel.
Decisions made here without the owner are listed in section 7.

## 1. Purpose

Each filing is parsed once into tables that hold what was filed and nothing else. No filer-specific rule,
no classification, no correction. Everything later (which contexts are positions, which column is which
field) reads these tables and never re-opens the raw files.

Scope: the five v0.5 funds, every cached instance file for them (86 files, about 1.6 GB of XML, each with a
cached inline HTML document). The fund list is read from `findings_scope.ciks` in
`data/reference/quarter_acceptance_thresholds.json`.

## 2. Inputs (read-only)

| Input | Path | Use |
|---|---|---|
| XBRL instance | `data/raw/filings/bdc_xbrl/<cik without leading zeros>/<accession, 18 digits>.xml` | contexts, members, units, facts (values already scaled and signed) |
| Inline document | `data/raw/filings/bdc_html/<cik without leading zeros>/<accession, 18 digits>.html` | where each fact is printed: table, row, cell; footnotes |

The two tie on the fact `id` (checked on one Apollo filing: same id in both files).

## 3. Output

```
warehouse/data/filed/cik=<10-digit cik>/accession=<dashed accession>/
    filing.parquet  context.parquet  context_member.parquet  unit.parquet  tagged_fact.parquet
    document_row.parquet  fact_placement.parquet  footnote.parquet  fact_footnote.parquet
    _manifest.json
```

`warehouse/data/` is git-ignored. Accession is stored dashed everywhere (`0001193125-26-215667`), CIK as
10 digits with leading zeros, to match the existing outputs.

Write rules:

1. A filing folder is written to a temporary folder and renamed into place, so a half-written folder never
   exists under its final name.
2. Write-once: if `_manifest.json` exists with the same parser version and the same input hashes, the filing
   is skipped.
3. Same accession, different input hash: stop with an error naming the file. The raw cache changed; a person
   decides. `--reparse` overrides.
4. Different parser version: skipped with a warning unless `--reparse` is given.
5. Rows are written in primary-key order. The same inputs and parser version give the same content hash
   for every table.

## 4. Tables

PK = primary key. Every table carries `accession` (and the folder gives `cik`).

### filing (one row)

| Column | Type | Source |
|---|---|---|
| `accession` | text | file name |
| `cik` | text | folder name, padded |
| `document_type` | text | `dei:DocumentType` |
| `document_period_end_date` | date | `dei:DocumentPeriodEndDate` |
| `amendment_flag` | boolean | `dei:AmendmentFlag` |
| `fiscal_year_focus` | text | `dei:DocumentFiscalYearFocus` |
| `fiscal_period_focus` | text | `dei:DocumentFiscalPeriodFocus` |
| `registrant_name` | text | `dei:EntityRegistrantName` |
| `instance_file`, `instance_sha256`, `instance_bytes` | text, text, bigint | the XML file |
| `html_file`, `html_sha256`, `html_bytes` | text, text, bigint | the HTML file; null if absent |
| `parser_version` | text | constant in the package |

A `dei` value is taken from the fact whose context has no members. If there are several such facts with
different values, the first in document order is used and `dei_conflict` (boolean column) is true.

### context (PK `accession`, `context_id`)

| Column | Type | Source |
|---|---|---|
| `context_id` | text | `id` |
| `entity_scheme`, `entity_identifier` | text | `entity/identifier` |
| `period_type` | text | `instant`, `duration` or `forever` |
| `instant_date`, `start_date`, `end_date` | date | `period` |
| `member_count` | integer | number of dimension members |

### context_member (PK `accession`, `context_id`, `axis`)

| Column | Type | Source |
|---|---|---|
| `member_index` | integer | order in the document, from 0 |
| `axis` | text | `dimension` attribute, as written (`us-gaap:InvestmentIdentifierAxis`) |
| `member_kind` | text | `explicit` or `typed` |
| `member` | text | explicit: the member name as written, trimmed. typed: the full text content of the typed element exactly as filed (no collapsing, no trimming, non-breaking spaces kept) |
| `typed_element` | text | typed only: the element name inside the typed member |
| `container` | text | `segment` or `scenario` |

### unit (PK `accession`, `unit_id`)

| Column | Type | Source |
|---|---|---|
| `numerator` | text | measures as written, joined with `*` |
| `denominator` | text | null unless the unit is a ratio |

### tagged_fact (PK `accession`, `fact_id`)

| Column | Type | Source |
|---|---|---|
| `fact_id` | text | the fact's `id`. If missing: `noid:<fact_index>` and `id_is_synthetic` true |
| `fact_index` | integer | order in the instance, from 0 |
| `id_is_synthetic` | boolean | |
| `concept` | text | prefix and local name as written (`us-gaap:InvestmentOwnedAtFairValue`) |
| `concept_namespace` | text | the namespace address |
| `concept_local` | text | local name |
| `context_id` | text | `contextRef` |
| `unit_id` | text | `unitRef`; null for text facts |
| `value_text` | text | the value as written, trimmed; first 4,000 characters if longer |
| `value_numeric` | decimal(38,10) | the value where it parses as a number and the fact has a unit; else null |
| `decimals`, `precision` | text | as written (`-3`, `INF`) |
| `is_nil` | boolean | `xsi:nil` |
| `value_length` | integer | length of the full value in characters |
| `value_sha256` | text | hash of the full value (UTF-8) |
| `value_truncated` | boolean | true where `value_text` was cut |

Long text blocks (whole notes embedded as text) are most of the bytes in an instance and are not used
downstream; they are cut at 4,000 characters with the length and hash kept. Numeric facts are never cut.

### document_row (PK `accession`, `row_index`)

One printed table row. Kept: every row of every table that contains at least one tagged fact or one element that points at a hidden fact (`fact_placement.shown_row_index`). A row
belongs to its nearest enclosing table.

| Column | Type | Source |
|---|---|---|
| `row_index` | integer | order in the document over kept rows, from 0 |
| `table_index` | integer | order in the document over kept tables, from 0 |
| `row_in_table` | integer | order within the table, from 0 |
| `cell_count` | integer | number of `td`/`th` cells |
| `cells` | list of text | text of each cell, white space collapsed, trimmed; a space is inserted at the edges of `br`, `p`, `div`, `tr`, `td`, `th`, `li` first, so text on separate printed lines is not glued together |
| `cell_colspans` | list of integer | `colspan` of each cell, same length as `cells`; 1 when absent or not a positive integer |
| `cell_rowspans` | list of integer | `rowspan` of each cell, same rule |
| `fact_count` | integer | tagged facts placed in this row |

Rows with no facts are kept on purpose: they are the headings (industry, borrower) that later steps need.
Heading path, row kind and footnote marks are read from these rows by the next layer, not here.

### fact_placement (PK `accession`, `fact_id`)

Where a fact is printed.

| Column | Type | Source |
|---|---|---|
| `fact_id` | text | `id` of the `ix:nonFraction` / `ix:nonNumeric` element; `noid-html:<n>` if missing |
| `placement_index` | integer | order in the document, from 0 |
| `ix_element` | text | `nonFraction` or `nonNumeric` |
| `concept` | text | `name` attribute |
| `context_id` | text | `contextRef` |
| `row_index` | integer | the `document_row` it sits in; null if it is not inside a kept table row |
| `cell_index` | integer | the cell within the row, from 0 |
| `displayed_text` | text | text as printed, white space collapsed (same block-boundary rule as `cells`); first 4,000 characters |
| `scale`, `sign`, `format` | text | attributes as written |
| `in_hidden` | boolean | inside `ix:hidden` |
| `shown_row_index` | integer | row of the printed element whose `style` contains `-sec-ix-hidden:<this fact id>`; null if there is none. If several, the first in document order that sits in a table row |
| `shown_cell_index` | integer | cell of that element within the row. A table holding such an element is a kept table even with no tagged fact |

### footnote (PK `accession`, `footnote_id`) and fact_footnote (PK `accession`, `fact_id`, `footnote_id`)

`footnote`: `footnote_id`, `text` (first 4,000 characters; same block-boundary rule as `cells`), `text_length`, `text_sha256`.
`fact_footnote`: one row per pair in an `ix:relationship` with the fact-footnote arc role.

### _manifest.json

Parser version, the two input hashes and sizes, and per table: row count and content hash. The content
hash is computed from the ordered rows, not from the Parquet file bytes. A `written_at` time is recorded
and is not part of any hash.

## 5. Commands

```
.\warehouse\parse.ps1                      # all five funds; skips filings already parsed
.\warehouse\parse.ps1 --cik 0001837532     # one fund
.\warehouse\parse.ps1 --accession 0001193125-26-215667
.\warehouse\parse.ps1 --verify             # re-parse to a temporary folder, compare hashes, write nothing
.\warehouse\parse.ps1 --reparse            # overwrite (needed after a parser change)
```

One filing at a time, in one process, with a progress line per filing (ASCII). No network.

## 6. Checks (dbt, on every build)

Structure: every primary key unique; fact to context, fact to unit, member to context, placement to row, placement and fact agree on concept and context,
fact-footnote to both sides all resolve; one `filing` row per folder and one manifest per folder; one parser version in all manifests and filing rows; every filing has a document type and period end; manifest row counts equal table
counts for every filing and table (dbt, from the manifests; the parser's `--verify` also compares content hashes).

Bridge to the existing pipeline (measured, recorded as a baseline, with ceilings as in step 1):

| Check | Question |
|---|---|
| Filings covered | Does every accession in `dim_filing` have a filed `filing` row? |
| Context found | Does every published holdings row's accession + `src_context_id` exist in `context`? |
| Fair value equals filed | Does the holdings fair value equal the tagged fair-value fact on that context? Counted separately for rows with and without a recorded correction |
| Placement found | Does every numeric fact in the instance have a placement in the document, and the reverse? |
| Position facts in a row | Share of facts on investment-identifier contexts that sit in a kept table row |

A different count from the baseline is a result to record, not something to fix by changing a test.

"All tests pass" is not "data correct": these checks show the tables are internally consistent, that their
counts tie to the manifests, and where they differ from the old extractor. They do not show that either reading is right.

## 7. Decisions made without the owner (each can be reversed)

| # | Decision | Why | Cost if wrong |
|---|---|---|---|
| 1 | Output under `warehouse/data/filed/`, not `data/filed/` | The agreed relaxation covers `warehouse/` only | Move one folder, change one dbt variable |
| 2 | `schedule_line` of the logical model becomes `document_row` + `fact_placement`; kind, heading path and footnote marks are derived in the next layer | Those need judgement per filer, which this layer must not hold | None if the next layer derives them; the raw rows are kept |
| 3 | `document` is folded into `filing` | One instance and one inline document per filing in the cache | Split out if a filing ever has several documents |
| 4 | Text values longer than 4,000 characters are cut, with length and hash kept | They are most of the bytes and unused | Re-parse with a higher limit |
| 5 | Every cached instance for the five funds is parsed, including small non-periodic filings | Cheaper than deciding which to skip; the filing's own `document_type` says what it is | A few small extra folders |
| 6 | `lxml` and `pytest` installed into `warehouse\.venv` (not the shared Python) | Needed to parse and to test | Two packages in a private environment |
| 7 | Fund-level filing facts (`fund`, `fund_name`, `adviser`) are not built here | Already covered by the step 1 dimensions | None |
| 8 | (parser version 3) Typed members are stored exactly as filed: no collapsing, no trimming, non-breaking spaces kept. Version 2 collapsed white space | Collapsing made distinct filed positions identical (BCRED 0001803498-22-000021, two `Apex Group Treasury, LLC` members). Found in the final review | A normalised copy can be derived downstream; the original cannot be restored |
| 9 | (3) `document_row` gains `cell_colspans` and `cell_rowspans` (integer lists, 1 when absent or not a positive integer) | Which printed column a cell belongs to cannot be worked out from the cell list alone (colspan is used heavily in the latest filings) | Re-parse |
| 10 | (3) A space is inserted at the edges of `br`, `p`, `div`, `tr`, `td`, `th`, `li` before white space is collapsed, in `cells`, `displayed_text` and footnote text | Text on separate printed lines was glued together (`First LienSecured Debt`) | Re-parse. Other elements (for example `span`) are not boundaries |
| 11 | (3) `fact_placement.shown_row_index` and `shown_cell_index` hold the row and cell of the printed element whose `style` has `-sec-ix-hidden:<fact id>`. A table holding such an element is kept | Hidden facts had no printed location; this ties them back to the page | Drop two columns. The style is read by a pattern: an id ends at `;` or white space |
| 12 | (3) dbt matches the investment-identifier axis on its local name (`:InvestmentIdentifierAxis`) and the fair-value concept on local name `InvestmentOwnedAtFairValue` plus a `http://fasb.org/us-gaap/` namespace | Nine filings use `us-gaap-supplement:InvestmentIdentifierAxis`; a prefix match skipped them | Edit the tests. Every filing uses the `us-gaap` prefix for the fair-value concept today |
| 13 | (3) dbt reads the manifests (`stg_filed_manifest`) and tests them: one manifest per filing row, one parser version, row counts equal the tables | A missing or empty table file passed every test; the count check lived only in `--verify` | None |
