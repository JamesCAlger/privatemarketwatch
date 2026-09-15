"""Source roles must not inherit the extractor's blind spots or excuse ambiguity."""
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from pipeline.context_inventory import fund_quarter_class, scan_instance

HEADER = '''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:iso="http://www.xbrl.org/2003/iso4217"
 xmlns:gaap="http://fasb.org/us-gaap/2022" xmlns:dei="http://xbrl.sec.gov/dei/2022"
 xmlns:f="http://example.test/fund" xmlns:n="http://www.npci.com/20230331">
 <xbrli:unit id="USD"><xbrli:measure>iso:USD</xbrli:measure></xbrli:unit>'''


def context(key, dimensions="", date="2023-03-31", cik="1588272"):
    return f'''<xbrli:context id="{key}"><xbrli:entity>
    <xbrli:identifier scheme="http://www.sec.gov/CIK">{cik}</xbrli:identifier>
    <xbrli:segment>{dimensions}</xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:instant>{date}</xbrli:instant></xbrli:period></xbrli:context>'''


def typed(value):
    return ('<xbrldi:typedMember dimension="f:InvestmentIdentifierAxis">'
            f'<f:Identifier>{escape(value)}</f:Identifier></xbrldi:typedMember>')


def explicit(axis, member):
    return f'<xbrldi:explicitMember dimension="{axis}">{member}</xbrldi:explicitMember>'


def fact(key, value="100", concept="gaap:InvestmentOwnedAtFairValue", unit="USD", fid=""):
    return f'<{concept} contextRef="{key}" unitRef="{unit}" id="{fid}">{value}</{concept}>'


def scan(tmp_path, body, **kwargs):
    path = tmp_path / "instance.xml"
    path.write_text(HEADER + body + "</xbrli:xbrl>", encoding="utf-8")
    return scan_instance(path, "1588272", "2023-03-31", **kwargs)


def disposition(result, total="100"):
    return fund_quarter_class(complete=result["source_complete"],
        positions=result["counts"]["confirmed_position"], unresolved=result["counts"]["unresolved"],
        investment_total=Decimal(total) if total is not None else None)


def test_mixed_preserves_unknown_and_counts_contexts_once(tmp_path):
    body = context("loan", typed("Total Safety LLC First Lien")) + context("unknown")
    body += fact("loan", "0") + fact("loan", "1", "gaap:InvestmentOwnedAtCost") + fact("unknown")
    result = scan(tmp_path, body)
    assert result["source_complete"]
    assert result["counts"] == {"confirmed_position": 1, "aggregate": 0, "unresolved": 1}
    assert result["candidate_context_count"] == sum(result["counts"].values()) == 2
    assert disposition(result) == "extraction_failure"
    assert result["contexts"][0]["fair_value"] == "0"


def test_aggregate_only_requires_independent_accounting_basis(tmp_path):
    result = scan(tmp_path, context("fund") + fact("fund") + fact("fund", "150", "gaap:Assets"))
    assert result["counts"] == {"confirmed_position": 0, "aggregate": 1, "unresolved": 0}
    assert disposition(result) == "eligible_no_position_facts"


@pytest.mark.parametrize("basis", ["", fact("fund", "150", "f:Assets")])
def test_bare_total_or_lookalike_extension_is_unresolved(tmp_path, basis):
    result = scan(tmp_path, context("fund") + fact("fund") + basis)
    assert disposition(result) == "unresolved_context_pattern"


def test_standard_category_is_aggregate_not_position(tmp_path):
    dims = explicit("gaap:FairValueByFairValueHierarchyLevelAxis", "gaap:FairValueInputsLevel3Member")
    result = scan(tmp_path, context("category", dims) + fact("category"))
    assert result["counts"]["aggregate"] == 1


@pytest.mark.parametrize("identifier", ["Software", "Total Investments", "First Lien", "123456"])
def test_category_typed_identifier_is_not_a_position(tmp_path, identifier):
    result = scan(tmp_path, context("category", typed(identifier)) + fact("category"))
    assert result["contexts"][0]["extractor_recognized"]
    assert disposition(result) == "unresolved_context_pattern"


