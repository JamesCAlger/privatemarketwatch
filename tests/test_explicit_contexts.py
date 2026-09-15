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
    assert set(EXPLICIT_MEMBER_RULES)=={'0002008748','0001634452','0001860424'}
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


# ---------------------------------------------------------------------------
# Generic semantics of period-scoped ``excluded_axis_members``
# ---------------------------------------------------------------------------
def test_excluded_axis_members_scope_by_period_and_never_match_unknown_period(monkeypatch):
    rule=ExplicitMemberRule(name='synthetic',identity_axis='ownershipaxis',
                            member_namespace_pattern=r'https?://synthetic\.example/\d{8}$',
                            instrument_axes=('debtinstrumentaxis',),
                            excluded_axis_members=frozenset({
                                ('debtinstrumentaxis','stalefamilymember','2024-06-30'),
                                ('debtinstrumentaxis','alwaysoutmember',''),
                            }))
    monkeypatch.setitem(EXPLICIT_MEMBER_RULES,'0009999999',rule)
    dims=lambda member:[('explicit','http://fasb.org/srt/2024','OwnershipAxis','http://synthetic.example/20240630','AcmeTermLoanMember'),
                        ('explicit','http://fasb.org/us-gaap/2024','DebtInstrumentAxis','http://synthetic.example/20240630',member)]
    assert explicit_member_dimensions('9999999',dims('StaleFamilyMember'),period='2024-06-30') is None
    assert explicit_member_dimensions('9999999',dims('StaleFamilyMember'),period='2024-03-31') is not None
    assert explicit_member_dimensions('9999999',dims('StaleFamilyMember')) is not None      # unknown period
    assert explicit_member_dimensions('9999999',dims('AlwaysOutMember'),period='2024-03-31') is None
    assert explicit_member_dimensions('9999999',dims('AlwaysOutMember')) is None
    assert explicit_member_dimensions('9999999',dims('LiveFamilyMember'),period='2024-06-30') is not None


# ---------------------------------------------------------------------------
# AB Private Credit Investors Corp (CIK 1634452): positions on dei:LegalEntityAxis
# with DebtInstrument / CreditFacility / InvestmentType / ClassOfStock members
# ---------------------------------------------------------------------------
AB_NS='http://www.abpcic.com/20230331'


def ab_context(*,cik='1634452',legal='AmerCareRoyalLlcFourMember',legal_ns='n',
               debt='FirstLienSeniorSecuredDebtAt241.34Member',facility='TermLoanMember',facility_ns='n',
               itype='UsCorporateDebtMember',service='BusinessServicesMember',stock=None,stock_ns='n',
               namespace=AB_NS,period='2023-03-31',instant=True,extra=''):
    period_xml='<instant>'+period+'</instant>' if instant else '<startDate>2023-01-01</startDate><endDate>'+period+'</endDate>'
    members=''
    if legal is not None:
        members+='<d:explicitMember dimension="dei:LegalEntityAxis">'+legal_ns+':'+legal+'</d:explicitMember>'
    if service is not None:
        members+='<d:explicitMember dimension="n:InvestmentServiceTypeAxis">n:'+service+'</d:explicitMember>'
    if itype is not None:
        members+='<d:explicitMember dimension="g:InvestmentTypeAxis">n:'+itype+'</d:explicitMember>'
    if debt is not None:
        members+='<d:explicitMember dimension="g:DebtInstrumentAxis">n:'+debt+'</d:explicitMember>'
    if facility is not None:
        members+='<d:explicitMember dimension="g:CreditFacilityAxis">'+facility_ns+':'+facility+'</d:explicitMember>'
    if stock is not None:
        members+='<d:explicitMember dimension="g:StatementClassOfStockAxis">'+stock_ns+':'+stock+'</d:explicitMember>'
    return etree.fromstring(('''<context xmlns="http://www.xbrl.org/2003/instance"
        xmlns:d="http://xbrl.org/2006/xbrldi" xmlns:dei="http://xbrl.sec.gov/dei/2022"
        xmlns:g="http://fasb.org/us-gaap/2022" xmlns:us-gaap="http://fasb.org/us-gaap/2022" xmlns:srt="http://fasb.org/srt/2022"
        xmlns:corr="http://corenergy.example/20240630" xmlns:n="'''+namespace+'''">
        <entity><identifier scheme="http://www.sec.gov/CIK">'''+cik+'''</identifier><segment>
        '''+members+extra+'''</segment></entity><period>'''+period_xml+'''</period></context>''').encode())


