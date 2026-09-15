"""Public totals conserve the exact same signed holding observations."""
from decimal import Decimal
import json

import duckdb
import pytest

from pipeline.public_partitions import public_snapshot
from tests.test_holdings_finalizer import holdings


def population(tmp_path):
    path = tmp_path / "private_markets_holdings.csv"
    holdings([
        {"row_id":"positive","fair_value":"100.125","lien_position":"First Lien", "gics_sub_industry":"Software"},
        {"row_id":"negative","fair_value":"-15.125","index_classification":"COMMON_EQUITY"},
        {"row_id":"zero","fair_value":"0","index_classification":"CASH"},
        {"row_id":"null","fair_value":"","index_classification":"UNCLASSIFIED"},
        {"row_id":"outside","fair_value":"999999","cik":"0000000999"},
        {"row_id":"older","fair_value":"999999","report_date":"2025-12-31"},
        {"row_id":"future","fair_value":"999999","report_date":"2026-06-30"},
    ]).to_csv(path, index=False)
    return path


def snapshot(con, path):
    return public_snapshot(con,path,cutoff="2026-03-31",cohort={"0000000123"},
                           hierarchy={"Software":{"sector":"Information Technology"}})


def test_signed_partitions_conserve_rows_nulls_and_exact_total(tmp_path):
    with duckdb.connect() as con:
        result = snapshot(con,population(tmp_path))
        assert result["asOf"] == "2026-03-31"
        assert result["portfolioFv"] == 85
        assert result["positionCount"] == 4
        assert result["missingFairValueCount"] == 1
        assert set(r[0] for r in con.execute("SELECT row_id FROM public_holdings").fetchall()) == {"positive","negative","zero","null"}
        for rows in result["partitions"].values():
            assert sum(Decimal(r["fairValueExact"]) for r in rows) == Decimal(result["fairValueExact"])
            assert sum(r["positionCount"] for r in rows) == 4
        instrument = {r["label"]:r for r in result["partitions"]["instrument"]}
        assert instrument["Common Equity"]["totalFv"] == -15.125
        assert instrument["Cash"]["totalFv"] == 0
        assert instrument["Other"]["missingFairValueCount"] == 1


def test_instrument_class_is_not_evidence_of_sector(tmp_path):
    path = tmp_path / "holdings.csv"
    holdings([{"index_classification":"PRIVATE_CREDIT_FUND","fair_value":"7.5", "gics_sub_industry":""}]).to_csv(path,index=False)
    with duckdb.connect() as con:
        result = snapshot(con,path)
    assert result["partitions"]["sector"][0]["label"] == "Unknown"


def test_unrepresentable_fair_value_blocks_export(tmp_path):
    path = tmp_path / "holdings.csv"
    holdings([{"fair_value":"garbage"}]).to_csv(path,index=False)
    with duckdb.connect() as con, pytest.raises(ValueError,match="unrepresentable"):
        snapshot(con,path)


def test_empty_cohort_cannot_silently_publish_all_vehicles(tmp_path):
    with duckdb.connect() as con, pytest.raises(ValueError,match="nonempty wrapper cohort"):
        public_snapshot(con,population(tmp_path),cohort=set())


@pytest.mark.parametrize('currency',['GBP','AUD','UNRESOLVED'])
@pytest.mark.parametrize('amount',['176106000','0','-12.25'])
def test_public_sum_rejects_non_usd_values_even_when_partitions_reconcile(tmp_path,currency,amount):
    path=tmp_path/'holdings.csv'
    holdings([dict(fair_value=amount,fair_value_currency=currency)]).to_csv(path,index=False)
    with duckdb.connect() as con,pytest.raises(ValueError,match='non-USD or unresolved'):
        snapshot(con,path)


def test_unresolved_foreign_fv_retains_position_in_every_partition(tmp_path):
    path=tmp_path/'holdings.csv'
    holdings([dict(fair_value='',fair_value_currency='GBP'),dict(row_id='USD',fair_value='12.5')]).to_csv(path,index=False)
    with duckdb.connect() as con:
        actual=snapshot(con,path)
    assert actual['positionCount']==2 and actual['missingFairValueCount']==1
    assert actual['portfolioFv']==12.5
    for partition in actual['partitions'].values():
        assert sum(row['positionCount'] for row in partition)==2
        assert sum(row['missingFairValueCount'] for row in partition)==1


def test_exporters_share_one_snapshot_without_replacing_unknowns(tmp_path,monkeypatch):
    from pipeline.export import analytics_exports,helpers,index_exports
    path = population(tmp_path)
    monkeypatch.setattr(helpers,"FRONTEND_DATA_DIR",tmp_path)
    monkeypatch.setattr(index_exports,"UNIFIED_HOLDINGS_CSV",path)
    monkeypatch.setattr(analytics_exports,"UNIFIED_HOLDINGS_CSV",path)
    monkeypatch.setattr(index_exports,"BDC_DERIVATIVES_FILE",tmp_path / "absent.csv")
    with duckdb.connect() as con:
        result = snapshot(con,path)
        index_exports._export_portfolio_characteristics(con,snapshot=result)
        analytics_exports._export_gics_sector_breakdown(con,snapshot=result)
    portfolio = json.loads((tmp_path / "portfolio_characteristics.json").read_text())
    sectors = json.loads((tmp_path / "gics_sector_breakdown.json").read_text())
    assert portfolio["portfolioFv"] == 85
    for rows in (portfolio["instrumentBreakdown"],sectors):
        assert sum(Decimal(row["fairValueExact"]) for row in rows) == Decimal(portfolio["fairValueExact"])
    assert next(row for row in sectors if row["sector"] == "Unknown")["totalFv"] == -15.125
