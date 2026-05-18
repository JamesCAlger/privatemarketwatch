from pathlib import Path

import pandas as pd

from pipeline.validate_nonaccruals import (
    NO_CACHE,
    PASS,
    PASS_POSITION,
    UNDER_REVIEW,
    classify_reconciliation,
    parse_xbrl_evidence,
    select_cached_accession,
)
from pipeline.extract_nonaccrual_flags import build_flags
from pipeline.nonaccrual_evidence import classify_footnote


def _write_xml(path: Path, body: str) -> Path:
    path.write_text(
        f"""<xbrl
            xmlns="http://www.xbrl.org/2003/instance"
            xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink"
            xmlns:test="http://example.com/test">
            {body}
        </xbrl>""",
        encoding="utf-8",
    )
    return path


def _ctx(ctx_id: str, investment_id: str, extra_member: str = "") -> str:
    return f"""
    <xbrli:context id="{ctx_id}">
      <xbrli:entity>
        <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
        <xbrli:segment>
          <xbrldi:typedMember dimension="test:InvestmentIdentifierAxis">
            <test:InvestmentIdentifier>{investment_id}</test:InvestmentIdentifier>
          </xbrldi:typedMember>
          {extra_member}
        </xbrli:segment>
      </xbrli:entity>
      <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
    </xbrli:context>
    """


def _aggregate_ctx(ctx_id: str, period: str) -> str:
    return f"""
    <xbrli:context id="{ctx_id}">
      <xbrli:entity>
        <xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
      </xbrli:entity>
      <xbrli:period><xbrli:instant>{period}</xbrli:instant></xbrli:period>
    </xbrli:context>
    """


def test_select_cached_accession_from_holding_row(tmp_path):
    xml = tmp_path / "acc.xml"
    xml.write_text("<xbrl/>", encoding="utf-8")
    filings = pd.DataFrame([{
        "cik": "1",
        "accession_number": "0000000001-26-000001",
        "xbrl_local_path": str(xml),
    }])
    row = {"cik": "0000000001", "accession_number": "0000000001-26-000001"}

    accession, path = select_cached_accession(row, filings)

    assert accession == "0000000001-26-000001"
    assert path == str(xml)


def test_nonaccrual_dimension_evidence_detection(tmp_path):
    xml = _write_xml(
        tmp_path / "dimension.xml",
        _ctx(
            "c1",
            "Acme Loan",
            '<xbrldi:explicitMember dimension="test:InvestmentTypeAxis">'
            "test:DebtSecuritiesNonAccrualStatusMember"
            "</xbrldi:explicitMember>",
        )
        + '<test:InvestmentOwnedAtFairValue contextRef="c1">900</test:InvestmentOwnedAtFairValue>',
    )

    evidence, aggregate, has_language = parse_xbrl_evidence(xml, {"Acme Loan"})

    assert bool(evidence.iloc[0]["has_position_evidence"]) is True
    assert bool(evidence.iloc[0]["dimension_evidence"]) is True
    assert has_language is True
    assert aggregate.fair_value is None


def test_nonaccrual_footnote_to_position_evidence_detection(tmp_path):
    xml = _write_xml(
        tmp_path / "footnote.xml",
        _ctx("c1", "Beta Loan")
        + """
        <test:InvestmentOwnedAtFairValue contextRef="c1" id="fact1">100</test:InvestmentOwnedAtFairValue>
        <link:footnoteLink>
          <link:loc xlink:label="loc1" xlink:href="#fact1" />
          <link:footnote xlink:label="fn1">Placed on non-accrual status.</link:footnote>
          <link:footnoteArc xlink:from="loc1" xlink:to="fn1" />
        </link:footnoteLink>
        """,
    )

    evidence, _, _ = parse_xbrl_evidence(xml, {"Beta Loan"})

    assert bool(evidence.iloc[0]["has_position_evidence"]) is True
    assert bool(evidence.iloc[0]["footnote_evidence"]) is True


def test_footnote_classifier_rejects_negated_and_exclusion_language():
    no_investments = classify_footnote(
        "The Company had no portfolio company investment on non-accrual status.",
        "2025-12-31",
    )
    excludes = classify_footnote(
        "The listed investments exclude those on non-accrual.",
        "2025-12-31",
    )

    assert no_investments.accepted is False
    assert no_investments.reason == "negated_language"
    assert excludes.accepted is False
    assert excludes.reason == "exclusion_language"


