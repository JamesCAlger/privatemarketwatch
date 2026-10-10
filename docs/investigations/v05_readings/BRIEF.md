# Reading brief: one fund's findings against its filings (READ-ONLY)

Repo: SEC XBRL pipeline for unlisted BDCs. Each fund has a "fund sandbox" build under
`scratch/fund_sandbox/<label>/` holding its published holdings, the tagged facts, and a findings
ledger. Your job: read every outstanding finding of your fund(s) against the cached filing and say,
with the printed line as evidence, whether it is a real error (and what generic fix would repair
it) or a false alarm / as filed. Then look beyond the findings (section 4). You diagnose only; the
lead applies fixes.

## 1. Hard rules

- READ-ONLY. Do not edit anything under `pipeline/`, `scripts/`, `data/overrides/`, `tests/`,
  `docs/`, `AGENTS.md`. Do not run pytest, rebuilds, `fund_ledger_trial.py`, `rebuild_outputs.py`
  or anything that writes outside `scratch/2026-10-10_read/<cik>/`. A sandbox build may be
  running; do not disturb it. No git commands that change state.
- No network calls of any kind. All filings are cached on disk.
- Never run `python -`, `python -c`, or a heredoc piped to python. Put SQL in a file and run it
  with the runner below. If you need Python, write a named file under
  `scratch/2026-10-10_read/<cik>/`, with row limits, and run it with a timeout.
- Use Bash (Git Bash). Always `cd "/c/Users/alger/Documents/000. Projects/005. evergreen funds platform xbrl"` first.
- ASCII only in anything you write. DuckDB memory limit 3GB per query. No pandas loops on big files.
- Do not spawn further agents.

## 2. Tools (all read-only)

- SQL runner: `python scratch/2026-10-07_printed_rates/q.py <label> <file.sql>`; `{S}` in the SQL
  is the sandbox output folder; statements split on `;`; prints at most 80 rows each.
- Filing text: `python scripts/v05_evidence/filing_grep.py <cik> <accession no dashes> html "<phrase>" [max hits] [chars after]`
  shows the printed text around a phrase (tags stripped). Raw facts of one context:
  `python scripts/v05_evidence/filing_grep.py <cik> <accession no dashes> xml "<context id>"`.
  Cached files: `data/raw/filings/bdc_html/<cik no zeros>/<accession>.html`, `data/raw/filings/bdc_xbrl/<cik no zeros>/<accession>.xml`.
- One row, every column: `python scripts/v05_evidence/row.py <label> <cik> <quarter> "<identifier text>" [n]`.
- Row-rule issues of a fund: `python scripts/v05_evidence/issues2.py <label> <rule> <cik>`.
- Findings still needing a reading, by fund and rule (prints, writes nothing without `--write`; never pass `--write`):
  `python scripts/v05_evidence/make_batch_dispositions.py <label> x <cik>`.
- Totals against the filed investments figure by quarter: `python scratch/2026-10-07_printed_rates/q.py <label> scratch/2026-10-07_printed_rates/s1_tot3.sql` (lists only quarters that differ by more than 0.5M).
- The fund's wrapper (how its labels are parsed): `data/overrides/bdc_xbrl_wrappers/<cik10>.json`;
  fund-level wrapper `data/overrides/fund_highlights_wrappers/<cik10>.json`; promoted rules
  `data/overrides/agent_investigate_rules/<cik no zeros>/`.

Files in `scratch/fund_sandbox/<label>/`:
- `findings_ledger.csv`: one row per finding (review_id, state, cik, rule_name, report_date, engine).
  Outstanding states: open, needs_human, evidence_backlog, real_error_unremediated, remediation_pulled, remediation_staged.
- `output/private_markets_holdings.parquet`: published rows (cik, report_date, issuer_name,
  instrument_description, bdc_investment_identifier, fair_value, cost, principal_amount,
  principal_amount_usd, interest_rate, interest_rate_reported, basis_spread, pik_rate,
  reference_rate_type, coupon_type, maturity_date, pct_of_net_assets, asset_category,
  index_classification, accounting_record_class, accession_number, src_context_id, src_facts,
  src_transforms, ...). Published basis excludes `accounting_record_class = 'underlying_schedule'`.
- `output/bdc_holdings.parquet`: tagged facts per context as extracted (investment_identifier, period, dimensions_raw, values).
- `output/source_reconciliation_detail.parquet`: each tagged row against its published row
  (status, source_wrapper_disposition, raw_investment_identifier, source_fair_value, output_fair_value, context_id; use `period = report_date`).
