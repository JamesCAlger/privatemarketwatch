"""One status per finding: who acts next.

The findings ledger (``scripts/findings_ledger.py``) gives every finding a detailed lifecycle
state. Those states describe history. ``status_of`` maps a detailed state, plus the facts the
decision store holds about the finding, to one of six statuses that say what happens next. It is
the only place that mapping lives: the ledger, the status view and work selection all call it.

The acceptance gate is unchanged: outstanding = state not in
``pipeline.quarter_acceptance.RESOLVED_FINDING_STATES``, which is exactly status != ``closed``.

First match wins:

  1  state is resolved                                              closed
  2  a fix is recorded and no build has run since                   fix_awaiting_build
  3  a check-repair request stands, or a proposal says the check
     misfires (class rule_problem / false_alarm)                    needs_check_repair
  4  state needs a human (needs_human, evidence_backlog)            needs_owner_ruling
  5  a proposal in a store class stands (as_filed, not_applicable,
     informational)                                                 needs_owner_ruling
  6  state carries a real-error verdict                             needs_data_fix
  7  supported fund-agent conclusion confirmed_error                needs_data_fix
  8  supported fund-agent conclusion false_alarm                    needs_check_repair
  9  supported fund-agent conclusion source_ambiguity               needs_owner_ruling
  10 anything else                                                  needs_agent_review

An unknown detailed state raises: a state nobody mapped must not be counted as anything.
"""
from __future__ import annotations

from dataclasses import dataclass

NEEDS_AGENT_REVIEW = "needs_agent_review"
NEEDS_DATA_FIX = "needs_data_fix"
NEEDS_CHECK_REPAIR = "needs_check_repair"
NEEDS_OWNER_RULING = "needs_owner_ruling"
FIX_AWAITING_BUILD = "fix_awaiting_build"
CLOSED = "closed"
STATUSES = (NEEDS_AGENT_REVIEW, NEEDS_DATA_FIX, NEEDS_CHECK_REPAIR, NEEDS_OWNER_RULING,
            FIX_AWAITING_BUILD, CLOSED)

# Kept equal to pipeline.quarter_acceptance.RESOLVED_FINDING_STATES (a test compares them); listed
# here so this module imports nothing heavy.
RESOLVED_STATES = frozenset({
    "adjudicated_false_alarm", "remediated_promoted", "resolved_upstream", "gone_unadjudicated",
    "verdict_retired", "dispositioned_informational", "dispositioned_as_filed",
    "dispositioned_not_applicable"})
HUMAN_STATES = frozenset({"needs_human", "evidence_backlog"})
REAL_ERROR_STATES = frozenset({
    "real_error_unremediated", "remediation_staged", "remediation_pulled", "real_error_check_silent",
    "b1_route_missing", "b2_execution_unproven", "b3_pass_pending_promotion",
    "promoted_pending_verification"})
UNREVIEWED_STATES = frozenset({"open", "b1_re_adjudication_required", "unverified_absence"})
KNOWN_STATES = RESOLVED_STATES | HUMAN_STATES | REAL_ERROR_STATES | UNREVIEWED_STATES

MISFIRE_CLASSES = frozenset({"rule_problem", "false_alarm"})
STORE_CLASSES = frozenset({"as_filed", "not_applicable", "informational"})
CONCLUSIONS = ("confirmed_error", "false_alarm", "source_ambiguity", "insufficient_evidence")


@dataclass(frozen=True)
class Facts:
    """What the decision store says about one finding (see pipeline.decision_store.facts_by_finding)."""
    fix_queued: bool = False          # a standing fix_record newer than the ledger's build names it
    check_repair: bool = False        # a standing check_repair_request names it
    proposal_class: str = ""          # class of a proposal that still bears on it, else ""
    conclusion: str = ""              # fund agent's conclusion, "" when none
    conclusion_supported: bool = False  # an independent review supported that conclusion


NO_FACTS = Facts()


def status_of(state: str, facts: Facts = NO_FACTS) -> str:
    """The status of a finding in detailed state ``state`` given ``facts``."""
    if state not in KNOWN_STATES:
        raise ValueError("unknown finding state: %r" % (state,))
    if state in RESOLVED_STATES:
        return CLOSED
    if facts.fix_queued:
        return FIX_AWAITING_BUILD
    if facts.check_repair or facts.proposal_class in MISFIRE_CLASSES:
        return NEEDS_CHECK_REPAIR
    if state in HUMAN_STATES:
        return NEEDS_OWNER_RULING
    if facts.proposal_class in STORE_CLASSES:
        return NEEDS_OWNER_RULING
    if state in REAL_ERROR_STATES:
        return NEEDS_DATA_FIX
    if facts.conclusion_supported:
        if facts.conclusion == "confirmed_error":
            return NEEDS_DATA_FIX
        if facts.conclusion == "false_alarm":
            return NEEDS_CHECK_REPAIR
        if facts.conclusion == "source_ambiguity":
            return NEEDS_OWNER_RULING
    return NEEDS_AGENT_REVIEW


def is_outstanding(status: str) -> bool:
    return status != CLOSED
