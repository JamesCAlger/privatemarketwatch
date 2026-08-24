"""Re-assemble source-reconciliation legacy artifacts from cached per-CIK parquets.

Use after changing the ARTIFACT-layer classifiers (build_source_only_blocker_detail /
residual classification) while the reconciliation partitions themselves are clean --
the reconciliation logic hash covers only the matching path, so classifier-only
changes do not dirty the cache and the runner's clean branch would skip assembly.
Mirrors the assembly branch of run_bdc_source_reconciliation_cached exactly.

Usage: python scripts/reassemble_source_recon_artifacts.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.source_reconciliation import (  # noqa: E402
    DETAIL_COLUMNS,
    METRIC_COLUMNS,
    _assemble_legacy_reconciliation_outputs,
    _read_parquet_glob,
)
from pipeline.config import (  # noqa: E402
    SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR,
    SOURCE_RECONCILIATION_METRICS_BY_CIK_DIR,
)


def main() -> int:
    t0 = time.time()
    detail_paths = sorted(SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR.glob("*.parquet"))
    metrics_paths = sorted(SOURCE_RECONCILIATION_METRICS_BY_CIK_DIR.glob("*.parquet"))
    if not detail_paths:
        print("No cached detail partitions found; run the reconciliation first.")
        return 1
    print(f"[reassemble] reading {len(detail_paths)} detail partitions ...")
    detail = _read_parquet_glob(detail_paths, DETAIL_COLUMNS)
    if not detail.empty:
        detail = detail[DETAIL_COLUMNS].sort_values(
            ["cik", "report_date", "accession_number", "raw_investment_identifier", "status"]
        ).reset_index(drop=True)
    metrics = _read_parquet_glob(metrics_paths, METRIC_COLUMNS)
    if not metrics.empty:
        metrics = metrics[METRIC_COLUMNS].sort_values(["cik", "report_date"]).reset_index(drop=True)
    print(f"[reassemble] detail rows: {len(detail)}, metrics rows: {len(metrics)} "
          f"({time.time() - t0:.0f}s)")
    _assemble_legacy_reconciliation_outputs(detail, metrics)
    print(f"[reassemble] artifacts written ({time.time() - t0:.0f}s total)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
