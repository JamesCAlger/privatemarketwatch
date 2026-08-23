"""Tests for the audited Agent A basis_spread correction applier."""

import pandas as pd
import numpy as np

from pipeline.identifier_spread_corrections import (
    apply_spread_corrections,
    spread_changed_index,
)
from pipeline.agent_promoted import append_corrected_fields

_CORR = [
    {"cik": "0001993402", "report_date": "2025-03-31",
     "identifier": "Investments ... Acme LLC Asset Type First Lien S + 4.75% Interest Rate 9.04%",
     "new_value_decimal": 0.0475, "old_value_xbrl": 0.04},
]


def _df():
    return pd.DataFrame([
        {"cik": "1993402", "report_date": "2025-03-31 00:00:00",  # unpadded cik + datetime
         "bdc_investment_identifier": _CORR[0]["identifier"], "basis_spread": 0.04},
        {"cik": "0001993402", "report_date": "2025-03-31",        # no match (diff identifier)
         "bdc_investment_identifier": "Other Co Asset Type S + 6.00%", "basis_spread": 0.06},
    ])


def test_applies_to_matched_row_only():
    out, n = apply_spread_corrections(_df(), corrections=_CORR, log=lambda *_: None)
    assert n == 1
    assert out.iloc[0]["basis_spread"] == 0.0475   # overridden
    assert out.iloc[1]["basis_spread"] == 0.06      # untouched


def test_cik_and_date_normalization_match():
    # unpadded cik (1993402) and datetime report_date must still match
    out, n = apply_spread_corrections(_df(), corrections=_CORR, log=lambda *_: None)
    assert n == 1


def test_no_corrections_is_noop():
    df = _df()
    out, n = apply_spread_corrections(df, corrections=[], log=lambda *_: None)
    assert n == 0
    assert out.equals(df)


def test_idempotent_reapply():
    out1, n1 = apply_spread_corrections(_df(), corrections=_CORR, log=lambda *_: None)
    out2, n2 = apply_spread_corrections(out1, corrections=_CORR, log=lambda *_: None)
    assert n1 == n2 == 1
    assert out2.iloc[0]["basis_spread"] == 0.0475


def test_missing_columns_safe():
    df = pd.DataFrame([{"cik": "1", "report_date": "2025-03-31"}])  # no basis_spread/identifier
    out, n = apply_spread_corrections(df, corrections=_CORR, log=lambda *_: None)
    assert n == 0


def test_spread_stamp_nan_rows_not_falsely_marked():
    """NaN-safe stamp: rows with NaN basis_spread that are NOT corrected must not
    get 'basis_spread' stamped in corrected_fields.  Only the one corrected row
    (index 0) should be stamped; the NaN row (index 1) must stay empty.

    Uses spread_changed_index() -- the production helper from
    identifier_spread_corrections -- rather than an inline re-implementation,
    so this test exercises exactly the same code path as staging_bdc.py.
    """
    _CORR_SINGLE = [
        {"cik": "0001993402", "report_date": "2025-03-31",
         "identifier": _CORR[0]["identifier"],
         "new_value_decimal": 0.0475, "old_value_xbrl": 0.04},
    ]
    df = pd.DataFrame([
        {"cik": "1993402", "report_date": "2025-03-31 00:00:00",
         "bdc_investment_identifier": _CORR[0]["identifier"],
         "basis_spread": 0.04, "corrected_fields": ""},
        {"cik": "0001993402", "report_date": "2025-03-31",
         "bdc_investment_identifier": "NaN row no spread",
         "basis_spread": np.nan, "corrected_fields": ""},
    ])
    _spread_before = df["basis_spread"].copy()
    result, _n = apply_spread_corrections(
        df, corrections=_CORR_SINGLE, log=lambda *_: None
    )
    # Call the production helper (same code path as staging_bdc.py).
    _spread_changed = spread_changed_index(_spread_before, result["basis_spread"])
    if len(_spread_changed):
        append_corrected_fields(result, _spread_changed, ["basis_spread"])
    assert result.loc[0, "corrected_fields"] == "basis_spread"  # corrected row stamped
    assert result.loc[1, "corrected_fields"] == ""              # NaN row NOT stamped
