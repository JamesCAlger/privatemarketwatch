"""Orchestrator decisions (spec section 7): a fixed menu, enforced in code.

The orchestrator agent proposes; ``enforce`` turns a proposal into what the driver will do. It can
never accept, close or record anything, overrule a reviewer, or lift a limit.
"""
from __future__ import annotations

from config import MAX_ROUNDS

MENU = ("continue", "return_with_notes", "dispute_to_reviewer", "recheck_sample_row", "park", "ask_owner", "stop_run")

# Which decisions make sense at which decision point; anything else falls back to continue.
POINTS = {
    "after_checks": ("continue", "return_with_notes", "park", "ask_owner", "stop_run"),
    "after_review": ("continue", "return_with_notes", "dispute_to_reviewer", "recheck_sample_row", "park", "ask_owner", "stop_run"),
    "agent_stopped": ("continue", "park", "ask_owner", "stop_run"),
    "route_investigation": ("continue", "park", "ask_owner"),
    "end_of_run": ("continue",),
}

SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": list(MENU)},
        "reason": {"type": "string"},
        "notes": {"type": "string"},
        "items": {"type": "array", "items": {"type": "string"}},
        "question": {"type": "string"},
    },
    "required": ["decision", "reason"],
    "additionalProperties": False,
}


def enforce(point: str, proposal: dict | None, *, round_no: int, items_known: set[str] | None = None) -> dict:
    """Return {decision, reason, notes, items, question, overridden}. Never raises."""
    out = {"decision": "continue", "reason": "", "notes": "", "items": [], "question": "", "overridden": ""}
    if not isinstance(proposal, dict):
        out["overridden"] = "no structured decision; continue"
        return out
    decision = proposal.get("decision")
    out.update({k: proposal.get(k) or out[k] for k in ("reason", "notes", "question")})
    items = [i for i in (proposal.get("items") or []) if isinstance(i, str)]
    if decision not in MENU:
        out["overridden"] = "off-menu decision %r; continue" % decision
        return out
    if decision not in POINTS.get(point, ()):
        out["overridden"] = "%s not available at %s; continue" % (decision, point)
        return out
    if decision == "return_with_notes" and round_no >= MAX_ROUNDS:
        out["decision"], out["overridden"] = "park", "round limit %d reached; parked instead of returned" % MAX_ROUNDS
        return out
    if decision in ("dispute_to_reviewer", "recheck_sample_row", "ask_owner"):
        if items_known is not None:
            unknown = [i for i in items if i not in items_known]
            items = [i for i in items if i in items_known]
            if unknown:
                out["overridden"] = "unknown items dropped: %s" % unknown[:5]
        if not items and decision != "ask_owner":
            out["decision"], out["overridden"] = "continue", "%s with no known items; continue" % decision
            return out
    if decision == "ask_owner" and not out["question"]:
        out["decision"], out["overridden"] = "continue", "ask_owner without a question; continue"
        return out
    out["decision"], out["items"] = decision, items
    return out