def ab_position(node):
    parsed=explicit_member_position(node)
    if parsed is None: return None
    assert parsed['rule']=='abpcic_explicit_legal_entity_and_instrument'
    return parsed


def test_abpcic_debt_tranche_combines_entity_lien_family_facility_and_type():
    parsed=ab_position(ab_context())
    assert parsed['investment_identifier']=='Amer Care Royal Llc Four - First Lien Senior Secured Debt At 241.34 - Term Loan - Us Corporate Debt'
    assert parsed['industry']=='Business Services' and parsed['subsidiary']==''
    assert parsed['dimensions']['legalentityaxis']=='AmerCareRoyalLlcFourMember'
    assert parsed['dimensions']['creditfacilityaxis']=='TermLoanMember'


def test_abpcic_revolver_and_term_loan_of_one_borrower_stay_separate():
    term=ab_position(ab_context(legal='OmhhealthedgeHoldingsLlcOneMember'))
    revolver=ab_position(ab_context(legal='OmhhealthedgeHoldingsLlcOneMember',debt='FirstLienSeniorSecuredDebt241.34Member',
                                    facility='RevolvingCreditFacilityMember',facility_ns='g'))
    assert term['investment_identifier']!=revolver['investment_identifier']
    assert revolver['investment_identifier'].endswith('First Lien Senior Secured Debt 241.34 - Revolving Credit Facility - Us Corporate Debt')


def test_abpcic_preferred_and_warrant_of_same_series_are_distinct_equity_positions():
    preferred=ab_position(ab_context(legal='VectraAIIncMember',debt=None,facility=None,
                                     itype='U.s.preferredStockAtTwoPointZeroThreePercentageMember',
                                     service='SoftwareTechServicesMember',stock='SeriesFMember'))
    warrant=ab_position(ab_context(legal='VectraAIIncMember',debt=None,facility=None,
                                   itype='U.s.WarrantsAtZeroPointOneNinePercentageMember',
                                   service='SoftwareTechServicesMember',stock='SeriesFMember'))
    assert preferred['investment_identifier']=='Vectra AI Inc - U.s.preferred Stock At Two Point Zero Three Percentage - Series F'
    assert warrant['investment_identifier']=='Vectra AI Inc - U.s.Warrants At Zero Point One Nine Percentage - Series F'
    # us-gaap class members and fund interests without a service-type axis are inside the filer total
    fund=ab_position(ab_context(legal='AbEquityInvestorsLpMember',debt=None,facility=None,service=None,
                                itype='InvestmentCompaniesAtOnePointTwoThreePercentageMember',stock='CommonClassAMember',stock_ns='g'))
    assert fund['investment_identifier']=='Ab Equity Investors Lp - Investment Companies At One Point Two Three Percentage - Common Class A'
    assert fund['industry']==''


def test_abpcic_misdated_q2_comparative_family_is_excluded_only_at_2023_06_30():
    q2=dict(namespace='http://www.abpcic.com/20230630',debt='FirstLienSeniorSecuredDebtAt234.31Member',legal='KaseyaIncOneMember',
            facility='RevolvingCreditFacilityMember',facility_ns='g')
    assert ab_position(ab_context(period='2023-06-30',**q2)) is None
    live=ab_position(ab_context(period='2023-06-30',**dict(q2,debt='FirstLienSeniorSecuredDebt241.16Member')))
    assert live['investment_identifier']=='Kaseya Inc One - First Lien Senior Secured Debt 241.16 - Revolving Credit Facility - Us Corporate Debt'
    q1=ab_position(ab_context(period='2023-03-31',**dict(q2,namespace=AB_NS)))   # genuine Q1 rows carry the same label
    assert q1['investment_identifier'].startswith('Kaseya Inc One - First Lien Senior Secured Debt At 234.31')


