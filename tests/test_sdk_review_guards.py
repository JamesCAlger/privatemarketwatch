"""Guard rules for SDK review agents (scripts/sdk_review/guards.py). No network, no SDK call."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "sdk_review"))
import guards  # noqa: E402

REPO = guards.REPO
RUN = REPO / "scratch" / "sdk_review" / "0001786108_test"


def call(tool, **inp):
    return guards.check_call(tool, inp, run_dir=RUN)


# --- writes ---------------------------------------------------------------
def test_write_inside_run_dir_allowed():
    assert call("Write", file_path=str(RUN / "verdicts.json")) is None


@pytest.mark.parametrize("target", [
    "data/output/private_markets_holdings.csv",
    "data/decisions/0001786108.jsonl",
    "AGENTS.md",
    "scratch/sdk_review/0001786108_other/verdicts.json",   # a sibling run folder
    "scratch/sdk_review/0001786108_test/../x.json",        # traversal out of the run folder
])
def test_write_outside_run_dir_refused(target):
    assert call("Write", file_path=target) is not None


def test_edit_refused_even_inside_repo():
    assert call("Edit", file_path="pipeline/unified_holdings.py") is not None


# --- reads ----------------------------------------------------------------
def test_read_repo_file_allowed():
    assert call("Read", file_path="pipeline/decision_store.py") is None
    assert call("Grep", path="data/raw") is None
    assert call("Glob") is None


@pytest.mark.parametrize("target", [
    str(Path.home() / ".claude" / "settings.json"),
    # A drive-letter path is absolute only on Windows; elsewhere it is a relative path inside the repo.
    pytest.param("C:/Windows/win.ini", marks=pytest.mark.skipif(sys.platform != "win32", reason="drive-letter path is relative off Windows")),
    ".env",
])
def test_read_outside_repo_or_secret_refused(target):
    assert call("Read", file_path=target) is not None


def test_read_cli_spilled_tool_result_allowed_but_not_other_claude_files():
    proj = Path.home() / ".claude" / "projects" / "C--x"
    assert call("Read", file_path=str(proj / "sess" / "tool-results" / "toolu_1.txt")) is None
    assert call("Read", file_path=str(proj / "memory" / "MEMORY.md")) is not None
    assert call("Read", file_path=str(proj / "sess.jsonl")) is not None


# --- tools ----------------------------------------------------------------
@pytest.mark.parametrize("tool", ["Task", "Agent", "SomethingNew"])
def test_unknown_tools_refused(tool):
    assert call(tool) is not None


def test_evidence_tools_allowed():
    assert call("mcp__evidence__page_line", accession="0001234567-24-000028", phrase="x") is None


def test_sec_fetch_refused_other_url_allowed():
    assert call("WebFetch", url="https://www.sec.gov/Archives/edgar/data/1/2.htm") is not None
    assert call("WebFetch", url="https://example.com/") is None


# --- shell rules (for Claude Code hooks later) ------------------------------
@pytest.mark.parametrize("cmd", [
    "python - <<'EOF'\nprint(1)\nEOF",
    "cd x && python -",
    "python3 << EOF\nimport duckdb\nEOF",
    "python -c \"" + "x=1;" * 60 + "\"",
    "git checkout -- data/overrides/row_corrections.csv",
    "git reset --hard ensemble-fp-experiment",
    "curl -s https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
])
def test_shell_breaches_refused(cmd):
    assert guards.check_shell(cmd) is not None


@pytest.mark.parametrize("cmd", [
    "python scripts/v05_evidence/page_line.py 1786108 0001234567-24-000028 \"Acme\"",
    "python -c \"import sys; print(sys.version)\"",          # short inline is allowed
    "python -m pytest tests/test_sdk_review_guards.py -q",
    "grep -n edgar_client pipeline/config.py",              # mentions edgar, no network tool
    "git status --short",
    "git diff --name-only",
])
def test_shell_ordinary_commands_allowed(cmd):
    assert guards.check_shell(cmd) is None


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE cik = 1786108",
    "WITH h AS (SELECT * FROM read_parquet('{S}/row_validation_issues.parquet')) SELECT count(*) FROM h;",
    "SELECT last_update, fair_value FROM read_csv_auto('{S}/x.csv')",   # 'update' inside a word is fine
])
def test_sql_read_only_select_allowed(sql):
    tools = pytest.importorskip("tools")
    assert tools.sql_problem(sql) is None


@pytest.mark.parametrize("sql", [
    "COPY (SELECT 1) TO 'data/output/x.csv'",
    "SELECT 1; DROP TABLE t",
    "SELECT * FROM read_parquet('data/output/private_markets_holdings.parquet')",
    "SELECT * FROM read_parquet('{S}/../../../data/output/x.parquet')",
    "ATTACH 'x.duckdb'",
    "SELECT * FROM read_text('C:/Users/alger/.claude/settings.json')",
    "SET memory_limit='20GB'",
])
def test_sql_writes_and_escapes_refused(sql):
    tools = pytest.importorskip("tools")
    assert tools.sql_problem(sql) is not None


def test_git_reset_allowed_inside_worktree():
    wt = REPO / ".claude" / "worktrees" / "agent-x"
    assert guards.check_shell("git reset --hard ensemble-fp-experiment", cwd=wt) is None
