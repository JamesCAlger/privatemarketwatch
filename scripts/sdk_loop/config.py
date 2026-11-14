"""Constants for the SDK fund loop. Values marked 'starting value' are revised from the cost ledger."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUN_ROOT = REPO / "scratch" / "sdk_loop"
WORKTREE_ROOT = REPO / ".claude" / "worktrees"
STATUS_CSV = REPO / "docs" / "investigations" / "findings_status.csv"
OBSERVATIONS_CSV = REPO / "docs" / "investigations" / "v05_observations.csv"
BRIEF_DIR = REPO / ".claude" / "skills" / "v05-fund-clearing"
READER_BRIEF = REPO / "docs" / "investigations" / "v05_field_sample" / "reader_brief.md"
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"

SDK_VERSION_MIN = (0, 2, 0)   # 0.1.x loaded no settings by default; 0.2.x loads all unless told

MODELS = {
    "fund_agent": "claude-sonnet-5-5",
    "reviewer": "claude-opus-5-5",
    "reader": "claude-sonnet-5-5",
    "orchestrator": "claude-opus-5-5",
    "investigator": "claude-opus-5-5",
    "shared_fix": "claude-opus-5-5",
}
EFFORT = {"fund_agent": "high", "reviewer": "high", "reader": "medium", "orchestrator": "medium",
          "investigator": "high", "shared_fix": "high"}

# Per-agent caps passed to the SDK (starting values).
AGENT_CAP_USD = {"fund_agent": 8.0, "reviewer": 4.0, "reader": 1.0, "orchestrator": 1.0,
                 "investigator": 5.0, "shared_fix": 8.0}
MAX_TURNS = {"fund_agent": 400, "reviewer": 200, "reader": 80, "orchestrator": 30,
             "investigator": 200, "shared_fix": 400}

MAX_ROUNDS = 4
MAX_BUILDS_PER_ROUND = 6
MAX_AGENT_ERRORS = 2
MAX_INVESTIGATIONS = 3
MAX_SHARED_FIXES = 1
SAMPLE_ROWS = 20
MIN_FREE_GB = 6.0             # a fund build; the unified build is never run by the loop

# Paths in the main checkout whose state must not change during a run (section 5, check 2).
PROTECTED = ("data/output", "frontend/public/data", "data/decisions", "data/overrides")
# Paths a fund change may touch that the main checkout must not have uncommitted (precondition).
SHARED_OVERRIDE_FILES = ("data/overrides/row_corrections.csv", "data/overrides/row_corrections_by_context.csv",
                         "data/overrides/finding_dispositions/fundloop_accepted_by_check.json")


def allowed_paths(cik10: str) -> tuple[str, ...]:
    """Regexes (repo-relative, forward slashes) a fund agent may write. Shared code is allowed here
    and judged afterwards (fund_gate 'files': it must be declared and tested)."""
    c = cik10
    return (
        r"^data/overrides/bdc_xbrl_wrappers/%s\.json$" % c,
        r"^data/overrides/fund_highlights_wrappers/%s\.json$" % c,
        r"^data/overrides/position_match_overrides/%s\.json$" % c,
        r"^data/overrides/row_corrections(_by_context)?\.csv$",
        r"^data/overrides/agent_investigate_rules/%s/" % c,
        r"^data/overrides/finding_dispositions_proposed/fund_%s\.json$" % c,
        r"^data/overrides/finding_dispositions/fundloop_accepted_by_check\.json$",
        r"^data/overrides/verdict_retirements/[^/]*%s[^/]*\.json$" % c,
        r"^scripts/v05_evidence/row_correction_specs/%s[^/]*$" % c,
        r"^scratch/",
        r"^pipeline/[^/]+\.py$", r"^scripts/(?!v05_evidence/fund_gate|v05_evidence/investigation_review)[^/]+\.py$",
        r"^tests/test_[^/]+\.py$", r"^schemas/",
    )


SHARED_CODE_RES = (r"^pipeline/", r"^scripts/(?!v05_evidence/row_correction_specs/)", r"^tests/", r"^schemas/")