def test_footnote_classifier_rejects_stale_comparative_date():
    decision = classify_footnote(
        "Loan was on non-accrual status as of December 31, 2024.",
        "2025-12-31",
    )

    assert decision.accepted is False
    assert decision.reason == "stale_or_comparative_date"


def test_parse_xbrl_rejects_stale_footnote_evidence(tmp_path):
    xml = _write_xml(
        tmp_path / "stale_footnote.xml",
        _ctx("c1", "Gamma Loan")
        + """
        <test:InvestmentOwnedAtFairValue contextRef="c1" id="fact1">100</test:InvestmentOwnedAtFairValue>
        <link:footnoteLink>
          <link:loc xlink:label="loc1" xlink:href="#fact1" />
          <link:footnote xlink:label="fn1">Loan was on non-accrual status as of December 31, 2024.</link:footnote>
          <link:footnoteArc xlink:from="loc1" xlink:to="fn1" />
        </link:footnoteLink>
        """,
    )

    evidence, _, has_language = parse_xbrl_evidence(
        xml,
        {"Gamma Loan"},
        report_date="2025-12-31",
    )

    assert bool(evidence.iloc[0]["has_position_evidence"]) is False
    assert bool(evidence.iloc[0]["footnote_evidence"]) is False
    assert has_language is False


def test_current_period_aggregate_selection_ignores_larger_prior_period(tmp_path):
    xml = _write_xml(
        tmp_path / "aggregate_period.xml",
        _aggregate_ctx("prior", "2024-12-31")
        + _aggregate_ctx("current", "2025-12-31")
        + """
        <test:NonAccrualLoansAtFairValue contextRef="prior" unitRef="usd">500000000</test:NonAccrualLoansAtFairValue>
        <test:NonAccrualLoansAtFairValue contextRef="current" unitRef="usd">100000000</test:NonAccrualLoansAtFairValue>
        """,
    )

    _, aggregate, has_language = parse_xbrl_evidence(
        xml,
        set(),
        report_date="2025-12-31",
    )

    assert aggregate.fair_value == 100_000_000
    assert aggregate.cost is None
    assert has_language is True


def test_extractor_preserves_nonaccrual_flag_join_contract(tmp_path):
    xml = _write_xml(
        tmp_path / "extract.xml",
        _ctx("c1", "Delta Loan")
        + """
        <test:InvestmentOwnedAtFairValue contextRef="c1" id="fact1">100</test:InvestmentOwnedAtFairValue>
        <link:footnoteLink>
          <link:loc xlink:label="loc1" xlink:href="#fact1" />
          <link:footnote xlink:label="fn1">Asset is on non-accrual status.</link:footnote>
          <link:footnoteArc xlink:from="loc1" xlink:to="fn1" />
        </link:footnoteLink>
        """,
    )
    filings = pd.DataFrame([{
        "cik": "1",
        "accession_number": "0000000001-26-000001",
        "report_date": "2025-12-31",
        "xbrl_local_path": str(xml),
    }])

    flags, candidates = build_flags(filings)

    assert {
        "cik",
        "report_date",
        "investment_identifier",
    }.issubset(flags.columns)
    assert flags.loc[0, "cik"] == "0000000001"
    assert flags.loc[0, "report_date"] == "2025-12-31"
    assert flags.loc[0, "investment_identifier"] == "Delta Loan"
    assert bool(candidates.loc[0, "accepted"]) is True


def test_agl_no_nonaccrual_language_produces_no_accepted_flags(tmp_path):
    xml = _write_xml(
        tmp_path / "agl.xml",
        _ctx("c1", "AGL Loan")
        + """
        <test:InvestmentOwnedAtFairValue contextRef="c1" id="fact1">100</test:InvestmentOwnedAtFairValue>
        <link:footnoteLink>
          <link:loc xlink:label="loc1" xlink:href="#fact1" />
          <link:footnote xlink:label="fn1">The Company had no portfolio company investment on non-accrual status.</link:footnote>
          <link:footnoteArc xlink:from="loc1" xlink:to="fn1" />
        </link:footnoteLink>
        """,
    )
    filings = pd.DataFrame([{
        "cik": "1",
        "accession_number": "0000000001-26-000001",
        "report_date": "2025-12-31",
        "xbrl_local_path": str(xml),
    }])

    flags, candidates = build_flags(filings)

    assert flags.empty
    assert candidates.loc[0, "rejection_reason"] == "negated_language"


