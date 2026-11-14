"""Worktree per fund attempt (spec section 4).

data/raw and data/output are git-ignored, so a worktree has neither. Both are linked to the main
checkout with a directory junction: a sandbox build reads them (fund_ledger_trial seeds from
data/output and fails if data/output changes). Cleanup removes the links BEFORE the worktree, so
removing a worktree never touches the cached filings or the published outputs.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from config import REPO, WORKTREE_ROOT

# scratch/fund_sandbox is linked too: builds land beside today's sandboxes, and --before labels resolve.
LINKED = ("data/raw", "data/output", "scratch/fund_sandbox")


def _git(*args, cwd: Path = REPO, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def name_for(cik10: str, run_id: str) -> str:
    return "sdk-%s-%s" % (cik10[-6:], run_id[-6:])


def _junction(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    else:
        link.symlink_to(target, target_is_directory=True)


def _unlink_junction(link: Path) -> None:
    if not os.path.lexists(link):
        return
    if os.name == "nt":
        # rmdir on a junction removes the link only, never the target's contents.
        subprocess.run(["cmd", "/c", "rmdir", str(link)], check=True, capture_output=True)
    else:
        link.unlink()


def create(cik10: str, run_id: str, base: str = "HEAD") -> tuple[Path, str]:
    name = name_for(cik10, run_id)
    path = WORKTREE_ROOT / name
    branch = "sdk-loop/%s/%s" % (run_id, cik10)
    if path.exists():
        return path, branch                      # resume
    _git("worktree", "add", "-b", branch, str(path), base)
    _git("config", "core.longpaths", "true", cwd=path)
    for rel in LINKED:
        _junction(path / rel, REPO / rel)
    return path, branch


def remove(path: Path, keep_branch: bool = True) -> None:
    path = Path(path)
    for rel in LINKED:
        _unlink_junction(path / rel)
    for rel in LINKED:                            # refuse to continue if a link survived
        if os.path.lexists(path / rel):
            raise RuntimeError("link still present, not removing worktree: %s" % (path / rel))
    _git("worktree", "remove", "--force", str(path))


def changed_paths(path: Path, base: str) -> list[str]:
    """Every path changed against the base commit, committed or not, plus untracked files
    (scratch/ and the linked folders are git-ignored, so they never appear)."""
    out = set()
    for args in (("diff", "--name-only", base), ("ls-files", "--others", "--exclude-standard")):
        res = _git(*args, cwd=path)
        out |= {line.strip().strip('"') for line in res.stdout.splitlines() if line.strip()}
    return sorted(out)


def diff_lines(path: Path, base: str, rel: str) -> list[str]:
    """Added and removed lines of one file against the base (without the +++/--- headers)."""
    res = _git("diff", "-U0", base, "--", rel, cwd=path)
    return [l for l in res.stdout.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]


def commit_all(path: Path, message: str) -> str:
    _git("add", "-A", cwd=path)
    res = _git("commit", "-m", message, cwd=path, check=False)
    if res.returncode != 0 and "nothing to commit" not in (res.stdout + res.stderr):
        raise RuntimeError("commit failed: " + (res.stderr or res.stdout)[:400])
    return _git("rev-parse", "HEAD", cwd=path).stdout.strip()
