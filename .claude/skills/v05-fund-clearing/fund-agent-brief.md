# Brief: clear one fund

You own ONE fund end to end: build it, read its findings against the filings, fix what is wrong,
rebuild, and write up what is left. An orchestrator will run a mechanical gate on your result. It
does not re-read your work; it checks that the build is clean, totals tie, every changed field is
one you declared, every quote you cite is in the filing, and you touched nothing you may not.

Read first: `AGENTS.md` (Contracts, Non-Negotiable Data Semantics), the fund's reading report
`docs/investigations/v05_readings/<cik10>.md` if it exists, and its entries in
`docs/investigations/v05_decision_log.md` (search the CIK and the fund name).

## Inputs you are given

`CIK`, `LABEL_PREFIX` (make sandbox labels `<prefix>a`, `<prefix>b`, ...), `BEFORE` (the last
accepted sandbox for this fund, or none), `ADD_QUARTER` (a date, or none), `REPORT` (path of the
JSON you must write).

## Review scope (owner 2026-11-10)

`docs/investigations/v05_readings/outstanding_status.csv` (column `category`) says which of your
fund's findings were reviewed before. Investigate on the page only findings in category
`unreviewed` or `investigated`, plus finding ids your rebuild produces that are not in that file.
For every other outstanding finding, copy its existing investigation forward unchanged into
`investigations`, with `"carried_from": "<the archived file it came from>"` (the fund's earlier
report, `docs/investigations/v05_readings/unreviewed_2026-10-21/<cik10>.json`, or the proposal
evidence). If its currently flagged rows differ from the carried `affected_rows`, it is back in
scope: investigate it fully. Fixing errors earlier reviews confirmed is still your job.

## Loop

1. **Build.** `bash scripts/v05_evidence/build_fund.sh <label> [--add-quarter <date>] <cik>`. One
   build at a time. Edit nothing while it runs. A fund takes 4 to 15 minutes.
2. **Measure.**
   - `python scripts/v05_evidence/fund_ledger_latest.py <cik> --rules` (outstanding by rule)
   - `python scripts/v05_evidence/make_batch_dispositions.py <label> fundloop <cik>` (what a reason
     the owner accepted clears by check; add `--write`, then
     `python scripts/fund_ledger_trial.py --label <label> --from ledger`)
   - `python scripts/v05_evidence/left.py <label> <rule> ...` and `flagged.py <label> <rule> <cik> <quarter>`
   - Issuer names: the gate fails a fund where more than 1 pct of published rows have an issuer
     name that still holds an instrument ('Acme, Inc., First lien senior secured loan'), a row
     number ('Acme LLC 2') or a holder label ('Acme, Inc., Emerald JV LP'). Run
     `fund_gate.py check` early to see the count. Fix with the wrapper's
     `issuer_name_strip_re` (plus `issuer_name_strip_to_instrument: true` to keep the cut text as
     the instrument) and `instrument_description_strip_re` (plus
     `instrument_description_strip_may_empty: true` where the "instrument" is only a label);
     `data/overrides/bdc_xbrl_wrappers/0001869453.json` and `0001803498.json` are worked examples.
     Dry-run the pattern on every distinct name of the fund before building. A name printed that
     way on the page goes under `name_shape_exceptions` with the shape, the row count and why.
   - `python scripts/v05_evidence/verdicts.py <label> 1500` for what earlier reviewers found. A finding
     in state `real_error_unremediated`, `remediation_staged` or `remediation_pulled` has a verdict
     with the rows it cites: read it and check each cited row on the page. They are sometimes
     wrong and sometimes already fixed, and you must say which.
3. **Read every remaining finding on the page** before deciding anything:
   `python scripts/v05_evidence/page_line.py <cik> <accession> "<phrase>"` for the printed line,
   `python scripts/v05_evidence/filing_grep.py <cik> <accession no dashes> xml <context>` for the
   tagged facts. Group findings by cause across quarters: one cause usually explains many quarters.
4. **Fix**, in this order of preference:
   1. a setting in the fund's wrapper (`data/overrides/bdc_xbrl_wrappers/<cik>.json`, or the
      highlights wrapper) that already exists for this kind of filer behaviour;
   2. a value declared from the page (`source_encodings.untagged_values`);
   3. a row correction (`data/overrides/row_corrections.csv`, through
      `scripts/v05_evidence/make_row_corrections.py`);
   4. an exclusion rule under `data/overrides/agent_investigate_rules/<cik>/`, only for a row that
      is not a position (a total, a note figure), with the printed lines that show it;
   5. new shared code, only when none of the above can express it: switched on by this fund's
      wrapper, off for every other fund, with a focused test and one false-positive test, and the
      key added to `schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json`. Set `"shared_code": true` in
      your report.
5. **Rebuild** under a new label and compare with the build before it:
   `python scripts/v05_evidence/holdings_field_diff.py <new> <old>`. Explain every changed
   column. A change you did not aim at is a defect until shown otherwise.
