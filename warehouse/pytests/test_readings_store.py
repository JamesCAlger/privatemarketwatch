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
    assert {k: v["rows"] for k, v in manifest["tables"].items()} == {"reading_rule": 1, "correction": 2, "not_loaded": 1,
                                                                    "wrapper_drift": 0, "rule_label_example": 0}
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
        "_manifest.json", "correction.parquet", "not_loaded.parquet", "reading_rule.parquet", "rule_label_example.parquet",
        "wrapper_drift.parquet"]
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


# Drift check (owner decision 2026-11-19): the new pipeline reads its own wrapper copies; the loader reports whether
# each production wrapper changed since its copy was taken.

def _copies(tmp_path, production_text):
    wrappers, stores = _inputs(tmp_path)
    production = tmp_path / "production"
    production.mkdir()
    prod_file = production / "0000000001.json"
    prod_file.write_text(production_text, encoding="utf-8")
    copied = store.file_sha256(prod_file)
    (wrappers / "_source.json").write_text(json.dumps(
        {"copied_on": "2026-11-19", "funds": {"0000000001": {"sha256": copied, "git_blob": "x"}}}), encoding="utf-8")
    return wrappers, stores, production, prod_file


def test_unchanged_production_wrapper_is_not_drift(tmp_path):
    wrappers, stores, production, _ = _copies(tmp_path, '{"a": 1}\n')
    tables, inputs = cli.load(["0000000001"], wrappers, stores, production)
    assert [r["changed"] for r in tables["wrapper_drift"]] == [False]
    manifest = store.write(tmp_path / "out", tables, inputs)
    assert manifest["production_wrappers_changed"] == []
    assert manifest["tables"]["wrapper_drift"]["rows"] == 1
    assert (wrappers / "_source.json").as_posix() in inputs


def test_edited_production_wrapper_is_drift_in_table_and_manifest(tmp_path):
    wrappers, stores, production, prod_file = _copies(tmp_path, '{"a": 1}\n')
    prod_file.write_text('{"a": 2}\n', encoding="utf-8")
    tables, inputs = cli.load(["0000000001"], wrappers, stores, production)
    row = _one_row(tables["wrapper_drift"])
    assert row["changed"] is True and row["current_sha256"] == store.file_sha256(prod_file)
    manifest = store.write(tmp_path / "out", tables, inputs)
    assert manifest["production_wrappers_changed"] == ["0000000001"]
    con = duckdb.connect()
    got = con.execute(f"select cik, changed from read_parquet('{(tmp_path / 'out' / 'wrapper_drift.parquet').as_posix()}')").fetchall()
    assert got == [("0000000001", True)]


def test_missing_production_wrapper_is_drift(tmp_path):
    wrappers, stores, production, prod_file = _copies(tmp_path, '{"a": 1}\n')
    prod_file.unlink()
    tables, _ = cli.load(["0000000001"], wrappers, stores, production)
    assert _one_row(tables["wrapper_drift"])["changed"] is True


def test_missing_copy_record_stops_the_load(tmp_path):
    wrappers, stores, production, _ = _copies(tmp_path, '{"a": 1}\n')
    (wrappers / "_source.json").unlink()
    with pytest.raises(LoadError, match="no copy record"):
        cli.load(["0000000001"], wrappers, stores, production)


def test_fund_missing_from_copy_record_stops_the_load(tmp_path):
    wrappers, stores, production, _ = _copies(tmp_path, '{"a": 1}\n')
    (wrappers / "0000000002.json").write_text('{"source_encodings": {}}', encoding="utf-8")
    with pytest.raises(LoadError, match="no copied hash"):
        cli.load(["0000000001", "0000000002"], wrappers, stores, production)


def test_wrapper_reading_rules_load_end_to_end(tmp_path):
    wrappers, stores = _inputs(tmp_path)
    (wrappers / "0000000001.json").write_text(json.dumps({"source_encodings": {}, "reading_rules": [
        {"target": "role", "action": "subtotal_on_fair_value", "evidence": "D12"}]}), encoding="utf-8")
    tables, inputs = cli.load(["0000000001"], wrappers, stores)
    store.write(tmp_path / "out", tables, inputs)
    con = duckdb.connect()
    got = con.execute(f"select origin, rule_class, sel_concept_namespace from read_parquet('{(tmp_path / 'out' / 'reading_rule.parquet').as_posix()}')").fetchall()
    assert got == [("wrapper:reading_rules", "fund_rule", "")]