@pytest.mark.parametrize('change',[
    {'legal':'AbPrivateCreditInvestorsCorpMember'},                 # the fund itself
    {'legal':'ParentCompanyMember','legal_ns':'srt'},               # reporting-entity use of the axis
    {'legal':'CrimsonMidstreamHoldingsLLCMember','legal_ns':'corr'},# member outside abpcic.com
    {'legal':None},                                                 # DebtInstrument family subtotal
    {'legal':None,'debt':None,'facility':None,'service':None},      # InvestmentType-only subtotal
    {'itype':None},                                                 # InvestmentTypeAxis is required
    {'extra':'<d:explicitMember dimension="g:CashAndCashEquivalentsAxis">us-gaap:MoneyMarketFundsMember</d:explicitMember>',
     'legal':'BlackrockTFundIMember','debt':None,'facility':None,'service':'MoneyMarketPortfolioMember'},  # cash equivalents
    {'extra':'<d:explicitMember dimension="srt:ConsolidatedEntitiesAxis">srt:AffiliatedEntityMember</d:explicitMember>',
     'legal':'BowlineTopcoLlcMember'},                              # affiliate rollup
    {'legal':None,'debt':None,'facility':None,'service':None,
     'extra':'<d:explicitMember dimension="n:InvesteeAxis">n:CerifiLLCMember</d:explicitMember>'
             '<d:explicitMember dimension="n:FacilityTypeAxis">g:RevolvingCreditFacilityMember</d:explicitMember>'},  # unfunded commitment table
    {'cik':'1588272'},                                              # NexPoint has its own rule path
    {'namespace':'http://www.abpcic.com/2023'},                     # namespace pattern is 8 digits
    {'period':'2022-12-31'},                                        # outside the pinned instants
    {'instant':False},
    {'extra':'<d:typedMember dimension="g:InvestmentIdentifierAxis"><name>Acme</name></d:typedMember>'},
])
def test_abpcic_adjacent_scopes_are_not_rescued(change):
    assert ab_position(ab_context(**change)) is None


def test_abpcic_parser_sets_identifier_industry_and_rejects_non_positions():
    from pipeline.bdc_filings import _parse_xbrl_contexts
    nodes={
        'term':ab_context(),
        'revolver':ab_context(debt='FirstLienSeniorSecuredDebt241.34Member',facility='RevolvingCreditFacilityMember',facility_ns='g'),
        'preferred':ab_context(legal='VectraAIIncMember',debt=None,facility=None,service='SoftwareTechServicesMember',
                               itype='U.s.preferredStockAtTwoPointZeroThreePercentageMember',stock='SeriesFMember'),
        'misdated':ab_context(period='2023-06-30',namespace='http://www.abpcic.com/20230630',debt='FirstLienSeniorSecuredDebtAt234.31Member'),
        'fund':ab_context(legal='AbPrivateCreditInvestorsCorpMember'),
        'subtotal':ab_context(legal=None),
        'mmf':ab_context(legal='BlackrockTFundIMember',debt=None,facility=None,service='MoneyMarketPortfolioMember',
                         extra='<d:explicitMember dimension="g:CashAndCashEquivalentsAxis">us-gaap:MoneyMarketFundsMember</d:explicitMember>'),
    }
    root=etree.Element('{http://www.xbrl.org/2003/instance}xbrl')
    for key,node in nodes.items():
        node.set('id',key); root.append(node)
    parsed=_parse_xbrl_contexts(etree.ElementTree(root))
    assert parsed['term']['is_investment']
    assert parsed['term']['investment_identifier']=='Amer Care Royal Llc Four - First Lien Senior Secured Debt At 241.34 - Term Loan - Us Corporate Debt'
    assert parsed['term']['industry']=='Business Services'
    assert parsed['term']['investment_type']=='UsCorporateDebtMember'
    assert parsed['revolver']['investment_identifier']!=parsed['term']['investment_identifier']
    assert parsed['preferred']['investment_identifier']=='Vectra AI Inc - U.s.preferred Stock At Two Point Zero Three Percentage - Series F'
    assert 'nonconsolidatedsubsidiar' not in parsed['term']['dimensions_raw']
    for key in ('misdated','fund','subtotal','mmf'):
        assert not parsed[key]['is_investment'], key
        assert parsed[key]['investment_identifier']=='', key


