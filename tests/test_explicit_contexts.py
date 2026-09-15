from lxml import etree
import pytest

from pipeline.explicit_contexts import nexpoint_position


def context(*,cik='1588272',period='2023-03-31',namespace='http://www.npci.com/20230331',
            legal='AcmeCorpMember',extra='',instant=True):
    period_xml='<instant>'+period+'</instant>' if instant else '<startDate>2023-01-01</startDate><endDate>'+period+'</endDate>'
    return etree.fromstring(('''<context xmlns="http://www.xbrl.org/2003/instance"
        xmlns:d="http://xbrl.org/2006/xbrldi" xmlns:dei="http://xbrl.sec.gov/dei/2023"
        xmlns:g="http://fasb.org/us-gaap/2023" xmlns:n="'''+namespace+'''">
        <entity><identifier>'''+cik+'''</identifier><segment>
        <d:explicitMember dimension="dei:LegalEntityAxis">n:'''+legal+'''</d:explicitMember>
        <d:explicitMember dimension="g:InvestmentTypeAxis">g:DebtMember</d:explicitMember>
        <d:explicitMember dimension="g:InvestmentSecondaryCategorizationAxis">n:FirstLienMember</d:explicitMember>
        '''+extra+'''</segment></entity><period>'''+period_xml+'''</period></context>''').encode())


def test_explicit_investee_requires_joint_instrument_scope():
    parsed=nexpoint_position(context(extra='<d:explicitMember dimension="g:DebtInstrumentAxis">n:TrancheBMember</d:explicitMember>'))
    assert parsed['legalentityaxis']=='AcmeCorpMember'
    assert parsed['debtinstrumentaxis']=='TrancheBMember'


@pytest.mark.parametrize('change',[
    {'cik':'123'}, {'period':'2023-06-30'}, {'namespace':'http://www.npci.com/20221231'},
    {'legal':'TotalInvestmentsMember'}, {'legal':'NexPointCapitalIncMember'}, {'instant':False},
    {'extra':'<d:explicitMember dimension="g:InvestmentIndustryAxis">g:SoftwareMember</d:explicitMember>'},
    {'extra':'<d:explicitMember dimension="g:InvestmentTypeAxis">g:EquityMember</d:explicitMember>'},
    {'extra':'<d:typedMember dimension="g:InvestmentIdentifierAxis"><name>Acme</name></d:typedMember>'},
])
def test_adjacent_unproved_scopes_are_not_rescued(change):
    assert nexpoint_position(context(**change)) is None


def test_legal_entity_alone_is_insufficient():
    node=context()
    for member in node.findall('.//{http://xbrl.org/2006/xbrldi}explicitMember')[1:]:
        member.getparent().remove(member)
    assert nexpoint_position(node) is None


def test_parser_preserves_tranche_discriminators_and_does_not_admit_aggregate():
    from pipeline.bdc_filings import _parse_xbrl_contexts
    first=context(extra='<d:explicitMember dimension="g:DebtInstrumentAxis">n:TrancheBMember</d:explicitMember>')
    first.set('id','position')
    total=context(legal='TotalInvestmentsMember');total.set('id','total')
    root=etree.Element('{http://www.xbrl.org/2003/instance}xbrl')
    root.extend([first,total])
    parsed=_parse_xbrl_contexts(etree.ElementTree(root))
    assert parsed['position']['is_investment']
    assert 'Tranche B' in parsed['position']['investment_identifier']
    assert not parsed['total']['is_investment']


# ---------------------------------------------------------------------------
# Per-CIK explicit-member rule table; first entry Lord Abbett Private Credit
# Fund (CIK 2008748): positions on srt:OwnershipAxis
# ---------------------------------------------------------------------------
from pipeline.explicit_contexts import (
    EXPLICIT_MEMBER_RULES, ExplicitMemberRule, explicit_member_dimensions,
    explicit_member_position, rule_for)


def lordabbett_position(node):
    """Rule-table dimensions for a Lord Abbett context (None when not a position)."""
    parsed=explicit_member_position(node)
    if parsed is None: return None
    assert parsed['rule']=='lordabbett_explicit_ownership_and_industry'
    return parsed['dimensions']


