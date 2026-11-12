"""What one batch build did to the findings: the previous ledger against the new one.

``compare`` returns one row per finding that moved, or that a recorded fix expected to move:

  fixed                     a fix named it; it was outstanding and is now closed or gone
  fixed_pending_retirement  a fix named it; its check is silent but a real-error verdict still
                            stands (retire the verdict on evidence, or it stays outstanding)
  failed_fix                a fix named it; it is still outstanding and its check still fires
  unexplained_silence       it had been reviewed, no fix named it, and it stopped firing. A check
                            that goes quiet without a fix may have been taught to miss the error.
  closed_other              it closed without a fix naming it: a disposition, a retirement, or a
                            never-reviewed finding that stopped firing (owner decision 8)
  new_finding               not in the previous ledger, outstanding now
  reopened                  closed before, outstanding now

``outside_expected_funds`` marks a moved finding whose fund no fix in the batch named: a fix that
moves another fund's findings is a regression until explained.

Limit, stated where the result is reported: a reviewed finding with no reviewer verdict file that
stops firing leaves the ledger (state gone_unadjudicated, or absent). It is flagged
unexplained_silence here but is not held outstanding by the gate.
"""
from __future__ import annotations

from collections import Counter

from pipeline import finding_status

OUTCOMES = ("fixed", "fixed_pending_retirement", "failed_fix", "unexplained_silence", "closed_other",
            "new_finding", "reopened")
SILENT_STATES = frozenset({"real_error_check_silent"})
VANISHED_STATES = frozenset({"gone_unadjudicated", ""})
COLUMNS = ["review_id", "cik", "engine", "rule_name", "report_date", "prior_state", "state",
           "prior_status", "status", "outcome", "outside_expected_funds", "fix_ids"]


def _status(row: dict | None) -> str:
    if row is None:
        return ""
    return row.get("status") or finding_status.status_of(row["state"])


def _out(row: dict | None) -> bool:
    return row is not None and _status(row) != finding_status.CLOSED


def compare(prior: list[dict], current: list[dict], fix_records: list[dict] = ()) -> list[dict]:
    """``fix_records``: the standing fix_record decisions this batch carried (decision_store)."""
    before = {r["review_id"]: r for r in prior}
    after = {r["review_id"]: r for r in current}
    expected: dict[str, list[str]] = {}
    expected_funds: set[str] = set()
    for fix in fix_records:
        expects = fix.get("expects") or {}
        expected_funds.update(str(c).zfill(10) for c in expects.get("ciks", []))
        for rid in expects.get("finding_ids", []):
            expected.setdefault(rid, []).append(str(fix.get("decision_id") or ""))
    rows = []
    for rid in sorted(set(before) | set(after) | set(expected)):
        old, new = before.get(rid), after.get(rid)
        named = rid in expected
        was_out, is_out = _out(old), _out(new)
        new_state = (new or {}).get("state", "")
        outcome = ""
        if old is None and new is None:
            continue  # a fix named a finding neither ledger holds
        if old is None:
            outcome = "new_finding" if is_out else ""
        elif was_out and not is_out:
            reviewed = _status(old) != finding_status.NEEDS_AGENT_REVIEW
            if named:
                outcome = "fixed"
            elif new_state in VANISHED_STATES and reviewed:
                outcome = "unexplained_silence"
            else:
                outcome = "closed_other"
        elif was_out and is_out:
            went_silent = new_state in SILENT_STATES and old.get("state") not in SILENT_STATES
            if named:
                outcome = "fixed_pending_retirement" if new_state in SILENT_STATES else "failed_fix"
            elif went_silent:
                outcome = "unexplained_silence"
        elif not was_out and is_out:
            outcome = "reopened"
        if not outcome:
            continue
        ref = new or old
        cik = str(ref.get("cik") or "").zfill(10) if ref.get("cik") else ""
        rows.append({
            "review_id": rid, "cik": cik, "engine": ref.get("engine", ""), "rule_name": ref.get("rule_name", ""),
            "report_date": str(ref.get("report_date") or "")[:10],
            "prior_state": (old or {}).get("state", ""), "state": new_state,
            "prior_status": _status(old), "status": _status(new), "outcome": outcome,
            "outside_expected_funds": bool(fix_records) and not named and cik not in expected_funds,
            "fix_ids": ";".join(expected.get(rid, [])),
        })
    return rows


def summarize(rows: list[dict]) -> dict:
    counts = Counter(r["outcome"] for r in rows)
    return {"outcomes": {k: counts.get(k, 0) for k in OUTCOMES},
            "outside_expected_funds": sum(1 for r in rows if r["outside_expected_funds"]),
            "n_moved": len(rows)}