def test_explicit_equity_is_supported_only_in_observed_source_scope(tmp_path):
    dims = explicit("dei:LegalEntityAxis", "n:IqhqIncMember")
    dims += explicit("gaap:InvestmentTypeAxis", "n:CommonStocksAtTwentySevenPointTwoPercentMember")
    dims += explicit("gaap:InvestmentSecondaryCategorizationAxis", "n:RealEstateAtEightPointSevenPercentageMember")
    result = scan(tmp_path, context("equity", dims) + fact("equity", "2359000"))
    assert result["counts"]["confirmed_position"] == 1
    assert result["contexts"][0]["extractor_recognized"]
    # A new accounting scope is not rescued by merely finding a legal entity.
    dims += explicit("f:ConsolidationAxis", "f:UnknownScopeMember")
    result = scan(tmp_path, context("equity", dims) + fact("equity"))
    assert result["counts"]["unresolved"] == 1


def test_unknown_concept_and_comparative_period_do_not_prove_absence(tmp_path):
    body = context("prior", typed("Acme First Lien"), date="2022-12-31") + fact("prior")
    body += context("current", typed("Acme First Lien")) + fact("current", concept="f:NewInvestmentFairValue")
    result = scan(tmp_path, body)
    assert result["candidate_context_count"] == 1
    assert result["target_instant_contexts"] == 1
    assert result["contexts"][0]["context_id"] == "current"
    assert disposition(result) == "unresolved_context_pattern"


@pytest.mark.parametrize("value", ["0", "-100"])
def test_nonpositive_positions_are_retained(tmp_path, value):
    result = scan(tmp_path, context("loan", typed("Acme First Lien")) + fact("loan", value))
    assert result["counts"]["confirmed_position"] == 1
    assert result["contexts"][0]["fair_value"] == value


def test_conflicting_fv_and_unknown_currency_remain_unassessable(tmp_path):
    body = context("loan", typed("Acme First Lien")) + fact("loan") + fact("loan", "200")
    result = scan(tmp_path, body)
    assert result["contexts"][0]["fair_value_status"] == "conflicting_facts"
    body = context("loan", typed("Acme First Lien")) + fact("loan", unit="fake")
    body += '<xbrli:unit id="fake"><xbrli:measure>f:USD</xbrli:measure></xbrli:unit>'
    result = scan(tmp_path, body)
    assert result["contexts"][0]["fair_value_currency"] is None
    assert result["contexts"][0]["fair_value_status"] == "unavailable"


@pytest.mark.parametrize("body", [context("same") * 2 + fact("same"), fact("missing")])
def test_broken_context_references_block_absence_claim(tmp_path, body):
    result = scan(tmp_path, body)
    assert not result["source_complete"]
    assert disposition(result) == "source_unavailable"


def test_missing_and_oversized_sources_are_unavailable(tmp_path):
    result = scan_instance(tmp_path / "missing.xml", "1588272", "2023-03-31")
    assert disposition(result) == "source_unavailable"
    result = scan(tmp_path, context("loan") + fact("loan"), max_bytes=1)
    assert disposition(result) == "source_unavailable"


def test_large_disclosure_text_does_not_hide_small_position_facts(tmp_path):
    body = context("loan", typed("Acme First Lien")) + fact("loan")
    body += '<gaap:ScheduleOfInvestmentsTextBlock>' + ('x' * 10_000_100) + '</gaap:ScheduleOfInvestmentsTextBlock>'
    result = scan(tmp_path, body)
    assert result["source_complete"]
    assert result["counts"]["confirmed_position"] == 1


def test_dtd_is_rejected_even_with_large_text_support(tmp_path):
    path = tmp_path / "instance.xml"
    path.write_text('<!DOCTYPE xbrli:xbrl [<!ENTITY hidden "100">]>' + HEADER +
                    context("loan", typed("Acme First Lien")) + fact("loan", "&hidden;") +
                    '</xbrli:xbrl>', encoding="utf-8")
    result = scan_instance(path, "1588272", "2023-03-31")
    assert not result["source_complete"]
    assert disposition(result) == "source_unavailable"


