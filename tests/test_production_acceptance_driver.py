"""The P4 driver must exercise the real conservation SQL before cohort work."""
import json

import duckdb
import pandas as pd
import pytest

from scripts.run_production_acceptance import primary_evidence
from tests.test_holdings_finalizer import holdings


@pytest.mark.parametrize('current', [True, False])
def test_completed_collector_must_name_the_current_register(tmp_path, current):
    from scripts.run_production_acceptance import verify_registered_experiment
    from pipeline.programme.core import ContractError, sha
    register = tmp_path / 'obligations.csv'
    register.write_text('cik,report_date,eligibility_status\n123,2026-03-31,eligible_source_investments\n')
    directory = tmp_path / 'collector'
    directory.mkdir()
    summary = directory / 'summary.json'
    summary.write_text(json.dumps(dict(input_sha256={str(register.resolve()): sha(register) if current else '0' * 64})))
    (directory / 'complete.json').write_text(json.dumps({'summary.json': sha(summary)}))
    if current:
        verify_registered_experiment(directory, register)
    else:
        with pytest.raises(ContractError, match='different obligation register'):
            verify_registered_experiment(directory, register)


def test_primary_driver_runs_existing_engine_in_isolated_files(tmp_path):
    frozen=tmp_path/"frozen"
    data=frozen/"data/output";data.mkdir(parents=True)
    output=tmp_path/"evaluation";output.mkdir()
    hp=tmp_path/"private_markets_holdings.csv"
    holdings([dict(cik=cik,row_id=rid,fair_value=value,fair_value_currency="USD",
                   accounting_scope_id=cik+"|parent",accounting_record_class="parent_schedule")
              for cik,rid,value in (("0000000123","ROW-1","110"),
                                    ("0000000456","R2","90"),
                                    ("0000000789","R3","100"))]).to_csv(hp,index=False)
    pd.DataFrame([dict(cik=c,report_date="2026-03-31",source="companyfacts",
        investments_at_fair_value=100,cash_equivalents_at_fair_value=0)
        for c in ("123","456")]).to_csv(data/"fund_financials.csv",index=False)
    pd.DataFrame([dict(cik="789",report_date="2026-03-31",period="2026-03-31",
        investment_identifier="Total investments",fair_value=100)]).to_csv(data/"bdc_holdings.csv",index=False)
    primary_evidence(hp,frozen,output,{"0000000123","0000000456","0000000789"})
    anchors=pd.read_csv(output/"primary_anchors.csv",dtype=str).set_index("cik")
    assert anchors.loc["0000000123","currency"]=="USD"
    assert anchors.loc["0000000123","published_value"]=="110.0"
    assert anchors.loc["0000000456","residual_pct"]=="-10.0"
    assert anchors.loc["0000000789","anchor_kind"]=="schedule_total"
    assert pd.isna(anchors.loc["0000000789","currency"])
    ledger=pd.read_csv(output/"conservation_ledger.csv",dtype=str)
    assert list(ledger.status)==["fail","fail","pass"]
    assert json.loads((output/"primary_inputs.json").read_text())
    assert {p.name for p in data.iterdir()}=={"fund_financials.csv","bdc_holdings.csv"}
    with duckdb.connect() as con:
        membership=con.execute("SELECT cik,membership,reason FROM read_parquet(?) ORDER BY cik",
            [str(output/"accounting_membership.parquet")]).fetchall()
    assert membership==[
        ("0000000123","included","declared_anchor_population"),
        ("0000000456","included","declared_anchor_population"),
        ("0000000789","unknown","anchor_evidence_unavailable")]
    totals=pd.read_csv(output/"accounting_anchor_summaries.csv",dtype={"cik":str}).set_index("cik")
    assert totals.retained_rows.sum()==3
    assert totals.retained_fair_value.sum()==300
    assert totals.loc["0000000789","unknown_absolute_fair_value"]==100
