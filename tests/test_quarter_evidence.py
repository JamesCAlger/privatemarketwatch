"""The expanded quarter gate cannot pass by omitting difficult evidence."""
import json
from copy import deepcopy

import duckdb
import pandas as pd
import pytest

from pipeline import quarter_acceptance as qa
from pipeline.quarter_evidence import Evidence,collect,observation
from pipeline.programme.core import ContractError,sha
from tests.test_holdings_finalizer import holdings

Q="2026-03-31"
CIK="0000000123"


def evidence(tmp_path,files=None,**metadata):
    hp=tmp_path/"private_markets_holdings.csv"
    holdings([{"fair_value":"100","src_context_id":"c1"},
              {"row_id":"ROW-2","position_id":"POS-2","fair_value":"-10","src_context_id":"c2"}]).to_csv(hp,index=False)
    payload=dict(holdings_sha256=sha(hp),files={},**metadata)
    for name,content in (files or {}).items():
        path=tmp_path/(name+".json" if isinstance(content,dict) else name+".csv")
        if isinstance(content,dict):
            path.write_text(json.dumps(content))
        else:
            pd.DataFrame(content).to_csv(path,index=False)
        payload["files"][name]=dict(path=path.name,sha256=sha(path),holdings_sha256=sha(hp))
    manifest=tmp_path/"evidence.json"
    manifest.write_text(json.dumps(payload))
    return hp,manifest


def legacy():
    return dict(verdict="PASS",checks=[dict(id="fund_coverage",actual=70,**{"pass":True}),
        dict(id="reconcile_rate",actual=95,**{"pass":True})],thresholds_version=3,calibration="provisional")


def test_all_required_rows_survive_missing_collectors():
    prior=legacy()
    result=qa.extend_acceptance(deepcopy(prior),{})
    assert result["v3_history"]==prior
    checks={c["id"]:c for c in result["checks"]}
    assert len(checks)==26
    assert "fund_coverage" not in checks
    assert checks["other_field_accuracy"]["status"]=="UNASSESSABLE"
    assert checks["public_partition_delta"]["status"]=="UNASSESSABLE"
    assert result["readiness"]=="blocked"


@pytest.mark.parametrize("value",[float("nan"),float("inf"),float("-inf"),True])
def test_nonfinite_and_boolean_values_cannot_pass(value):
    result=qa.extend_acceptance(legacy(),{"companion_parity":observation(value)})
    assert next(c for c in result["checks"] if c["id"]=="companion_parity")["status"]=="UNASSESSABLE"


def test_pending_floor_cannot_be_satisfied_by_perfect_subset():
    result=qa.extend_acceptance(legacy(),{"field_assessed_coverage":observation(1),
        "amount_field_accuracy":observation(None,assessable=False)})
    checks={c["id"]:c for c in result["checks"]}
    assert checks["field_assessed_coverage"]["status"]=="UNASSESSABLE"
    assert checks["amount_field_accuracy"]["status"]=="UNASSESSABLE"


def test_exact_zero_anchor_mismatch_is_failure_with_undefined_ratio():
    result=qa.extend_acceptance(legacy(),{"fund_primary_error_ratio":dict(observation(None),exact_failure=True)})
    assert next(c for c in result["checks"] if c["id"]=="fund_primary_error_ratio")["status"]=="FAIL"


def test_evidence_mutation_and_wrong_candidate_rejected(tmp_path):
    hp,manifest=evidence(tmp_path,{"gics_hierarchy":{"Software":{"sector":"Information Technology"}}})
    checked=Evidence(manifest,hp)
    checked.paths["gics_hierarchy"].write_text("{}")
    with pytest.raises(ContractError,match="changed"):
        checked.verify()
    with pytest.raises(ContractError,match="changed"):
        Evidence(manifest,hp)
    hp.write_text("changed holdings")
    with pytest.raises(ContractError,match="different holdings"):
        Evidence(manifest,hp)


def test_provisional_denominator_keeps_incomplete_sources(tmp_path):
    obligations=[dict(cik=CIK,report_date=Q,eligibility_status="eligible_source_investments"),
        dict(cik="0000000456",report_date=Q,eligibility_status="eligible_source_investments")]
    contexts=[dict(cik=CIK,quarter=Q,P=2,U=1,source_complete="True",evidence_sha256="e1",P_with_result=2,unrecognized_context_share="0.333"),
        dict(cik="0000000456",quarter=Q,P=0,U=0,source_complete="False",evidence_sha256="e2",P_with_result=0,unrecognized_context_share="")]
    hp,manifest=evidence(tmp_path,dict(obligations=obligations,contexts=contexts))
    result=collect(hp,manifest,Q,{CIK,"0000000456"})
    assert result["fund_coverage_share"]["actual"]==.5
    assert not result["fund_coverage_share"]["assessable"]
    assert result["reconciliation_coverage"]["actual"]==.5
    assert result["obligation_status_coverage"]["actual"]==1
    assert not result["unrecognized_context_share"]["assessable"]
    assert result["position_id_fill"]["actual"]==1
    assert not result["companion_parity"]["assessable"]


