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
        # added 2026-10-13 at the owner's request (decision D-149)
        "field_coverage_drop",
        # page-reading rules of pipeline/candidate_rules.py, wired 2026-10-19 (D-207)
        "issuer_name_printed", "units_printed", "pik_printed", "industry_coverage", "preferred_printed",
    }


def _page_fixture(tmp_path):
    """A tiny cohort: one fund, a quarter the page test can see and one it cannot."""
    import duckdb
    import pandas as pd
    cik = "0000000001"

    def row(rid, rd, issuer, member, category="LOAN", **kw):
        return dict(source="bdc", cik=cik, report_date=rd, accession_number="ACC-" + rd, row_id=rid, issuer_name=issuer,
                    bdc_investment_identifier=member, bdc_dimensions_raw=None, fair_value=10.0, asset_category=category,
                    index_classification=None, accounting_record_class=None, shares_held=kw.get("shares"),
                    shares_held_source=kw.get("shares_source"), pik_rate=None, interest_rate=None,
                    instrument_description=None, extracted_industry=None, gics_sub_industry="Application Software",
                    gics_sector=None, basis_spread=None)
    holdings = [
        # seen quarter: Apollo-style group prefix (finding), a clean row, an HPS units-scale row (weaker kind)
        row("r1", "2025-12-31", "Gannett Gannett Holdings, LLC", "m1"),
        row("r2", "2025-12-31", "Acme Corp", "m2"),
        row("r3", "2025-12-31", "Wash & Wax Group LP", "m3", category="EQUITY_COMMON", shares=6312000.0,
            shares_source="derived_proxy"),
        # blind quarter: no printed rows at all, and a shape-only bad name
        row("b1", "2025-09-30", "Gannett Gannett Holdings, LLC", "m1"),
        row("b2", "2025-09-30", "Debt Investments Capital Markets Cliffwater, LLC", "m4"),
    ]
    status = [
        dict(cik=cik, accession_number="ACC-2025-12-31", period_role="current", raw_id_lower="m1",
             printed_row="Gannett Holdings, LLC | First Lien Secured Debt - Term Loan | S+511 | 44,195"),
        dict(cik=cik, accession_number="ACC-2025-12-31", period_role="current", raw_id_lower="m2",
             printed_row="Acme Corp | First Lien | S + 5.00% | 1,000"),
        dict(cik=cik, accession_number="ACC-2025-12-31", period_role="current", raw_id_lower="m3",
             printed_row="Wash & Wax Group LP (4)(20)(22) | 6,312 | 8,547 | 6,991"),
    ]
    con = duckdb.connect()
    con.register("h", pd.DataFrame(holdings))
    con.execute(f"COPY (SELECT * FROM h) TO '{(tmp_path / 'holdings.parquet').as_posix()}' (FORMAT PARQUET)")
    pd.DataFrame(status).to_csv(tmp_path / "status.csv", index=False)
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.execute("INSERT INTO wrapped VALUES (?)", [cik])
    return con


def test_page_rules_reach_the_ledger_only_where_they_can_test(tmp_path):
    import pandas as pd
    con = _page_fixture(tmp_path)
    out_dir = tmp_path / "shadow"
    engine.ensure_page_rules(con, holdings=tmp_path / "holdings.parquet", status=tmp_path / "status.csv", out_dir=out_dir)
    cache: dict = {}
    for rule in [r for r in engine.RULES if r.name in engine.PAGE_RULE_NAMES]:
        assert engine.run_rule(con, rule, cache), rule.name
    got = con.execute("""SELECT report_date, row_id, holds FROM result_issuer_name_printed ORDER BY 1, 2""").fetchall()
    # the seen quarter is tested and fails on r1; the blind quarter gets no result at all
    assert got == [("2025-12-31", "r1", False), ("2025-12-31", "r2", True), ("2025-12-31", "r3", True)]
    # the units-scale row is tested but not a finding: units_printed passes there
    assert con.execute("SELECT bool_and(holds) FROM result_units_printed").fetchone()[0] is True
    info = pd.read_csv(out_dir / "page_rules_informational.csv")
    assert {("units_printed", "units_scale_unclear"), ("issuer_name_printed", "begins_with_section_word")} <= set(
        zip(info["rule_name"], info["kind"]))
    blind = pd.read_csv(out_dir / "page_rules_name_blind_spots.csv", dtype={"report_date": str})
    assert dict(zip(blind["report_date"], blind["page_test_suppressed"])) == {"2025-09-30": True, "2025-12-31": False}
    findings = pd.read_csv(out_dir / "page_rule_findings.csv")
    assert list(findings["row_id"]) == ["r1"]


