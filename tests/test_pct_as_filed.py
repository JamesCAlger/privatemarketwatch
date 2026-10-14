"""disposition_validity kind pct_as_filed_with_calculated: the filer's percent of net assets, as filed,
with the schema value (fair value over net assets) published beside it."""
import json
import sys
from pathlib import Path

import pandas as pd

from pipeline import disposition_validity as dv

CIK = "0001234567"
NAV = 1_000_000_000.0


def _row(row_id, fv, pct, *, tagged=None, calc="auto", corrected="", printed=None, raw_id=None, record_class=""):
    raw_id = raw_id or "acme %s" % row_id
    facts = {} if tagged is False else {"pct_of_net_assets": {"r": (pct / 100.0) if tagged is None else tagged}}
    return {"cik": CIK, "report_date": pd.Timestamp("2025-09-30"), "row_id": row_id, "fair_value": fv,
            "pct_of_net_assets": pct, "pct_of_net_assets_calculated": (fv / NAV * 100) if calc == "auto" else calc,
            "src_facts": json.dumps(facts), "corrected_fields": corrected, "accession_number": "0001234567-25-000001",
            "bdc_investment_identifier": raw_id, "bdc_dimensions_raw": "investmentidentifieraxis=" + raw_id,
            "accounting_record_class": record_class}, (raw_id, printed)


def _sandbox(tmp_path, rows):
    out = tmp_path / "output"
    out.mkdir()
    pd.DataFrame([r for r, _ in rows]).to_parquet(out / "private_markets_holdings.parquet")
    pd.DataFrame({"cik": [CIK], "report_date": ["2025-09-30"], "source": ["companyfacts"], "net_assets": [NAV]}).to_csv(
        out / "fund_financials.csv", index=False)
    pd.DataFrame([{"cik": CIK, "accession_number": "0001234567-25-000001", "raw_id_lower": raw, "period_role": "current",
                   "printed_row": printed} for raw, printed in (p for _, p in rows) if printed is not None],
                 columns=["cik", "accession_number", "raw_id_lower", "period_role", "printed_row"]).to_csv(
        out / "bdc_ixbrl_field_status.csv", index=False)
    return out


def _run(out):
    entry = {"disposition_id": "t", "rule_name": "pct_of_net_assets_identity", "ciks": [CIK],
             "carry_forward": {"from": "2022-01-01", "check": "pct_as_filed_with_calculated", "params": {}}}
    return dv.evaluate([entry], out)


def test_as_filed_percent_with_calculated_value_passes(tmp_path):
    # printed 0.1 against 0.17 by fair value over net assets: fails the identity, filed as printed
    out = _sandbox(tmp_path, [_row("a", 1.7e6, 0.1, printed="Acme | S + 5.00% | 1,700 | 1,700 | 0.1 | %"),
                              _row("ok", 5e6, 0.5, printed=None)])          # holds the identity: not tested
    [result] = _run(out)
    assert result["passed"] and result["rows_tested"] == 1


def test_each_way_the_reason_stops_fitting_fails(tmp_path):
    line = "Acme | 1,700 | 1,700 | 0.1 %"
    cases = {
        "tag differs": _row("b", 1.7e6, 0.1, tagged=0.0017, printed=line),
        "corrected": _row("c", 1.7e6, 0.1, corrected="pct_of_net_assets", printed=line),
        "no calculated": _row("d", 1.7e6, 0.1, calc=None, printed=line),
        # a tag of the wrong scale: published 0.1 is the tag, the page prints 0.17
        "not on the page": _row("e", 1.7e6, 0.1, printed="Acme | 1,700 | 1,700 | 0.17"),
        "not read": _row("f", 1.7e6, 0.1, printed=None),
    }
    for why, row in cases.items():
        folder = tmp_path / why.replace(" ", "_")
        folder.mkdir()
        [result] = _run(_sandbox(folder, [row]))
        assert not result["passed"] and result["rows_failing"] == 1, why


def test_underlying_schedule_rows_are_out_of_scope(tmp_path):
    out = _sandbox(tmp_path, [_row("j", 1.7e6, 0.1, record_class="underlying_schedule", printed=None),
                              _row("a", 1.7e6, 0.1, printed="Acme | 0.1")])
    [result] = _run(out)
    assert result["passed"] and result["rows_tested"] == 1


def test_percent_split_across_cells_is_read_cell_by_cell():
    assert dv._printed_row_shows_percent("Acme | 4,660 | 0.1 | 7", 0.1)
    assert not dv._printed_row_shows_percent("Acme | 4,660 | 0.17", 0.1)
    assert dv._printed_row_shows_percent("Acme | 4,660 | 0.17 | %", 0.17)


def test_row_test_is_the_identity_engines():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import shadow_identity_engine as engine
    [rule] = [r for r in engine.RULES if r.name == "pct_of_net_assets_identity"]
    assert rule.row_filter == dv.PCT_IDENTITY_FILTER
    assert rule.holds_sql == dv.PCT_IDENTITY_HOLDS


def test_kind_is_valid_in_a_carry_forward():
    assert dv.validate_carry_forward({"from": "2022-01-01", "check": "pct_as_filed_with_calculated", "params": {}}) == []
