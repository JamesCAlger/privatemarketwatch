"""Tool-call policy per role (spec section 4). Pure functions; the SDK hook calls ``Policy.check``.

Hooks read a call before it runs: they stop habits and mistakes, not a determined agent. The
after-the-fact checks (checks.py) are the protection.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk_review"))
import guards  # noqa: E402  (scripts/sdk_review/guards.py)

from config import REPO  # noqa: E402

# Shell rules for agents that have a shell, on top of guards.check_shell.
_EXTRA_SHELL = (
    (re.compile(r"\bgit\s+(stash|push|merge|rebase|commit|cherry-pick|worktree)\b"), "git stash/push/merge/rebase/commit: the driver commits; you do not"),
    (re.compile(r"--no-verify"), "--no-verify is never allowed"),
    (re.compile(r"\b(run_batch|rebuild_outputs)\.py\b"), "batch and production rebuilds are not run by the loop"),
    (re.compile(r"pipeline\.main\b[^;&|]*--unified"), "the unified build is not run by the loop"),
    (re.compile(r"\b(fund_ledger_trial|sandbox_add_quarter)\.py\b"), "build only with scripts/v05_evidence/build_fund.sh"),
    (re.compile(r"(>>?|\btee\b|\bcp\b|\bmv\b|\brm\b|Set-Content|Out-File|Remove-Item|Copy-Item|Move-Item)[^;&|]*"
                r"(data/output|frontend/public/data|data/decisions)/"), "no writes into data/output, frontend/public/data or data/decisions"),
    (re.compile(r"\bdecide\.py\b"), "decisions are recorded by the driver, not by agents"),
)
_SH_SCRIPT = re.compile(r"\b(bash|sh)\s+(\S+\.sh)\b")


def check_shell_fund(command: str, *, cwd: Path) -> str | None:
    reason = guards.check_shell(command, cwd=cwd)
    if reason:
        return reason
    for pattern, why in _EXTRA_SHELL:
        if pattern.search(command):
            return why
    for _, script in _SH_SCRIPT.findall(command):
        if script.replace("\\", "/").strip("\"'").lstrip("./") != "scripts/v05_evidence/build_fund.sh":
            return "the only shell script you may run is scripts/v05_evidence/build_fund.sh"
    return None


@dataclass
class Policy:
    role: str
    write_roots: tuple[Path, ...] = ()          # absolute folders writable in full
    worktree: Path | None = None                # base for allowed_res
    allowed_res: tuple[str, ...] = ()           # repo-relative regexes inside the worktree
    read_roots: tuple[Path, ...] = (REPO,)
    shell: bool = False
    max_builds: int = 0                         # build_fund.sh calls allowed (shell roles)
    builds: int = 0
    refusals: list = field(default_factory=list)

    def _rel(self, p: Path) -> str | None:
        if self.worktree is None or not guards._inside(p, self.worktree):
            return None
        return p.relative_to(self.worktree.resolve()).as_posix()

    def check_write(self, path: str, cwd: Path) -> str | None:
        p = guards._resolve(path, cwd)
        if any(guards._inside(p, r) for r in self.write_roots):
            return None
        rel = self._rel(p)
        if rel is not None and any(re.search(rx, rel) for rx in self.allowed_res):
            return None
        return "write refused for %s: %s is outside the paths this role may change" % (self.role, p)

    def check(self, tool_name: str, tool_input: dict, cwd: Path) -> str | None:
        roots = tuple(self.read_roots) + tuple(self.write_roots) + ((self.worktree,) if self.worktree else ())
        if tool_name == "Read":
            return guards.check_read(tool_input.get("file_path", ""), cwd=cwd, roots=roots)
        if tool_name in ("Grep", "Glob"):
            return guards.check_read(tool_input.get("path", ""), cwd=cwd, roots=roots)
        if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            return self.check_write(tool_input.get("file_path") or tool_input.get("notebook_path", ""), cwd)
        if tool_name in ("Bash", "PowerShell"):
            if not self.shell:
                return "%s has no shell" % self.role
            command = tool_input.get("command", "")
            reason = check_shell_fund(command, cwd=cwd)
            if reason is None and "build_fund.sh" in command:
                if self.builds >= self.max_builds:
                    return "build limit reached for this round (%d)" % self.max_builds
                self.builds += 1
            return reason
        if tool_name in ("WebFetch", "WebSearch"):
            return guards.check_url(tool_input.get("url", "") or tool_input.get("query", ""))
        if tool_name.startswith("mcp__evidence__"):
            return None
        return "tool %s is not available to %s" % (tool_name, self.role)