@pytest.mark.needs_cache
def test_abpcic_cached_2023_instances_reconcile_to_filer_totals():
    """Control on the real source: Q1-2023 and Q2-2023 explicit-member rows sum
    exactly to the undimensioned InvestmentOwnedAtFairValue; the mis-dated
    12/31/2022 family is absent at 6/30 and genuine at 3/31."""
    from pathlib import Path
    from pipeline.bdc_filings import _parse_single_filing
    base=Path(__file__).resolve().parents[1]/'data/raw/filings/bdc_xbrl/1634452'
    expected={'000119312523145163.xml':('2023-03-31',448,1179343662,41),
              '000119312523212335.xml':('2023-06-30',461,1227572852,0)}
    for name,(report_date,count,total,stale_rows) in expected.items():
        path=base/name
        if not path.is_file():
            pytest.skip('AB Private Credit source not cached')
        records=_parse_single_filing(str(path),{'cik':'1634452','report_date':report_date})
        rows=[r for r in records if r['period']==report_date]
        assert (len(records),len(rows))==(count,count)
        assert all(r['fair_value'] is not None and r['cost'] is not None for r in rows)
        assert sum(r['fair_value'] for r in rows)==total
        assert len({r['investment_identifier'] for r in rows})==count
        assert sum('at234.31member' in r['dimensions_raw'].lower() for r in rows)==stale_rows
        assert not any(w in r['investment_identifier'] for r in rows for w in ('Blackrock','State Street','Total'))
    q1=_parse_single_filing(str(base/'000119312523145163.xml'),{'cik':'1634452','report_date':'2023-03-31'})
    sample=next(r for r in q1 if r['investment_identifier']=='Amercareroyal Llc Two - First Lien Senior Secured Debt At 241.34 - Term Loan - Us Corporate Debt')
    assert sample['industry']=='Business Services' and sample['fair_value']==1978551


# ---------------------------------------------------------------------------
# Onex Direct Lending BDC Fund (CIK 1860424): positions on
# us-gaap:EquityMethodInvestmentNonconsolidatedInvesteeAxis + LongtermDebtTypeAxis
# ---------------------------------------------------------------------------
ONEX_NS='http://onexfalcondirectlending.com/20230331'


def onex_context(*,cik='1860424',investee='SailpointTechnologiesHoldingsIncMember',investee_ns='n',
                 tranche='InitialTermLoanMember',tranche_ns='n',industry='HighTechIndustriesMember',
                 itype='DebtInvestmentsMember',affiliation='NonControlledAndNonAffiliatedInvestmentsMember',
                 namespace=ONEX_NS,period='2023-03-31',instant=True,extra=''):
    period_xml='<instant>'+period+'</instant>' if instant else '<startDate>2023-01-01</startDate><endDate>'+period+'</endDate>'
    members=''
    if affiliation is not None:
        members+='<d:explicitMember dimension="g:DebtInstrumentAxis">n:'+affiliation+'</d:explicitMember>'
    if investee is not None:
        members+='<d:explicitMember dimension="g:EquityMethodInvestmentNonconsolidatedInvesteeAxis">'+investee_ns+':'+investee+'</d:explicitMember>'
    if industry is not None:
        members+='<d:explicitMember dimension="g:EquitySecuritiesByIndustryAxis">n:'+industry+'</d:explicitMember>'
    if itype is not None:
        members+='<d:explicitMember dimension="g:InvestmentTypeAxis">n:'+itype+'</d:explicitMember>'
    if tranche is not None:
        members+='<d:explicitMember dimension="g:LongtermDebtTypeAxis">'+tranche_ns+':'+tranche+'</d:explicitMember>'
    return etree.fromstring(('''<context xmlns="http://www.xbrl.org/2003/instance"
        xmlns:d="http://xbrl.org/2006/xbrldi" xmlns:dei="http://xbrl.sec.gov/dei/2022"
        xmlns:g="http://fasb.org/us-gaap/2022" xmlns:srt="http://fasb.org/srt/2022"
        xmlns:corr="http://corenergy.example/20240630" xmlns:n="'''+namespace+'''">
        <entity><identifier scheme="http://www.sec.gov/CIK">'''+cik+'''</identifier><segment>
        '''+members+extra+'''</segment></entity><period>'''+period_xml+'''</period></context>''').encode())


