import json
import shutil
from pathlib import Path

import duckdb
import pytest

from filed_parser import PARSER_VERSION, instance, store

FIXTURE = Path(__file__).parent / "fixtures" / "mini_instance.xml"
ACC = "0001234567-23-000001"
CIK = "0001234567"


def make_inputs(tmp_path, with_html=True):
    xml = tmp_path / "raw" / "bdc_xbrl" / "1234567" / "000123456723000001.xml"
    xml.parent.mkdir(parents=True, exist_ok=True)
    if not xml.exists():
        shutil.copy(FIXTURE, xml)
    inputs = store.describe_file(xml, tmp_path / "raw", "instance")
    if with_html:
        html = tmp_path / "raw" / "bdc_html" / "1234567" / "000123456723000001.html"
        html.parent.mkdir(parents=True, exist_ok=True)
        html.write_text("<html><body>x</body></html>", encoding="utf-8")
        inputs.update(store.describe_file(html, tmp_path / "raw", "html"))
    else:
        inputs.update(store.describe_file(None, None, "html"))
    return inputs


def folder(out):
    return out / f"cik={CIK}" / f"accession={ACC}"


def pq(out, table):
    return (folder(out) / f"{table}.parquet").as_posix()


def parsed():
    return instance.parse_instance(FIXTURE, accession=ACC)


def test_tables_have_spec_columns():
    assert [c for c, _ in store.TABLES["filing"]] == [
        "accession", "cik", "document_type", "document_period_end_date", "amendment_flag",
        "fiscal_year_focus", "fiscal_period_focus", "registrant_name", "instance_file",
        "instance_sha256", "instance_bytes", "html_file", "html_sha256", "html_bytes",
        "parser_version", "dei_conflict"]
    assert dict(store.TABLES["tagged_fact"])["value_numeric"] == "DECIMAL(38,10)"
    assert dict(store.TABLES["document_row"])["cells"] == "VARCHAR[]"
    assert [c for c, _ in store.TABLES["document_row"]][5:8] == ["cells", "cell_colspans", "cell_rowspans"]
    assert dict(store.TABLES["document_row"])["cell_colspans"] == dict(store.TABLES["document_row"])["cell_rowspans"] == "INTEGER[]"
    assert [c for c, _ in store.TABLES["fact_placement"]][-3:] == ["in_hidden", "shown_row_index", "shown_cell_index"]
    assert set(store.TABLES) == {
        "filing", "context", "context_member", "unit", "tagged_fact",
        "document_row", "fact_placement", "footnote", "fact_footnote"}


def test_write_creates_all_tables_and_manifest(tmp_path):
    out = tmp_path / "out"
    m = store.write_filing(out, CIK, ACC, parsed(), make_inputs(tmp_path))
    assert m["status"] == "written"
    for t in store.TABLES:
        assert (folder(out) / f"{t}.parquet").exists()
    assert (folder(out) / "_manifest.json").exists()
    con = duckdb.connect()
    assert con.sql(f"select count(*) from read_parquet('{pq(out, 'tagged_fact')}')").fetchone()[0] == 11
    assert con.sql(f"select count(*) from read_parquet('{pq(out, 'document_row')}')").fetchone()[0] == 0
    dtypes = {r[0]: r[1] for r in con.sql(
        f"describe select * from read_parquet('{pq(out, 'document_row')}')").fetchall()}
    assert dtypes["cells"] == "VARCHAR[]"
    ftypes = {r[0]: r[1] for r in con.sql(
        f"describe select * from read_parquet('{pq(out, 'tagged_fact')}')").fetchall()}
    assert ftypes["value_numeric"] == "DECIMAL(38,10)" and ftypes["fact_index"] == "INTEGER"
    row = con.sql(
        "select cik, document_type, instance_bytes, html_bytes, parser_version "
        f"from read_parquet('{pq(out, 'filing')}')").fetchall()
    assert row == [(CIK, "10-Q", FIXTURE.stat().st_size, 27, PARSER_VERSION)]


def test_manifest_content(tmp_path):
    out = tmp_path / "out"
    store.write_filing(out, CIK, ACC, parsed(), make_inputs(tmp_path))
    m = json.loads((folder(out) / "_manifest.json").read_text())
    assert m["parser_version"] == PARSER_VERSION
    assert m["inputs"]["instance_sha256"] and m["inputs"]["html_sha256"]
    assert set(m["tables"]) == set(store.TABLES)
    assert m["tables"]["tagged_fact"]["rows"] == 11
    assert m["tables"]["filing"]["rows"] == 1
    assert len(m["tables"]["tagged_fact"]["content_hash"]) == 64
    assert "written_at" in m


def test_html_absent_is_null(tmp_path):
    out = tmp_path / "out"
    store.write_filing(out, CIK, ACC, parsed(), make_inputs(tmp_path, with_html=False))
    con = duckdb.connect()
    r = con.sql(
        f"select html_file, html_sha256, html_bytes from read_parquet('{pq(out, 'filing')}')").fetchone()
    assert r == (None, None, None)


