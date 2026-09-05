# Match-Gold Operator Runbook

Dispatch workflow for batch-building, scoring, and auditing position-match verdicts. Use this
after completing a match-quality cohort review and before running agents on the residual.

## 1. Prereqs

- **Rebuild metrics**: `python scripts/rebuild_outputs.py --match-quality`. Check
  `match_quality_metrics.csv` column `chain_continuity_rate` denominator. If 0 (stale holdings), first
  run `python scripts/rebuild_outputs.py --returns` to populate position_id, then re-run
  --match-quality.
- **Check concurrent fleet state**: No other match-gold, agent-b, or codex worker fleet should be
  running. See AGENTS.md concurrency rule. Run `ps | grep codex` (bash) or check
  `data/output/agent_b*|match_gold|conventions/` batch directories for active workers.
- **Operator shell**: Launch from admin PowerShell (conda-activated, `codex login` done). Do NOT
  run from inside a Codex session -- dispatcher refuses to dispatch from within one.

## 2. Build batch

```powershell
python scripts/match_gold/build_packets.py --batch-id mg1
```

Output: `data/output/match_quality/gold/mg1/` with:
- `worklist.csv` -- packet manifest with `has_cached_filing` column (1=has HTML, 0=no cached HTML).
- `packets/` -- blinded position-match JSON packets (one per packet_id).
- `packets_meta/` -- per-packet metadata (indices, context).
- `filings/<pid>/` -- directory per filing for roaming (`<accession>.json`).
- `prompts/<packet_id>.md` -- individual worker instruction files.
- `verdicts/` -- (empty at start; workers write here).

Note the batch-id (e.g. `mg3`); use it throughout.

### 2a. Check coverage before dispatching

```powershell
python scripts/match_gold/cache_coverage.py --batch-dir data/output/match_quality/gold/mg3
```

Reports, per packet and per stratum, how much filing evidence a worker can actually roam.
Prefer this over the worklist's `has_cached_filing` column: that column is an
all-or-nothing snapshot taken at build time and reads `False` both for a packet with no
accessions at all and for one with 5 of 6 filings cached.

| category | meaning | dispatch? |
|---|---|---|
| `full`    | every accession cached | yes |
| `partial` | some cached | yes — worker adjudicates on what exists, else INSUFFICIENT_EVIDENCE |
| `none`    | accessions exist, none cached | no — re-queue after a cache fill |
| `no_acc`  | packet has no accession numbers | **build defect, not a cache gap** |

`no_acc` should be zero. It was 223/580 on batch mg2 (2026-09-05) because `sample_chains`
drew `tier_random`/`fv_jump` from `position_id_edges.csv`, which is not cohort-filtered,
while the holdings frame is — so those packets were written with zero rows. Fixed by the
`e_cohort` view plus a fail-loud guard in `write_batch`; if you ever see `no_acc > 0`
again, fix the sampler rather than dispatching around it.

## 3. Dispatch worker fleet

```powershell
python scripts/match_gold/build_packets.py --batch-id mg3     # if not already built
powershell -File scripts\match_gold\dispatch_match_gold_workers.ps1 -BatchId mg3 -MaxParallel 4
```

Must run from an **elevated** shell (the worker config sets `[windows] sandbox = "elevated"`;
non-admin dispatch fails with logon errors 1223/1326 and writes no verdict). The dispatcher
asserts this, and asserts it is not running inside a Codex session.

Useful flags: `-DryRun` (print the plan), `-PacketId <id>` (canary/targeted re-run),
`-Limit N`, `-RequireFullCache`, `-IncludeUncached`, `-Redispatch` (re-run packets that
already hold a valid verdict), `-MaxAttempts` (default 2), `-TimeoutMinutes` (default 15).

**Resume**: re-running the same command is the resume path. The dispatcher scans every
existing verdict through the deterministic gate first and skips packets that already hold a
valid one, so an abort (circuit breaker, killed shell) costs only the in-flight workers.

What it does per packet, and why (each point cost a real incident):