def test_rule_table_is_keyed_by_ten_digit_cik_and_lookup_tolerates_padding():
    assert set(EXPLICIT_MEMBER_RULES)=={'0002008748'}
    assert all(len(key)==10 and isinstance(rule,ExplicitMemberRule)
               for key,rule in EXPLICIT_MEMBER_RULES.items())
    assert rule_for('2008748') is rule_for('0002008748')
    assert rule_for('1588272') is None and rule_for('') is None
    assert explicit_member_dimensions('1347652',[('explicit','http://fasb.org/srt/2026','OwnershipAxis',
        'http://corenergy.example/20240630','CrimsonMidstreamHoldingsLLCMember')]) is None

LA_NS='http://www.lordabbett.com/20260331'


def la_context(*,cik='2008748',own='AADMidcoIncTermLoanMember',industry='AerospaceAndDefenseMember',
               industry_ns='n',subsidiary=None,namespace=LA_NS,own_ns='n',extra='',instant=True,
               period='2026-03-31'):
    period_xml='<instant>'+period+'</instant>' if instant else '<startDate>2026-01-01</startDate><endDate>'+period+'</endDate>'
    members=''
    if own is not None:
        members+='<d:explicitMember dimension="srt:OwnershipAxis">'+own_ns+':'+own+'</d:explicitMember>'
    if industry is not None:
        members+='<d:explicitMember dimension="g:EquitySecuritiesByIndustryAxis">'+industry_ns+':'+industry+'</d:explicitMember>'
    if subsidiary is not None:
        members+='<d:explicitMember dimension="g:InvestmentCompanyNonconsolidatedSubsidiaryAxis">n:'+subsidiary+'</d:explicitMember>'
    return etree.fromstring(('''<context xmlns="http://www.xbrl.org/2003/instance"
        xmlns:d="http://xbrl.org/2006/xbrldi" xmlns:dei="http://xbrl.sec.gov/dei/2026"
        xmlns:g="http://fasb.org/us-gaap/2026" xmlns:srt="http://fasb.org/srt/2026"
        xmlns:corr="http://corenergy.example/20240630" xmlns:n="'''+namespace+'''">
        <entity><identifier scheme="http://www.sec.gov/CIK">'''+cik+'''</identifier><segment>
        '''+members+extra+'''</segment></entity><period>'''+period_xml+'''</period></context>''').encode())


def test_lordabbett_term_loan_on_ownership_axis_is_a_position():
    parsed=explicit_member_position(la_context())
    assert parsed=={'rule':'lordabbett_explicit_ownership_and_industry',
                    'investment_identifier':'AAD Midco Inc Term Loan',
                    'industry':'Aerospace And Defense','subsidiary':'',
                    'dimensions':{'ownershipaxis':'AADMidcoIncTermLoanMember',
                                  'equitysecuritiesbyindustryaxis':'AerospaceAndDefenseMember'}}


def test_lordabbett_standard_industry_member_and_older_namespace_are_admitted():
    parsed=lordabbett_position(la_context(industry='AerospaceSectorMember',industry_ns='g',
                                          namespace='http://www.lordabbett.com/20240930'))
    assert parsed['equitysecuritiesbyindustryaxis']=='AerospaceSectorMember'


def test_lordabbett_jv_lookthrough_is_retained_with_subsidiary_member():
    parsed=explicit_member_position(la_context(own='AccelInternationalHoldingsIncTermLoanMember',
                                               subsidiary='SBLAPrivateCreditLLCMember'))
    assert parsed['investment_identifier']=='Accel International Holdings Inc Term Loan'
    assert parsed['subsidiary']=='SBLAPrivateCreditLLCMember'
    assert parsed['dimensions']['investmentcompanynonconsolidatedsubsidiaryaxis']=='SBLAPrivateCreditLLCMember'