def test_rows_sorted_by_primary_key(tmp_path):
    out = tmp_path / "out"
    store.write_filing(out, CIK, ACC, parsed(), make_inputs(tmp_path))
    con = duckdb.connect()
    ids = [r[0] for r in con.sql(f"select fact_id from read_parquet('{pq(out, 'tagged_fact')}')").fetchall()]
    assert ids == sorted(ids) and ids[0] == "f_amend" and ids[-1] == "noid:6"
    idx = [r[0] for r in con.sql(f"select fact_index from read_parquet('{pq(out, 'tagged_fact')}')").fetchall()]
    assert idx != sorted(idx)


def test_same_input_twice_same_content_hashes(tmp_path):
    inputs = make_inputs(tmp_path)
    m1 = store.write_filing(tmp_path / "a", CIK, ACC, parsed(), inputs)
    m2 = store.write_filing(tmp_path / "b", CIK, ACC, parsed(), inputs)
    assert {t: v["content_hash"] for t, v in m1["tables"].items()} == {
        t: v["content_hash"] for t, v in m2["tables"].items()}


def test_skip_on_same_manifest(tmp_path):
    out = tmp_path / "out"
    inputs = make_inputs(tmp_path)
    store.write_filing(out, CIK, ACC, parsed(), inputs)
    before = (folder(out) / "_manifest.json").read_text()
    m = store.write_filing(out, CIK, ACC, parsed(), inputs)
    assert m["status"] == "skipped"
    assert (folder(out) / "_manifest.json").read_text() == before


def test_error_on_changed_input_hash(tmp_path):
    out = tmp_path / "out"
    store.write_filing(out, CIK, ACC, parsed(), make_inputs(tmp_path))
    xml = tmp_path / "raw" / "bdc_xbrl" / "1234567" / "000123456723000001.xml"
    xml.write_bytes(xml.read_bytes() + b"\n")
    with pytest.raises(store.InputChanged) as e:
        store.write_filing(out, CIK, ACC, parsed(), make_inputs(tmp_path))
    assert "000123456723000001.xml" in str(e.value)


def test_reparse_overwrites_even_when_input_changed(tmp_path):
    out = tmp_path / "out"
    store.write_filing(out, CIK, ACC, parsed(), make_inputs(tmp_path))
    xml = tmp_path / "raw" / "bdc_xbrl" / "1234567" / "000123456723000001.xml"
    xml.write_bytes(xml.read_bytes() + b"\n")
    inputs = make_inputs(tmp_path)
    m = store.write_filing(out, CIK, ACC, parsed(), inputs, reparse=True)
    assert m["status"] == "written"
    on_disk = json.loads((folder(out) / "_manifest.json").read_text())
    assert on_disk["inputs"]["instance_sha256"] == inputs["instance_sha256"]


def test_reparse_overwrites_same_input_and_leaves_no_temp_folders(tmp_path):
    out = tmp_path / "out"
    inputs = make_inputs(tmp_path)
    store.write_filing(out, CIK, ACC, parsed(), inputs)
    m = store.write_filing(out, CIK, ACC, parsed(), inputs, reparse=True)
    assert m["status"] == "written"
    assert sorted(p.name for p in out.iterdir()) == [f"cik={CIK}"]
    assert sorted(p.name for p in (out / f"cik={CIK}").iterdir()) == [f"accession={ACC}"]


def test_different_parser_version_skipped_unless_reparse(tmp_path, capsys):
    out = tmp_path / "out"
    inputs = make_inputs(tmp_path)
    store.write_filing(out, CIK, ACC, parsed(), inputs)
    mf = folder(out) / "_manifest.json"
    m = json.loads(mf.read_text())
    m["parser_version"] = "0-old"
    mf.write_text(json.dumps(m))
    r = store.write_filing(out, CIK, ACC, parsed(), inputs)
    assert r["status"] == "skipped_version"
    assert "WARNING" in capsys.readouterr().out
    assert json.loads(mf.read_text())["parser_version"] == "0-old"
    r = store.write_filing(out, CIK, ACC, parsed(), inputs, reparse=True)
    assert r["status"] == "written"
    assert json.loads(mf.read_text())["parser_version"] == PARSER_VERSION


def test_failure_mid_write_leaves_no_final_folder(tmp_path, monkeypatch):
    out = tmp_path / "out"
    real = store._write_parquet
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("disk full")
        return real(*a, **k)

    monkeypatch.setattr(store, "_write_parquet", boom)
    with pytest.raises(RuntimeError):
        store.write_filing(out, CIK, ACC, parsed(), make_inputs(tmp_path))
    assert not folder(out).exists()
    assert not any(out.rglob("*.parquet"))


def test_failure_during_reparse_keeps_old_folder(tmp_path, monkeypatch):
    out = tmp_path / "out"
    inputs = make_inputs(tmp_path)
    store.write_filing(out, CIK, ACC, parsed(), inputs)
    before = (folder(out) / "_manifest.json").read_text()

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "_write_parquet", boom)
    with pytest.raises(RuntimeError):
        store.write_filing(out, CIK, ACC, parsed(), inputs, reparse=True)
    assert (folder(out) / "_manifest.json").read_text() == before


