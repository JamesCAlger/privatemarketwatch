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
        # added 2026-10-07 at the owner's request (decision D-030)
        "fourth_quarter_income",
        "reference_rate_printed",
        "spread_printed",
    }


def _run(rule_name, tables):
    """Evaluate one rule over registered frames; returns {(cik, report_date, row_id): holds}."""
    import duckdb
    import pandas as pd
    rule = next(r for r in engine.RULES if r.name == rule_name)
    con = duckdb.connect()
    for name, rows in tables.items():
        con.register(name, pd.DataFrame(rows))
    if rule_name == "fourth_quarter_income":
        source = engine.year_end_income_sql("ff", "income")
    else:
        source = engine.printed_reference_sql("unified", "status", ["0001812554"])
    cols = ", ".join(rule.needed_cols)
    present = " AND ".join(f"{c} IS NOT NULL" for c in rule.needed_cols)   # the engine evaluates only such rows
    out = con.execute(f"SELECT cik, report_date, {cols}, ({rule.holds_sql}) AS holds FROM {source} "
                      f"WHERE {rule.row_filter} AND {present}").fetchdf()
    return {(r.cik, r.report_date): bool(r.holds) for r in out.itertuples()}, out


def _income(cik, day, months, income):
    return dict(cik=cik, report_date=day, duration_months=str(months), total_investment_income=str(income))


def _ff_row(cik, day, income):
    return dict(cik=cik, report_date=day, entity_name="Fund", source="companyfacts", total_investment_income=income)


def test_fourth_quarter_income_is_the_annual_figure_less_three_filed_quarters():
    # HPS: quarters 178.8, 215.8 and 233.9 (10-Qs of 2023), annual 893.2. The income table holds 893.2 / 4 = 223.3
    # for 2023-12-31; the filings imply 264.7.
    quarters = [_income("1838126", "2023-03-31", 3, 178.8), _income("0001838126", "2023-06-30", 3, 215.8),
                _income("1838126", "2023-09-30", 3, 233.9)]
    holds, out = _run("fourth_quarter_income", dict(
        income=quarters + [_income("1838126", "2023-12-31", 12, 223.3)],
        ff=[_ff_row(1838126, "2023-12-31", 223.3), _ff_row(1838126, "2023-09-30", 233.9)]))
    assert holds == {("0001838126", "2023-12-31"): False}          # only the year-end quarter is tested
    assert abs(out.fourth_quarter_expected[0] - 264.7) < 1e-6
    # once the published figure is the quarter itself, the rule holds
    holds, _ = _run("fourth_quarter_income", dict(
        income=quarters + [_income("1838126", "2023-12-31", 12, 223.3)], ff=[_ff_row(1838126, "2023-12-31", 264.7)]))
    assert holds == {("0001838126", "2023-12-31"): True}


def test_fourth_quarter_income_says_nothing_without_three_filed_quarters():
    # a first year with two 10-Qs, and a year-end with no annual fact: no expected value, so no finding
    holds, _ = _run("fourth_quarter_income", dict(
        income=[_income("1", "2023-06-30", 3, 10.0), _income("1", "2023-09-30", 3, 12.0), _income("1", "2023-12-31", 12, 9.0),
                _income("2", "2023-03-31", 3, 5.0), _income("2", "2023-06-30", 3, 5.0), _income("2", "2023-09-30", 3, 5.0),
                _income("2", "2023-12-31", 3, 5.0)],
        ff=[_ff_row(1, "2023-12-31", 9.0), _ff_row(2, "2023-12-31", 5.0)]))
    assert holds == {}


def _holding(context, member, published, cik="0001812554", scope="", spread=None):
    return dict(cik=cik, report_date="2023-06-30", accession_number="A", src_context_id=context,
                bdc_investment_identifier=member.split(" | Non-")[0], bdc_dimensions_raw="investmentidentifieraxis=" + member,
                reference_rate_type=published, accounting_record_class=scope, basis_spread=spread)


def _printed(member, code, status="value", role="current", cik="0001812554", margin=None):
    row = dict(cik=cik, accession_number="A", report_date="2023-06-30", period_role=role, raw_id_lower=member.lower(),
               reference_rate_type=code, reference_rate_status=status)
    return row if margin is None else dict(row, printed_margin=margin)


def test_reference_rate_printed_compares_published_with_the_printed_code():
    # Blue Owl 2023-06-30: Anaplan is printed 'SR +' (SOFR) and published as LIBOR, a rate inferred from the date
    members = ["Anaplan, Inc. | Non-Affiliated Issuer", "Global Music Rights, LLC | Non-Affiliated Issuer"]
    holds, out = _run("reference_rate_printed", dict(
        unified=[_holding("c1", members[0], "LIBOR"), _holding("c2", members[1], "libor ")],
        status=[_printed(members[0], "SOFR"), _printed(members[1], "LIBOR")]))
    assert sorted(out.reference_rate_agrees) == [0.0, 1.0] and len(out) == 2


