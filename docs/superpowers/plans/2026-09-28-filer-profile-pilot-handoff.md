# Handoff prompt: execute the filer-profile pilot, Stage A

Paste everything below the line into a fresh Claude Code session started in
`C:\Users\alger\Documents\000. Projects\005. evergreen funds platform xbrl\.claude\worktrees\filer-profile-pilot`.

---

You are executing Stage A (Tasks 1-3) of the filer-profile pilot in this
repository. Read this whole prompt before running anything.

## Where you are

- You are in a git worktree at `.claude/worktrees/filer-profile-pilot` on
  branch `filer-profile-pilot`. HEAD is `98cd0d1` or later. Confirm with
  `git rev-parse --abbrev-ref HEAD` and `git worktree list` before any edit.
- The main checkout (two directories up, the repo root without
  `.claude/worktrees/...`) is SEALED for the V13 closeout. Never edit, check
  out, stash, or run tests inside it. Read-only commands against it are fine.
- This worktree has NO `data/raw/` and NO `data/output/`. All cache and
  output reads resolve to the main checkout's `data/` directory through an
  explicit data root. Pilot writes go ONLY to
  `<data_root>/pilot/filer_profile/<run_id>/`, plus the two coordination
  writes named in spec section 2.

## Read first, in this order

1. `AGENTS.md` (repo contracts; especially no network, no pipeline edits from
   this branch, ASCII logs, no ad-hoc inline Python, one heavy job at a time).
2. `docs/superpowers/specs/2026-09-28-filer-profile-pilot-design.md` (v4.2).
   Sections 2, 5, 6, 8, 9, 10, 14 and 15 are binding.
3. `docs/superpowers/plans/2026-09-28-filer-profile-pilot.md` (v4.2). The
   "Facts verified against the repo" block saves you re-deriving column
   lists, loader signatures and cache layout. The "Verified integration
   points and cautions" table lists every production function you may call
   and the boundary that must stay explicit.
4. The last three entries of `docs/agent_changelog.md`.
5. If a memory file `filer-profile-pilot.md` is loaded in your context, treat
   it as background; the spec and plan on disk are authoritative.

## What to build in this session

Stage A only: Task 1 (paths, frozen inputs, protection of the real data
roots, shared lease adapter), Task 2 (immutable temporal envelope with
executable partition predicates), Task 3 (graduation test and M3). Stop
after Task 3 and report. Do not start Task 4 in this session.

Use the `superpowers:subagent-driven-development` skill: one fresh subagent
per task, with the two-stage review between tasks. Every subagent you spawn
MUST run on the Opus 5.5 model. Pass the model override explicitly on every
Agent call and do not fall back to a smaller model for review or
implementation work. If the harness does not expose an "opus 5.5" identifier,
stop and report the identifiers it does expose before spawning anything;
do not substitute silently.

Each task's acceptance bullets in the plan are the definition of done. The
plan deliberately contains no code templates: design the module, write the
failing tests named in the bullets first, then implement, then run the
focused tests, then the backstop, then commit. Do not treat a passing
synthetic test as proof that cached data passes.

## Hard rules for this session

- No edits under `pipeline/` in either checkout. If a production function
  cannot be called safely with all writes confined to the run root, return
  an explicit integration-gap result; never patch the pipeline.
- No network, no SEC downloads, no model calls inside pilot code, no
  rebuilds of production outputs, no baseline refresh, no wrapper edits.
- Heavy work (census on Ares 0001287750 or BCRED 0001803498, any all-quarter
  scan, any stage reconstruction that triggers a large parse) requires the
  shared lease `pipeline.programme.runner.heavy_lock(candidate)` bound to the
  MAIN checkout root, with a pseudo-candidate directory
  `data/programme/candidates/pilot-filer-profile-<run_id>/` (spec 10).
  There is no `--allow-heavy`. A failed lock or process inspection blocks
  the work. The V13 controllers may still be running; if the lease is held,
  stop and report rather than wait in a loop.
- Stage A should need no heavy work. If Task 3's origin-frame reconstruction
  would trigger one, leave that item `insufficient_evidence` and report it.
- Protect the REAL roots before any cache-backed test imports pipeline code:
  the main checkout's `data/output/` and `frontend/public/data/` and the
  worktree equivalents, for both Python writes and native-IO changes. After
  each pytest invocation run `scripts/diff_outputs.py --semantic` as a
  read-only subprocess with the main checkout as working directory and keep
  the receipt under `verification/` in the run root. Empty worktree output
  directories do not satisfy this.
- Before a broad pytest run, check for other pytest or rebuild processes.
  Never run the full repository suite in this session; focused
  `tests/test_profile_pilot_*.py` files only.
- Bash in this worktree refuses compound commands that it cannot prove stay
  inside the worktree. Use plain, separate git commands; use the Read, Edit
  and Write tools for files; keep heredocs simple.
- Commit after each task with a short subject and a 2-4 line body. Do not
  push. Do not rebase onto main; the V13 merge has not landed.
- ASCII only in logs, prints, and test output.

## Report at the end of Stage A

Write a short report (in chat, and appended to `docs/agent_changelog.md`)
that states, with numbers:

- Task 1: the resolved data root, the run id, the protected roots actually
  registered, the lease binding (candidate path, lock file path) and the
  semantic-diff receipt path.
- Task 2: envelope test count and the two supersession-kind cases proven.
- Task 3: M3 denominator, per-class counts (generalises, quarter_bound,
  conflicts, insufficient_evidence, not_expressible), and the causes of every
  insufficient_evidence item.
- What was NOT run, and any integration gap hit.
- Measured wall time for Tasks 1-3, so the owner can price Stage B.

Then stop. The owner reads the Stage A report before authorising Stage B.
