"""Guard rules for SDK review agents (and, later, Claude Code hooks).

Pure functions: each returns None when a tool call is allowed, or the reason it is refused.
They read the call's text before it runs, so they stop habits and mistakes, not a determined
agent: the after-the-fact checks (decide.py quote check, fund_gate, diff_outputs --semantic)
remain the real protection. ASCII only.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Never readable, even inside the repo.
SECRET_PARTS = (".env", "auth.json", ".credentials", ".git/config", "id_rsa", ".claude/settings")

# Shell rules: shared with Claude Code hooks later; the review agent gets no shell at all.
INLINE_PY_MAX = 200
_PY_STDIN = re.compile(r"\bpython[0-9.]*(\.exe)?\s+-(\s|$)")
_PY_HEREDOC = re.compile(r"\bpython[0-9.]*(\.exe)?\b[^|;&]*<<")
_PY_INLINE = re.compile(r"\bpython[0-9.]*(\.exe)?\s+(-[A-Za-z]+\s+)*-c\s+(.*)", re.S)
_GIT_REVERT = re.compile(r"\bgit\s+(checkout\s+--\s|reset\s+--hard|clean\s+-[a-z]*f|restore\s)")
_SEC = re.compile(r"(sec\.gov|edgar)", re.I)


def _resolve(path: str, cwd: Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = cwd / p
    return p.resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _cli_tool_result(p: Path) -> bool:
    """The CLI saves a large tool output to ~/.claude/projects/<project>/<session>/tool-results/ and
    tells the agent to read it there; that file is the agent's own output, so it is readable."""
    parts = p.parts
    base = (Path.home() / ".claude" / "projects").resolve()
    return _inside(p, base) and len(parts) >= 2 and parts[-2] == "tool-results" and p.suffix == ".txt"


def check_read(path: str, *, cwd: Path = REPO, roots: tuple[Path, ...] = (REPO,)) -> str | None:
    if not path:
        return None  # Grep/Glob without a path search the cwd, which is the repo
    p = _resolve(path, cwd)
    if _cli_tool_result(p):
        return None
    if not any(_inside(p, r) for r in roots):
        return "reading outside the repository is not allowed: %s" % p
    text = p.as_posix().lower()
    if any(part in text for part in SECRET_PARTS):
        return "this file may hold credentials and is not readable: %s" % p
    return None


def check_write(path: str, *, run_dir: Path, cwd: Path = REPO) -> str | None:
    p = _resolve(path, cwd)
    if not _inside(p, run_dir):
        return "write only inside your run folder %s; refused: %s" % (run_dir.as_posix(), p)
    return None


def check_shell(command: str, *, cwd: Path = REPO, allow_sec: bool = False) -> str | None:
    if _PY_STDIN.search(command) or _PY_HEREDOC.search(command):
        return "no 'python -' or heredoc Python (AGENTS.md): write a named .py file in scratch and run it"
    m = _PY_INLINE.search(command)
    if m and len(m.group(3)) > INLINE_PY_MAX:
        return "inline 'python -c' over %d characters (AGENTS.md): use a named .py file" % INLINE_PY_MAX
    if _GIT_REVERT.search(command) and ".claude/worktrees/" not in (cwd.as_posix() + " " + command):
        return "git checkout --/reset --hard/clean/restore only inside .claude/worktrees/ (do not revert others' changes)"
    if not allow_sec and _SEC.search(command) and re.search(r"\b(curl|wget|Invoke-WebRequest|iwr|requests)\b", command):
        return "no SEC/EDGAR network calls without the owner's explicit go; use the cached filings"
    return None


def check_url(url: str, *, allow_sec: bool = False) -> str | None:
    if not allow_sec and _SEC.search(url or ""):
        return "no SEC/EDGAR fetches without the owner's explicit go; use the cached filings"
    return None


def check_call(tool_name: str, tool_input: dict, *, run_dir: Path, cwd: Path = REPO) -> str | None:
    """One decision for any tool call a review agent makes."""
    roots = (REPO, run_dir)
    if tool_name == "Read":
        return check_read(tool_input.get("file_path", ""), cwd=cwd, roots=roots)
    if tool_name in ("Grep", "Glob"):
        return check_read(tool_input.get("path", ""), cwd=cwd, roots=roots)
    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return check_write(tool_input.get("file_path") or tool_input.get("notebook_path", ""), run_dir=run_dir, cwd=cwd)
    if tool_name in ("Bash", "PowerShell"):
        return check_shell(tool_input.get("command", ""), cwd=cwd)
    if tool_name in ("WebFetch", "WebSearch"):
        return check_url(tool_input.get("url", "") or tool_input.get("query", ""))
    if tool_name.startswith("mcp__evidence__"):
        return None  # our own read-only tools; they check their own arguments
    return "tool %s is not available to review agents" % tool_name
