"""Broad source industries remain distinct from unsupported GICS classifications."""
import pandas as pd
import pytest

from pipeline.unified_holdings import _apply_printed_industry


@pytest.mark.parametrize("cik,label,expected", [
    ("0001838126", "Real Estate Investment and Services", "Real Estate Investment and Services"),
    ("0001838126", "Paladone", ""),
    ("0001837532", "Real Estate Investment and Services", ""),
])
def test_reviewed_heading_is_exact_and_fund_scoped(monkeypatch, cik, label, expected):
    monkeypatch.setattr("pipeline.source_encodings.load_encodings", lambda: {
        "0001838126": {"printed_industry_labels": ["Real Estate Investment and Services"]}
    })
    frame = pd.DataFrame([{
        "source": "bdc", "cik": cik, "accession_number": "test",
        "bdc_investment_identifier": "Borrower LLC", "extracted_industry": label,
        "gics_sub_industry": None, "index_classification": "DIRECT_LENDING",
    }] * 21)
    result = _apply_printed_industry(frame)
    assert result["extracted_industry"].eq(expected).all()
    assert result["gics_sub_industry"].isna().all()
