"""Whole-PIK loan classification preserves the published all-in/cash split."""
import csv
import json

import duckdb
import pandas as pd
import pytest

from pipeline.financial_conventions import prepare, synchronize_matches
from pipeline.financial_validation import violations
from pipeline.holdings_finalizer import write_final_identity
from pipeline.index_returns import compute_returns
from pipeline.unified_holdings import _apply_row_corrections
from tests.test_holdings_finalizer import holdings, matches


CIK = "0001918712"
READING = dict(rate_readings={CIK: "all_in"}, pik_only_coupon={CIK},
               pik_only_margin=set(), no_untagged_pik=set())


def test_corrected_unit_loan_publishes_zero_cash_and_counts_pik_income_once(tmp_path, monkeypatch):
    # Source-reviewed class correction activates the existing PIK-only coupon reading.
    # A separate, explicitly tagged cash coupon must keep its actual cash component.
    observations = []
    corrections = []
    for name, rate, concept in (("CFC Funding", "", ""),
                                ("Cash Coupon Control", "4.0", "investmentinterestratepaidincash")):
        for number, date in enumerate(("2025-12-31", "2026-03-31")):
            key = dict(cik=CIK, report_date=date, accession_number="accession-" + str(number),
                       bdc_investment_identifier=name + " Loan Units")
            observations.append(dict(key, row_id=name + str(number), position_id=name,
                src_context_id="context-" + name + str(number), issuer_name=name,
                instrument_description="Loan Units", asset_category="EQUITY_COMMON",
                index_classification="COMMON_EQUITY", asset_class="PRIVATE_EQUITY",
                fair_value="1000000", cost="1000000", principal_amount="1000000",
                interest_rate=rate, interest_rate_kind="", pik_rate="9.75", basis_spread="",
                src_facts=json.dumps({"interest_rate": {"c": concept}})))
            for field, value in (("asset_category", "LOAN"),
                                 ("index_classification", "DIRECT_LENDING"),
                                 ("asset_class", "PRIVATE_CREDIT")):
                corrections.append(dict(key, field=field, value=value, reason="reviewed loan units",
                    source_evidence="synthetic source-contract fixture", author="test", date_added="2026-11-13"))
    path = tmp_path / "corrections.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(corrections[0]))
        writer.writeheader()
        writer.writerows(corrections)
    corrected = _apply_row_corrections(holdings(observations), corrections_path=path)
    assert corrected.asset_category.eq("LOAN").all()
    prepared, states = prepare(corrected, source_frame=True, **READING)
    assert violations(prepared) == []
    replay, _ = prepare(prepared, prior_states=states, **READING)
    pd.testing.assert_series_equal(prepared.interest_rate_cash, replay.interest_rate_cash)

    financial_pairs = matches()
    for name in ("CFC Funding", "Cash Coupon Control"):
        financial_pairs.loc[len(financial_pairs)] = {**dict.fromkeys(financial_pairs.columns, ""),
            "cik": CIK, "source": "bdc", "position_id": name,
            "begin_issuer_name": name, "end_issuer_name": name,
            "begin_report_date": "2025-12-31", "end_report_date": "2026-03-31",
            "begin_quarter": "2025Q4", "end_quarter": "2026Q1", "span_months": "3",
            "index_classification": "DIRECT_LENDING", "asset_category": "LOAN",
            "begin_principal_amount": "1000000", "end_principal_amount": "1000000"}
    synced = synchronize_matches(financial_pairs, prepared)
    hp, mp = tmp_path / "private_markets_holdings.csv", tmp_path / "position_matches.csv"
    write_final_identity(prepared, synced, holdings_file=hp, matches_file=mp)
    with duckdb.connect() as con:
        final = con.execute("SELECT * FROM read_parquet(?)", [str(hp.with_suffix(".parquet"))]).fetchdf()
        written_pairs = con.execute("SELECT * FROM read_parquet(?)", [str(mp.with_suffix(".parquet"))]).fetchdf()
    pik_only = final[final.issuer_name.eq("CFC Funding")]
    assert pik_only.interest_rate.eq(9.75).all()  # Published v2 rate is all-in.
    assert pik_only.interest_rate_cash.eq(0.0).all()
    assert pik_only.interest_rate_reported.isna().all()
    assert pik_only.pik_rate.eq(9.75).all()
    assert pik_only.src_transforms.str.contains("interest_rate:pik_only", regex=False).all()
    cash = final[final.issuer_name.eq("Cash Coupon Control")]
    assert cash.interest_rate_cash.eq(4.0).all()
    assert cash.interest_rate.eq(13.75).all()
    monkeypatch.setattr("pipeline.index_returns.POSITION_RETURNS_FILE", tmp_path / "returns.csv")
    monkeypatch.setattr("pipeline.index_returns.INDEX_RETURNS_FILE", tmp_path / "indices.csv")
    returns, _ = compute_returns(written_pairs,
        fee_uplift_df=pd.DataFrame(columns=["cik", "quarter", "effective_uplift"]),
        unified_pik_df=final[["cik", "source", "report_date", "position_id", "pik_rate"]])
    income = returns.set_index("position_id").income_return
    assert income["CFC Funding"] == pytest.approx(0.0975 / 4)
    assert income["Cash Coupon Control"] == pytest.approx(0.1375 / 4)


@pytest.mark.parametrize("change", [
    {"cik": "0000000123"}, {"asset_category": "EQUITY_COMMON"},
    {"basis_spread": "6.0"}, {"pik_rate": ""},
])
def test_missing_or_unsupported_coupon_keeps_unknown_cash(change):
    row = dict(cik=CIK, interest_rate="", interest_rate_kind="", pik_rate="9.75", basis_spread="")
    final, _ = prepare(holdings([dict(row, **change)]), source_frame=True, **READING)
    assert final.interest_rate_cash.isna().all()
    assert final.interest_rate.isna().all()
