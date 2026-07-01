"""Guard tests for the shadow rate-convention gate.

The gate classifies each wrapped BDC CIK's interest_rate semantics (ALL_IN coupon
vs SPREAD reported as the rate) from the arithmetic identity
`interest_rate ~= basis_spread + implied_reference`. It is the per-filer field that
distinguishes cash-leg interest_rate from all-in interest_rate -- the exact field
the 2026-06-19 retirement of `pik_le_interest_rate` (see
tests/test_shadow_identity_rules.py) said must exist before any PIK-vs-rate
ordering check can be sound.

These tests pin (a) the documented classification thresholds and (b) that the
single-source-of-truth STATUS_CASE_SQL assigns the intended label on synthetic
boundary cases, so a silent threshold/logic drift fails loudly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import build_shadow_rate_convention_gate as gate  # noqa: E402


def test_documented_thresholds_unchanged():
    assert gate.MIN_N_FLOATING == 20
    assert gate.DEV_TOL == 1.0
    assert gate.ABSDEV_TOL == 1.75
    assert gate.SPREAD_RESID_MAX == 1.0


def _classify(rows):
    """Run the production STATUS_CASE_SQL over synthetic per-CIK aggregates."""
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE base(cik VARCHAR, n_floating INTEGER, median_dev DOUBLE, "
        "median_abs_dev DOUBLE, median_residual DOUBLE)"
    )
    con.executemany("INSERT INTO base VALUES (?, ?, ?, ?, ?)", rows)
    out = con.execute(
        f"SELECT cik, {gate.STATUS_CASE_SQL} AS status FROM base"
    ).fetchall()
    con.close()
    return dict(out)


def test_status_classification_boundaries():
    result = _classify([
        # (cik, n_floating, median_dev, median_abs_dev, median_residual)
        ("all_in",       5000, 0.01, 0.4, 4.40),   # dev~0 -> all-in coupon
        ("spread",       7000, -4.16, 4.16, 0.00),  # residual~0 -> spread reported as rate
        ("unresolved",   1379, -1.02, 2.15, 3.80),  # dev>tol, residual>1 -> unresolved
        ("too_few",        14, 0.00, 0.10, 4.30),   # < MIN_N_FLOATING
        ("none",            0, None, None, None),    # no floating rows
    ])
    assert result == {
        "all_in": "all_in_coupon",
        "spread": "spread_as_rate",
        "unresolved": "unresolved_convention",
        "too_few": "insufficient_floating",
        "none": "no_floating_rate_rows",
    }


def test_all_in_requires_both_dev_and_absdev():
    # dev within tol but high variance (median_abs_dev over guard) must NOT be
    # classified all_in -- it falls through to spread/unresolved by residual.
    result = _classify([
        ("noisy_lowresid", 5000, 0.5, 3.0, 0.5),   # absdev>1.75, residual<=1 -> spread
        ("noisy_hiresid",  5000, 0.5, 3.0, 4.0),   # absdev>1.75, residual>1  -> unresolved
    ])
    assert result["noisy_lowresid"] == "spread_as_rate"
    assert result["noisy_hiresid"] == "unresolved_convention"
