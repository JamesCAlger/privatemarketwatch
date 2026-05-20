"""Canonical CIK-quarter GAV reconciliation entry point.

The implementation currently lives in ``pipeline.validate_holdings`` for
backward compatibility with existing callers and tests.  This module is the
stable import path for new validation/export code.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def build_gav_reconciliation(
    unified_df: Optional[pd.DataFrame] = None,
    fund_financials_df: Optional[pd.DataFrame] = None,
    nport_fund_info_df: Optional[pd.DataFrame] = None,
    bdc_source_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Build per-CIK/report-date holdings-to-denominator reconciliation."""
    from pipeline.validate_holdings import check_gav_reconciliation

    return check_gav_reconciliation(
        unified_df=unified_df,
        fund_financials_df=fund_financials_df,
        nport_fund_info_df=nport_fund_info_df,
        bdc_source_df=bdc_source_df,
    )
