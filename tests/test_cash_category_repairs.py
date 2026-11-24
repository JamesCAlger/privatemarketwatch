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