@pytest.mark.parametrize("total", [None, Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_empty_candidate_is_not_automatically_excluded(total):
    assert fund_quarter_class(complete=True, positions=0, unresolved=0,
        investment_total=total) == "eligible_empty_candidate"


@pytest.mark.needs_cache
def test_nexpoint_complete_schedule_control():
    path = Path(__file__).resolve().parents[1] / "data/raw/filings/bdc_xbrl/1588272/000119312523145196.xml"
    if not path.is_file():
        pytest.skip("NexPoint source not cached")
    result = scan_instance(path, "1588272", "2023-03-31")
    positions = [c for c in result["contexts"] if c["role"] == "confirmed_position"]
    assert result["source_complete"]
    assert len(positions) == 39  # 32 was one HTML table's candidate count, not the full schedule.
    assert all(c["extractor_recognized"] for c in positions)
    assert sum(Decimal(c["fair_value"]) for c in positions) == Decimal("48731529")
    auris = next(c for c in positions if "AurisLuxembourg" in c["context_id"])
    assert auris["fair_value"] == "1331038"
    assert result["counts"]["aggregate"] > 0
    assert result["counts"]["unresolved"] > 0
    assert disposition(result) == "extraction_failure"


def test_census_prefers_primary_quarter_over_later_comparative():
    from scripts.run_context_census import select_source
    obligation = dict(cik="0001588272", report_date="2023-03-31", positive_source_accession="later")
    filings = [dict(cik="0001588272", report_date="2023-03-31", filing_date="2023-05-01", accession_number="original"),
               dict(cik="0001588272", report_date="2023-03-31", filing_date="2023-05-02", accession_number="amended"),
               dict(cik="0001588272", report_date="2023-06-30", filing_date="2023-08-01", accession_number="later")]
    assert select_source(obligation, filings) == ("amended", "latest_indexed_primary_for_quarter", 2)


def test_census_missing_primary_retains_explicit_fallback_basis():
    from scripts.run_context_census import select_source
    obligation = dict(cik="0001588272", report_date="2023-03-31", positive_source_accession="later")
    assert select_source(obligation, []) == ("later", "companyfacts_accession_fallback", 0)
    obligation["positive_source_accession"] = ""
    assert select_source(obligation, []) == ("", "no_selected_accession", 0)


def test_cash_sweep_is_aggregate_and_primary_census_reports_cash_only(tmp_path):
    from scripts.run_context_census import classify_selected_source
    from pipeline.context_inventory import CASH_ONLY_PUBLIC_WORDING
    body = context("fund") + fact("fund", "500", "gaap:MoneyMarketFundsAtCarryingValue")
    body += context("sweep", typed("Morgan Stanley Institutional Liquidity Funds"))
    body += fact("sweep", "500", "gaap:MoneyMarketFundsAtCarryingValue")
    body += '<dei:DocumentPeriodEndDate contextRef="fund">2023-03-31</dei:DocumentPeriodEndDate>'
    result = scan(tmp_path, body)
    assert result["counts"] == {"confirmed_position": 0, "aggregate": 2, "unresolved": 0}
    assert result["cash_equivalent_total"] == "500"
    assert classify_selected_source(result, None) == "eligible_no_position_facts"
    assert result["public_status_wording"] == CASH_ONLY_PUBLIC_WORDING


@pytest.mark.parametrize("other,expected", [
    ("gaap:InvestmentOwnedAtFairValue", "confirmed_position"),
    ("f:NovelInvestmentFairValue", "unresolved"),
])
def test_cash_fact_does_not_excuse_non_cash_in_same_context(tmp_path, other, expected):
    result = scan(tmp_path, context("mixed", typed("Acme First Lien")) +
        fact("mixed", concept="gaap:MoneyMarketFundsAtCarryingValue") + fact("mixed", concept=other))
    assert result["contexts"][0]["role"] == expected
    assert not result["cash_only_contexts"]


def test_extension_cash_lookalike_is_not_excused(tmp_path):
    result = scan(tmp_path, context("sweep", typed("Acme First Lien")) +
        fact("sweep", concept="f:MoneyMarketFundsAtCarryingValue"))
    assert result["counts"]["confirmed_position"] == 1
    assert result["cash_equivalent_status"] == "unavailable"


@pytest.mark.parametrize("value,unit", [("200", "USD"), ("NaN", "USD"), ("100", "missing")])
def test_conflicting_or_invalid_cash_total_does_not_certify_absence(tmp_path, value, unit):
    from scripts.run_context_census import classify_selected_source
    body = context("fund") + fact("fund", concept="gaap:MoneyMarketFundsAtCarryingValue")
    body += fact("fund", value, "gaap:MoneyMarketFundsAtCarryingValue", unit)
    body += '<dei:DocumentPeriodEndDate contextRef="fund">2023-03-31</dei:DocumentPeriodEndDate>'
    result = scan(tmp_path, body)
    assert result["cash_equivalent_status"] == "conflicting_facts"
    assert classify_selected_source(result, None) == "eligible_empty_candidate"


@pytest.mark.parametrize("complete,primary", [(False, True), (True, False)])
def test_cash_does_not_excuse_incomplete_or_comparative_only_source(complete, primary):
    from scripts.run_context_census import classify_selected_source
    result = dict(counts=dict(confirmed_position=0, aggregate=1, unresolved=0), source_complete=complete,
        target_instant_contexts=1, quarter="2023-03-31", errors=[],
        document_period_ends=["2023-03-31" if primary else "2023-06-30"],
        cash_equivalent_total="500", cash_equivalent_status="reported", cash_only_contexts=True)
    assert classify_selected_source(result, None) == "source_unavailable"
    assert not result["public_status_wording"]


@pytest.mark.needs_cache
def test_golub_cash_only_primary_source():
    from scripts.run_context_census import classify_selected_source
    from pipeline.context_inventory import CASH_ONLY_PUBLIC_WORDING
    source = Path(__file__).resolve().parents[1] / "data/raw/filings/bdc_xbrl/1930087/000193008723000010.xml"
    if not source.is_file():
        pytest.skip("Golub primary source not cached")
    result = scan_instance(source, "1930087", "2023-06-30")
    assert result["source_complete"]
    assert result["counts"]["confirmed_position"] == result["counts"]["unresolved"] == 0
    assert result["cash_equivalent_total"] == "650323000"
    assert classify_selected_source(result, None) == "eligible_no_position_facts"
    assert result["public_status_wording"] == CASH_ONLY_PUBLIC_WORDING


def test_aggregate_investments_are_not_labelled_cash_only(tmp_path):
    from scripts.run_context_census import classify_selected_source
    result = scan(tmp_path, context("fund") + fact("fund") + fact("fund", "150", "gaap:Assets") +
        '<dei:DocumentPeriodEndDate contextRef="fund">2023-03-31</dei:DocumentPeriodEndDate>')
    assert classify_selected_source(result, Decimal("100")) == "eligible_no_position_facts"
    assert result["public_status_wording"] == "No portfolio position facts disclosed."


def test_active_obligation_register_conserves_the_owner_approved_cohort():
    import csv
    from scripts.run_context_census import REGISTER, ELIGIBLE_OBLIGATIONS, EXCLUDED_OBLIGATIONS, ZERO_OUTPUT_OBLIGATIONS
    with REGISTER.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len({(r["cik"], r["report_date"]) for r in rows}) == 70 * 13
    assert len({r["cik"] for r in rows}) == 70
    eligible = [r for r in rows if r["eligibility_status"].startswith("eligible")]
    excluded = [r for r in rows if r["eligibility_status"] in {"not_yet_investment_operating", "not_yet_reporting"}]
    assert len(eligible) == ELIGIBLE_OBLIGATIONS == 804
    assert len(excluded) == EXCLUDED_OBLIGATIONS == 106
    assert sum(int(r["holdings_rows"]) == 0 for r in eligible) == ZERO_OUTPUT_OBLIGATIONS == 25
    reporting = [r for r in excluded if r["eligibility_status"] == "not_yet_reporting"]
    assert len(reporting) == 8
    assert all("EDGAR-" in r["evidence_ids"] and int(r["holdings_rows"]) == 0 for r in reporting)


@pytest.mark.parametrize("primary", [False, True])
def test_comparative_aggregate_cannot_establish_exception(primary):
    from scripts.run_context_census import classify_selected_source
    result = dict(counts={"confirmed_position": 0, "aggregate": 1, "unresolved": 0},
                  source_complete=True, target_instant_contexts=1, quarter="2024-06-30", errors=[],
                  document_period_ends=["2024-06-30" if primary else "2024-09-30"])
    assert classify_selected_source(result, Decimal("228062000")) == (
        "eligible_no_position_facts" if primary else "source_unavailable")


def test_comparative_positive_positions_still_prove_omission():
    from scripts.run_context_census import classify_selected_source
    result = dict(counts={"confirmed_position": 2, "aggregate": 1, "unresolved": 1},
                  source_complete=True, target_instant_contexts=3, quarter="2023-12-31", errors=[],
                  document_period_ends=["2024-12-31"])
    assert classify_selected_source(result, Decimal("100")) == "extraction_failure"


# ---------------------------------------------------------------------------
# Lord Abbett (CIK 2008748): explicit srt:OwnershipAxis positions
# ---------------------------------------------------------------------------
LA_HEADER = HEADER.replace('xmlns:n="http://www.npci.com/20230331">',
    'xmlns:n="http://www.npci.com/20230331" xmlns:srt="http://fasb.org/srt/2026"'
    ' xmlns:la="http://www.lordabbett.com/20260331">')


def la_scan(tmp_path, body):
    path = tmp_path / "instance.xml"
    path.write_text(LA_HEADER + body + "</xbrli:xbrl>", encoding="utf-8")
    return scan_instance(path, "2008748", "2026-03-31")


def test_lordabbett_ownership_axis_positions_are_confirmed_and_recognized(tmp_path):
    own = explicit("srt:OwnershipAxis", "la:AADMidcoIncTermLoanMember")
    ind = explicit("gaap:EquitySecuritiesByIndustryAxis", "la:AerospaceAndDefenseMember")
    jv = explicit("gaap:InvestmentCompanyNonconsolidatedSubsidiaryAxis", "la:SBLAPrivateCreditLLCMember")
    cp = explicit("srt:OwnershipAxis", "la:StifelBankTrustMember")
    body = (context("pos", own + ind, "2026-03-31", "2008748") + fact("pos", "1000")
            + context("jv", own + ind + jv, "2026-03-31", "2008748") + fact("jv", "500")
            + context("ind", ind, "2026-03-31", "2008748") + fact("ind", "1500")
            + context("cp", cp, "2026-03-31", "2008748") + fact("cp", "1"))
    result = la_scan(tmp_path, body)
    roles = {c["context_id"]: (c["role"], c["role_reason"]) for c in result["contexts"]}
    assert roles["pos"] == ("confirmed_position", "lordabbett_explicit_ownership_and_industry")
    assert roles["jv"] == ("confirmed_position", "lordabbett_explicit_ownership_and_industry")
    assert roles["ind"][0] != "confirmed_position"
    assert roles["cp"][0] != "confirmed_position"
    assert all(c["extractor_recognized"] for c in result["contexts"] if c["role"] == "confirmed_position")
    assert result["counts"]["confirmed_position"] == 2


def test_lordabbett_rule_does_not_rescue_other_filers_ownership_axis(tmp_path):
    own = explicit("srt:OwnershipAxis", "f:CrimsonMidstreamHoldingsLLCMember")
    ind = explicit("gaap:EquitySecuritiesByIndustryAxis", "gaap:AerospaceSectorMember")
    path = tmp_path / "instance.xml"
    path.write_text(LA_HEADER + context("own", own + ind, "2024-06-30", "1347652")
                    + fact("own", "100") + "</xbrli:xbrl>", encoding="utf-8")
    result = scan_instance(path, "1347652", "2024-06-30")
    assert result["counts"]["confirmed_position"] == 0
    assert not result["contexts"][0]["extractor_recognized"]