def test_page_rules_without_holdings_create_an_empty_table(tmp_path):
    import duckdb
    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    assert engine.ensure_page_rules(con, holdings=tmp_path / "absent.parquet", status=tmp_path / "absent.csv",
                                    out_dir=tmp_path) == 0
    assert con.execute(f"SELECT count(*) FROM {engine.PAGE_RULES_TABLE}").fetchone()[0] == 0


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
    # the five v0.5 funds name it; since 2026-10-10 so do the funds whose wrapper was given the
    # column as each was read (the list is the wrappers' own, so it is not pinned here)
    from pipeline.source_encodings import load_encodings
    named = engine._named_reference_column_ciks()
    assert {"0001287750", "0001803498", "0001812554", "0001837532", "0001838126"} <= set(named)
    assert all(load_encodings()[cik].get("reference_rate_columns") for cik in named)


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
    typed = ", ".join("TRY_CAST(%s AS DOUBLE) AS %s" % (c, c) for c in rule.needed_cols + rule.optional_cols)
    return [bool(r[0]) for r in con.execute(f"SELECT ({rule.holds_sql}) FROM (SELECT {typed} FROM {source} WHERE {gate})").fetchall()]


def _cash_plus_holds(quarters, cik="0002052153"):
    """spread_printed per quarter for one position: quarters = [(report_date, published spread, printed margin,
    printed row, position_id, maturity)]."""
    import duckdb
    import pandas as pd
    rule = next(r for r in engine.RULES if r.name == "spread_printed")
    hold, stat = [], []
    for i, (day, spread, margin, printed, pid, maturity) in enumerate(quarters):
        member = f"Zeus Company LLC {i} | Non-Affiliated Issuer"
        h = _holding(f"c{i}", member, "SOFR", cik=cik, spread=spread)
        hold.append(dict(h, report_date=day, accession_number=f"A{i}", position_id=pid, issuer_name="Zeus Company LLC",
                         maturity_date=maturity))
        stat.append(dict(_printed(member, "SOFR", cik=cik, margin=margin), report_date=day, accession_number=f"A{i}",
                         printed_row=printed))
    con = duckdb.connect()
    con.register("unified", pd.DataFrame(hold))
    con.register("status", pd.DataFrame(stat))
    source = engine.printed_reference_sql("unified", "status", [cik])
    typed = ", ".join("TRY_CAST(%s AS DOUBLE) AS %s" % (c, c) for c in rule.needed_cols + rule.optional_cols)
    rows = con.execute(f"SELECT report_date, ({rule.holds_sql}) FROM (SELECT report_date, {typed} FROM {source}) "
                       "WHERE basis_spread IS NOT NULL AND printed_margin IS NOT NULL").fetchall()
    return {d: bool(h) for d, h in rows}


def test_spread_printed_cash_plus_figure_that_another_quarter_prints_as_the_total_holds():
    # 0002052153 Zeus: 'S+600 Cash plus 3.00% PIK' at 2025-12-31 and 2026-03-31, printed 'S+600 Cash (includes 3.00%
    # PIK)' at 2025-09-30 (margin not read): 6.00 is the total margin, the published 6.00 is right
    out = _cash_plus_holds([
        ("2025-09-30", 6.0, None, "Term Loan | S+600 Cash (includes 3.00% PIK), 0.75% Floor | 2/28/2031", "p1", "2031-02-28"),
        ("2025-12-31", 6.0, "9.0", "Term Loan | S+600 Cash plus 3.00% PIK, 0.75% Floor | 2/28/2031", "p1", "2031-02-28"),
        ("2026-03-31", 6.0, "9.0", "Zeus Company LLC | Term Loan | S+600 Cash plus 3.00% PIK | 2/28/2031", "p1", "2031-02-28"),
    ])
    assert out == {"2025-12-31": True, "2026-03-31": True}
    # Deerfield: 'S+575 Cash plus 2.75% PIK' and, a quarter later, 'S+300 Cash plus 2.75% PIK' (5.75 in all);
    # matched by position_id across a one-day maturity change
    out = _cash_plus_holds([
        ("2025-12-31", 5.75, "8.5", "Term Loan | S+575 Cash plus 2.75% PIK | 9/13/2032", "p2", "2032-09-13"),
        ("2026-06-30", 5.75, "5.75", "Term Loan | S+300 Cash plus 2.75% PIK, 0.75% Floor | 9/13/2032", "p2", "2032-09-12"),
    ])
    assert out == {"2025-12-31": True, "2026-06-30": True}


def test_spread_printed_cash_plus_still_fires_without_evidence_or_on_a_third_value():
    out = _cash_plus_holds([
        # the cash leg published, and no other quarter shows X as a cash-and-PIK total: the check's case
        ("2025-12-31", 6.0, "9.0", "Term Loan | S+600 Cash plus 3.00% PIK | 2/28/2031", "p1", "2031-02-28"),
        # an earlier all-cash quarter at the same figure is not evidence (a PIK leg may have been added)
        ("2025-09-30", 6.0, "6.0", "Term Loan | S+600, 0.75% Floor | 2/28/2031", "p1", "2031-02-28"),
    ])
    assert out == {"2025-12-31": False, "2025-09-30": True}
    out = _cash_plus_holds([
        # a published spread equal to neither X nor X+Y
        ("2025-12-31", 7.0, "9.0", "Term Loan | S+600 Cash plus 3.00% PIK | 2/28/2031", "p1", "2031-02-28"),
        ("2025-09-30", 6.0, None, "Term Loan | S+600 Cash (includes 3.00% PIK) | 2/28/2031", "p1", "2031-02-28"),
        # another position's total is not evidence
        ("2026-03-31", 6.0, "9.0", "Term Loan | S+600 Cash plus 3.00% PIK | 2/28/2031", "p9", "2033-01-01"),
    ])
    assert out == {"2025-12-31": False, "2026-03-31": False}
    # the sum X+Y still holds as before
    out = _cash_plus_holds([("2025-12-31", 9.0, "9.0", "Term Loan | S+600 Cash plus 3.00% PIK | 2/28/2031", "p1", "2031-02-28")])
    assert out == {"2025-12-31": True}