def test_reference_rate_printed_ignores_what_it_cannot_compare():
    member = "Anaplan, Inc. | Non-Affiliated Issuer"
    cases = [
        (_holding("c1", member, ""), _printed(member, "SOFR")),                       # nothing published
        (_holding("c1", member, "LIBOR"), _printed(member, "SOFR", status="validation_needed")),
        (_holding("c1", member, "LIBOR"), _printed(member, "SOFR", role="comparative")),
        (_holding("c1", member, "LIBOR", scope="underlying_schedule"), _printed(member, "SOFR")),
        # a fund whose wrapper names no reference-rate column
        (_holding("c1", member, "LIBOR", cik="0001838126"), _printed(member, "SOFR", cik="0001838126")),
    ]
    for holding, printed in cases:
        _, out = _run("reference_rate_printed", dict(unified=[holding], status=[printed]))
        assert len(out) == 0


def test_reference_rate_printed_is_limited_to_funds_that_name_the_column():
    # the five v0.5 funds; every other wrapper names no column
    assert engine._named_reference_column_ciks() == ["0001287750", "0001803498", "0001812554", "0001837532", "0001838126"]


def test_reference_rate_printed_fails_a_reference_rate_the_page_does_not_print():
    # BCRED 2022-09-30, Camelot Return Merger: printed '8.75% | 8.75%' with an empty code cell, published LIBOR by date
    member = "Camelot Return Merger SU | Non-Affiliated Issuer"
    holds, out = _run("reference_rate_printed", dict(
        unified=[_holding("c1", member, "LIBOR")], status=[_printed(member, "", status="not_applicable")]))
    assert list(out.reference_rate_agrees) == [0.0]
    # nothing published on such a row is not a finding
    _, out = _run("reference_rate_printed", dict(
        unified=[_holding("c1", member, "")], status=[_printed(member, "", status="not_applicable")]))
    assert len(out) == 0


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


def _income_rows(rows):
    import duckdb
    import pandas as pd
    rule = next(r for r in engine.RULES if r.name == "income_identity")
    con = duckdb.connect()
    con.register("ff", pd.DataFrame(rows))
    return [bool(v[0]) for v in con.execute(f"SELECT ({rule.holds_sql}) FROM ff").fetchall()]


def test_income_identity_uses_net_expenses_where_the_fund_files_them():
    # HPS, three months to 2022-06-30: income 37,750,000, gross expenses 16,022,000, expenses after fee waivers
    # 4,097,000, net investment income 33,653,000 (decision D-025). Without a net figure the gross one is used.
    hps = dict(net_investment_income=33_653_000.0, total_investment_income=37_750_000.0, total_expenses=16_022_000.0)
    assert _income_rows([dict(hps, net_expenses=4_097_000.0), dict(hps, net_expenses=None),
                         dict(hps, net_expenses=9_000_000.0)]) == [True, False, False]
    # HPS 2023-12-31: the income table's quarter is the annual figure divided by four (gross expenses
    # 104,167,750) while net expenses are the true fourth quarter (127,460,000). Net above gross means
    # different bases; the gross figure is compared and the identity holds as it did before.
    q4 = dict(net_investment_income=119_177_250.0, total_investment_income=223_345_000.0, total_expenses=104_167_750.0)
    assert _income_rows([dict(q4, net_expenses=127_460_000.0)]) == [True]
    rule = next(r for r in engine.RULES if r.name == "income_identity")
    assert rule.optional_cols == ("net_expenses",)


def _spread_holds(spread, margin):
    import duckdb
    import pandas as pd
    member = "Inovalon Holdings, Inc. | Non-Affiliated Issuer"
    rule = next(r for r in engine.RULES if r.name == "spread_printed")
    con = duckdb.connect()
    con.register("unified", pd.DataFrame([_holding("c1", member, "SOFR", spread=spread)]))
    con.register("status", pd.DataFrame([_printed(member, "SOFR", margin=margin)]))
    source = engine.printed_reference_sql("unified", "status", ["0001812554"])
    gate = " AND ".join("TRY_CAST(%s AS DOUBLE) IS NOT NULL" % c for c in rule.needed_cols)
    typed = ", ".join("TRY_CAST(%s AS DOUBLE) AS %s" % (c, c) for c in rule.needed_cols)
    return [bool(r[0]) for r in con.execute(f"SELECT ({rule.holds_sql}) FROM (SELECT {typed} FROM {source} WHERE {gate})").fetchall()]


def test_spread_printed_compares_the_published_spread_with_the_printed_margin():
    # Inovalon first lien 2025-12-31: printed 'S+ | 2.75% | 2.75%' (5.50 in all); a published 2.75 is the cash part only
    assert _spread_holds(2.75, "5.5") == [False]
    assert _spread_holds(5.5, "5.5") == [True]
    assert _spread_holds(6.25, "6.250") == [True]
    # nothing to compare: no published spread, a margin that was not read, or an artifact without the column
    assert _spread_holds(None, "5.5") == [] and _spread_holds(2.75, "") == [] and _spread_holds(2.75, None) == []