def onex_position(node):
    parsed=explicit_member_position(node)
    if parsed is None: return None
    assert parsed['rule']=='onex_explicit_investee_and_debt_type'
    return parsed


def test_onex_tranche_on_investee_axis_is_an_own_book_position():
    parsed=onex_position(onex_context())
    assert parsed['investment_identifier']=='Sailpoint Technologies Holdings Inc - Initial Term Loan'
    assert parsed['industry']=='High Tech Industries' and parsed['subsidiary']==''
    assert parsed['dimensions']['equitymethodinvestmentnonconsolidatedinvesteeaxis']=='SailpointTechnologiesHoldingsIncMember'
    assert 'debtinstrumentaxis' in parsed['dimensions']          # affiliation category permitted, not identity
    assert 'Non Controlled' not in parsed['investment_identifier']


def test_onex_tranches_of_one_borrower_stay_separate_including_equity_and_standard_members():
    term=onex_position(onex_context(investee='CrashChampionsIntermediateLlcMember',industry='AutomotiveMember'))
    revolver=onex_position(onex_context(investee='CrashChampionsIntermediateLlcMember',industry='AutomotiveMember',
                                        tranche='RevolvingCreditLoanMember'))
    equity=onex_position(onex_context(investee='MilestoneTechnologiesIncMember',tranche='CommonEquityMember',
                                      itype='EquityInvestmentMember'))
    standard=onex_position(onex_context(investee='AmplityParentIncMember',industry='HealthcareAndPharmaceuticalsMember',
                                        tranche='RevolvingCreditFacilityMember',tranche_ns='g'))
    assert term['investment_identifier']=='Crash Champions Intermediate Llc - Initial Term Loan'
    assert revolver['investment_identifier']=='Crash Champions Intermediate Llc - Revolving Credit Loan'
    assert equity['investment_identifier']=='Milestone Technologies Inc - Common Equity'
    assert standard['investment_identifier']=='Amplity Parent Inc - Revolving Credit Facility'


def test_onex_borrower_subtotal_without_tranche_axis_is_not_a_position():
    # Foundation Risk Partners: the 4-axis context equals its term loan + DDTL.
    assert onex_position(onex_context(investee='FoundationRiskPartnersCorpMember',industry='InsuranceMember',tranche=None)) is None


@pytest.mark.parametrize('change',[
    {'investee':'OnexDirectLendingBdcFundMember'},                  # the fund itself
    {'investee':'CrimsonMidstreamHoldingsLLCMember','investee_ns':'corr'},  # member outside the filer namespace
    {'cik':'1347652','investee':'CrimsonMidstreamHoldingsLLCMember','investee_ns':'corr'},  # genuine equity-method investee elsewhere
    {'industry':None,'itype':None,'affiliation':None},              # investee + tranche spread-only contexts
    {'itype':None},                                                 # InvestmentTypeAxis is required
    {'investee':None,'tranche':None},                               # industry x type subtotal
    {'investee':None,'tranche':None,'itype':None,'affiliation':None},  # industry subtotal
    {'extra':'<d:explicitMember dimension="g:VariableRateAxis">g:SecuredOvernightFinancingRateSofrMember</d:explicitMember>'},  # rate-only contexts
    {'extra':'<d:explicitMember dimension="g:FairValueByFairValueHierarchyLevelAxis">g:FairValueInputsLevel3Member</d:explicitMember>'},
    {'namespace':'http://onexfalcondirectlending.com/2023'},
    {'period':'2022-12-31'},                                        # comparatives outside the pinned instant
    {'instant':False},
    {'extra':'<d:typedMember dimension="g:InvestmentIdentifierAxis"><name>Acme</name></d:typedMember>'},
])
def test_onex_adjacent_scopes_are_not_rescued(change):
    assert onex_position(onex_context(**change)) is None


