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

**Action on missing filings**: If any packets have `has_cached_filing=0`, list them in run notes
and do NOT dispatch them. They will be re-queued for a later pass after cached HTML is available
from a full pipeline rebuild.

Note the batch-id (e.g. `mg1`); use it throughout.

## 3. Dispatch worker fleet

Follow `docs/reference/codex_worker_dispatch.md` fleet pattern:

1. **Per packet**:
   - Set up sandbox: `setup_codex_worker_harness.ps1 -WorkerHome <path> -WriteDirs @(<verdicts>)`.
   - Copy auth: `Copy-Item $operator_auth <WorkerHome>\auth.json`.
   - Run worker: `run_codex_worker.ps1 -PromptPath prompts/<packet_id>.md -WorkerHome <path> -TraceDir logs/ -TracePrefix "<packet_id>__"`.

2. **Parallelism**: Dispatch all packets with `has_cached_filing=1` in parallel (no ordering).
   Workers write `verdicts/<packet_id>.json` independently.

3. **Read grants**: Repo root + interpreter site-packages (use `_worker_read_dirs` from
   `scripts/agent_b/dispatch_preflight.py`).
   **Blinding is PROMPT-level, not filesystem-level.** `setup_codex_worker_harness.ps1`
   hardcodes a read grant on the repo root, and `evidence_cli.py` resolves cached filing
   HTML relative to the repo (`REPO = parents[2]`), so a repo-root read grant is
   unavoidable — which means `packets_meta/` and `worklist.csv` (carrying `stratum` /
   `match_method`) ARE readable by a worker. The prompts never mention them, and the
   2026-09-04 canary's three rollout traces contain zero references, but that is
   compliance by behavior, not by sandbox. To make it structural, move `packets_meta/`
   and `worklist.csv` out of the batch dir for the duration of a dispatch.

4. **Sandbox traps** (baked into scripts; verify your dispatcher includes them):
   - User site-packages read grant (omit `-ReadDirs` site-packages = ImportError).
   - Runroot boundary: the `[permissions...filesystem]` write grant is what authorizes a
     write, NOT the `-C` boundary. Canary-verified 2026-09-04: workers wrote to an
     absolute verdicts path OUTSIDE the runroot via `apply_patch`. So the runroot can stay
     a short per-worker scratch dir; it does not have to contain `verdicts/`.
   - Windows MAX_PATH: keep batch-id and WORKER ids short (`c1`, not the 16-char MGP id).
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
