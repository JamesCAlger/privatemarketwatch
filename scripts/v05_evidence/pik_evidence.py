"""Re-derive position PIK evidence inside a fund sandbox (the step sandbox_add_quarter.py runs). Cached files only."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
target = Path(os.environ.get("PM_OUTPUT_DIR", "")).resolve() if os.environ.get("PM_OUTPUT_DIR") else None
if target is None or (ROOT / "scratch" / "fund_sandbox").resolve() not in target.parents:
    raise SystemExit("PM_OUTPUT_DIR must point inside scratch/fund_sandbox")
from pipeline.bdc_position_pik import extract_bdc_position_pik_evidence  # noqa: E402

print("position PIK evidence: %d rows" % len(extract_bdc_position_pik_evidence()))
