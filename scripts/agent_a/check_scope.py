"""Deterministic scope guard for an Agent A2 sandbox run.

The worker must write ONLY staged proposal files under data/output/agent_a/. This guard
verifies that independently of the sandbox: it lists everything that changed vs a baseline
and FAILS (exit 1) if any path falls outside the allowlist. It is the belt-and-suspenders
the whole v1 leans on -- config.toml/sandbox flags are the agent PROMISING; this VERIFIES.

CRITICAL (learned the hard way): `git status --porcelain` collapses an untracked directory
to a single line, hiding per-file additions inside it. This guard uses
`--untracked-files=all` so writes into an untracked override dir are actually seen.

Usage:
  python -m scripts.agent_a.check_scope --snapshot      # write baseline before the agent runs
  python -m scripts.agent_a.check_scope --check [CIK..]  # after; exit 1 on out-of-scope writes
"""

from __future__ import annotations

import subprocess
import sys

from pipeline import config

_SNAP = config.OUTPUT_DIR / "agent_a" / ".scope_baseline.txt"

# the ONLY paths an A2 worker run may create/modify
_ALLOW_PREFIXES = (
    "data/output/agent_a/",          # staged proposals, bundles, worklists, gate results
)


def _status():
    # -uall: do NOT collapse untracked dirs (the bug the v1 trial exposed)
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=config.PROJECT_ROOT, capture_output=True, text=True,
    ).stdout
    # porcelain line: 'XY <path>' (path starts at col 3); strip quotes git adds for spaces
    rows = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip().strip('"')
        rows.append(path)
    return set(rows)


def snapshot():
    _SNAP.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(_status())
    _SNAP.write_text("\n".join(rows), encoding="utf-8")
    print(f"scope baseline: {len(rows)} entries -> {_SNAP}")


def check(expect_ciks=None):
    before = set(_SNAP.read_text(encoding="utf-8").splitlines()) if _SNAP.exists() else set()
    changed = _status() - before
    in_scope, out_scope = [], []
    for p in sorted(changed):
        (in_scope if p.replace("\\", "/").startswith(_ALLOW_PREFIXES) else out_scope).append(p)

    print(f"scope check: {len(changed)} changed vs baseline "
          f"({len(in_scope)} in-scope, {len(out_scope)} OUT-OF-SCOPE)")
    if expect_ciks:
        for cik in expect_ciks:
            wrote = any(cik in p for p in in_scope
                        if "identifier_rate_grammars" in p.replace("\\", "/"))
            print(f"  {cik}: grammar written = {wrote}")
    if out_scope:
        print("OUT-OF-SCOPE writes (a hard sandbox would have BLOCKED these):")
        for p in out_scope:
            print(f"  !! {p}")
        return 1
    print("OK -- all writes within staged agent_a output.")
    return 0


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in ("--snapshot", "--check"):
        print("usage: python -m scripts.agent_a.check_scope {--snapshot | --check [CIK...]}")
        return 2
    if argv[0] == "--snapshot":
        snapshot()
        return 0
    return check(expect_ciks=argv[1:])


if __name__ == "__main__":
    sys.exit(main())