- `output/row_validation_issues.parquet` (rule_id, cik, report_date, value, row_key, message).
- `output/oracle/check_failures.csv` (oracle rules A01, B01, C04, D06, E04 ...).
- `output/shadow/validation_results_ledger.csv` (identity, conservation, weak, provenance, nonaccrual, gav engines).
- `output/fund_financials_validation_current.csv` (F rules), `output/fund_financials.csv`, `output/bdc_fund_income.csv`.
- `output/review_queue/review_queue.csv` (review_id to rule, mechanism, metric).
- `output/provenance_ledger.parquet` (re-verification of each published field against its tag).

Data covers quarters to 2026-03-31. Only the current-period rows of each filing are published
(`period = report_date`).

## 3. What to decide for each outstanding finding (group them by rule and cause)

For each group: find the rows behind it, read the printed schedule line(s) in the filing of that
quarter, and classify:

- REAL, GENERIC: wrong published data with a cause that repeats (give the cause, the count of rows
  and quarters, fair value affected, two or three printed lines with accession, and the fix you
  would make: a wrapper setting or regex, a rule that excludes rows by a stated predicate, shared
  code). Fixes must be generic and switched on by the fund's wrapper, never keyed to one row
  unless the filing itself is wrong for one row.
- REAL, ONE ROW: the filing tags one row wrongly; give published value, printed value, printed line, accession, context id.
- AS FILED / FALSE ALARM: published equals the page and the check is wrong or not applicable here;
  quote the printed line that shows it, and say in one line why the check fires.
- NOT DETERMINED: say what you tried.

Causes seen again and again in other funds (look for these first):
1. Rows of an affiliate roll-forward note published as positions (no percent of net assets, no principal).
2. Dollar values tagged with a foreign unit and converted twice (fix: `source_encodings.foreign_unit_values: ["reported_in_usd"]`).
3. Loans with a PIK part publishing no rate or the cash leg only (`filed_rate_reading`: `all_in` when the tagged rate equals reference + spread including PIK, `cash_leg` otherwise).
4. Foreign-currency principal with no dollar equivalent (`principal_usd_reference: ["fred_h10"]`).
5. Subtotal or section rows published as positions; group-name rows.
6. Twin rows whose members end ' One' / ' Two' or ' 1' / ' 2' dropped as duplicates (`staging.distinct_member_suffix_re`).
7. Positions tagged on a context with no identifier member.
8. Reference-rate codes the reader does not know (`reference_rate_columns`, `reference_rate_codes`).
9. Issuer names that still carry the section heading, industry or instrument text; one "issuer" per row.
10. Real positions dropped because the label lacks an instrument word or a legal suffix.
11. Undrawn commitment rows listed gross and subtracted as a section line.
12. Cash-like rows (money market funds) missing, doubled by their subtotal, or classed as loans.

## 4. Beyond the findings (do this for every fund, it is where most real errors were found)

a. Totals: for every quarter where published differs from the filed investments total by more
   than 0.5M, find the rows that explain it (tagged and not published; published and not on the
   page; a subtotal). Read the printed total line. If no filed figure exists, read the printed
   'Total investments' line and report it.
b. Tagged position rows with a fair value that are not published (`source_reconciliation_detail`,
   `output_fair_value IS NULL`, disposition names a leaf): list by quarter with fair value, and say why they drop.
c. Names: sample 15 issuer names per quarter group; report quarters where names carry headings,
   industries, instrument text, a trailing 'Type', or where issuers per row is about 1.
d. Rates: share of loan rows with no interest_rate per quarter; read 5 such rows on the page. Is a
   rate printed? Compare published interest_rate, basis_spread, pik_rate, reference_rate_type,
   maturity_date with the printed line for the 10 largest loans at 2026-03-31 and at one early quarter.
e. Classes: equity, warrant and fund rows classed as loans or the reverse (10 largest non-loan rows; any loan with no maturity and no rate).
f. Fund-level figures: `fund_financials.csv` net assets, total assets, investments against the printed balance sheet for the latest and one early quarter.

## 5. What to hand back

Write your full notes to `scratch/2026-10-10_read/<cik10>.md` (one file per fund): a table of
finding groups (rule, count, quarters, verdict, cause, evidence with accession and printed line,
proposed fix), then the section 4 results. Be exact: quote the printed text, give accession
numbers, context ids, counts and dollar amounts. Say what you did not check.

Your final message (it goes to the lead, not to a person): at most 40 lines per fund. Real errors
first, largest by fair value first, each with the proposed fix; then counts of false alarms by
reason; then what is not determined. No praise, no filler. A clean result must say "findings
cleared is not data correct" items you could not test.
