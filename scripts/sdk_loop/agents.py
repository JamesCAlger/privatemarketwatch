"""Agent roles and the runner that calls the Agent SDK.

The driver only talks to a ``Runner``: ``SdkRunner`` calls the SDK; tests pass a stub. Every SDK
agent gets: its own system prompt, no project settings (``setting_sources=[]``: no CLAUDE.md,
AGENTS.md, memory or user hooks), only the tools its role needs, and a PreToolUse hook that applies
its ``Policy``.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from config import EFFORT, MAX_TURNS, MODELS, PROMPT_DIR, REPO, SDK_VERSION_MIN
from policy import Policy

sys.path.insert(0, str(REPO / "scripts" / "sdk_review"))

READ_TOOLS = ["Read", "Grep", "Glob"]
TOOLS = {
    "fund_agent": READ_TOOLS + ["Edit", "Write", "Bash"],
    "shared_fix": READ_TOOLS + ["Edit", "Write", "Bash"],
    "reviewer": READ_TOOLS + ["Write"],
    "reader": READ_TOOLS + ["Write"],
    "investigator": READ_TOOLS + ["Write"],
    "orchestrator": READ_TOOLS,
}
EVIDENCE = {
    "fund_agent": ("page_line", "filing_grep", "flagged", "left", "verdicts", "sandbox_sql"),
    "shared_fix": ("page_line", "filing_grep", "flagged", "left", "verdicts", "sandbox_sql", "cohort_sql"),
    "reviewer": ("page_line", "filing_grep", "flagged", "left", "verdicts", "sandbox_sql"),
    "reader": ("page_line", "filing_grep"),
    "investigator": ("page_line", "filing_grep", "cohort_sql"),
    "orchestrator": (),
}
NEVER = ["WebFetch", "WebSearch", "Task", "Agent", "NotebookEdit", "PowerShell", "Skill"]


@dataclass
class AgentSpec:
    role: str
    task: str                                  # the first user message
    prompt: str                                # the system prompt
    cwd: Path
    policy: Policy
    out_dir: Path                              # transcript and outputs
    cik: str = ""
    label: str | None = None                   # sandbox for evidence tools
    repo: Path = REPO                          # checkout for evidence tools
    max_budget_usd: float = 1.0
    output_schema: dict | None = None          # structured output (orchestrator)
    extra: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    ok: bool
    cost_usd: float = 0.0
    turns: int = 0
    duration_s: int = 0
    exit: str = ""                             # success | error_max_budget_usd | error_max_turns | error | ...
    summary: str = ""
    structured: dict | None = None
    usage: dict = field(default_factory=dict)


class Runner(Protocol):
    def __call__(self, spec: AgentSpec) -> AgentResult: ...


def load_prompt(name: str, **kw) -> str:
    text = (PROMPT_DIR / ("%s.md" % name)).read_text(encoding="utf-8")
    for key, value in kw.items():
        text = text.replace("{{%s}}" % key, str(value))
    return text


def check_sdk() -> str:
    import claude_agent_sdk
    version = tuple(int(x) for x in claude_agent_sdk.__version__.split(".")[:3])
    if version < SDK_VERSION_MIN:
        raise RuntimeError("claude-agent-sdk %s is older than %s" % (claude_agent_sdk.__version__, SDK_VERSION_MIN))
    return claude_agent_sdk.__version__


def _jsonable(msg) -> dict:
    body = dataclasses.asdict(msg) if dataclasses.is_dataclass(msg) else {"repr": repr(msg)}
    return {"kind": type(msg).__name__, **body}


class SdkRunner:
    """Calls the Agent SDK. Bills ANTHROPIC_API_KEY (the driver loads it from .env)."""

    def __call__(self, spec: AgentSpec) -> AgentResult:
        return asyncio.run(self._run(spec))

    async def _run(self, spec: AgentSpec) -> AgentResult:
        from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, ResultMessage, query
        from tools import build_server

        spec.out_dir.mkdir(parents=True, exist_ok=True)
        sql_dir = spec.out_dir / "sql"
        sql_dir.mkdir(exist_ok=True)
        include = EVIDENCE[spec.role]
        servers, evidence_names = {}, []
        if include:
            server, evidence_names = build_server(spec.cik, spec.label, sql_dir, repo=spec.repo, include=include)
            servers = {"evidence": server}

        async def guard(input_data, tool_use_id, context):
            reason = spec.policy.check(input_data.get("tool_name", ""), input_data.get("tool_input") or {}, spec.cwd)
            if reason:
                with open(spec.out_dir / "refusals.log", "a", encoding="utf-8") as fh:
                    fh.write("%s\t%s\t%s\n" % (time.strftime("%H:%M:%S"), input_data.get("tool_name"), reason))
                return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                               "permissionDecisionReason": reason}}
            return {}

        builtins = TOOLS[spec.role]
        options = ClaudeAgentOptions(
            system_prompt=spec.prompt,
            setting_sources=[],
            tools=builtins,
            allowed_tools=builtins + evidence_names,
            disallowed_tools=[t for t in NEVER + ["Bash", "Edit", "Write"] if t not in builtins],
            mcp_servers=servers,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[guard])]},
            permission_mode="default",
            cwd=str(spec.cwd),
            model=MODELS[spec.role],
            effort=EFFORT[spec.role],
            max_turns=MAX_TURNS[spec.role],
            max_budget_usd=spec.max_budget_usd,
            output_format={"type": "json_schema", "schema": spec.output_schema} if spec.output_schema else None,
            env={"ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"], "PYTHONIOENCODING": "utf-8",
                 "SDK_LOOP_DRIVER_PID": str(os.getpid())},
        )
        result = None
        turns = duration_ms = 0          # a session can end in several result messages (e.g. after a
        started = time.time()            # background task finishes); cost is cumulative, turns are not
        with open(spec.out_dir / ("%s_transcript.jsonl" % spec.role), "a", encoding="utf-8") as log:
            try:
                async for msg in query(prompt=spec.task, options=options):
                    log.write(json.dumps(_jsonable(msg), default=str, ensure_ascii=True) + "\n")
                    log.flush()
                    if isinstance(msg, ResultMessage):
                        result = msg
                        turns += msg.num_turns or 0
                        duration_ms += msg.duration_ms or 0
            except Exception as exc:  # the SDK raises on CLI failure; the driver counts it as an error
                log.write(json.dumps({"kind": "driver_error", "error": repr(exc)[:2000]}) + "\n")
                return AgentResult(ok=False, exit="error", summary=repr(exc)[:500], duration_s=int(time.time() - started))
        if result is None:
            return AgentResult(ok=False, exit="no_result", duration_s=int(time.time() - started))
        return AgentResult(ok=not result.is_error, cost_usd=result.total_cost_usd or 0.0, turns=turns,
                           duration_s=round(duration_ms / 1000), exit=result.subtype,
                           summary=(result.result or "")[:4000], structured=getattr(result, "structured_output", None),
                           usage=result.usage or {})
