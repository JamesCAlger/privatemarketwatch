"""Gold-standard regression tests for unified holdings.

Reads manually-verified CIK-quarter expectations from
tests/fixtures/gold_standard.json and compares against production data
in data/output/private_markets_holdings.csv.

Design constraints:
- Does NOT call any pipeline build functions (no CSV overwrite risk)
- Reads production data only, never modifies it
- Skips when production file is missing or all expected values are null
- Each fixture entry with non-null values asserts:
  - position count within tolerance
  - total fair value within tolerance
  - spot-check positions exist with FV within tolerance
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline.config import UNIFIED_HOLDINGS_FILE

_FIXTURES_PATH = Path(__file__).parent / "fixtures" / "gold_standard.json"


def _load_fixtures():
    """Load gold-standard fixture entries."""
    if not _FIXTURES_PATH.exists():
        return []
    with open(_FIXTURES_PATH) as f:
        return json.load(f)


def _has_any_verified(fixtures):
    """Check if any fixture entry has non-null expected values."""
    for entry in fixtures:
        if entry.get("expected_position_count") is not None:
            return True
        if entry.get("expected_total_fv") is not None:
            return True
        if entry.get("spot_checks"):
            return True
    return False


_fixtures = _load_fixtures()

_skip_no_production = pytest.mark.skipif(
    not UNIFIED_HOLDINGS_FILE.exists(),
    reason="Production unified holdings file not found",
)
_skip_no_verified = pytest.mark.skipif(
    not _has_any_verified(_fixtures),
    reason="No verified values in gold_standard.json (all null)",
)
_skip_no_fixtures = pytest.mark.skipif(
    not _FIXTURES_PATH.exists(),
    reason="Gold-standard fixtures file not found",
)


@_skip_no_fixtures
@_skip_no_production
@_skip_no_verified
class TestGoldStandard:
    """Regression tests against manually-verified CIK-quarter data."""

    @pytest.fixture(scope="class")
    def holdings(self):
        """Load production unified holdings once per test class."""
        return pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    @pytest.fixture(scope="class")
    def fixtures(self):
        return _load_fixtures()

    def _filter_holdings(self, holdings, cik, report_date):
        """Filter holdings to a specific CIK and report_date."""
        mask = (holdings["cik"] == cik) & (holdings["report_date"] == report_date)
        return holdings[mask]

    def test_position_counts(self, holdings, fixtures):
        """Verify position counts for entries with expected_position_count."""
        for entry in fixtures:
            expected = entry.get("expected_position_count")
            if expected is None:
                continue
            cik = entry["cik"]
            report_date = entry["report_date"]
            tolerance = entry.get("tolerance_count", 0.05)

            subset = self._filter_holdings(holdings, cik, report_date)
            actual = len(subset)

            pct_diff = abs(actual - expected) / expected if expected > 0 else 0
            assert pct_diff < tolerance, (
                f"{entry['name']} ({cik}) @ {report_date}: "
                f"expected ~{expected} positions, got {actual} "
                f"(diff {pct_diff:.1%}, tolerance {tolerance:.0%})"
            )

    def test_total_fair_values(self, holdings, fixtures):
        """Verify total FV for entries with expected_total_fv."""
        for entry in fixtures:
            expected = entry.get("expected_total_fv")
            if expected is None:
                continue
            cik = entry["cik"]
            report_date = entry["report_date"]
            tolerance = entry.get("tolerance_fv", 0.05)

            subset = self._filter_holdings(holdings, cik, report_date)
            actual = pd.to_numeric(subset["fair_value"], errors="coerce").sum()

            pct_diff = abs(actual - expected) / expected if expected > 0 else 0
            assert pct_diff < tolerance, (
                f"{entry['name']} ({cik}) @ {report_date}: "
                f"expected FV ~${expected:,.0f}, got ${actual:,.0f} "
                f"(diff {pct_diff:.1%}, tolerance {tolerance:.0%})"
            )

    def test_spot_checks(self, holdings, fixtures):
        """Verify specific positions exist with expected FV."""
        for entry in fixtures:
            spot_checks = entry.get("spot_checks", [])
            if not spot_checks:
                continue
            cik = entry["cik"]
            report_date = entry["report_date"]
            tolerance = entry.get("tolerance_fv", 0.05)

            subset = self._filter_holdings(holdings, cik, report_date)

            for check in spot_checks:
                issuer = check["issuer_name"]
                expected_fv = check["expected_fv"]

                # Find matching position (case-insensitive partial match)
                matches = subset[
                    subset["issuer_name"].str.lower().str.contains(
                        issuer.lower(), na=False
                    )
                ]
                assert len(matches) > 0, (
                    f"{entry['name']} ({cik}) @ {report_date}: "
                    f"position '{issuer}' not found"
                )

                actual_fv = pd.to_numeric(
                    matches["fair_value"], errors="coerce"
                ).max()
                pct_diff = (
                    abs(actual_fv - expected_fv) / expected_fv
                    if expected_fv > 0 else 0
                )
                assert pct_diff < tolerance, (
                    f"{entry['name']} ({cik}) @ {report_date}: "
                    f"'{issuer}' FV expected ~${expected_fv:,.0f}, "
                    f"got ${actual_fv:,.0f} "
                    f"(diff {pct_diff:.1%}, tolerance {tolerance:.0%})"
                )


@_skip_no_fixtures
class TestGoldStandardFixtureFormat:
    """Validate the fixture file format itself."""

    def test_fixture_is_valid_json(self):
        fixtures = _load_fixtures()
        assert isinstance(fixtures, list)
        assert len(fixtures) > 0

    def test_required_fields(self):
        fixtures = _load_fixtures()
        required = {"cik", "name", "report_date"}
        for entry in fixtures:
            missing = required - set(entry.keys())
            assert not missing, (
                f"Entry {entry.get('name', '?')} missing fields: {missing}"
            )

    def test_tolerances_in_range(self):
        fixtures = _load_fixtures()
        for entry in fixtures:
            for key in ("tolerance_count", "tolerance_fv"):
                val = entry.get(key)
                if val is not None:
                    assert 0 < val < 1, (
                        f"{entry['name']}: {key}={val} should be between 0 and 1"
                    )
