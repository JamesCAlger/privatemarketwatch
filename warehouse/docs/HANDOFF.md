# Handoff: data-model redesign in `warehouse/`

Written 2026-11-18 at the end of the session that built steps 1 and 2. Read this first, then the documents it points to.

## State

- **Nothing is committed.** Branch `ensemble-fp-experiment`. The whole of `warehouse/` is untracked. `docs/agent_changelog.md` is modified: it holds two entries from this work (step 1 marts, step 2 filed layer) and uncommitted entries from other agents.
- No process and no subagent was left running (checked at shutdown).
- The rest of the repository was not changed by this work: `data/output`, `frontend/public/data`, `pipeline`, `scripts`, `tests`.

## What is built

| Step | What | Where |
|---|---|---|
| 1 | dbt marts over today's pipeline outputs, five v0.5 funds, position level only | `models/staging/`, `models/marts/`; spec `docs/design.md`, columns `docs/marts_columns.md`, baseline `docs/baseline_2026-11-18.md` |
| 2 | Parse-once filed layer: each cached filing parsed into nine Parquet tables | parser `filed_parser/` (version 3), output `data/filed/` (git-ignored), views `models/staging/filed/`; spec `docs/filed_layer.md`, baseline `docs/baseline_filed_2026-11-18.md` |

Step 3, the middle layer (source rows with a role, observations, corrections), is **not started and not requested**. It is the first step that needs per-filer judgement. Agree the design with the owner before building.

## How to run

All from the repository root, in PowerShell.

- `.\warehouse\dbt.ps1 build` : last result `PASS=162 WARN=11 ERROR=0 TOTAL=173`. The 11 warnings are baseline tests: they warn above zero and fail above the ceiling in `dbt_project.yml` (`baseline_max`).
- `.\warehouse\parse.ps1` : parses filings not yet parsed. `--verify` re-parses and compares hashes (last result 86 of 86, about 5 minutes). `--reparse` overwrites. One run at a time: two runs interfere.
- `.\warehouse\.venv\Scripts\python.exe -m pytest -c warehouse\pytest.ini warehouse\pytests -q` : 67 parser tests.
- Python is `warehouse\.venv` only. Never `pip install` into the shared `python` on PATH.

Passing tests show the layers are consistent and repeatable. They do not show the data is correct.

## Owner decisions waiting

1. Commit `warehouse/` and the two changelog entries (stage exact paths; the changelog file also has other agents' entries).
2. Cash in the step 1 test `published_equals_filed`. The owner's ruling of 2026-11-04 (check A04 in `pipeline/oracle_checks.py`) leaves cash rows out of the comparison to the filed investments line in stated cases. The test does not apply it. Offered: add `cash_fair_value` and an ex-cash difference to `fact_fund_period`. Only Apollo is affected (18 rows).
3. Whether to start the middle layer, and its design.
4. Whether the findings ledger moves onto dbt. Discussed, no decision.

## Not examined

- 46 holdings rows whose fair value matches no filed fact on their context (Apollo 44, Ares 2).
- 12 parsed filings with no holdings rows.
- 55 groups of contexts in one filing with identical members and period (BCRED 30, Ares 13, HPS 9, Apollo 3).
- 320 of the 896 position facts that sit in no printed table row.
- Whether a fact sits in the right cell: checked on two whole filings (BCRED, Ares), not all 86.
- Row spans: checked on a test fixture only.

## Rulings made without the owner

Listed with the cost of each in `docs/filed_layer.md` section 7 and in the step 2 ledger. The owner said they were reviewing in parallel and has not yet confirmed them.

## Parked minor defects (step 2 ledger has all fourteen)

- Two parse runs at once interfere (shared staging folder is swept at start).
- A missing table file whose manifest count is 0 goes unnoticed.
- The content hash does not distinguish a null from the literal text `\N`, and does not escape its separators.
- The fallback HTML parser is tested on a fixture only; no real filing used it.

## Where the detail is

- Ledgers, task reports and reviews: `.superpowers/sdd/2026-11-18-step1-marts-plan/` and `.superpowers/sdd/2026-11-18-step2-filed-layer-plan/` (`progress.md` first). Git-ignored.
- Agreed model and every owner decision: `scratch/2026-11-18_data_model/models.md` and `design.md` (scratch is disposable; `docs/design.md` here is the kept copy of the design).
- Diagnostic scripts left by agents: `warehouse/scripts/` (`diag_*`, `finalreview_*`, `fixround_query.py`, `measure_inline.py`, `count_concept.py`). Safe to delete; `make_manager_brand_seed.py` builds a seed and should stay.

## Standing rules that bit during this work

- No inline Python (`python -`, `python -c`). Two subagents sent a bare `python -` by mistake and had to be stopped. Say it explicitly in every dispatch.
- Subagents on Sonnet or Opus only.
- The owner is learning dbt: explain dbt terms in plain words.
