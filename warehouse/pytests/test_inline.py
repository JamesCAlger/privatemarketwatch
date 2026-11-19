import hashlib
from pathlib import Path

import pytest

from filed_parser import inline, store

FIXTURE = Path(__file__).parent / "fixtures" / "mini_inline.html"
ACC = "0001234567-23-000001"


def dicts(tables, name):
    cols = [c for c, _ in store.TABLES[name]]
    return [dict(zip(cols, r)) for r in tables[name]]


@pytest.fixture(scope="module")
def parsed():
    return inline.parse_inline(FIXTURE, accession=ACC)


def test_parser_is_xml(parsed):
    assert parsed["html_parser"] == "xml"


def test_document_rows(parsed):
    rows = dicts(parsed, "document_row")
    assert [(r["row_index"], r["table_index"], r["row_in_table"], r["cell_count"], r["fact_count"]) for r in rows] == [
        (0, 0, 0, 3, 0), (1, 0, 1, 4, 1), (2, 0, 2, 2, 2),
        (3, 1, 0, 1, 1), (4, 2, 0, 2, 2), (5, 3, 0, 1, 1), (6, 4, 0, 2, 0), (7, 5, 0, 3, 1)]
    assert all(r["accession"] == ACC for r in rows)


def test_cells_keep_empty_spacers_and_collapse_white_space(parsed):
    rows = {r["row_index"]: r["cells"] for r in dicts(parsed, "document_row")}
    assert rows[0] == ["Industry: Software", "", ""]  # nbsp-only and blank cells stay, as empty text
    assert rows[1] == ["Borrower A", "", "1,234", "x y"]
    assert rows[2] == ["Senior Secured", "0.05"]


def test_table_without_facts_is_absent_and_outer_table_of_nested_fact_not_kept(parsed):
    texts = [c for r in dicts(parsed, "document_row") for c in r["cells"]]
    assert "No facts here" not in texts
    assert "after" not in texts  # T3: its only fact is in the nested table
    assert len({r["table_index"] for r in dicts(parsed, "document_row")}) == 6  # T1, T3inner, T4, T4inner, T5 (hidden link only), T6


def test_nested_fact_belongs_to_inner_row(parsed):
    p = {r["fact_id"]: r for r in dicts(parsed, "fact_placement")}
    assert (p["n3"]["row_index"], p["n3"]["cell_index"]) == (3, 0)
    assert (p["n5"]["row_index"], p["n5"]["cell_index"]) == (5, 0)
    rows = {r["row_index"]: r for r in dicts(parsed, "document_row")}
    assert rows[4]["fact_count"] == 2  # blk and n4, not n5 (inner table)


def test_placement_columns(parsed):
    p = {r["fact_id"]: r for r in dicts(parsed, "fact_placement")}
    assert [r["fact_id"] for r in dicts(parsed, "fact_placement")] == [
        "h1", "h2", "h3", "n1", "t1", "n2", "n3", "blk", "n4", "n5", "bk", "o1"]
    n1 = p["n1"]
    assert (n1["placement_index"], n1["ix_element"], n1["concept"], n1["context_id"]) == (
        3, "nonFraction", "us-gaap:InvestmentOwnedAtFairValue", "C_pos")
    assert (n1["row_index"], n1["cell_index"], n1["displayed_text"]) == (1, 2, "1,234")
    assert (n1["scale"], n1["sign"], n1["format"], n1["in_hidden"]) == ("3", "-", "ixt:num-dot-decimal", False)
    assert p["n2"]["scale"] is None and p["n2"]["sign"] is None and p["n2"]["format"] is None


def test_hidden_fact(parsed):
    h = next(r for r in dicts(parsed, "fact_placement") if r["fact_id"] == "h1")
    assert h["in_hidden"] is True and h["row_index"] is None and h["ix_element"] == "nonNumeric"
    assert h["displayed_text"] == "10-Q"


def test_fact_outside_any_table_has_null_row(parsed):
    o = next(r for r in dicts(parsed, "fact_placement") if r["fact_id"] == "o1")
    assert o["row_index"] is None and o["cell_index"] is None and o["displayed_text"] == "7"


def test_nonnumeric_own_text_only_and_continuation_not_followed(parsed):
    p = {r["fact_id"]: r for r in dicts(parsed, "fact_placement")}
    assert p["t1"]["displayed_text"] == "Senior Secured"
    assert (p["t1"]["row_index"], p["t1"]["cell_index"]) == (2, 0)


