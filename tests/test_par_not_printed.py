"""The check 'the page prints no par for this row' reads the printed row, not the tags."""
import pandas as pd

from pipeline import disposition_validity as dv

SSLP, APOLLO = "0001925309", "0001837532"


def test_rows_that_print_no_par_pass():
    # Sixth Street Lending Partners, Cordance 2025-06-30: par printed as a dash, cost (443), value 225
    row = "Cordance Operations, LLC (3) | First-lien loan ($- par, due 6/2027 ) | 6/12/2025 | SOFR + 9.00 % | - | ( 443 ) | 225 | 0.0 %"
    assert dv.unexplained_on_printed_row(row, 225000.0, -443000.0) == []
    # the second Galileo line, 2023-06-30: the par is printed once, on the line above
    assert dv.unexplained_on_printed_row("SOFR + 7.25 % | 12.34 % | 9,745 | 10,020 | 1.1 %", 10020000.0, 9745000.0) == []
    # as the page reader stores them: the percent sign and the closing bracket in cells of their own
    assert dv.unexplained_on_printed_row("SOFR + 7.25% | 12.34 | % | 9,745 | 10,020 | 1.1 | %", 10020000.0, 9745000.0) == []
    assert dv.unexplained_on_printed_row("First-lien loan ($- par, due 6/2027) | 6/12/2025 | SOFR + 9.00% | - | (443 | ) | 225 | 0.0 | %",
                                         225000.0, -443000.0) == []
    # Ares prints millions with one decimal; a footnote mark is not a figure
    assert dv.unexplained_on_printed_row("Senior subordinated loan | 13.00 % | 09/2024 | 09/2030 | 78.4 | 76.2 | (2)(11)", 76200000.0, 78400000.0) == []


def test_a_percent_printed_without_its_sign_is_the_rows_percent_and_nothing_else():
    # MSD 2024-03-31: 'Momentive Global - Revolving Credit Facility ... 5/31/2029 - ( 98 ) 45 0.00'
    row = "Momentive Global - Revolving Credit Facility | S + 7.00% | 1.00% | 12.33% | 5/31/2029 | - | (98 | ) | 45 | 0.00"
    assert dv.unexplained_on_printed_row(row, 45000.0, -98000.0) == ["figure not accounted for: 0.00"]
    assert dv.unexplained_on_printed_row(row, 45000.0, -98000.0, 0.002) == []
    # a figure that is not the row's percent is still unexplained
    assert dv.unexplained_on_printed_row(row.replace("0.00", "1.50"), 45000.0, -98000.0, 0.002) == ["figure not accounted for: 1.50"]


def test_a_printed_par_fails_however_it_is_tagged():
    # Apollo SumUp 2024-06-30: 'EUR 40,000 42,858 42,303' and no principal fact
    sumup = "SumUp Holdings Luxembourg S.a.r.l. | First Lien Secured Debt - Delayed Draw | E+ 650 , 1.50 % Floor | 4/25/2031 | EUR 40,000 | 42,858 | 42,303 | (3)(4)(8)"
    assert dv.unexplained_on_printed_row(sumup, 42303000.0, 42858000.0) == ["figure not accounted for: 40,000"]
    # HPS 2026-03-31 shape: par printed, tagged as a unit count
    assert dv.unexplained_on_printed_row("Acme, Inc. | 7/22/2031 | 43,333 | 42,900 | 43,100", 43100000.0, 42900000.0) == ["figure not accounted for: 43,333"]
    # the par stated in the label of the row
    galileo = "Galileo Parent, Inc. (3) | First-lien loan ($ 151,442 par, due 5/2030 ) | 5/3/2023 | 12.34 % | 147,004 | 148,792 | 16.4 %"
    assert any("label states a par" in p for p in dv.unexplained_on_printed_row(galileo, 148792000.0, 147004000.0))


def test_a_row_that_cannot_be_read_or_matched_fails():
    assert dv.unexplained_on_printed_row("", 1.0, 1.0) == ["row not read on the page"]
    assert dv.unexplained_on_printed_row(None, 1.0, 1.0) == ["row not read on the page"]
    # the fair value is not on the row: this is another row
    assert "fair value not found on the row" in dv.unexplained_on_printed_row("Acme | 9,745 | 10,020", 5000000.0, 9745000.0)
    # no cost published: the second amount cannot be called the cost
    assert dv.unexplained_on_printed_row("Acme | 9,745 | 10,020", 10020000.0, None) == ["figure not accounted for: 9,745"]


def _outputs(tmp_path, holdings, printed):
    pd.DataFrame(holdings).to_parquet(tmp_path / "private_markets_holdings.parquet")
    pd.DataFrame([{"cik": h["cik"], "report_date": h["report_date"], "row_id": h["row_id"], "rule_id": "X11",
                   "bdc_investment_identifier": h["bdc_investment_identifier"]} for h in holdings]
                 ).to_csv(tmp_path / "row_validation_issues.csv", index=False)
    pd.DataFrame(printed).to_csv(tmp_path / "bdc_ixbrl_field_status.csv", index=False)


def _row(row_id, name, fair_value, cost, **more):
    return {"row_id": row_id, "cik": SSLP, "report_date": "2025-06-30", "accession_number": "A", "bdc_investment_identifier": name,
            "fair_value": fair_value, "cost": cost, "principal_amount": None, "shares_held": None, "src_facts": "{}",
            "pct_of_net_assets": 0.0, "pct_of_net_assets_calculated": 0.0, **more}


def _entry():
    return {"disposition_id": "DS-X", "ciks": [SSLP], "rule_name": "X11",
            "carry_forward": {"from": "2025-06-30", "check": "par_not_printed", "params": {}}}


def test_the_check_reads_the_page_artifact_row_by_row(tmp_path):
    page = lambda name, text, role="current": {"cik": SSLP, "accession_number": "A", "raw_id_lower": name.lower(),
                                                 "period_role": role, "printed_row": text}
    _outputs(tmp_path, [_row("r1", "Cordance", 225000.0, -443000.0)], [page("Cordance", "First-lien loan ($- par) | - | ( 443 ) | 225")])
    assert [r["passed"] for r in dv.evaluate([_entry()], tmp_path)] == [True]
    # a unit count published, a principal fact tagged, or a par on the page: each fails
    for change, text in ((dict(shares_held=5.0), "( 443 ) | 225"), (dict(src_facts='{"principal_amount":{"unit_ref":"USD"}}'), "( 443 ) | 225"),
                         ({}, "1,000 | ( 443 ) | 225")):
        _outputs(tmp_path, [_row("r1", "Cordance", 225000.0, -443000.0, **change)], [page("Cordance", text)])
        assert [r["passed"] for r in dv.evaluate([_entry()], tmp_path)] == [False]
    # the member printed on two rows, or the row not read: no single printed row, so no pass
    _outputs(tmp_path, [_row("r1", "Cordance", 225000.0, -443000.0)],
             [page("Cordance", "( 443 ) | 225"), page("Cordance", "( 443 ) | 225")])
    assert [r["passed"] for r in dv.evaluate([_entry()], tmp_path)] == [False]
    _outputs(tmp_path, [_row("r1", "Cordance", 225000.0, -443000.0)], [page("Other", "( 443 ) | 225")])
    assert [r["passed"] for r in dv.evaluate([_entry()], tmp_path)] == [False]


def test_the_new_kind_is_a_valid_carry_forward():
    assert dv.validate_carry_forward({"from": "2025-06-30", "check": "par_not_printed", "params": {}}) == []