def test_verify_matches_then_detects_difference(tmp_path):
    out = tmp_path / "out"
    inputs = make_inputs(tmp_path)
    store.write_filing(out, CIK, ACC, parsed(), inputs)
    assert store.verify_filing(out, CIK, ACC, parsed(), inputs) == []
    other = parsed()
    other["tagged_fact"] = other["tagged_fact"][:-1]
    problems = store.verify_filing(out, CIK, ACC, other, inputs)
    assert any("tagged_fact" in p for p in problems)


def test_content_hash_is_pinned():
    import datetime
    from decimal import Decimal
    rows = [
        ("acc-1", None, True, False, 42, Decimal("1234.50"), Decimal("-0.00"),
         datetime.date(2026, 3, 31), "caf\u00e9 x", ["a", "b c"]),
        ("acc-2", "x", False, True, -7, Decimal("0E-10"), Decimal("1.0E+3"),
         datetime.date(2025, 12, 31), "", []),
    ]
    assert store.content_hash(rows) == "060cd9a028a26c6f0537c18364500a9e72f14ffe34217a1240f521f6b7cce1d0"
    # tuples (as built by the parser) and lists (as read back from Parquet) hash the same
    assert store.content_hash([r[:-1] + (tuple(r[-1]),) for r in rows]) == store.content_hash(rows)


def test_content_hash_rejects_unknown_types():
    with pytest.raises(TypeError):
        store.content_hash([(1.5,)])


def test_f3_temp_and_old_folders_are_staged_outside_the_out_tree(tmp_path, monkeypatch):
    out = tmp_path / "data" / "filed"
    inputs = make_inputs(tmp_path)
    store.write_filing(out, CIK, ACC, parsed(), inputs)
    seen = []
    real = store._write_parquet

    def spy(con, name, rows, path):
        seen.append(Path(path).resolve())
        # while a write is in progress, the readers' glob must see only the finished folder
        found = {p.parent.name for p in out.glob("*/*/filing.parquet")}
        assert found == {f"accession={ACC}"}
        assert not list(out.glob("*/_*")) and not list(out.glob("_*"))
        return real(con, name, rows, path)

    monkeypatch.setattr(store, "_write_parquet", spy)
    store.write_filing(out, CIK, ACC, parsed(), inputs, reparse=True)
    staging = (tmp_path / "data" / "_filed_staging").resolve()
    assert seen and all(staging in p.parents for p in seen)
    assert not any(out.rglob("_tmp_*")) and not any(out.rglob("_old_*"))
    assert list(staging.iterdir()) == []


def test_f3_failed_write_leaves_nothing_visible_to_the_glob(tmp_path, monkeypatch):
    out = tmp_path / "data" / "filed"

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "_write_parquet", boom)
    with pytest.raises(RuntimeError):
        store.write_filing(out, CIK, ACC, parsed(), make_inputs(tmp_path))
    assert list(out.glob("*/*/*.parquet")) == []


def test_f3_every_run_sweeps_the_staging_folder(tmp_path):
    from filed_parser import cli
    staging = tmp_path / "data" / "_filed_staging"
    (staging / "_tmp_leftover").mkdir(parents=True)
    (staging / "_tmp_leftover" / "filing.parquet").write_bytes(b"x")
    (staging / "_old_leftover").mkdir()
    rc = cli.main(["--cik", "1234567", "--raw", str(tmp_path / "raw"), "--out", str(tmp_path / "data" / "filed")])
    assert rc == 0
    assert list(staging.iterdir()) == []


def test_parser_version_is_3():
    assert PARSER_VERSION == "3"


def test_content_hash_accepts_integer_lists_and_rejects_mixed_lists():
    a = store.content_hash([("x", [1, 2, 1], [])])
    assert a == store.content_hash([("x", (1, 2, 1), ())])
    assert a != store.content_hash([("x", [1, 2, 2], [])])
    assert store.content_hash([("x", [], [])]) == store.content_hash([("x", (), ())])
    with pytest.raises(TypeError):
        store.content_hash([("x", [1, "a"])])
    with pytest.raises(TypeError):
        store.content_hash([("x", [True])])


def test_spans_and_shown_cells_round_trip_through_parquet(tmp_path):
    from filed_parser import inline
    tables = parsed()
    tables.update({k: v for k, v in inline.parse_inline(
        Path(__file__).parent / "fixtures" / "mini_inline.html", accession=ACC).items()
        if k in ("document_row", "fact_placement", "footnote", "fact_footnote")})
    out = tmp_path / "out"
    store.write_filing(out, CIK, ACC, tables, make_inputs(tmp_path))
    con = duckdb.connect()
    r = con.sql(
        f"select cell_colspans, cell_rowspans from read_parquet('{pq(out, 'document_row')}') where row_index = 1"
    ).fetchall()
    assert r == [([2, 1, 1, 1], [3, 1, 1, 1])]
    s = con.sql(
        f"select shown_row_index, shown_cell_index from read_parquet('{pq(out, 'fact_placement')}') "
        "where fact_id = 'h2'").fetchall()
    assert s == [(1, 3)]
    assert store.verify_filing(out, CIK, ACC, tables, make_inputs(tmp_path)) == []
