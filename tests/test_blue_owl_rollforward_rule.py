"""Blue Owl Credit Income (CIK 1812554): affiliate roll-forward facts tagged with the issuer name.

The filer tags the closing fair value in its transactions-with-affiliates table with the
investment identifier axis, using the issuer name alone. The rule excludes those rows in every
quarter. Real filing values; synthetic frame; no production files touched.
"""
import json
from pathlib import Path

import pytest

import pandas as pd

from pipeline.agent_promoted import late_resolved_columns
from pipeline.agent_rule import apply_rules, validate_rule

RULE_PATH = (Path(__file__).resolve().parent.parent / "data" / "overrides" / "agent_investigate_rules"
             / "1812554" / "exclude_affiliate_rollforward_issuer_only_rows.json")


def _rule():
    return json.loads(RULE_PATH.read_text(encoding="utf-8-sig"))


def _row(identifier, fv, quarter="2025-09-30", principal=None, shares=None, pct=None):
    return {"cik": "1812554", "report_date": quarter, "issuer_name": identifier.split(",")[0],
            "bdc_investment_identifier": identifier, "bdc_dimensions_raw": "investmentidentifieraxis=" + identifier,
            "fair_value": fv, "principal_amount": principal, "shares_held": shares, "pct_of_net_assets": pct}


def _kept(rows):
    out, audits = apply_rules(pd.DataFrame(rows), [_rule()])
    assert all(a.get("status") == "ok" for a in audits), audits
    return set(out["bdc_investment_identifier"])


def test_rule_is_valid_structural_and_covers_every_quarter():
    rule = _rule()
    assert validate_rule(rule) == []
    assert late_resolved_columns(rule) == []
    assert rule["scope"]["quarters"] == ["all"]
    assert "report_date" not in rule["predicate_sql"] and "src_context_id" not in rule["predicate_sql"]


@pytest.mark.parametrize("quarter", ["2023-03-31", "2024-06-30", "2025-09-30"])
def test_rollforward_row_is_excluded_and_its_schedule_row_kept(quarter):
    kept = _kept([
        _row("LSI Financing LLC", 333_800_000.0, quarter),
        _row("LSI Financing LLC, Specialty finance equity investment", 333_800_000.0, quarter, shares=333_800.0),
        _row("OCIC SLF LLC (fka Blue Owl Credit Income Senior Loan Fund LLC)", 286_300_000.0, quarter),
        _row("Associations, Inc., First lien senior secured loan", 498_200_000.0, quarter, principal=500_000_000.0),
    ])
    assert kept == {"LSI Financing LLC, Specialty finance equity investment",
                    "Associations, Inc., First lien senior secured loan"}


def test_issuer_only_positions_with_a_quantity_or_a_percent_are_kept():
    kept = _kept([
        _row("Associations Finance, Inc.", 227_100_000.0, "2023-03-31", shares=215_000_000.0, pct=3.9),
        _row("KWOR Acquisition, Inc. (dba Alacrity Solutions) 1", 32_500_000.0, "2023-03-31", principal=32_620_000.0, pct=0.6),
        _row("Insight CP (Blocker) Holdings, L.P. (dba CivicPlus, LLC)", 1_000_000.0, "2023-03-31", pct=0.02),
        _row("KWOL Acquisition, Inc. (dba Worldwide Clinical Trials), Class A", 16_700_000.0, shares=1205.0),
    ])
    assert len(kept) == 4


def test_instrument_rows_without_quantities_are_kept():
    kept = _kept([
        _row("Peraton Corp., Second lien senior secured loan", 2_900_000.0),
        _row("Fifth Season Investments LLC, Specialty finance equity investment", 310_900_000.0),
        _row("Hg Genesis 9 SumoCo Limited, Unsecured facility", 158_700_000.0),
    ])
    assert len(kept) == 3
