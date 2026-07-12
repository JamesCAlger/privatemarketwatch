"""Tests for the entity-name refresh overlay and export name cleanup."""

import pandas as pd
import pytest

from pipeline.export.fund_exports import _display_fund_name
from pipeline.merge import _apply_entity_name_overlay


# ---------------------------------------------------------------------------
# _display_fund_name
# ---------------------------------------------------------------------------

def test_display_name_strips_cik_suffix():
    assert (_display_fund_name("Owl Rock Core Income Corp.  (CIK 0001812554)")
            == "Owl Rock Core Income Corp.")


def test_display_name_strips_mid_string_cik():
    assert (_display_fund_name("Fund A (CIK 123) Continued")
            == "Fund A Continued")


def test_display_name_plain_name_unchanged():
    assert (_display_fund_name("Blue Owl Credit Income Corp.")
            == "Blue Owl Credit Income Corp.")


def test_display_name_keeps_ticker_parenthetical():
    # Only "(CIK N)" annotations are stripped, not other parentheticals
    assert (_display_fund_name("Ares Capital Corp (ARCC)")
            == "Ares Capital Corp (ARCC)")


def test_display_name_handles_none_and_empty():
    assert _display_fund_name(None) == ""
    assert _display_fund_name("") == ""


def test_display_name_collapses_whitespace():
    assert _display_fund_name("  Fund   B  ") == "Fund B"


# ---------------------------------------------------------------------------
# _apply_entity_name_overlay
# ---------------------------------------------------------------------------

@pytest.fixture
def universe_df():
    return pd.DataFrame({
        "cik": ["0001812554", "0001287750"],
        "entity_name": [
            "Owl Rock Core Income Corp.  (CIK 0001812554)",
            "ARES CAPITAL CORP",
        ],
        "vehicle_type": ["bdc", "bdc"],
    })


def _write_overlay(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_overlay_applies_current_name(tmp_path, universe_df):
    overlay = _write_overlay(tmp_path / "names.csv", [
        {"cik": "0001812554",
         "entity_name": "Blue Owl Credit Income Corp."},
    ])
    out = _apply_entity_name_overlay(universe_df, overlay_file=overlay)
    assert out.loc[out["cik"] == "0001812554", "entity_name"].iloc[0] \
        == "Blue Owl Credit Income Corp."
    # Untouched CIK keeps its name
    assert out.loc[out["cik"] == "0001287750", "entity_name"].iloc[0] \
        == "ARES CAPITAL CORP"


def test_overlay_pads_short_ciks(tmp_path, universe_df):
    overlay = _write_overlay(tmp_path / "names.csv", [
        {"cik": "1812554", "entity_name": "Blue Owl Credit Income Corp."},
    ])
    out = _apply_entity_name_overlay(universe_df, overlay_file=overlay)
    assert out.loc[out["cik"] == "0001812554", "entity_name"].iloc[0] \
        == "Blue Owl Credit Income Corp."


def test_overlay_missing_file_is_noop(tmp_path, universe_df):
    out = _apply_entity_name_overlay(
        universe_df, overlay_file=tmp_path / "does_not_exist.csv")
    pd.testing.assert_frame_equal(out, universe_df)


def test_overlay_missing_columns_is_noop(tmp_path, universe_df):
    overlay = _write_overlay(tmp_path / "names.csv",
                             [{"cik": "0001812554", "wrong_col": "x"}])
    out = _apply_entity_name_overlay(universe_df, overlay_file=overlay)
    pd.testing.assert_frame_equal(out, universe_df)


def test_overlay_does_not_mutate_input(tmp_path, universe_df):
    overlay = _write_overlay(tmp_path / "names.csv", [
        {"cik": "0001812554",
         "entity_name": "Blue Owl Credit Income Corp."},
    ])
    original = universe_df.copy()
    _apply_entity_name_overlay(universe_df, overlay_file=overlay)
    pd.testing.assert_frame_equal(universe_df, original)