def test_fact_inside_fact_is_its_own_placement(parsed):
    p = {r["fact_id"]: r for r in dicts(parsed, "fact_placement")}
    assert p["blk"]["displayed_text"] == "Block 9 end 2"
    assert p["n4"]["displayed_text"] == "9"
    assert (p["blk"]["row_index"], p["blk"]["cell_index"]) == (4, 0) == (p["n4"]["row_index"], p["n4"]["cell_index"])


def test_footnotes(parsed):
    fn = {r["footnote_id"]: r for r in dicts(parsed, "footnote")}
    assert set(fn) == {"fn1", "fn2"}
    assert fn["fn1"]["text"] == "Footnote one text." and fn["fn1"]["text_length"] == 18
    assert fn["fn1"]["text_sha256"] == hashlib.sha256(b"Footnote one text.").hexdigest()
    assert fn["fn2"]["text"] == "Second note."


def test_fact_footnote_keeps_only_fact_footnote_arcs(parsed):
    pairs = sorted((r["fact_id"], r["footnote_id"]) for r in dicts(parsed, "fact_footnote"))
    assert pairs == [("n1", "fn1"), ("n2", "fn1"), ("t1", "fn2")]


def test_rows_match_store_column_order(parsed):
    for name in ("document_row", "fact_placement", "footnote", "fact_footnote"):
        for r in parsed[name]:
            assert len(r) == len(store.TABLES[name])


