"""Tests for the rebuild-stable row_id column (unified_holdings._assign_row_ids).

row_id must be: unique per row, deterministic on content, invariant to frame
row order and to issuer_name drift (both excluded from the natural key), and
sensitive to the fields that define row identity (principal_amount).
"""

import re

import pandas as pd
import pytest

from pipeline.unified_holdings import _assign_row_ids

_ROW_ID_RE = re.compile(r"^ROW-[0-9a-f]{16}$")


def _base_df() -> pd.DataFrame:
    return pd.DataFrame({
        "cik": ["0000000001", "0000000001", "0000000002"],
        "source": ["bdc", "bdc", "nport"],
        "report_date": ["2025-12-31", "2025-12-31", "2025-12-31"],
        "bdc_investment_identifier": [
            "Acme Corp | First Lien Term Loan | SOFR+5.00%",
            "Beta LLC | Second Lien Term Loan | SOFR+8.50%",
            "",
        ],
        "nport_holding_id": ["", "", "HOLDING-123"],
        "principal_amount": [1000000.0, 2000000.0, None],
        "shares_held": [None, None, 500.0],
        "issuer_name": ["Acme Corp", "Beta LLC", "Gamma Fund"],
        "fair_value": [990000.0, 1980000.0, 51000.0],
        "cost": [1000000.0, 2000000.0, 50000.0],
        "bdc_dimensions_raw": ["", "", ""],
    })


def test_format_and_uniqueness():
    out = _assign_row_ids(_base_df())
    assert "row_id" in out.columns
    assert out["row_id"].map(lambda v: bool(_ROW_ID_RE.match(v))).all()
    assert out["row_id"].nunique() == len(out)


def test_row_order_invariance():
    a = _assign_row_ids(_base_df())
    shuffled = _base_df().sample(frac=1, random_state=7).reset_index(drop=True)
    b = _assign_row_ids(shuffled)
    map_a = dict(zip(a["issuer_name"], a["row_id"]))
    map_b = dict(zip(b["issuer_name"], b["row_id"]))
    assert map_a == map_b


def test_issuer_name_drift_does_not_change_id():
    a = _assign_row_ids(_base_df())
    drifted = _base_df()
    drifted.loc[0, "issuer_name"] = "ACME Corporation, Inc."
    b = _assign_row_ids(drifted)
    assert a.loc[0, "row_id"] == b.loc[0, "row_id"]


def test_principal_change_changes_id():
    # The id names the row as published: a corrected principal is a new id.
    a = _assign_row_ids(_base_df())
    changed = _base_df()
    changed.loc[0, "principal_amount"] = 999999.0
    b = _assign_row_ids(changed)
    assert a.loc[0, "row_id"] != b.loc[0, "row_id"]
    # untouched rows keep their ids
    assert a.loc[1, "row_id"] == b.loc[1, "row_id"]
    assert a.loc[2, "row_id"] == b.loc[2, "row_id"]


def test_base_key_collision_disambiguated_by_dimension_path():
    df = _base_df()
    twin = df.iloc[[0]].copy()
    df.loc[0, "bdc_dimensions_raw"] = "InvestmentIdentifierAxis=AcmeTL1"
    twin["bdc_dimensions_raw"] = "InvestmentIdentifierAxis=AcmeTL2"
    both = pd.concat([df, twin], ignore_index=True)
    out = _assign_row_ids(both)
    assert out["row_id"].nunique() == len(out)


def test_identical_rows_still_unique_via_lot_ordinal():
    # Two byte-identical rows (no dimension path): stage-2 ordinal must still
    # produce distinct ids, deterministically.
    df = _base_df()
    both = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    out1 = _assign_row_ids(both.copy())
    out2 = _assign_row_ids(both.copy())
    assert out1["row_id"].nunique() == len(out1)
    assert list(out1["row_id"]) == list(out2["row_id"])


def test_empty_frame():
    out = _assign_row_ids(pd.DataFrame())
    assert "row_id" in out.columns
    assert len(out) == 0
