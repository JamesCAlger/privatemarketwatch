# Step 2: Filed Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Parse every cached filing of the five v0.5 funds once into write-once Parquet tables, expose them in dbt, and measure how they tie to the existing pipeline outputs.

**Architecture:** A small Python package `warehouse/filed_parser/` reads the XBRL instance and the inline HTML and writes one folder per filing under `warehouse/data/filed/`. dbt reads those folders as a second source, adds staging views and tests. No change to marts.

**Tech Stack:** Python 3.13 in `warehouse\.venv` (lxml 6.1.3, duckdb 1.4.3, pytest 9.2.0), dbt-core 1.12.7 with dbt-duckdb 1.11.1.

**Spec:** `warehouse/docs/filed_layer.md` (binding; column names and types are exact).

## Global Constraints

- Scope: the five funds in `findings_scope.ciks` of `data/reference/quarter_acceptance_thresholds.json`; never hard-code the list.
- Read-only outside `warehouse/`. The one exception is appending an entry to `docs/agent_changelog.md` in Task 3.
- No interpretation in this layer: no filer-specific rule, no classification, no correction, no dropping of rows or facts.
- Never `pip install`. The environment is complete.
- No network calls.
- No inline Python (`python -`, `python -c`). Diagnostics go in a named file under `warehouse/scripts/` or through `.\warehouse\dbt.ps1 show --inline "..."`.
- One filing in memory at a time. No multiprocessing. Print one ASCII progress line per filing.
- ASCII only in anything printed to the console.
- No `git add`, `git commit`, stash or reset.
- Measured counts are results. Do not change a test or drop data to make a count look better.

---

### Task 1: Parser for the instance file

**Files:**
- Create: `warehouse/filed_parser/__init__.py` (holds `PARSER_VERSION = "1"`), `instance.py`, `store.py`, `cli.py`, `__main__.py`
- Create: `warehouse/parse.ps1`, `warehouse/pytest.ini`, `warehouse/pytests/test_instance.py`, `warehouse/pytests/test_store.py`, `warehouse/pytests/fixtures/mini_instance.xml`
- Modify: `warehouse/.gitignore` (add `data/`, `.pytest_cache/`, `__pycache__/`), `warehouse/requirements.txt` (add `lxml==6.1.3`, `pytest==9.2.0`)

**Interfaces (produced, used by Tasks 2 and 3):**
- `instance.parse_instance(path) -> dict[str, list[tuple]]` with keys `filing_dei`, `context`, `context_member`, `unit`, `tagged_fact`. Streaming parse (`lxml.etree.iterparse`, clearing elements), not a full tree.
- `store.TABLES`: for each table name, the ordered column names and DuckDB types from the spec.
- `store.write_filing(out_root, cik, accession, tables, inputs) -> manifest dict`: sorts rows by primary key, computes the content hash per table from the ordered rows, writes Parquet through DuckDB into a temporary folder, writes `_manifest.json`, renames into place. Implements write rules 1 to 5 of the spec.
- `cli`: arguments `--cik` (repeatable), `--accession` (repeatable), `--reparse`, `--verify`, `--out` (default `warehouse/data/filed`), `--raw` (default `data/raw/filings`). Exit code 0 on success, 1 on any failed filing. In this task the HTML tables are written empty with the right columns; Task 2 fills them.
- `parse.ps1`: runs `.venv\Scripts\python.exe -m filed_parser` with the repository root as the working directory and `warehouse` on `PYTHONPATH`, passes arguments through, returns the exit code.

**Steps:**
- [ ] Write `mini_instance.xml`: two contexts without members (instant, duration), one context with an explicit and a typed member (typed text with line breaks and repeated spaces), two units (plain, ratio), facts: `dei:DocumentType`, `dei:DocumentPeriodEndDate`, `dei:AmendmentFlag`, one numeric with `decimals="-3"`, one numeric without `id`, one `xsi:nil`, one text fact longer than 4,000 characters.
- [ ] Write failing tests for: every column of every instance table on the fixture; typed member white space; missing id gives `noid:<n>`; truncation with length and hash; rows sorted by key; same input twice gives the same content hashes; skip on same manifest; error on changed input hash; `--reparse` overwrites; a failure mid-write leaves no folder under the final name.
- [ ] Run them: `.\warehouse\.venv\Scripts\python.exe -m pytest -c warehouse\pytest.ini warehouse\pytests -q`. Expect failures.
- [ ] Implement until they pass.
- [ ] Run one real filing: `.\warehouse\parse.ps1 --accession 0001193125-26-215667`. Check `tagged_fact` has 2,374 rows with concept `us-gaap:InvestmentOwnedAtFairValue` (measured in the raw file).
- [ ] Run all five funds: `.\warehouse\parse.ps1`. Report: filings parsed, total rows per table, elapsed time, any filing that failed and why, count of synthetic ids, count of `dei_conflict`.
- [ ] Run `.\warehouse\parse.ps1 --verify`. Expect every filing to match.

