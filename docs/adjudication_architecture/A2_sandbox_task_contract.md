# Agent A2 - Sandboxed Induction Task Contract

The contract the Codex sandbox runs for one `(cik, [report_date])` identifier-grammar
induction. The deterministic A0/A1 build the bundle; A3 (held-out gate) decides promotion
outside the sandbox. The agent only proposes config; it never writes production fields.

## Invocation (deterministic, outside the sandbox)

```
python -m scripts.agent_a.run_quarter discover <QUARTER>          # -> worklist + per-CIK bundles
# bundle: data/output/agent_a/quarter/<QUARTER>/bundles/<CIK>_<QUARTER>.json
# dispatch the sandbox with: that bundle + the roam interface below
# worker writes PROPOSALS (staging); it never writes the override files.
python -m scripts.agent_a.run_quarter finalize <QUARTER> --staged # parent staging finalization
python -m scripts.agent_a.run_quarter gate <QUARTER> --staged     # A3 held-out gate on proposals
python -m scripts.agent_a.run_quarter promote <QUARTER>           # explicit PASS-only promotion
```

## Sandbox environment (staged-write guardrails; read denial is future work)

- **Cache-only, read-only on production.** No SEC network, no rebuild, no writes to the
  override files. The current worker harness writes proposals only to the staging proposal
  dir; the parent validates and promotes passing proposals to production override config.
  Full OS-level denial of repo-wide reads is not implemented yet because the evidence CLI
  still runs from the repo.
