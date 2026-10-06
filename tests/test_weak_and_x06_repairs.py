"""Two checks repaired on 2026-10-06 (decisions D-005 and D-006 in docs/investigations/v05_decision_log.md)."""
import duckdb
import pandas as pd

from pipeline.column_validation import validate_column_contracts
from pipeline.unified_holdings import UNIFIED_COLUMNS
from scripts.shadow_weak_engine import BASE_CONTEXT_COLUMNS, RULES


def _weak_holds(rule_name, rows):
    rule = next(r for r in RULES if r.name == rule_name)
    con = duckdb.connect()
    con.register("weak_base", pd.DataFrame(rows))
    return [bool(v[0]) for v in con.execute(f"SELECT ({rule.holds_sql}) FROM weak_base WHERE ({rule.gate_sql})").fetchall()]


def test_principal_cap_is_a_dollar_cap():
    # Apollo Debt Solutions, Delivery Hero Finco Germany: principal 194,831,194,000 Korean won, about 130M dollars.
    rows = [
        {"principal_amount": 194_831_194_000.0, "principal_amount_currency": "KRW"},
        {"principal_amount": 269_806_000_000.0, "principal_amount_currency": "USD"},   # Ares 2022-09-30 SDLP, a filed error
        {"principal_amount": 269_806_000_000.0, "principal_amount_currency": ""},
        {"principal_amount": -5.0, "principal_amount_currency": "KRW"},
        {"principal_amount": 5_000_000.0, "principal_amount_currency": "USD"},
    ]
    assert _weak_holds("fmt_principal_amount", rows) == [True, False, False, False, True]
    assert "principal_amount_currency" in BASE_CONTEXT_COLUMNS


def test_dollar_principal_keeps_its_cap_whatever_the_currency():
    rows = [{"principal_amount_usd": 269_806_000_000.0}, {"principal_amount_usd": 130_000_000.0}]
    assert _weak_holds("fmt_principal_amount_usd", rows) == [False, True]


def _x06(rows):
    base = {"source": "bdc", "cik": "0001837532", "report_date": "2026-03-31", "issuer_name": "Alera Group, Inc.",
            "fair_value": "100000", "principal_amount": "39614000", "principal_amount_usd": "39614000",
            "instrument_description": "", "bdc_investment_identifier": ""}
    frame = pd.DataFrame([{**{c: "" for c in UNIFIED_COLUMNS}, **base, **row} for row in rows])
    issues, _ = validate_column_contracts(frame)
    return sorted(issues.loc[issues["rule_id"] == "X06", "row_key"].astype(int)) if len(issues) else []


def test_x06_exempts_an_undrawn_line_named_in_the_instrument_or_the_identifier():
    flagged = _x06([
        {"instrument_description": "First Lien Secured Debt - Revolver Interest Rate S+525"},
        {"bdc_investment_identifier": "Insurance Alera Group Alera Group, Inc. Investment Type First Lien Secured Debt - Delayed Draw"},
        {"issuer_name": "Alera Group, Inc. Revolver"},
    ])
    assert flagged == []


def test_x06_still_flags_a_term_loan_whose_principal_is_far_above_its_value():
    # Ares 2022-09-30, Senior Direct Lending Program subordinated certificates: principal 269.8B against 1.1B.
    flagged = _x06([{"issuer_name": "Senior Direct Lending Program, LLC", "instrument_description": "Subordinated certificates",
                     "fair_value": "1121000000", "principal_amount": "269806000000", "principal_amount_usd": "269806000000"}])
    assert len(flagged) == 1
