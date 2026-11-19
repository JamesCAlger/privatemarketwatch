import json

import duckdb
import pytest

from readings_loader import LoadError, cli, row_stores, store

HEADER = "cik,report_date,accession_number,bdc_investment_identifier,field,value,reason,source_evidence,author,date_added,src_context_id\n"


def _csv(tmp_path, name, lines, header=HEADER):
    path = tmp_path / name
    path.write_text(header + "".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def test_row_store_pads_cik_and_drops_other_funds(tmp_path):
    path = _csv(tmp_path, "c.csv", [
        '1,2026-03-31,0000000001-26-000001,"Acme, Inc. | Loan",cost,100,why,where,me,2026-11-01,c-1',
        "2,2026-03-31,0000000002-26-000001,Other,cost,5,why,where,me,2026-11-01,",
    ])
    rows = row_stores.read_row_corrections(path, "row_corrections", ["0000000001"])
    assert len(rows) == 1
    r = rows[0]
    assert (r["cik"], r["identifier"], r["context_id"], r["field"], r["value"]) == (
        "0000000001", "Acme, Inc. | Loan", "c-1", "cost", "100")
    assert (r["kind"], r["store"], r["evidence"], r["author"]) == ("value", "row_corrections", "where", "me")


def test_row_store_keeps_an_empty_context_and_an_empty_value(tmp_path):
    path = _csv(tmp_path, "c.csv", ["1,2026-03-31,0000000001-26-000001,Acme,interest_rate,,withdrawn,where,me,2026-11-01,"])
    r = row_stores.read_row_corrections(path, "row_corrections", ["0000000001"])[0]
    assert r["context_id"] == "" and r["value"] == ""


def test_row_store_without_a_context_column_is_read(tmp_path):
    header = HEADER.replace(",src_context_id", "")
    path = _csv(tmp_path, "c.csv", ["1,2026-03-31,0000000001-26-000001,Acme,cost,1,why,where,me,2026-11-01"], header)
    assert row_stores.read_row_corrections(path, "row_corrections", ["0000000001"])[0]["context_id"] == ""


def test_row_store_missing_column_stops_the_load(tmp_path):
    path = _csv(tmp_path, "c.csv", ["1,x"], header="cik,field\n")
    with pytest.raises(LoadError, match="missing column"):
        row_stores.read_row_corrections(path, "row_corrections", ["0000000001"])


def _inputs(tmp_path):
    wrappers = tmp_path / "wrappers"
    wrappers.mkdir()
    (wrappers / "0000000001.json").write_text(json.dumps({"source_encodings": {
        "filed_rate_reading": ["all_in"],
        "rate_only_contexts": ["adopt_adjacent"],
        "untagged_values": ["0000000001-26-000001 c-9 cost 7"],
    }}), encoding="utf-8")
    rows = _csv(tmp_path, "c.csv", ["1,2026-03-31,0000000001-26-000001,Acme,cost,100,why,where,me,2026-11-01,c-1"])
    return wrappers, [("row_corrections", rows)]


def test_load_and_write_round_trip(tmp_path):
    wrappers, stores = _inputs(tmp_path)
    tables, inputs = cli.load(["0000000001"], wrappers, stores)
    manifest = store.write(tmp_path / "out", tables, inputs)
    assert {k: v["rows"] for k, v in manifest["tables"].items()} == {"reading_rule": 1, "correction": 2, "not_loaded": 1}
    con = duckdb.connect()
    got = con.execute(f"select action, priority from read_parquet('{(tmp_path / 'out' / 'reading_rule.parquet').as_posix()}')").fetchall()
    assert got == [("rate_is_all_in", 20)]
    stores_seen = con.execute(f"select store from read_parquet('{(tmp_path / 'out' / 'correction.parquet').as_posix()}') order by 1").fetchall()
    assert stores_seen == [("row_corrections",), ("wrapper:untagged_values",)]
    assert json.loads((tmp_path / "out" / "_manifest.json").read_text(encoding="utf-8")) == manifest


def test_two_runs_give_the_same_manifest_and_replace_the_output(tmp_path):
    wrappers, stores = _inputs(tmp_path)
    first = store.write(tmp_path / "out", *cli.load(["0000000001"], wrappers, stores))
    second = store.write(tmp_path / "out", *cli.load(["0000000001"], wrappers, stores))
    assert first == second
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "_manifest.json", "correction.parquet", "not_loaded.parquet", "reading_rule.parquet"]
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".readings_tmp_")] == []


def test_duplicate_key_stops_the_write_and_keeps_the_old_output(tmp_path):
    wrappers, stores = _inputs(tmp_path)
    tables, inputs = cli.load(["0000000001"], wrappers, stores)
    store.write(tmp_path / "out", tables, inputs)
    tables["reading_rule"] = tables["reading_rule"] * 2
    with pytest.raises(LoadError, match="duplicate key"):
        store.write(tmp_path / "out", tables, inputs)
    assert (tmp_path / "out" / "reading_rule.parquet").exists()


def test_missing_wrapper_stops_the_load(tmp_path):
    wrappers, stores = _inputs(tmp_path)
    with pytest.raises(LoadError, match="no wrapper"):
        cli.load(["0000000002"], wrappers, stores)