def test_spread_printed_compares_the_published_spread_with_the_printed_margin():
    # Inovalon first lien 2025-12-31: printed 'S+ | 2.75% | 2.75%' (5.50 in all); a published 2.75 is the cash part only
    assert _spread_holds(2.75, "5.5") == [False]
    assert _spread_holds(5.5, "5.5") == [True]
    assert _spread_holds(6.25, "6.250") == [True]
    # nothing to compare: no published spread, a margin that was not read, or an artifact without the column
    assert _spread_holds(None, "5.5") == [] and _spread_holds(2.75, "") == [] and _spread_holds(2.75, None) == []


def _coverage(rows):
    import duckdb
    import pandas as pd
    base = {"source": "bdc", "cik": "0001838126", "asset_category": "LOAN", "fair_value": 100.0, "principal_amount": 100.0,
            "interest_rate": 9.0, "basis_spread": 5.0, "cost": 99.0, "shares_held": None, "pct_of_net_assets": 0.1,
            "maturity_date": "2031-12-20", "reference_rate_type": "SOFR", "extracted_industry": "Software",
            "accounting_record_class": "parent_schedule"}
    con = duckdb.connect()
    con.register("unified", pd.DataFrame([{**base, **r} for r in rows]))
    rule = next(r for r in engine.RULES if r.name == "field_coverage_drop")
    out = con.execute(f"SELECT report_date, field_name, ({rule.holds_sql}) AS holds FROM {engine.field_coverage_sql('unified')} "
                      "WHERE coverage IS NOT NULL AND prior_coverage IS NOT NULL").fetchall()
    return {(d, f): bool(h) for d, f, h in out}


def test_field_coverage_drop_flags_the_quarter_a_field_disappears():
    # HPS 2026-03-31: par tagged as a share count, so most drawn loans lose their principal for one quarter.
    rows = [{"report_date": "2025-12-31"} for _ in range(30)]
    rows += [{"report_date": "2026-03-31", "principal_amount": None, "shares_held": 100.0} for _ in range(25)]
    rows += [{"report_date": "2026-03-31"} for _ in range(5)]
    rows += [{"report_date": "2026-06-30"} for _ in range(30)]
    result = _coverage(rows)
    assert result[("2026-03-31", "principal on drawn loans")] is False
    assert result[("2026-03-31", "cost")] is True               # the other fields did not move
    assert result[("2026-06-30", "principal on drawn loans")] is True   # a recovery is not a finding


def test_field_coverage_drop_says_nothing_on_thin_or_first_quarters_or_unpublished_rows():
    rows = [{"report_date": "2025-12-31"} for _ in range(30)]
    # a small drop is not a finding; fewer than 20 equity rows say nothing about unit counts
    rows += [{"report_date": "2026-03-31", "cost": None} for _ in range(4)] + [{"report_date": "2026-03-31"} for _ in range(26)]
    rows += [{"report_date": "2026-03-31", "asset_category": "EQUITY_COMMON", "shares_held": None} for _ in range(5)]
    # a joint venture's own schedule is not published and is not counted
    rows += [{"report_date": "2026-03-31", "principal_amount": None, "accounting_record_class": "underlying_schedule"} for _ in range(40)]
    result = _coverage(rows)
    assert result[("2026-03-31", "cost")] is True
    assert result[("2026-03-31", "principal on drawn loans")] is True
    assert not any(field == "unit count on equity" for _, field in result)
    assert not any(date == "2025-12-31" for date, _ in result)   # no previous quarter to compare with


def test_field_coverage_counts_rows_with_a_positive_value_only():
    # Blue Owl 2024-12-31: the commitments table is tagged from this filing; its rows carry a fair value of
    # zero or below and no cost, maturity, industry or percent. The positions lost nothing.
    bare = {"fair_value": -1.0, "cost": None, "maturity_date": None, "extracted_industry": None, "pct_of_net_assets": None,
            "principal_amount": None}
    rows = [{"report_date": "2024-09-30"} for _ in range(30)]
    rows += [{"report_date": "2024-12-31"} for _ in range(30)] + [{"report_date": "2024-12-31", **bare} for _ in range(15)]
    result = _coverage(rows)
    assert all(holds for (date, _field), holds in result.items() if date == "2024-12-31")
    # a field lost on the positions themselves is still a finding
    rows += [{"report_date": "2025-03-31", "pct_of_net_assets": None} for _ in range(30)]
    assert _coverage(rows)[("2025-03-31", "percent of net assets")] is False