6. **Repeat** 2 to 5 until nothing is left that you can fix. Stop after three attempts at one
   finding without a mechanism; record the hypotheses you tested.
7. **Propose** a disposition for each finding that is not a fix, in
   `data/overrides/finding_dispositions_proposed/fund_<cik10>.json`
   (`python scripts/v05_evidence/make_fund_proposals.py <label> <cik> --write` from a spec, or by
   hand in the same shape). Each entry needs at least one evidence item
   `{"source": "filing", "accession": "<with dashes>", "verbatim": "<line copied from page_line.py>", "quote": "<the same, with your reading>"}`.
   An entry that covers a finding with an earlier real-error verdict needs
   `"addresses_verdict": {"<quarter>": "<what that reviewer found, and why it does not stand or how it was fixed>"}`.
   A figure the page prints and the build does not publish is a gap to fix or to park, never
   "as filed": if one row correction can set it in one quarter, the same holds in the others.
   `class` is one of `as_filed`, `not_applicable`, `informational` (the store refuses any other),
   and every entry carries a `rerun` (the command that reproduces the evidence). Where the data is
   right and the check misfires, do not propose a disposition: raise an orchestrator request
   classified `verification_bug` for a check repair (owner ruling 2026-11-04).
   One reason per entry. Say why no fix applies. Give each entry a `reason_key`: a short slug for
   the reason itself, not the fund (`x11-undrawn-line-par-printed-as-dash`), reusing a key from
   `docs/investigations/v05_owner_queue.md` where the reason is the same, so the owner is asked once.
8. **Write the report** (below) and stop. Do not commit.

Before returning, satisfy `investigation-review.md`: one structured investigation per outstanding
ledger review_id, including findings with proposals. Record all affected rows and which were read,
source evidence, conclusion, hypotheses tested and next action. Generic parking text is insufficient.
The orchestrator commissions an independent reviewer; never author or approve your own review.
Every observation needs a detection decision, and every orchestrator request needs classification
as verification_bug or acceptance_change, evidence and next_action.

Write as you go: after every build, update `REPORT` and your notes under
`scratch/fund_runs/<cik10>/notes.md` (what you read, what you changed, what is left). A run that is
cut off must be resumable from those two files. At most six builds; if findings you could fix
remain after that, list them under `parked`. Finish source investigation even when no builds remain.
If evidence is unavailable, explicitly enumerate incomplete coverage and missing evidence; never
claim investigation complete. Do not rebuild simply to add documentation or proposals.

You may run the gate on your own result (`fund_gate.py check`, without `--snapshot`, so its
`files` check will fail: ignore that one). The orchestrator runs it again.

## What you may not do

- Accept a disposition. You propose; a check or the owner accepts. Never write under
  `data/overrides/finding_dispositions/` except through `make_batch_dispositions.py`.
- Change a rule, a threshold, a check, the ledger, the gate, a test fixture, or this skill to
  clear a finding. A rule you believe is wrong is an orchestrator request (`verification_bug`)
  with evidence, not a disposition proposal.
- Add a rule that inserts a row or a value without the printed line that shows it. No plug that
  makes a total tie.
- Use the network, run a build of more than this fund, write under `data/output/` or
  `frontend/public/data/`, run `git stash`, `git commit`, `git push`, or edit `AGENTS.md`.
- Edit a file that another session has modified (`git status` shows it before you start).
- Change something the gate forbids even if the fix needs it (a check, the provenance
  re-verifier, a rule, the ledger). Describe the change under `orchestrator_requests` in your
  report, with the evidence; the orchestrator makes it and re-runs your gate. A request that
  would have a check accept a value the pipeline itself derived (from member text, for example)
  is declined: declare the printed value in the wrapper (`source_encodings.untagged_values`,
  with the printed line) instead, which the re-verifier already checks against.
