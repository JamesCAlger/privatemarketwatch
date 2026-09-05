"""Report the sandbox read grants a match-gold worker needs, as JSON.

The generated prompts name an absolute interpreter (build_packets.WORKER_PYTHON),
so the sandbox must be able to EXECUTE it and IMPORT the project deps from it.
That is trap #1 in docs/reference/codex_worker_dispatch.md: omit the user
site-packages grant and evidence_cli.py dies with ImportError inside the sandbox.

Reuses scripts.agent_b.dispatch_preflight._worker_read_dirs so the match-gold
fleet and the agent-b fleet cannot drift on what "the deps live here" means.

    python scripts/match_gold/worker_env.py
    -> {"python": "...", "read_dirs": ["...", ...]}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.agent_b.dispatch_preflight import _worker_read_dirs  # noqa: E402


def main() -> int:
    read_dirs = list(_worker_read_dirs())
    # The interpreter's own directory: the sandbox needs read/execute on python.exe
    # itself, which is not necessarily any of the import roots above.
    exe_dir = str(Path(sys.executable).resolve().parent)
    if exe_dir not in read_dirs:
        read_dirs.insert(0, exe_dir)
    print(json.dumps({"python": sys.executable, "read_dirs": read_dirs}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
