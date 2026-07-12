"""Guard tests for the shadow identity engine's active rule set.

Regression guard for the 2026-06-19 retirement of `pik_le_interest_rate`. The
B-trial adjudicated 15/15 of that rule's flags as false alarms (Wilson95 [80,100]):
its row_filter selects exactly the split "X% cash, Y% PIK" coupons where the
pipeline stores the CASH leg in interest_rate, so PIK > cash-leg is legitimate and
the invariant pik_rate <= interest_rate is unsound. The sound invariant (pik <=
all-in = interest + pik) is vacuous, so no per-row ordering check remains.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import shadow_identity_engine as engine  # noqa: E402


def test_pik_le_interest_rate_is_retired():
    names = {r.name for r in engine.RULES}
    assert "pik_le_interest_rate" not in names, (
        "pik_le_interest_rate was retired (unsound: interest_rate holds the cash "
        "leg of split cash/PIK coupons). Do not re-add without a field that "
        "distinguishes cash-leg interest_rate from the all-in coupon."
    )


def test_active_identity_rules_unchanged():
    # The four sound identity rules that remain after the retirement.
    names = {r.name for r in engine.RULES}
    assert names == {
        "pct_of_net_assets_identity",
        "nav_identity",
        "income_identity",
        "balance_sheet_identity",
    }