- Kill a process by image name (`taskkill /IM python.exe` kills another session's build). Kill
  only a process you started, by its id.
- Start a command with a bare `python -` or an empty heredoc. Write scripts with the Write tool
  and run the file. Any file holding a regular expression goes through the Write or Edit tool.

## Checks that have caught real errors

| Before you rely on | Check |
|---|---|
| "totals tie" | List quarters with no filed total: they are unchecked, not passing. Find which printed total the filed figure is (with or without money-market funds, with or without a joint venture). |
| a reader's or an earlier agent's row list | Read each row's printed line yourself. |
| "as filed" for a rule | Read the flagged rows on the page; do not infer from the tag alone. |
| a tag reading that worked on a sibling fund | Check it on this fund's printed page. |
| a promoted `row_add`, `column_remap` or value-matching rule | Read the printed line; several were plugs. |
| a value-proximity setting you switched on | List every row it converted and read a sample. |
| a row correction | `grep "Row correction unmatched" scratch/fund_sandbox/<label>/logs/rebuild.log` for this fund. |
| a cleaned issuer name | Count rows that lost a GICS label and rows whose unit count became `derived_proxy`. |
| a removed subtotal | The ledger can go up (the source check then reports the fact as unpublished). Say so. |
| a withdrawn dollar par on a foreign loan | It raises FX01; supply the amount at the build's own rate for that date. |

## What independent reviewers rejected most often (2026-10-18/19 runs)

Check each before you return; every one cost a fund a full extra round.

- **Detection decisions.** `existing_detector` only if a named rule actually fired on these rows in your untouched build. An observation key, the observations log, or a guard that only warns is not a detector: use `propose_detector` with a concrete check.
- **Counts.** Every count in the report must reproduce from a query you saved in your notes folder. Recount after the last build.
- **Scope of a fix.** A sample error or finding is a symptom: search every row and quarter for the same shape (all name variants, abbreviations, every foreign marker), not just the cited rows, and list what you searched.
- **Coverage.** `affected_rows` lists every row or context the rule flagged, including prior-period comparative contexts in the same filing.
- **"As filed".** Only when the page prints the published value. If the page prints something else, or the build drops or mis-scales a printed value, it is an error to fix or park.
- **New rows.** Rows you newly publish (dash rows, restored rows, cash rows) must go through every fix you made earlier: re-run your name, rate and spread checks on them.
- **Accepted reasons.** A finding cleared by an accepted reason can still hide a printed value: read the flagged rows anyway.
- **Anchors.** Never declare a printed figure as an anchor that a check then compares with the same printed rows (D-212).
- **Shared tables and defaults.** Do not change them (alias tables, global maps, default thresholds); add an opt-in wrapper key instead and propose the shared change (D-211).
- **Owner conventions.** Spread = cash + PIK margin with `pik_rate` separate (D-031); `interest_rate` storage is still the cash leg (AGENTS.md).

## Report (`REPORT`, JSON)

The example below shows the original data-change fields. Also required: `investigator_id` and
`investigations` in the exact shape in `investigation-review.md`. Every observation adds
`detection_decision`; every request adds `request_id`, `classification`, `evidence`, `next_action`.
Do not copy this abbreviated example as a complete passing report.

```json
{
 "cik": "0001849894",
 "label": "<final sandbox label>",
 "before": "<sandbox compared against, or null>",
 "shared_code": false,
 "declared_changes": [{"column": "principal_amount", "rows": 12, "why": "par declared from the page for 12 rows"}],
 "rows_added": 0,
 "rows_removed": 1,
 "fixes": [{"what": "...", "kind": "wrapper|untagged_value|row_correction|exclusion|shared_code",
            "quarters": ["2024-03-31"],
            "quotes": [{"accession": "0001234567-24-000028", "text": "<line copied from page_line.py>"}]}],
 "total_exceptions": [{"quarter": "2023-06-30", "why": "...", "quote": {"accession": "...", "text": "..."}}],
 "parked": [{"finding": "engine rule quarter", "hypotheses": ["..."]}],
 "orchestrator_requests": [{"file": "pipeline/provenance_reverify.py", "what": "...", "why": "...", "quotes": []}],
 "observations": [{"observation_key": "unit-count-rescaled-by-issuer-normaliser", "what": "...", "field": "shares_held",
                   "quarters": ["2024-09-30"], "fair_value_m": 0.2, "cause": "row|fund|shared", "action": "fixed|parked|left",
                   "suggested_check": "...", "quote": {"accession": "...", "text": "..."}}],
 "name_shape_exceptions": [{"shape": "instrument_in_name|row_number_in_name|holder_label_in_name", "rows": 0,
                            "why": "the printed page names the issuer this way (quote it)"}],
 "tests_run": ["tests/test_x.py: 12 passed"],
 "not_done": ["what you did not check"]
}
```

`declared_changes` lists every column that differs from `BEFORE`, with a row count at least as
large as the actual one. `entity_id` and `canonical_name` need no entry. Every fix carries at least
one quote. A quote is copied from `page_line.py` output, 20 characters or more, unedited.

"All findings cleared" is not "data correct". `observations` is where you write down anything
wrong that no rule reported: a published value that differs from the page, a field the build
dropped, a row that should not be there, a shared step that changed a value. It is required (an
empty list if you truly saw nothing). For each one:

- `observation_key`: a slug for the PROBLEM, not the fund, so the same problem on another fund
  groups with it. Reuse a key from `python scripts/v05_evidence/observations.py show`.
- `cause`: `row` (this row only), `fund` (this fund's settings or filings), `shared` (a step every
  fund goes through; it may be wrong elsewhere, so say which step).
- `action`: `fixed`, `parked`, or `left` (seen, not touched; say why in `what`).
- `suggested_check`: the rule that would have caught it, in one sentence, if you can state one.
- `quote`: the printed line that shows it, copied from `page_line.py`.

While reading a finding's rows you see its neighbours. Look at them: compare a few published rows
per quarter with their printed lines on fields no finding names (unit count, rate, maturity,
industry, name).

After your gate is clean, the orchestrator has 20 random rows of your final build read against the
page by another agent. If it finds published errors, you get the table back: fix the cause at fund
level, or list each as an observation with the reason it is left, then rebuild and report again.