- **Source window = roam only**, via the shared evidence CLI (identical to B's):
  ```
  python scripts/review_agent/evidence_cli.py --bundle <bundle> tables
  python scripts/review_agent/evidence_cli.py --bundle <bundle> grid --table N [--start --count]
  python scripts/review_agent/evidence_cli.py --bundle <bundle> roam --query "tok1,tok2"
  python scripts/review_agent/evidence_cli.py --bundle <bundle> totals
  ```
  The bundle carries `evidence_items[].data[].accession_number`; the CLI resolves it to the
  cached SOI. No haystack: roam is targeted query-with-coordinates, never a dump.
- **Writable outputs (the only two, staging not production):**
  `data/output/agent_a/proposals/<CIK>.anchors.json`,
  `data/output/agent_a/proposals/<CIK>.grammar.json`.
  These are proposals. The parent (outside the sandbox) validates them (JSON + schema), uses
  them for finalize/A3 gate through staging-aware or temporary materialization, and durably
  promotes only passing ones to the real override paths
  `data/overrides/identifier_anchors/<CIK>.json` and
  `data/overrides/identifier_rate_grammars/<CIK>.json`. The worker must not write the override
  paths directly; those dirs are not in the worker harness writable set.

## Control plane and operating limits

- **Preferred control plane:** launch A2 through native Codex subagents from the active
  session. Do not shell out to `codex`, `codex.cmd`, `codex exec`, or
  `scripts/run_codex_worker.ps1` from inside Codex.
- **External worker fallback:** `scripts/run_codex_worker.ps1` is an operator-shell tool
  only. If it is used, launch it outside Codex and manage only captured worker PIDs.
  Never clean up workers by process name, timestamp, command substring, or broad
  `codex`/`node` process scans.
- **Repo access is a ceiling, not task permission.** The current worker harness still grants
  repo-root read so the allowed bundle and evidence tools work, but each A2 prompt must name
  the exact files/directories the agent may inspect. Missing evidence should produce
  `INSUFFICIENT_EVIDENCE`, not repo-wide discovery.
- **Operational budget:** each reconnaissance or induction prompt must include a maximum
  command/file-read count, a wall-clock limit, and an output-size limit. The harness should
  enforce these mechanically where possible.
- **Forbidden broad reads:** no recursive scans of `data/output`, `data/raw`, repo root, or
  the Git worktree; no broad `rg --files`, `Get-ChildItem -Recurse`, `git status`, or
  `git diff` from the agent. Diff/status reporting belongs to the parent harness after the
  agent exits.

## Input

The bundle (`data/output/agent_a/quarter/<QUARTER>/bundles/<CIK>_<QUARTER>.json`, produced by
`run_quarter discover`): regime, top `(cik, signature)` variants with about 12 homogeneous
samples, structured twins, per-sample `accession_number`, `(none)` examples, current anchor
labels, and source accessions. A non-quarterly ad-hoc bundle from `sample_variant <CIK>` lands
at `data/output/agent_a/bundles/<CIK>[_<REPORT_DATE>].json`; the quarterly path above is
canonical for Trial A2.

## Task

Induce/repair, grounded in source via roam:

0. **Available datapoints inventory.** Before proposing extractors, inspect the bundle's
   identifier strings and state which datapoints are actually present in
   `investment_identifier` (for example issuer, instrument type, tranche/index number,
   reference rate, spread, coupon, PIK, maturity). Do not infer fields from SOI columns as if
   they were present in the identifier.
1. **Anchor vocabulary** -> `proposals/<CIK>.anchors.json` so `(none)` rows gain a signature.
   Use roam to confirm a candidate marker is a real SOI section/column header before adding it.
2. **Rate grammar** -> `proposals/<CIK>.grammar.json` (schema `agentA-rate-grammar.v1`):
   extractors (reference_rate_type+map, basis_spread noting bps vs pct, interest_rate fields,
   pik_rate, maturity_date), `pik_convention` (`additive` "cash plus X PIK" or `inclusive`
   all-in incl PIK), derivations (coupon_type floating-iff-reference), and invariants.
   Only include these extractors when the datapoints are present in the identifier string.
   Use roam/grid to resolve ambiguities, but do not treat source-table columns as identifier
   text.
   If the identifier carries issuer/type/tranche only and rate fields live only in SOI columns,
   write a routing proposal with `status: "NOT_APPLICABLE_RATE_GRAMMAR"`, plus
   `available_identifier_datapoints`, `unsupported_identifier_datapoints`, and
   `not_applicable_reason`. This is a valid outcome; do not force a fake rate grammar.
3. **Aggregate candidates:** when a row looks like a leaked subtotal, roam to confirm it has
   no issuer or sits on a category line in the SOI; report it, but do not fold it into a
   position grammar.

## Discipline (prompt-level)

- Required fields are only fields present on nearly all dominant-variant rows. Never require
  optional PIK, floor, or cash-leg fields. Derive fixed/floating from reference presence; never
  invent a reference on a fixed loan. Where a twin looks mis-binned, flag it; do not fit the
  grammar to it.
- Ground every non-obvious choice in a roam/grid observation and cite the table/row. Plausible
  sample parses are not acceptance; the deterministic A3 gate decides.

## Required self-screen before finishing (deterministic)

Before exiting, run the deterministic self-screen on the proposal and iterate until it passes:

```
python -m scripts.agent_a.validate_proposal --cik <CIK> --bundle <bundle>
```

It applies the proposed grammar to the bundle's sample rows and checks: JSON/schema valid,
every extractor regex compiles, `required_fields` contains no optional field (pik_rate, floor,
cash_leg), non-applicable proposals include the datapoint inventory and are supported by the
bundle, the dominant signature matches sample rows under the proposed anchors, sample
completeness >= 90%, and the `(none)` examples gain a signature. Exit 0 = proceed; exit 1 =
fix and re-run. This is a screen, not promotion; the parent's A3 held-out gate over the full
population remains authoritative. `NOT_APPLICABLE_RATE_GRAMMAR` routes to a different
mechanism; it is not a PASS rate grammar.

## Per-CIK serialization (concurrency rule)

CIK is the unit of mutual exclusion. The A2 output is keyed by CIK (one anchors proposal and
one grammar proposal per CIK), so two agents on the same CIK would race the files or each
extend the grammar blind to the other's new rules.

- Across CIKs: fully parallel (disjoint files, no shared state).
- Within a CIK: strictly serial. The orchestrator must
  `python -m scripts.agent_a.run_quarter claim <CIK>` before launching (exit 0 = acquired;
  exit 1 = already in flight, do not launch a second), and the parent releases on gate
  completion. `discover` already emits one row per CIK and skips CIKs already in flight.
- Remediation is a follow-up pass, never concurrent with induction. It reads the promoted
  config and extends it, so each agent starts from the latest committed rules.

## Output -> parent validate + A3 gate -> durable promotion (outside the sandbox)

The worker emits the two staging proposals only (`proposals/<CIK>.anchors.json`,
`proposals/<CIK>.grammar.json`). The parent then: (1) validates JSON + schema; (2) runs
`finalize --staged` and `gate --staged` using staging-aware inputs; (3) durably promotes
proposals to override paths only after PASS. Promotion requires
`pipeline.identifier_held_out` PASS: per-quarter completeness >= 90% and gating-invariant >=
85% in every in-era signature-bearing quarter, none-share stable, FV preserved. A
narrow-confidence PASS routes to human review. Fail -> human and no durable override change.
The agent never writes production config or holdings fields; B, not A, authors value
corrections from the ledger flags.

## Why this is the same substrate as B / C

Shared: the cached-filing evidence library (`html_soi_evidence` + `evidence_cli`), the
bundle->accession->roam contract, cache-only/read-only guardrails, and the Codex sandbox.
Different per agent: the bundle builder, task, and output schema. One harness, four task
contracts.