1. **Worker homes are a reused pool** of `MaxParallel` short-path slots under
   `C:\cxw\mg\<batch>`, not one home per packet — Codex copies its ~308 MB binary into every
   fresh `CODEX_HOME`. `history.jsonl` and `sessions\` are purged between packets so one
   packet's prompt cannot leak into the next.
2. **Blinding is enforced structurally**: `packets_meta\` and `worklist.csv` (which carry the
   `stratum` / `match_method` labels the packets are blinded of) are MOVED to
   `%LOCALAPPDATA%\match_gold_hold\<batch>` for the duration and moved back on exit.
   `setup_codex_worker_harness.ps1` hardcodes a repo-root read grant and `evidence_cli.py`
   resolves cached HTML relative to the repo (`REPO = parents[2]`), so the grant cannot be
   narrowed — relocating the labels outside the repo is the cheap structural fix. Before
   this, blinding rested on the prompt alone (the 2026-09-04 canary's rollout traces showed
   zero references to those files, but that was compliance by behavior, not by sandbox).
   If a run dies mid-dispatch, `HOLD_README.txt` is left in the batch dir; recover with
   `-RestoreHoldOnly`.
3. **Deterministic gate after every worker**: `validate_verdict.py --packet ... --verdict ...`
   (schema, packet-id/type match, edge coverage, citation requirements). A worker that exits
   0 but wrote nothing or wrote off-schema JSON counts as a failure and is retried.
4. **Periodic ACE sweep**, not just at startup: every worker run leaks one sandbox-SID ACE
   onto the verdicts dir and the DACL ceiling is ~1,820 (2026-07-24 incident).
5. **Usage-limit circuit breaker**: the Codex quota is account-level, so once one worker hits
   it every remaining worker fails identically in seconds. The fleet aborts and tells you to
   re-run after the reset.

**Read grants**: repo root + the interpreter's import roots, from
`scripts/match_gold/worker_env.py` (which reuses `_worker_read_dirs` from
`scripts/agent_b/dispatch_preflight.py` so the two fleets cannot drift).

**Sandbox traps** (baked into the scripts; verify any new dispatcher includes them):

- User site-packages read grant (omit `-ReadDirs` site-packages = ImportError).
- Runroot boundary: the `[permissions...filesystem]` write grant is what authorizes a
  write, NOT the `-C` boundary. Canary-verified 2026-09-04: workers wrote to an
  absolute verdicts path OUTSIDE the runroot via `apply_patch`. So the runroot can stay
  a short per-worker scratch dir; it does not have to contain `verdicts/`.
- Windows MAX_PATH: keep batch-id and worker slot ids short (`w1`, not the 16-char MGP id).
- Auth: copy `auth.json` into each fresh CODEX_HOME or workers 401.

**Roaming during dispatch**: workers access filings via `evidence_cli.py`. `build_packets.py`
bakes the absolute invocation into each prompt — absolute interpreter (`sys.executable` of
the build), absolute CLI, one command triple per real accession. A worker's cwd is a scratch
runroot, so relative paths resolve against nothing:
```powershell
"<abs python.exe>" "<repo>\scripts\review_agent\evidence_cli.py" `
  --bundle "<batch>\filings\<packet_id>\<accession>.json" overview|roam|grid
```

The engine=match_gold is pre-registered. Workers see raw facts, not pipeline derivations.

## 4. Score verdicts

```powershell
python scripts/match_gold/score_gold.py --batch-dir data/output/match_quality/gold/mg1
```

Output:
- `gold_set.csv` -- all packets with computed verdict class (CONFIRMED/WRONG_MERGE/MISSED_LINK/MIXED).
- `precision_by_tier.csv` -- Wilson-interval confidence bounds per tier (A/B1/B2/C/D/unmatched).
- `audit_slice.csv` -- flagged packets for human review (see step 5).
- `summary.md` -- listing of INVALID verdicts (format errors) and MISSING verdicts (no verdict
  file written).

**Action on invalid/missing**: Re-dispatch those packets, or hand-review their filings and record
verdicts manually to `verdicts/<packet_id>.json` using the schema in
`pipeline/match_verdict_leaf.py`. Schema: packet_type, verdict (CONFIRMED|WRONG_MERGE|MISSED_LINK|MIXED|INSUFFICIENT_EVIDENCE for packets; CONFIRMED|WRONG|UNCERTAIN for edges), confidence [0,1], rationale, evidence list (quoted_text or table_index+row_index).

## 5. Human audit

Open `audit_slice.csv` (typically 50-100 rows sampled from `gold_set.csv`). Per flagged packet:

1. Fetch the filing from `filings/<packet_id>/<accession>.json`.
2. Review the worker verdict against the actual position facts.
3. Record **agree** or **disagree** in new column `owner_verdict`.

Tally disagree rate and note specific false-positive/false-negative patterns. Include count and
examples in the investigation write-up (step 6).

## 6. Record results

- **Investigation artifact**: Append new entry to the matching topic file in `docs/investigations/`
  per INDEX.md conventions. Include:
  - Date, batch-id, cohort size.
  - Per-tier precision, UNCERTAIN edge count, owner audit disagreement rate.
  - Caveats (see step 7).
  - Notable patterns from audit (false-positive/negative examples).

- **Changelog**: Append entry to `docs/agent_changelog.md`:
  ```
  ## YYYY-MM-DD Match-gold batch <batch_id>
  - Scored <N> packets; <M> tier-A, <K> tier-B1, etc.
  - Precision: DL A 92%, B1 78%, ... (Wilson CI).
  - Owner audit: <N> flagged, <X>% disagreement; <pattern1>, <pattern2>.
  - Caveats: UNCERTAIN edges excluded; batch versioned by id; no overlapping agent-author scoring.
  ```

- **Reindex**: `python scripts/split_investigations.py --reindex` to rebuild the topic index.

## 7. Caveats (state in every report)

- **Precision scope**: Estimates are per-tier on the current cohort only. Cross-quarter stability
  not measured.
- **UNCERTAIN exclusion**: Edge verdicts with UNCERTAIN are excluded from the precision
  denominator (true positives + false positives = precision denominator only includes CONFIRMED
  and WRONG edge verdicts).
- **Gold versioning**: Gold set is versioned by batch-id. Later agent runs must not re-score
  packets they authored in a prior batch -- use a fresh batch-id if re-running the same filings.
- **Interagent contamination**: Do not mix workers from different batches or agent types (A/B/anchor)
  when scoring. Each batch is standalone.