def test_command_line_reads_the_stores_and_folders_it_is_given(tmp_path, capsys):
    # The CI fixture build (warehouse/ci) passes every input by option; nothing is read from the default paths.
    wrappers, stores, production, _ = _copies(tmp_path, '{"a": 1}\n')
    by_context = _csv(tmp_path, "by_context.csv", ["1,2026-03-31,0000000001-26-000001,Acme,cost,5,why,where,me,2026-11-01,c-2"])
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"findings_scope": {"ciks": ["0000000001"]}}), encoding="utf-8")
    out = tmp_path / "out"
    code = cli.main(["--out", str(out), "--scope-file", str(scope), "--wrappers", str(wrappers),
                     "--production-wrappers", str(production), "--row-corrections", str(stores[0][1]),
                     "--row-corrections-by-context", str(by_context)])
    assert code == 0
    manifest = json.loads((out / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["production_wrappers_changed"] == []
    assert manifest["tables"]["wrapper_drift"]["rows"] == 1
    assert by_context.as_posix() in manifest["inputs"] and stores[0][1].as_posix() in manifest["inputs"]
    con = duckdb.connect()
    got = con.execute(f"select store, context_id from read_parquet('{(out / 'correction.parquet').as_posix()}') order by 1").fetchall()
    assert got == [("row_corrections", "c-1"), ("row_corrections_by_context", "c-2"), ("wrapper:untagged_values", "c-9")]
    assert "production wrappers changed since the copy: none" in capsys.readouterr().out


def test_command_line_missing_row_store_is_an_error_not_an_empty_table(tmp_path):
    wrappers, stores, production, _ = _copies(tmp_path, '{"a": 1}\n')
    scope = tmp_path / "scope.json"
    scope.write_text(json.dumps({"findings_scope": {"ciks": ["0000000001"]}}), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        cli.main(["--out", str(tmp_path / "out"), "--scope-file", str(scope), "--wrappers", str(wrappers),
                  "--production-wrappers", str(production), "--row-corrections", str(stores[0][1]),
                  "--row-corrections-by-context", str(tmp_path / "missing.csv")])


def _one_row(rows):
    assert len(rows) == 1
    return rows[0]


def test_label_examples_load_end_to_end(tmp_path):
    wrappers, stores = _inputs(tmp_path)
    (wrappers / "0000000001.json").write_text(json.dumps({"source_encodings": {}, "reading_rules": [
        {"target": "role", "action": "position_without_term_fact", "label_pattern": "acme fund lp - lp interest",
         "label_examples_match": ["Acme Fund LP - LP Interest"],
         "label_examples_no_match": ["Acme Fund LP", "Total Acme Fund LP - LP Interest"], "evidence": "x"}]}),
        encoding="utf-8")
    tables, inputs = cli.load(["0000000001"], wrappers, stores)
    manifest = store.write(tmp_path / "out", tables, inputs)
    assert manifest["tables"]["rule_label_example"]["rows"] == 3
    con = duckdb.connect()
    out = (tmp_path / "out").as_posix()
    got = con.execute(f"select e.label, e.expected_match, e.rule_id = r.rule_id from read_parquet('{out}/rule_label_example.parquet') e"
                      f" cross join read_parquet('{out}/reading_rule.parquet') r order by 1").fetchall()
    assert got == [("Acme Fund LP", False, True), ("Acme Fund LP - LP Interest", True, True),
                   ("Total Acme Fund LP - LP Interest", False, True)]


def test_one_label_listed_as_match_and_no_match_stops_the_write(tmp_path):
    wrappers, stores = _inputs(tmp_path)
    (wrappers / "0000000001.json").write_text(json.dumps({"source_encodings": {}, "reading_rules": [
        {"target": "role", "action": "position_without_term_fact", "label_pattern": "acme",
         "label_examples_match": ["Acme"], "label_examples_no_match": ["Acme"], "evidence": "x"}]}), encoding="utf-8")
    tables, inputs = cli.load(["0000000001"], wrappers, stores)
    with pytest.raises(LoadError, match="duplicate key"):
        store.write(tmp_path / "out", tables, inputs)
