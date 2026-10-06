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


def _pct_rule():
    return next(r for r in engine.RULES if r.name == "pct_of_net_assets_identity")


def test_pct_identity_allows_for_a_percent_filed_to_one_decimal():
    # BCRED and Blue Owl file the percent to one or two decimals. A 7.9M position in a 13.2B fund is
    # 0.06 pct and is filed as 0.1; relative to its own fair value that is far outside 10 pct
    # (decision D-014: 3,348 BCRED and 541 Blue Owl rows are at that rounding floor).
    import duckdb
    rule = _pct_rule()
    rows = duckdb.connect().execute(f"""SELECT ({rule.holds_sql.replace('_scalar', 'nav')}) FROM (VALUES
        (7900000.0, 0.1, 13200000000.0),      -- rounding: 0.06 pct filed as 0.1
        (270189000.0, 4.0, 6700000000.0),     -- 4.03 pct filed as 4.0
        (270189000.0, 40.0, 6700000000.0),    -- a scale error, ten times too large
        (36814000.0, 50.0, 6700000000.0)      -- Blue Owl 2023-06-30 before the scale fix
        ) t(fair_value, pct_of_net_assets, nav)""").fetchall()
    assert [bool(r[0]) for r in rows] == [True, True, False, False]


def test_pct_identity_reads_published_rows_only():
    # A JV's own schedule states percent of the JV's net assets, not the fund's
    # (8,387 BCRED and 1,397 Blue Owl rows outside the band were such rows).
    assert "underlying_schedule" in engine.SOURCES["unified"][1]
