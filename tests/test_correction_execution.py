"""Actual write intersections, explicit dependencies and shared semantic order."""
import pandas as pd
import pytest

from pipeline.agent_rule import apply_rules
from pipeline.correction_execution import CorrectionConflict,KEY,ordered_rules
from tests.test_agent_rule import _rule


def frame():
    return pd.DataFrame([dict(cik='0001377936',source='bdc',report_date=q,issuer_name='Acme',fair_value=v,
        cost=20,bdc_dimensions_raw='investmentidentifieraxis=Acme') for q,v in [('2025-12-31',10),('2026-03-31',30)]])


def scale(name,quarter='all',**kw):
    return _rule(rule_id=name,rule_type='value_rescale',action='rescale',field='fair_value',factor=2,
        predicate_sql='TRUE',scope={'quarters':[quarter]},**kw)


def test_overlapping_writers_stop_but_disjoint_quarters_do_not():
    original=frame()
    with pytest.raises(CorrectionConflict,match='writer conflict'):
        apply_rules(original,[scale('first'),scale('second')])
    assert original.fair_value.tolist()==[10,30]
    result,_=apply_rules(original,[scale('first','2025-12-31'),scale('second','2026-03-31')])
    assert result.fair_value.tolist()==[20,60] and KEY not in result


def test_dependency_governs_order_and_distinct_fields_are_independent():
    first=scale('first');second=scale('second',depends_on=['first'])
    result,audits=apply_rules(frame(),[second,first])
    assert result.fair_value.tolist()==[40,120]
    assert [a['rule_id'] for a in audits]==['first','second']
    second={**scale('cost'),'field':'cost'}
    result,_=apply_rules(frame(),[first,second])
    assert result.fair_value.tolist()==[20,60] and result.cost.tolist()==[40,40]


def test_unknown_dependency_cycle_and_reverse_stage_fail():
    with pytest.raises(CorrectionConflict,match='admitted execution plan'):
        ordered_rules([scale('first',depends_on=['missing'])])
    with pytest.raises(CorrectionConflict,match='Cyclic'):
        ordered_rules([scale('first',depends_on=['second']),scale('second',depends_on=['first'])])
    exclusion=_rule(rule_id='exclude',depends_on=['scale'])
    with pytest.raises(CorrectionConflict,match='reverses semantic'):
        ordered_rules([exclusion,scale('scale')])


def test_exclusions_run_before_value_writers_in_verifier():
    exclusion=_rule(rule_id='exclude',predicate_sql='fair_value=10')
    result,audits=apply_rules(frame(),[scale('scale'),exclusion])
    assert result.fair_value.tolist()==[60]
    assert [a['rule_id'] for a in audits]==['exclude','scale']


def test_mixed_b2_and_rule_writers_share_one_guard():
    from pipeline.agent_promoted import apply_promoted_plan
    b2=dict(cik='1377936',fix_class='unit_rescale',scope={'quarters':['2025-12-31']},
        template=dict(field='fair_value',factor=2,row_selector={'issuer_name':'Acme'}))
    with pytest.raises(CorrectionConflict,match='writer conflict'):
        apply_promoted_plan(frame(),[b2],{'0001377936':[scale('rule','2025-12-31')]})
