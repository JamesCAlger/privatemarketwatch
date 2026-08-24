# scratch/ -- operator & agent session scratch

The single home for ad-hoc artifacts produced by interactive operator or agent
sessions: shell redirect logs (`command > foo.log`), one-off analysis plots,
session kickoff notes, throwaway CSV dumps. Anything you would previously have
left in the repo root goes here instead.

## Convention

- One subdirectory per session: `YYYY-MM-DD_<topic>/` (e.g.
  `2026-07-23_q1shakedown/`). Date = session start, topic = short slug.
- Redirect session output here from the start:
  `python -m pipeline.main --financials > scratch/2026-08-21_myrun/financials.log`
- ASCII filenames, no spaces.

## What does NOT go here

Machine-written logs from fleet/pipeline operation already have homes and must
stay in them:

- `data/output/pipeline.log` -- written by `pipeline/main.py` each run.
- `data/output/quarter_pass/<pass_id>/<stage>.log` -- written by
  `scripts/run_quarter_pass.py` alongside that pass's state and acceptance
  artifacts.
- Worker batch dirs under `data/output/agent_*/batch/` -- dispatch logs,
  harvested traces, gate JSONL.

Those are pass/fleet provenance; this directory is disposable session noise.

## Lifecycle

- Git-ignored (everything except this README). Never committed, never in
  baseline snapshots, not backed up.
- Safe to delete any session dir once its findings are recorded in
  `docs/investigations/` or `docs/agent_changelog.md`. If a file matters,
  its contents belong in one of those, not here.