def test_onex_parser_keeps_investee_axis_without_triggering_subsidiary_patterns():
    from pipeline.bdc_filings import _parse_xbrl_contexts
    nodes={
        'term':onex_context(),
        'revolver':onex_context(tranche='RevolvingLoanMember'),
        'subtotal':onex_context(investee='FoundationRiskPartnersCorpMember',industry='InsuranceMember',tranche=None),
        'spread_only':onex_context(industry=None,itype=None,affiliation=None),
        'fund':onex_context(investee='OnexDirectLendingBdcFundMember'),
        'other_filer':onex_context(cik='1347652',investee='CrimsonMidstreamHoldingsLLCMember',investee_ns='corr'),
    }
    root=etree.Element('{http://www.xbrl.org/2003/instance}xbrl')
    for key,node in nodes.items():
        node.set('id',key); root.append(node)
    parsed=_parse_xbrl_contexts(etree.ElementTree(root))
    assert parsed['term']['is_investment']
    assert parsed['term']['investment_identifier']=='Sailpoint Technologies Holdings Inc - Initial Term Loan'
    assert parsed['term']['industry']=='High Tech Industries'
    assert parsed['term']['investment_type']=='DebtInvestmentsMember'
    assert parsed['revolver']['investment_identifier']=='Sailpoint Technologies Holdings Inc - Revolving Loan'
    raw=parsed['term']['dimensions_raw'].lower()
    assert 'equitymethodinvestmentnonconsolidatedinvesteeaxis=sailpointtechnologiesholdingsincmember' in raw
    # staging_bdc derives is_subsidiary from these two patterns; the Onex axis matches neither (own-book rows)
    assert 'nonconsolidatedsubsidiar' not in raw
    assert 'equitymethodinvestmentequitymethodinvesteenameaxis' not in raw
    for key in ('subtotal','spread_only','fund','other_filer'):
        assert not parsed[key]['is_investment'], key
        assert parsed[key]['investment_identifier']=='', key


@pytest.mark.needs_cache
def test_onex_cached_q1_2023_instance_reconciles_within_source_omission():
    """Control on the real source: 57 tranche rows at 2023-03-31 (53 with FV,
    3 unfunded rows with cost only, 1 duplicate-dimension context carrying a
    stray rate fact) sum to 521,760,590 against the filer's 526,177,088; the
    -4,416,498 residual is untagged Automotive/Healthcare FV, not a dropped
    context. The Foundation Risk Partners borrower subtotal never appears."""
    from pathlib import Path
    from pipeline.bdc_filings import _parse_single_filing
    path=Path(__file__).resolve().parents[1]/'data/raw/filings/bdc_xbrl/1860424/000095017023021345.xml'
    if not path.is_file():
        pytest.skip('Onex source not cached')
    records=_parse_single_filing(str(path),{'cik':'1860424','report_date':'2023-03-31'})
    rows=[r for r in records if r['period']=='2023-03-31']
    assert (len(records),len(rows))==(57,57)
    assert sum(r['fair_value'] for r in rows if r['fair_value'] is not None)==521760590
    assert abs(526177088-521760590)/526177088<0.01
    assert all(' - ' in r['investment_identifier'] for r in rows)          # every row is borrower + tranche
    assert 'Foundation Risk Partners Corp' not in {r['investment_identifier'] for r in rows}
    frp=sorted(r['investment_identifier'] for r in rows if r['investment_identifier'].startswith('Foundation Risk Partners Corp'))
    assert frp==['Foundation Risk Partners Corp - Delayed Draw Term Loan','Foundation Risk Partners Corp - Term Loan']
    sample=next(r for r in rows if r['investment_identifier']=='Crash Champions Intermediate Llc - Initial Term Loan' and r['fair_value'])
    assert sample['industry']=='Automotive' and sample['fair_value']==6229735
    assert not any('nonconsolidatedsubsidiar' in r['dimensions_raw'].lower() for r in rows)