### Task 2: Parser for the inline document

**Files:**
- Create: `warehouse/filed_parser/inline.py`, `warehouse/pytests/test_inline.py`, `warehouse/pytests/fixtures/mini_inline.html`
- Modify: `warehouse/filed_parser/cli.py`, `store.py` if needed, `__init__.py` (`PARSER_VERSION = "2"`)

**Interfaces:**
- Consumes: `store.TABLES`, `store.write_filing`, `cli` from Task 1.
- Produces: `inline.parse_inline(path) -> dict[str, list[tuple]]` with keys `document_row`, `fact_placement`, `footnote`, `fact_footnote`, exactly as in the spec.

**Steps:**
- [ ] Write `mini_inline.html`: an `ix:header` with one hidden fact; one table with a heading row (no facts), two rows with `ix:nonFraction` facts (one with `scale` and `sign`), one `ix:nonNumeric`; a table with no facts (must not be kept); a table nested in a cell of a kept table, with a fact; one fact outside any table; two `ix:footnote` and `ix:relationship` elements, one with several `fromRefs`.
- [ ] Write failing tests for every column of the four tables on the fixture, including: the table without facts is absent; the nested fact belongs to the inner table's row; the outside fact has null `row_index`; `fact_count` per row; white space collapsed.
- [ ] Implement. The largest document is 55 MB: parse with `lxml.etree` using a recovering, huge-tree parser, free the tree before the next filing. If a document does not parse as XML, fall back to `lxml.html` and record `html_parser` (`xml` or `html`) in the manifest.
- [ ] Run the tests until they pass, then `.\warehouse\parse.ps1 --reparse` for all five funds, then `--verify`.
- [ ] Report: rows per table, elapsed time, peak memory if observed, documents that used the fallback, and for the instance against the document: numeric facts in the instance with no placement, placements with no instance fact.

### Task 3: dbt source, staging, tests, baseline, documents

**Files:**
- Create: `warehouse/models/staging/filed/_filed_sources.yml`, `_filed_staging.yml`, and one view per table: `stg_filed_filing.sql`, `stg_filed_context.sql`, `stg_filed_context_member.sql`, `stg_filed_unit.sql`, `stg_filed_fact.sql`, `stg_filed_document_row.sql`, `stg_filed_fact_placement.sql`, `stg_filed_footnote.sql`, `stg_filed_fact_footnote.sql`
- Create: singular tests under `warehouse/tests/` named `filed_*.sql` (structure) and `baseline_filed_*.sql` (bridge)
- Create: `warehouse/docs/baseline_filed_2026-11-18.md`
- Modify: `warehouse/dbt_project.yml` (var `filed_dir: "data/filed"`, new `baseline_max` keys), `warehouse/README.md` (how to parse, what the filed layer is, in plain words for a dbt beginner), `docs/agent_changelog.md` (append one entry)

**Interfaces:**
- Consumes: the folders written by Tasks 1 and 2; existing models `stg_holdings` (has `accession_number`, `src_context_id`, `fair_value`, `corrected_fields`, `accounting_record_class`), `dim_filing`.
- Sources read with `read_parquet('{{ var("filed_dir") }}/*/*/<table>.parquet', hive_partitioning=true, union_by_name=true)`; `cik` comes from the folder name and must be text with leading zeros.

**Steps:**
- [ ] Sources and staging views (views select columns by name; no logic beyond casting the folder `cik` to text).
- [ ] Structure tests from spec section 6 (primary keys with the existing generic `unique`/`not_null` or a singular test for composite keys; relationships as singular tests returning the unmatched rows).
- [ ] Bridge tests from spec section 6, written like the existing `baseline_*` tests: `{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['<key>']) }}`. First run them with a very high ceiling, record the measured counts, then set each ceiling to the measured count.
- [ ] For "fair value equals filed": the fair-value concept is `us-gaap:InvestmentOwnedAtFairValue`. Where a holdings context carries no such fact, count it under its own test, do not guess another concept. Split the mismatch count by whether `corrected_fields` mentions fair value.
- [ ] `.\warehouse\dbt.ps1 build`. Expect 0 errors; the earlier 105 passes and 8 warnings unchanged; new tests added.
- [ ] Write `baseline_filed_2026-11-18.md`: every measured count, the five largest groups behind each non-zero count, and what was not checked.
- [ ] Append the changelog entry (append only; do not touch other lines).
