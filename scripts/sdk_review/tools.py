"""Read-only evidence tools for SDK review agents.

Each tool runs one existing script in scripts/v05_evidence/ as a subprocess (no inline Python),
with the fund's CIK and sandbox label fixed by the runner, so the agent cannot point a tool at
another fund or sandbox. Output is cut at MAX_CHARS. ASCII only.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

REPO = Path(__file__).resolve().parents[2]
EV = REPO / "scripts" / "v05_evidence"
MAX_CHARS = 20000
TIMEOUT_S = 180
_ACC = re.compile(r"^\d{10}-?\d{2}-?\d{6}$")
_SAFE = re.compile(r"^[A-Za-z0-9_.:\-]+$")


def dashed(acc: str) -> str:
    a = acc.replace("-", "")
    return "%s-%s-%s" % (a[:10], a[10:12], a[12:])


async def _run(script: str, *args: str, repo: Path = REPO) -> str:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(script if Path(script).is_absolute() else repo / "scripts" / "v05_evidence" / script), *args, cwd=str(repo), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return "timed out after %ds" % TIMEOUT_S
    text = out.decode("utf-8", errors="replace")
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n[cut at %d characters; narrow the query]" % MAX_CHARS
    return text or "(no output)"


def _reply(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _refuse(text: str) -> dict:
    return {"content": [{"type": "text", "text": "refused: " + text}], "is_error": True}


_SQL_WRITE = re.compile(r"\b(copy|attach|detach|install|load|export|import|create|insert|update|delete|drop|alter|"
                        r"pragma|set|call|checkpoint|vacuum)\b|write_|read_text|read_blob|read_json|parquet_scan|"
                        r"sniff_csv|glob\s*\(|getenv", re.I)


def sql_problem(sql: str, placeholder: str = "{S}") -> str | None:
    """None for one SELECT/WITH statement that reads only files under the placeholder folder;
    else why it is refused. Any string literal that looks like a path must start with it."""
    body = sql.strip().rstrip(";").strip()
    if ";" in body:
        return "one statement only"
    if not re.match(r"^(select|with)\b", body, re.I):
        return "SELECT or WITH only"
    if _SQL_WRITE.search(body):
        return "read-only queries only (no COPY, ATTACH, SET, file functions other than read_parquet/read_csv)"
    for literal in re.findall(r"'([^']*)'", body):
        if re.search(r"[/\\]|^[A-Za-z]:|\.(parquet|csv|json|duckdb|txt)$", literal, re.I):
            if not literal.startswith(placeholder + "/") or ".." in literal:
                return "read only files under %s/" % placeholder
    return None


ALL_TOOLS = ("page_line", "filing_grep", "flagged", "left", "verdicts", "sandbox_sql", "cohort_sql")
COHORT_SQL = Path(__file__).resolve().parents[1] / "sdk_loop" / "cohort_sql.py"


def build_server(cik: str, label: str | None, sql_dir: Path, repo: Path = REPO,
                 include: tuple[str, ...] = ("page_line", "filing_grep", "flagged", "left", "verdicts", "sandbox_sql")):
    """The evidence MCP server for one fund and one sandbox; SQL files go to sql_dir (the run folder).
    ``repo`` is the checkout whose scripts and sandboxes are used (a fund's worktree in the loop);
    ``include`` picks the tools a role gets. ``cik`` may be empty for cohort-wide roles."""
    cik10 = cik.zfill(10) if cik else ""

    async def run(script: str, *args: str) -> str:
        if label is None and script in ("flagged.py", "left.py", "verdicts.py", "sandbox_sql.py"):
            return "refused: this role has no sandbox"
        return await _run(script, *args, repo=repo)

    @tool("page_line", "Printed schedule lines for a phrase in a cached filing of this fund. "
          "Copy quotes from this output: it is normalised the way decide.py checks quotes.",
          {"type": "object", "properties": {
              "accession": {"type": "string"}, "phrase": {"type": "string"},
              "max_hits": {"type": "integer"}, "chars_after": {"type": "integer"}},
           "required": ["accession", "phrase"]})
    async def page_line(a):
        if not _ACC.match(a["accession"]):
            return _refuse("accession must look like 0001234567-24-000028")
        return _reply(await run("page_line.py", cik10, dashed(a["accession"]), a["phrase"],
                                 str(min(int(a.get("max_hits", 4)), 20)), str(min(int(a.get("chars_after", 350)), 2000))))

    @tool("filing_grep", "Text around a phrase in a cached filing (kind=html), or the XBRL facts on a "
          "context and its sibling contexts (kind=xml, phrase=context id).",
          {"type": "object", "properties": {
              "accession": {"type": "string"}, "kind": {"type": "string", "enum": ["html", "xml"]},
              "phrase": {"type": "string"}, "max_hits": {"type": "integer"}},
           "required": ["accession", "kind", "phrase"]})
    async def filing_grep(a):
        if not _ACC.match(a["accession"]):
            return _refuse("accession must look like 0001234567-24-000028")
        return _reply(await run("filing_grep.py", cik10, a["accession"].replace("-", ""), a["kind"],
                                 a["phrase"], str(min(int(a.get("max_hits", 4)), 20))))

    @tool("flagged", "Published rows one row rule flags for this fund in one quarter (from the sandbox).",
          {"type": "object", "properties": {
              "rule": {"type": "string"}, "quarter": {"type": "string"}, "max_rows": {"type": "integer"}},
           "required": ["rule", "quarter"]})
    async def flagged(a):
        if not _SAFE.match(a["rule"]) or not re.match(r"^\d{4}-\d{2}-\d{2}$", a["quarter"]):
            return _refuse("rule must be a rule id and quarter YYYY-MM-DD")
        return _reply(await run("flagged.py", label, a["rule"], cik10, a["quarter"],
                                 str(min(int(a.get("max_rows", 40)), 200))))

    @tool("left", "Unresolved ledger rows in the sandbox for the given rules (all funds; filter by this CIK).",
          {"type": "object", "properties": {"rules": {"type": "array", "items": {"type": "string"}}},
           "required": ["rules"]})
    async def left(a):
        rules = [r for r in a["rules"] if _SAFE.match(r)][:10]
        if not rules:
            return _refuse("give one to ten rule ids")
        return _reply(await run("left.py", label, *rules))

    @tool("verdicts", "Earlier reviewers' recorded verdicts behind unresolved findings in the sandbox ledger.",
          {"type": "object", "properties": {"chars": {"type": "integer"}}})
    async def verdicts(a):
        return _reply(await run("verdicts.py", label, str(min(int(a.get("chars", 1500)), 4000))))

    @tool("sandbox_sql", "One read-only DuckDB SELECT against this sandbox's outputs; write {S} for the "
          "output folder, e.g. SELECT * FROM read_parquet('{S}/private_markets_holdings.parquet') WHERE ... "
          "At most 80 rows are printed.",
          {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]})
    async def sandbox_sql(a):
        problem = sql_problem(a["sql"])
        if problem:
            return _refuse(problem)
        path = sql_dir / ("q_%d.sql" % (len(list(sql_dir.glob("q_*.sql"))) + 1))
        path.write_text(a["sql"], encoding="utf-8")
        return _reply(await run("sandbox_sql.py", label, str(path)))

    @tool("cohort_sql", "One read-only DuckDB SELECT over the PUBLISHED outputs of the whole cohort; write {P} "
          "for data/output, e.g. SELECT cik, count(*) FROM read_parquet('{P}/private_markets_holdings.parquet') GROUP BY 1. "
          "At most 200 rows are printed.",
          {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]})
    async def cohort_sql(a):
        problem = sql_problem(a["sql"], placeholder="{P}")
        if problem:
            return _refuse(problem)
        path = sql_dir / ("c_%d.sql" % (len(list(sql_dir.glob("c_*.sql"))) + 1))
        path.write_text(a["sql"], encoding="utf-8")
        return _reply(await _run(str(COHORT_SQL), str(path), repo=REPO))

    by_name = {"page_line": page_line, "filing_grep": filing_grep, "flagged": flagged, "left": left,
               "verdicts": verdicts, "sandbox_sql": sandbox_sql, "cohort_sql": cohort_sql}
    chosen = [n for n in ALL_TOOLS if n in include]
    return (create_sdk_mcp_server(name="evidence", version="1.0.0", tools=[by_name[n] for n in chosen]),
            ["mcp__evidence__" + n for n in chosen])
