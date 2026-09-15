"""Cash vocabulary consistency and source-grounded position identities."""
import json
from pathlib import Path

import pytest

from pipeline.agent_rule import apply_rules,validate_rule
from pipeline.unified_holdings import _enforce_schema
from tests.test_holdings_finalizer import holdings

ROOT=Path(__file__).resolve().parents[1]


def test_cash_category_requires_the_existing_cash_partition():
    row=dict(asset_category='CASH',index_classification='CASH',asset_class='CASH',exposure_type='LIQUID')
    assert not any(name in ('asset_category_enum','cash_classification_consistency') for name,_ in _enforce_schema(holdings([row])))
    row['asset_class']='PRIVATE_CREDIT'
    assert ('cash_classification_consistency',1) in _enforce_schema(holdings([row]))
    assert ('asset_category_enum',1) in _enforce_schema(holdings([dict(asset_category='cash_equivalent')]))


def test_repaired_cash_rule_adds_individual_positions_with_unchanged_fv():
    path=ROOT/'data/overrides/agent_investigate_rules/1715933/1715933_2025q2_add_cash_short_term_investments.json'
    rule=json.loads(path.read_text())
    assert validate_rule(rule)==[]
    result,audits=apply_rules(holdings([]).iloc[:0], [rule])
    assert len(result)==2 and result.fair_value.sum()==401562086
    assert set(result.asset_category)=={'CASH'}
    assert set(result.issuer_name)=={'First American Government Obligation Fund, Yield 4.26%, Class X (FGXXX)',
        'U.S. Treasury Bill, Yield 4.30%, Maturity Date 10/28/25'}
    assert audits[0]['rows_added']==2
    replay,_=apply_rules(result,[rule])
    assert len(replay)==2
    # An equal-valued corporate loan is not the recovered Treasury bill.
    unrelated=holdings([dict(report_date='2025-06-30',issuer_name='Acme senior loan',
        bdc_investment_identifier='Acme senior loan',fair_value=394466500)])
    with_loan,_=apply_rules(unrelated,[rule])
    assert len(with_loan)==3


@pytest.mark.needs_cache
def test_cash_identities_are_the_two_individual_cached_rows():
    from lxml import html
    from pipeline.programme.core import sha
    path=ROOT/'data/raw/filings/bdc_html/1715933/000095017025107431.html'
    if not path.exists(): pytest.skip('Cached source unavailable')
    assert sha(path)=='d7ce471e0a1e327a45173ad8eb19d934a1863685dadccc5ce5124694808c26c8'
    table=html.fromstring(path.read_bytes()).xpath('//table')[7]
    rows=[' '.join(r.text_content().split()) for r in table.xpath('./tr|./tbody/tr')]
    assert 'First American' in rows[28] and '7,095,586' in rows[28]
    assert 'U.S. Treasury Bill' in rows[31] and '394,466,500' in rows[31]
    assert rows[29].startswith('Total Cash') and rows[32].startswith('Total Short-term')