def test_prospect_excludes_nonaccrual_language_does_not_flag_pik_rows(tmp_path):
    xml = _write_xml(
        tmp_path / "prospect_pik.xml",
        _ctx("c1", "Prospect PIK Table Row")
        + """
        <test:InvestmentOwnedAtFairValue contextRef="c1" id="fact1">100</test:InvestmentOwnedAtFairValue>
        <link:footnoteLink>
          <link:loc xlink:label="loc1" xlink:href="#fact1" />
          <link:footnote xlink:label="fn1">PIK income excludes those on non-accrual.</link:footnote>
          <link:footnoteArc xlink:from="loc1" xlink:to="fn1" />
        </link:footnoteLink>
        """,
    )
    filings = pd.DataFrame([{
        "cik": "2",
        "accession_number": "0000000002-26-000001",
        "report_date": "2025-12-31",
        "xbrl_local_path": str(xml),
    }])

    flags, candidates = build_flags(filings)

    assert flags.empty
    assert candidates.loc[0, "rejection_reason"] == "exclusion_language"


def test_aggregate_reconciliation_pass_fail_tolerance():
    assert classify_reconciliation(
        flagged_fv=100_500_000,
        flagged_cost=120_000_000,
        disclosed_fv=100_000_000,
        disclosed_cost=None,
        all_positions_evidenced=False,
        has_nonaccrual_language=True,
        cache_available=True,
    ) == PASS

    assert classify_reconciliation(
        flagged_fv=130_000_000,
        flagged_cost=130_000_000,
        disclosed_fv=100_000_000,
        disclosed_cost=None,
        all_positions_evidenced=False,
        has_nonaccrual_language=True,
        cache_available=True,
    ) == "FAIL_OVER_FLAGGED"


def test_fv_aggregate_match_passes_even_when_cost_mismatches():
    assert classify_reconciliation(
        flagged_fv=100_500_000,
        flagged_cost=150_000_000,
        disclosed_fv=100_000_000,
        disclosed_cost=80_000_000,
        all_positions_evidenced=False,
        has_nonaccrual_language=True,
        cache_available=True,
    ) == PASS


def test_complete_direct_position_evidence_passes_despite_aggregate_variance():
    assert classify_reconciliation(
        flagged_fv=130_000_000,
        flagged_cost=140_000_000,
        disclosed_fv=100_000_000,
        disclosed_cost=100_000_000,
        all_positions_evidenced=True,
        has_nonaccrual_language=True,
        cache_available=True,
    ) == PASS_POSITION


def test_incomplete_direct_evidence_with_current_fv_variance_fails():
    assert classify_reconciliation(
        flagged_fv=130_000_000,
        flagged_cost=140_000_000,
        disclosed_fv=100_000_000,
        disclosed_cost=100_000_000,
        all_positions_evidenced=False,
        has_nonaccrual_language=True,
        cache_available=True,
    ) == "FAIL_OVER_FLAGGED"

    assert classify_reconciliation(
        flagged_fv=70_000_000,
        flagged_cost=80_000_000,
        disclosed_fv=100_000_000,
        disclosed_cost=100_000_000,
        all_positions_evidenced=False,
        has_nonaccrual_language=True,
        cache_available=True,
    ) == "FAIL_UNDER_FLAGGED"


def test_no_cache_and_under_review_statuses():
    assert classify_reconciliation(
        flagged_fv=1,
        flagged_cost=1,
        disclosed_fv=None,
        disclosed_cost=None,
        all_positions_evidenced=False,
        has_nonaccrual_language=False,
        cache_available=False,
    ) == NO_CACHE

    assert classify_reconciliation(
        flagged_fv=1,
        flagged_cost=1,
        disclosed_fv=None,
        disclosed_cost=None,
        all_positions_evidenced=False,
        has_nonaccrual_language=True,
        cache_available=True,
    ) == UNDER_REVIEW


def test_near_par_flagged_position_rejected_without_direct_evidence():
    assert classify_reconciliation(
        flagged_fv=99_900_000,
        flagged_cost=100_000_000,
        disclosed_fv=None,
        disclosed_cost=None,
        all_positions_evidenced=False,
        has_nonaccrual_language=True,
        cache_available=True,
    ) == UNDER_REVIEW

    assert classify_reconciliation(
        flagged_fv=99_900_000,
        flagged_cost=100_000_000,
        disclosed_fv=None,
        disclosed_cost=None,
        all_positions_evidenced=True,
        has_nonaccrual_language=True,
        cache_available=True,
    ) == PASS_POSITION