def test_excluded_positive_facts_fail_even_with_other_unresolved_cases(tmp_path):
    obligations=[dict(cik=CIK,report_date=Q,eligibility_status="eligible_source_investments"),
        dict(cik="456",report_date=Q,eligibility_status="pre_investment")]
    exclusions=[dict(cik="456",quarter=Q,P=1,positive_total_observations=0,verdict="exclusion_unassessable")]
    hp,manifest=evidence(tmp_path,dict(obligations=obligations,exclusions=exclusions))
    result=collect(hp,manifest,Q,{CIK})["excluded_with_positive_facts"]
    assert result["actual"]==1 and result["assessable"]


def test_field_weight_currencies_separate_and_accuracy_withheld(tmp_path):
    rows=[dict(quarter=Q,field="fair_value",source_fv_currency=currency,source_fv=100,
        category=category,reference_origin="selected_source_roster")
        for currency,category in (("USD","correct"),("EUR","incorrect"))]
    hp,manifest=evidence(tmp_path,dict(fields=rows))
    result=collect(hp,manifest,Q,{CIK})["amount_field_accuracy"]
    assert result["actual"] is None
    assert set(result["details"])=={"fair_value|USD","fair_value|EUR"}
    assert all(r["accuracy_row"] is None for r in result["details"].values())


@pytest.mark.parametrize('category,score', [('correct',1),('incorrect',0),('missing_output',0)])
def test_categorical_gate_measures_all_fields_with_both_weights(tmp_path, category, score):
    from pipeline.categorical_field_assessment import FIELDS
    rows = [dict(quarter=Q,field=field,source_fv_currency='USD',source_fv=100,
        category=category,reference_origin='selected_source_roster') for field in FIELDS]
    hp, manifest = evidence(tmp_path,dict(other_fields=rows),
        field_assessability_floors={f:1 for f in FIELDS},field_floor_adoption='fixture-adoption',
        source_roster_certified=True)
    result = collect(hp,manifest,Q,{CIK})['other_field_accuracy']
    assert result['assessable'] and result['actual']==score
    assert len(result['details'])==len(FIELDS)


def test_categorical_unsupported_meaning_cannot_pass_on_easy_subset(tmp_path):
    from pipeline.categorical_field_assessment import FIELDS
    rows = [dict(quarter=Q,field=field,source_fv_currency='USD',source_fv=100,
        category='correct',reference_origin='selected_source_roster') for field in FIELDS]
    rows.append(dict(rows[0],category='disclosed_unassessable'))
    hp, manifest = evidence(tmp_path,dict(other_fields=rows),
        field_assessability_floors={f:.9 for f in FIELDS},field_floor_adoption='fixture-adoption',
        source_roster_certified=True)
    result = collect(hp,manifest,Q,{CIK})['other_field_accuracy']
    assert not result['assessable'] and result['actual'] is None
    assert result['details'][FIELDS[0]+'|USD']['assessed_row_share']==.5


def test_primary_errors_cannot_net_and_schedule_is_not_independent(tmp_path):
    obligations=[dict(cik=c,report_date=Q,eligibility_status="eligible_source_investments") for c in (CIK,"0000000456","0000000789")]
    anchors=[dict(cik=c,quarter=Q,anchor_value=100,published_value=value,currency="USD",source_evidence="cached_source",anchor_kind=kind,scope_comparable=True)
        for c,value,kind in ((CIK,110,"fund_financials"),("0000000456",90,"verified_override"),("0000000789",100,"schedule_total"))]
    hp,manifest=evidence(tmp_path,dict(obligations=obligations,primary_anchors=anchors))
    result=collect(hp,manifest,Q,{CIK})
    assert result["primary_absolute_error_ratio"]["actual"]==.1
    assert result["primary_fund_coverage"]["actual"]==2/3


def test_primary_comparison_cannot_exclude_rows_to_make_public_total_pass(tmp_path):
    obligations=[dict(cik=CIK,report_date=Q,eligibility_status='eligible_source_investments')]
    anchors=[dict(cik=CIK,quarter=Q,anchor_value=90,published_value=90,currency='USD',
        source_evidence='cached_source',anchor_kind='fund_financials',scope_comparable=True)]
    summaries=[dict(cik=CIK,anchor_date=Q,excluded_rows=1,unknown_rows=0)]
    hp,manifest=evidence(tmp_path,dict(obligations=obligations,primary_anchors=anchors,
                                    accounting_anchor_summaries=summaries))
    result=collect(hp,manifest,Q,{CIK})['primary_fund_coverage']
    assert result['actual']==0
    assert 'Public population differs' in result['details']['unavailable'][0]['reason']


