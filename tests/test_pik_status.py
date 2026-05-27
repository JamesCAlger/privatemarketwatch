from pathlib import Path

import pandas as pd
from lxml import etree

from pipeline.bdc_position_pik import (
    _extract_pik_evidence_facts,
    _is_pik_current_concept,
    extract_bdc_position_pik_evidence,
)
from pipeline.bdc_filings import _parse_xbrl_contexts
from pipeline.pik_status import build_pik_transitions, build_position_pik_status


def _unified(rows: list[dict]) -> pd.DataFrame:
    cols = [
        "source", "cik", "entity_name", "accession_number", "filing_date",
        "report_date", "issuer_name", "instrument_description",
        "fair_value", "index_classification", "pik_rate",
        "bdc_investment_identifier", "bdc_dimensions_raw",
        "nport_is_paid_in_kind", "position_id",
    ]
    df = pd.DataFrame(rows)
    for col in cols:
        if col not in df.columns:
            df[col] = ""
    return df[cols]


def _xml_tree(body: str) -> etree._ElementTree:
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <xbrli:xbrl
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:bdc="http://example.com/bdc"
      xmlns:test="http://example.com/test">
      {body}
    </xbrli:xbrl>
    """
    return etree.ElementTree(etree.fromstring(xml.encode("utf-8")))


def test_nport_paid_in_kind_flag_maps_to_current_status(tmp_path):
    status, _ = build_position_pik_status(
        unified_df=_unified([
            {"source": "nport", "cik": "1", "report_date": "2024-03-31",
             "issuer_name": "Paying Co", "nport_is_paid_in_kind": "Y"},
            {"source": "nport", "cik": "1", "report_date": "2024-03-31",
             "issuer_name": "Cash Co", "nport_is_paid_in_kind": "N"},
            {"source": "nport", "cik": "1", "report_date": "2024-03-31",
             "issuer_name": "Unknown Co", "nport_is_paid_in_kind": ""},
        ]),
        bdc_evidence_df=pd.DataFrame(),
        output_path=tmp_path / "status.csv",
        transitions_path=tmp_path / "transitions.csv",
    )

    by_name = status.set_index("issuer_name")
    assert by_name.loc["Paying Co", "pik_current_status"] == "paying"
    assert by_name.loc["Paying Co", "pik_current_flag"] == "True"
    assert by_name.loc["Cash Co", "pik_current_status"] == "not_paying"
    assert by_name.loc["Cash Co", "pik_current_flag"] == "False"
    assert by_name.loc["Unknown Co", "pik_current_status"] == "unknown"
    assert by_name.loc["Unknown Co", "pik_current_flag"] == ""


def test_bdc_positive_and_zero_position_evidence_maps_status(tmp_path):
    evidence = pd.DataFrame([
        {"cik": "100", "accession_number": "ACC1", "report_date": "2024-03-31",
         "period": "2024-03-31", "dimensions_raw": "investmentidentifieraxis=Acme Loan",
         "matched_identifier": "Acme Loan", "amount": "125", "evidence_kind": "bdc_position_pik_income_positive",
         "position_level": True},
        {"cik": "100", "accession_number": "ACC1", "report_date": "2024-03-31",
         "period": "2024-03-31", "dimensions_raw": "investmentidentifieraxis=Beta Loan",
         "matched_identifier": "Beta Loan", "amount": "0", "evidence_kind": "bdc_position_pik_income_zero",
         "position_level": True},
    ])
    status, _ = build_position_pik_status(
        unified_df=_unified([
            {"source": "bdc", "cik": "100", "accession_number": "ACC1",
             "report_date": "2024-03-31", "issuer_name": "Acme",
             "bdc_investment_identifier": "Acme Loan",
             "bdc_dimensions_raw": "investmentidentifieraxis=Acme Loan"},
            {"source": "bdc", "cik": "100", "accession_number": "ACC1",
             "report_date": "2024-03-31", "issuer_name": "Beta",
             "bdc_investment_identifier": "Beta Loan",
             "bdc_dimensions_raw": "investmentidentifieraxis=Beta Loan"},
        ]),
        bdc_evidence_df=evidence,
        output_path=tmp_path / "status.csv",
        transitions_path=tmp_path / "transitions.csv",
    )
    by_name = status.set_index("issuer_name")
    assert by_name.loc["Acme", "pik_current_status"] == "paying"
    assert by_name.loc["Acme", "pik_current_amount"] == 125
    assert by_name.loc["Beta", "pik_current_status"] == "not_paying"


def test_fund_level_pik_income_does_not_mark_position_paying(tmp_path):
    evidence = pd.DataFrame([
        {"cik": "100", "accession_number": "ACC1", "report_date": "2024-03-31",
         "period": "2024-03-31", "dimensions_raw": "",
         "matched_identifier": "", "amount": "999", "evidence_kind": "bdc_fund_level_pik_income",
         "position_level": False},
    ])
    status, _ = build_position_pik_status(
        unified_df=_unified([
            {"source": "bdc", "cik": "100", "accession_number": "ACC1",
             "report_date": "2024-03-31", "issuer_name": "Acme",
             "bdc_investment_identifier": "Acme Loan"},
        ]),
        bdc_evidence_df=evidence,
        output_path=tmp_path / "status.csv",
        transitions_path=tmp_path / "transitions.csv",
    )
    assert status.iloc[0]["pik_current_status"] == "unknown"
    assert status.iloc[0]["pik_current_evidence"] == "none"


def test_pik_rate_sets_terms_only_not_current_status(tmp_path):
    status, _ = build_position_pik_status(
        unified_df=_unified([
            {"source": "bdc", "cik": "100", "report_date": "2024-03-31",
             "issuer_name": "Terms Co", "pik_rate": "2.5"},
        ]),
        bdc_evidence_df=pd.DataFrame(),
        output_path=tmp_path / "status.csv",
        transitions_path=tmp_path / "transitions.csv",
    )
    row = status.iloc[0]
    assert row["pik_terms_flag"] == "True"
    assert row["pik_terms_rate"] == 2.5
    assert row["pik_current_status"] == "unknown"
    assert row["pik_current_evidence"] == "terms_only"


def test_pik_transitions_split_observable_and_new_evidence():
    status = pd.DataFrame([
        {"source": "bdc", "cik": "1", "entity_name": "BDC", "position_id": "P1",
         "report_date": "2024-03-31", "pik_current_status": "not_paying",
         "pik_current_evidence": "bdc_position_pik_income_zero", "fair_value": "10"},
        {"source": "bdc", "cik": "1", "entity_name": "BDC", "position_id": "P1",
         "report_date": "2024-06-30", "pik_current_status": "paying",
         "pik_current_evidence": "bdc_position_pik_income_positive", "fair_value": "11"},
        {"source": "bdc", "cik": "1", "entity_name": "BDC", "position_id": "P2",
         "report_date": "2024-03-31", "pik_current_status": "unknown",
         "pik_current_evidence": "none", "fair_value": "20"},
        {"source": "bdc", "cik": "1", "entity_name": "BDC", "position_id": "P2",
         "report_date": "2024-06-30", "pik_current_status": "paying",
         "pik_current_evidence": "bdc_position_pik_income_positive", "fair_value": "21"},
        {"source": "bdc", "cik": "1", "entity_name": "BDC", "position_id": "P3",
         "report_date": "2024-03-31", "pik_current_status": "not_paying",
         "pik_current_evidence": "bdc_position_pik_income_zero", "fair_value": "30"},
        {"source": "bdc", "cik": "2", "entity_name": "BDC2", "position_id": "P3",
         "report_date": "2024-06-30", "pik_current_status": "paying",
         "pik_current_evidence": "bdc_position_pik_income_positive", "fair_value": "31"},
    ])
    transitions = build_pik_transitions(status)
    assert len(transitions[transitions["transition_type"] == "started_paying_pik"]) == 1
    assert len(transitions[transitions["transition_type"] == "new_pik_evidence"]) == 1
    assert set(transitions["position_id"]) == {"P1", "P2"}


def test_bdc_extractor_requires_position_dimension_for_position_level():
    tree = _xml_tree("""
      <xbrli:context id="pos">
        <xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>
          <xbrli:segment>
            <xbrldi:typedMember dimension="bdc:InvestmentIdentifierAxis">
              <bdc:InvestmentIdentifier>Acme Loan</bdc:InvestmentIdentifier>
            </xbrldi:typedMember>
          </xbrli:segment>
        </xbrli:entity>
        <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
      </xbrli:context>
      <xbrli:context id="fund">
        <xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-03-31</xbrli:endDate></xbrli:period>
      </xbrli:context>
      <test:PaidInKindInterestIncome contextRef="pos" unitRef="usd" decimals="0">12</test:PaidInKindInterestIncome>
      <test:PaidInKindInterestIncome contextRef="fund" unitRef="usd" decimals="0">99</test:PaidInKindInterestIncome>
      <test:InvestmentInterestRatePaidInKind contextRef="pos">0.02</test:InvestmentInterestRatePaidInKind>
    """)
    contexts = _parse_xbrl_contexts(tree)
    records = _extract_pik_evidence_facts(
        tree,
        contexts,
        {"cik": "100", "accession_number": "ACC1", "report_date": "2024-03-31"},
    )
    assert len(records) == 2
    by_ctx = {r["context_id"]: r for r in records}
    assert by_ctx["pos"]["position_level"] is True
    assert by_ctx["pos"]["matched_identifier"] == "Acme Loan"
    assert by_ctx["fund"]["position_level"] is False
    assert _is_pik_current_concept("InvestmentInterestRatePaidInKind") is False


def test_extract_bdc_position_pik_evidence_cache_only(tmp_path, monkeypatch):
    xml_path = tmp_path / "filing.xml"
    xml_path.write_text("""<?xml version="1.0" encoding="UTF-8"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:bdc="http://example.com/bdc" xmlns:test="http://example.com/test">
      <xbrli:context id="pos">
        <xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>
          <xbrli:segment>
            <xbrldi:typedMember dimension="bdc:InvestmentIdentifierAxis">
              <bdc:InvestmentIdentifier>Acme Loan</bdc:InvestmentIdentifier>
            </xbrldi:typedMember>
          </xbrli:segment>
        </xbrli:entity>
        <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
      </xbrli:context>
      <test:PaidInKindInterestIncome contextRef="pos" unitRef="usd">12</test:PaidInKindInterestIncome>
    </xbrli:xbrl>""", encoding="utf-8")
    monkeypatch.setattr(
        "pipeline.bdc_position_pik.BDC_POSITION_PIK_EVIDENCE_FILE",
        tmp_path / "evidence.csv",
    )
    filings = pd.DataFrame([{
        "cik": "100", "entity_name": "BDC", "accession_number": "ACC1",
        "form_type": "10-Q", "filing_date": "2024-05-01",
        "report_date": "2024-03-31", "xbrl_download_status": "cached",
        "xbrl_local_path": str(xml_path),
    }])
    result = extract_bdc_position_pik_evidence(filings_index=filings)
    assert len(result) == 1
    assert Path(tmp_path / "evidence.csv").exists()
    assert result.iloc[0]["matched_identifier"] == "Acme Loan"
