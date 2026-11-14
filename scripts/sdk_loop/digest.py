"""Print the investigation-review digest for a report, using a worktree's own gate code.

    python scripts/sdk_loop/digest.py <worktree> <label> <cik10> <report.json>

The reviewer must bind its review to this digest (investigation-review.md). Read-only.
"""
import json
import sys
from pathlib import Path

worktree, label, cik, report_path = Path(sys.argv[1]), sys.argv[2], sys.argv[3].zfill(10), Path(sys.argv[4])
sys.path.insert(0, str(worktree / "scripts" / "v05_evidence"))
import fund_gate  # noqa: E402
import investigation_review  # noqa: E402

if Path(fund_gate.REPO).resolve() != worktree.resolve():
    raise SystemExit("fund_gate imported from %s, not the worktree %s" % (fund_gate.REPO, worktree))
report = json.loads(report_path.read_text(encoding="utf-8"))
print(investigation_review.report_digest(report, fund_gate.outstanding_findings(label, cik)))