@pytest.mark.parametrize('change',[
    {'own':'LordAbbettAndOtherInvestmentCompaniesMember'},
    {'own':'LordAbbettPrivateCreditFundMember'},
    {'own':'StifelBankTrustMember'},
    {'own':None},                                   # industry-only subtotal
    {'industry':None},                              # ownership-only (unfunded commitment rows)
    {'cik':'1347652','own':'CrimsonMidstreamHoldingsLLCMember','own_ns':'corr'},  # other filer
    {'own_ns':'corr'},                              # right CIK, member outside lordabbett.com
    {'namespace':'http://www.lordabbett.com/2026'}, # namespace pattern is 8 digits
    {'instant':False},
    {'extra':'<d:explicitMember dimension="g:InvestmentTypeAxis">g:DebtMember</d:explicitMember>'},
    {'extra':'<d:typedMember dimension="g:InvestmentIdentifierAxis"><name>Acme</name></d:typedMember>'},
])
def test_lordabbett_adjacent_scopes_are_not_rescued(change):
    assert lordabbett_position(la_context(**change)) is None


def test_lordabbett_parser_sets_identifier_industry_and_keeps_subsidiary_axis():
    from pipeline.bdc_filings import _parse_xbrl_contexts
    nodes={
        'position':la_context(),
        'ddtl':la_context(own='AADMidcoIncDelayedDraw2024Member'),
        'jv':la_context(own='AccelInternationalHoldingsIncTermLoanMember',subsidiary='SBLAPrivateCreditLLCMember'),
        'counterparty':la_context(own='StifelBankTrustMember',industry=None),
        'industry_only':la_context(own=None),
        'other_filer':la_context(cik='1347652',own='CrimsonMidstreamHoldingsLLCMember',own_ns='corr'),
    }
    root=etree.Element('{http://www.xbrl.org/2003/instance}xbrl')
    for key,node in nodes.items():
        node.set('id',key); root.append(node)
    parsed=_parse_xbrl_contexts(etree.ElementTree(root))
    assert parsed['position']['is_investment']
    assert parsed['position']['investment_identifier']=='AAD Midco Inc Term Loan'
    assert parsed['position']['industry']=='Aerospace And Defense'
    assert parsed['ddtl']['investment_identifier']=='AAD Midco Inc Delayed Draw 2024'
    assert parsed['jv']['is_investment']
    assert parsed['jv']['investment_identifier']=='Accel International Holdings Inc Term Loan'
    assert 'investmentcompanynonconsolidatedsubsidiaryaxis=SBLAPrivateCreditLLCMember' in parsed['jv']['dimensions_raw']
    assert 'nonconsolidatedsubsidiar' not in parsed['position']['dimensions_raw']
    for key in ('counterparty','industry_only','other_filer'):
        assert not parsed[key]['is_investment'], key
        assert parsed[key]['investment_identifier']=='', key


@pytest.mark.needs_cache
def test_lordabbett_cached_q1_2026_instance_reconciles_to_filer_total():
    """Control on the real source: own-book OwnershipAxis rows sum to the filer's
    'Total Investments at Fair Value' at 2025-12-31; JV look-through rows are
    retained and carry the subsidiary axis; counterparties never appear."""
    from pathlib import Path
    from pipeline.bdc_filings import _parse_single_filing
    path=Path(__file__).resolve().parents[1]/'data/raw/filings/bdc_xbrl/2008748/000093041326001612.xml'
    if not path.is_file():
        pytest.skip('Lord Abbett source not cached')
    records=_parse_single_filing(str(path),{'cik':'2008748','report_date':'2026-03-31'})
    own=[r for r in records if 'ownershipaxis=' in r['dimensions_raw'].lower()]
    jv=[r for r in own if 'nonconsolidatedsubsidiar' in r['dimensions_raw'].lower()]
    assert (len(own),len(jv))==(332,70)
    assert all(r['fair_value'] is not None for r in own)
    assert not any('Stifel' in r['investment_identifier'] or 'Lord Abbett' in r['investment_identifier'] for r in records)
    own_book_q4=sum(r['fair_value'] for r in own if r not in jv and r['period']=='2025-12-31')
    total_q4=next(r['fair_value'] for r in records if r['period']=='2025-12-31'
                  and r['investment_identifier']=='Total Investments at Fair Value')
    assert own_book_q4==total_q4==1309928000
    sample=next(r for r in own if r['investment_identifier']=='AAD Midco Inc Term Loan' and r['period']=='2026-03-31')
    assert sample['industry']=='Aerospace And Defense' and sample['fair_value']==37372000