def test_duplicate_fact_id_fails_the_filing(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8").replace('id="n2"', 'id="n1"')
    p = tmp_path / "dup.html"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(inline.InlineError) as e:
        inline.parse_inline(p, accession=ACC)
    assert "n1" in str(e.value)


def test_namespace_address_not_prefix(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8").replace("ix:", "zz:").replace("xmlns:ix=", "xmlns:zz=")
    p = tmp_path / "prefix.html"
    p.write_text(text, encoding="utf-8")
    other = inline.parse_inline(p, accession=ACC)
    base = inline.parse_inline(FIXTURE, accession=ACC)
    assert other["fact_placement"] == base["fact_placement"] and other["document_row"] == base["document_row"]
    assert other["fact_footnote"] == base["fact_footnote"]


def test_html_fallback_matches_case_insensitively(tmp_path):
    # &nbsp; is not defined in XML, so this document cannot be parsed as XML; tags are upper case
    text = (
        "<HTML><BODY><TABLE><TR><TD>Head&nbsp;ing</TD><TD></TD></TR>"
        '<TR><TD>A</TD><TD><IX:NONFRACTION ID="a1" NAME="us-gaap:Assets" CONTEXTREF="C1" UNITREF="USD" SCALE="3">1,0</IX:NONFRACTION></TD></TR>'
        "</TABLE>"
        '<IX:FOOTNOTE ID="f1">Note</IX:FOOTNOTE>'
        '<IX:RELATIONSHIP FROMREFS="a1" TOREFS="f1" ARCROLE="http://www.xbrl.org/2003/arcrole/fact-footnote"></IX:RELATIONSHIP>'
        "</BODY></HTML>")
    p = tmp_path / "fallback.html"
    p.write_text(text, encoding="utf-8")
    r = inline.parse_inline(p, accession=ACC)
    assert r["html_parser"] == "html"
    rows = dicts(r, "document_row")
    assert [x["cells"] for x in rows] == [["Head ing", ""], ["A", "1,0"]]
    (pl,) = dicts(r, "fact_placement")
    assert (pl["fact_id"], pl["ix_element"], pl["concept"], pl["context_id"], pl["row_index"], pl["cell_index"],
            pl["displayed_text"], pl["scale"]) == ("a1", "nonFraction", "us-gaap:Assets", "C1", 1, 1, "1,0", "3")
    assert [(x["fact_id"], x["footnote_id"]) for x in dicts(r, "fact_footnote")] == [("a1", "f1")]
    assert dicts(r, "footnote")[0]["text"] == "Note"


def test_cli_writes_inline_tables_and_manifest_records_parser(tmp_path):
    import json
    import shutil

    import duckdb

    from filed_parser import cli
    raw = tmp_path / "raw"
    (raw / "bdc_xbrl" / "1234567").mkdir(parents=True)
    (raw / "bdc_html" / "1234567").mkdir(parents=True)
    shutil.copy(Path(__file__).parent / "fixtures" / "mini_instance.xml", raw / "bdc_xbrl" / "1234567" / "000123456723000001.xml")
    shutil.copy(FIXTURE, raw / "bdc_html" / "1234567" / "000123456723000001.html")
    out = tmp_path / "data" / "filed"
    args = ["--cik", "1234567", "--raw", str(raw), "--out", str(out)]
    assert cli.main(args) == 0
    folder = out / "cik=0001234567" / f"accession={ACC}"
    m = json.loads((folder / "_manifest.json").read_text())
    assert m["html_parser"] == "xml" and m["tables"]["document_row"]["rows"] == 8
    assert m["tables"]["fact_placement"]["rows"] == 12 and m["stats"]["placements"] == 12
    assert m["stats"]["facts"] == 11  # instance stats are kept
    con = duckdb.connect()
    n = con.sql(
        f"select count(*) from read_parquet('{(folder / 'document_row.parquet').as_posix()}', hive_partitioning=false)").fetchone()[0]
    assert n == 8
    assert cli.main(args + ["--verify"]) == 0


def test_cell_spans_one_entry_per_cell_one_when_absent_or_not_positive(parsed):
    rows = {r["row_index"]: r for r in dicts(parsed, "document_row")}
    assert rows[1]["cell_colspans"] == [2, 1, 1, 1] and rows[1]["cell_rowspans"] == [3, 1, 1, 1]  # colspan="0" -> 1
    assert rows[6]["cell_colspans"] == [1, 1] and rows[6]["cell_rowspans"] == [1, 1]  # colspan="x" -> 1
    for r in rows.values():
        assert len(r["cell_colspans"]) == len(r["cell_rowspans"]) == len(r["cells"]) == r["cell_count"]
    assert all(type(v) is int for r in rows.values() for v in r["cell_colspans"] + r["cell_rowspans"])


def test_block_boundaries_separate_text_but_white_space_still_collapses(parsed):
    rows = {r["row_index"]: r["cells"] for r in dicts(parsed, "document_row")}
    assert rows[7] == ["Line one Line two", "Para one", "a b cFirst Lien Secured"]
    p = {r["fact_id"]: r for r in dicts(parsed, "fact_placement")}
    assert p["bk"]["displayed_text"] == "First Lien Secured"
    assert (p["bk"]["row_index"], p["bk"]["cell_index"]) == (7, 2)


def test_block_boundaries_in_footnote_text(tmp_path):
    text = (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>'
        '<ix:footnote id="f1">First<br/>second<p>third</p>fourth  <div>fifth</div></ix:footnote>'
        '<ix:footnote id="f2">no<b>break</b>here</ix:footnote></body></html>')
    p = tmp_path / "fn.html"
    p.write_text(text, encoding="utf-8")
    fn = {r["footnote_id"]: r for r in dicts(inline.parse_inline(p, accession=ACC), "footnote")}
    assert fn["f1"]["text"] == "First second third fourth fifth"
    assert fn["f2"]["text"] == "nobreakhere"


def test_hidden_link_gives_shown_row_and_cell(parsed):
    p = {r["fact_id"]: r for r in dicts(parsed, "fact_placement")}
    # h2: two elements point at it, both in row 1 cell 3; first in document order wins
    assert (p["h2"]["in_hidden"], p["h2"]["row_index"], p["h2"]["shown_row_index"], p["h2"]["shown_cell_index"]) == (
        True, None, 1, 3)
    # h3: the only element sits in a table that has no tagged fact; that table counts as kept
    assert (p["h3"]["shown_row_index"], p["h3"]["shown_cell_index"]) == (6, 1)
    # not linked, and ordinary facts: null
    assert (p["h1"]["shown_row_index"], p["h1"]["shown_cell_index"]) == (None, None)
    assert (p["n1"]["shown_row_index"], p["n1"]["shown_cell_index"]) == (None, None)


def test_hidden_link_id_must_match_exactly_and_outside_tables_gives_null(tmp_path):
    text = (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>'
        '<ix:hidden><ix:nonNumeric id="h1" name="a:B" contextRef="C">x</ix:nonNumeric>'
        '<ix:nonNumeric id="h10" name="a:B" contextRef="C">y</ix:nonNumeric></ix:hidden>'
        '<table><tr><td style="-sec-ix-hidden:h10">z</td></tr></table>'
        '<p style="-sec-ix-hidden:h1">outside any table</p></body></html>')
    p = tmp_path / "hid.html"
    p.write_text(text, encoding="utf-8")
    pl = {r["fact_id"]: r for r in dicts(inline.parse_inline(p, accession=ACC), "fact_placement")}
    assert (pl["h10"]["shown_row_index"], pl["h10"]["shown_cell_index"]) == (0, 0)  # the td itself is the cell
    assert (pl["h1"]["shown_row_index"], pl["h1"]["shown_cell_index"]) == (None, None)
