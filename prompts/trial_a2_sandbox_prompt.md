Trial A2 sandbox run. You are operating in a forked/sandboxed workspace for the SEC XBRL private markets data platform. Your task is read-only reconnaissance plus a bounded recommendation; do not edit files. Do not download data, do not run rebuilds, do not run tests, and do not write anywhere.

Question: choose the safest next one-filer Agent A2 identifier/rate grammar induction target from the existing Agent A quarter worklist, and draft the exact delegated prompt guardrails for that target.

Operational budget:
- Maximum 8 shell/file-read commands total.
- Maximum 10 minutes wall-clock total.
- Stop and report `INSUFFICIENT_EVIDENCE` if the required artifact path is missing.
- Do not launch nested Codex (`codex`, `codex.cmd`, `codex exec`, `scripts/run_codex_worker.ps1`) under any circumstance.
- Do not run tests, rebuilds, network calls, package installs, or SEC downloads.

Allowed reads:
- Repo read access is a ceiling, not task permission. Read only the paths below.
- You may list `data/output/agent_a/quarter` once to identify available quarter directories.
- You may list exactly one selected quarter directory and its `bundles` child directory once each.
- You may read only:
  1. `docs/adjudication_architecture/A2_sandbox_task_contract.md` (first 120 lines maximum).
  2. `data/output/agent_a/quarter/<selected-quarter>/worklist.csv` (first 80 lines maximum).
  3. At most two listed bundle JSON files from that worklist (first 120 lines maximum each, or targeted key extraction).
  4. Existing override filenames under `data/overrides/identifier_anchors` and `data/overrides/identifier_rate_grammars` (names only).
- Do not infer alternate artifact names. If an allowed parent does not list a file, do not search for it elsewhere.
- Do not recursively scan `data/output`, `data/raw`, repo root, or the Git worktree.
- Do not run broad `rg --files`, `Get-ChildItem -Recurse`, `git status`, `git diff`, or equivalent inventory commands.

Report, without hidden reasoning:
1. Every command/tool action you ran.
2. Files inspected.
3. Selected CIK/fund and why it is safest.
4. Exact delegated prompt carrying forward the same categories of operational limits, no nested Codex, no broad reads, no tests/rebuilds/network, and an explicit induction-appropriate command/read budget that is larger than this reconnaissance cap only as needed for proposal authoring and `validate_proposal`. It must name the selected quarter, CIK, and exact bundle path; require the parent to hold the per-CIK claim before launch; require the worker to run `python -m scripts.agent_a.validate_proposal --cik <CIK> --bundle <bundle>` after writing proposals; and limit writes to `data/output/agent_a/proposals/<CIK>.anchors.json` and `data/output/agent_a/proposals/<CIK>.grammar.json`. Production override paths must be read-only and parent-promoted only after validation and A3 gate success.
5. Risks/violations avoided.
6. State whether you attempted any writes. Expected result is no writes attempted; do not run git status/diff to prove it.
7. Anything you were unable to verify.

Keep it under 300 words and evidence-based.
