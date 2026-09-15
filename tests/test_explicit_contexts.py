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
