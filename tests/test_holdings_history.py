import json
from pathlib import Path
import duckdb
import pytest

from pipeline.holdings_history import export_history
from pipeline.holdings_finalizer import project_artifact
from tests.test_holdings_finalizer import holdings


def test_history_preserves_all_positions_signed_zero_and_complete_ids(tmp_path):
    hp=tmp_path/"private_markets_holdings.csv"
    frame=holdings([dict(row_id="R1",position_id="P1",cik="0000000123",fair_value="100"),
        dict(row_id="R2",position_id="P2",cik="0000000123",fair_value="-5"),
        dict(row_id="R3",position_id="P3",cik="0000000123",fair_value="0"),
        dict(row_id="old",position_id="P1",cik="0000000123",report_date="2025-12-31",fair_value="95"),
        dict(row_id="other",position_id="P4",cik="0000000456",fair_value="99")])
    project_artifact(frame,"private_markets_holdings.csv").to_csv(hp,index=False)
    with duckdb.connect() as con:
        manifest=export_history(con,hp,tmp_path/"history",cohort={"0000000123","0000000789"},release_id="R")
    assert manifest["accessible_holdings_difference"]==0 and manifest["rows"]==4
    index=json.loads((tmp_path/"history/0000000123/index.json").read_text())
    assert [q["rows"] for q in index["quarters"]]==[1,3]
    current=json.loads((tmp_path/"history/0000000123/2026-03-31.json").read_text())
    assert [r["row_id"] for r in current["rows"]]==["R1","R2","R3"]
    assert sum(r["fair_value"] for r in current["rows"])==95
    assert all(r["position_id"] for r in current["rows"])
    assert json.loads((tmp_path/"history/0000000789/index.json").read_text())["quarters"]==[]


def test_sparse_text_after_null_only_quarter_files_keeps_its_literal_value(tmp_path):
    # Initial files contain no values for these text columns. Later observations
    # carry ordinary text and intentional quotes/JSON-looking text, all VARCHAR.
    rows=[dict(row_id=f"R{i:03}",position_id=f"P{i:03}",cik=f"{i+1:010}",
        bdc_investment_country=None,jv_subsidiary=None,src_conflict_fields=None)
        for i in range(35)]
    rows[-2].update(bdc_investment_country="United States",jv_subsidiary="Y",
        src_conflict_fields="principal_amount")
    rows[-1].update(bdc_investment_country='"United States"',jv_subsidiary='["Y"]',
        src_conflict_fields='["principal_amount"]')
    hp=tmp_path/"private_markets_holdings.csv"
    project_artifact(holdings(rows),"private_markets_holdings.csv").to_csv(hp,index=False)
    with duckdb.connect() as con:
        manifest=export_history(con,hp,tmp_path/"history",cohort={r["cik"] for r in rows},release_id="R")
    assert manifest["accessible_holdings_difference"]==0 and manifest["rows"]==35
    for original in (rows[0],rows[-2],rows[-1]):
        payload=json.loads((tmp_path/"history"/original["cik"]/"2026-03-31.json").read_text())
        actual=payload["rows"][0]
        for field in ("bdc_investment_country","jv_subsidiary","src_conflict_fields"):
            assert actual[field]==original[field]


def test_history_readback_still_rejects_a_changed_written_value(tmp_path,monkeypatch):
    hp=tmp_path/"private_markets_holdings.csv"
    project_artifact(holdings(),"private_markets_holdings.csv").to_csv(hp,index=False)
    before=hp.read_bytes()
    write_text=Path.write_text
    def change_written_value(path,text,*args,**kwargs):
        if path.name=="2026-03-31.json":
            payload=json.loads(text)
            payload["rows"][0]["fair_value"]+=1
            text=json.dumps(payload)
        return write_text(path,text,*args,**kwargs)
    monkeypatch.setattr(Path,"write_text",change_written_value)
    with duckdb.connect() as con, pytest.raises(ValueError,match="typed_difference=2"):
        export_history(con,hp,tmp_path/"history",cohort={"0000000123"},release_id="R")
    assert hp.read_bytes()==before
    assert not (tmp_path/"history/manifest.json").exists()