def test_public_membership_and_exact_bucket_values(tmp_path):
    from pipeline.public_partitions import public_snapshot,write_public_contributors
    hp,manifest=evidence(tmp_path)
    payload=json.loads(manifest.read_text())
    with duckdb.connect() as con:
        snap=public_snapshot(con,hp,cohort={CIK},hierarchy={})
        portfolio=dict(asOf=Q,fairValueExact=snap["fairValueExact"],instrumentBreakdown=snap["partitions"]["instrument"])
        sector=[dict(r,sector=r["label"]) for r in snap["partitions"]["sector"]]
        cp=tmp_path/"public_contributors.json"
        write_public_contributors(con,cp,Q)
    for name,value in (("public_portfolio",portfolio),("public_sectors",sector)):
        path=tmp_path/(name+".json");path.write_text(json.dumps(value))
    for name in ("public_portfolio","public_sectors","public_contributors"):
        path=tmp_path/(name+".json")
        payload["files"][name]=dict(path=path.name,sha256=sha(path),holdings_sha256=sha(hp))
    manifest.write_text(json.dumps(payload))
    result=collect(hp,manifest,Q,{CIK})["public_partition_delta"]
    assert result["assessable"] and result["actual"]==0
    # A duplicated contributor preserves some plausible totals but must fail.
    broken=json.loads(cp.read_text());broken["rows"][1]=broken["rows"][0]
    cp.write_text(json.dumps(broken));payload["files"]["public_contributors"]["sha256"]=sha(cp)
    manifest.write_text(json.dumps(payload))
    assert collect(hp,manifest,Q,{CIK})["public_partition_delta"]["actual"]==1


@pytest.mark.parametrize('typed',[False,True])
def test_public_exact_large_amounts_agree_for_text_and_typed_holdings(tmp_path,typed):
    from pipeline.public_partitions import public_snapshot,write_public_contributors
    from pipeline.quarter_evidence import collect_public
    hp,manifest=evidence(tmp_path)
    frame=pd.read_csv(hp,dtype=str)
    frame['fair_value']=['2031871000.0','-0.01']
    frame.to_csv(hp,index=False)
    payload=dict(holdings_sha256=sha(hp),files={})
    with duckdb.connect() as con:
        snap=public_snapshot(con,hp,cohort={CIK},hierarchy={})
        portfolio=dict(asOf=Q,fairValueExact=snap['fairValueExact'],instrumentBreakdown=snap['partitions']['instrument'])
        sector=[dict(r,sector=r['label']) for r in snap['partitions']['sector']]
        cp=tmp_path/'public_contributors.json'
        write_public_contributors(con,cp,Q)
        for name,value in (('public_portfolio',portfolio),('public_sectors',sector)):
            (tmp_path/(name+'.json')).write_text(json.dumps(value))
        for name in ('public_portfolio','public_sectors','public_contributors'):
            path=tmp_path/(name+'.json')
            payload['files'][name]=dict(path=path.name,sha256=sha(path),holdings_sha256=sha(hp))
        manifest.write_text(json.dumps(payload))
        cast='CAST(fair_value AS DOUBLE)' if typed else 'fair_value'
        con.execute('CREATE TABLE h AS SELECT row_id,'+cast+' AS fair_value FROM read_csv(?,all_varchar=true)',[str(hp)])
        result={}
        collect_public(con,Evidence(manifest,hp),Q,result)
        assert result['public_partition_delta']['actual']==0
        assert result['public_partition_delta']['details']['headline_delta']=='0E-12'
        con.execute('DROP TABLE public_members')
        # Equal numbers in all three exports cannot certify currency compatibility.
        con.execute("ALTER TABLE h ADD COLUMN fair_value_currency VARCHAR DEFAULT 'GBP'")
        collect_public(con,Evidence(manifest,hp),Q,result)
        assert result['public_partition_delta']['actual']==1
        assert result['public_partition_delta']['details']['headline_delta']=='0E-12'
        assert result['public_partition_delta']['details']['incompatible_currency_rows']==2
        con.execute('DROP TABLE public_members')
        con.execute("UPDATE h SET fair_value_currency='USD'")
        con.execute("UPDATE h SET fair_value=CAST(fair_value AS DOUBLE)+0.01 WHERE CAST(fair_value AS DOUBLE)<0")
        collect_public(con,Evidence(manifest,hp),Q,result)
        assert result['public_partition_delta']['actual']==1
