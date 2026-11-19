import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from filed_parser import instance, store

FIXTURE = Path(__file__).parent / "fixtures" / "mini_instance.xml"
ACC = "0001234567-23-000001"


def as_dicts(tables, name):
    cols = [c for c, _ in store.TABLES[name]]
    return [dict(zip(cols, row)) for row in tables[name]]


@pytest.fixture(scope="module")
def parsed():
    return instance.parse_instance(FIXTURE, accession=ACC)


def test_filing_dei(parsed):
    (row,) = parsed["filing_dei"]
    assert row == ("10-Q", date(2023, 3, 31), False, None, None, "Mini Fund Inc.", False)


def test_dei_conflict_and_first_in_document_order(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8").replace(
        "</xbrl>",
        '<dei:DocumentType contextRef="C_dur" id="f_doctype2">10-K</dei:DocumentType></xbrl>',
    )
    p = tmp_path / "conflict.xml"
    p.write_text(text, encoding="utf-8")
    (row,) = instance.parse_instance(p, accession=ACC)["filing_dei"]
    assert row[0] == "10-Q" and row[-1] is True


def test_dei_ignores_facts_on_member_contexts(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8").replace(
        "</xbrl>",
        '<dei:DocumentType contextRef="C_pos" id="f_doctype2">N-CSR</dei:DocumentType></xbrl>',
    )
    p = tmp_path / "member.xml"
    p.write_text(text, encoding="utf-8")
    (row,) = instance.parse_instance(p, accession=ACC)["filing_dei"]
    assert row[0] == "10-Q" and row[-1] is False


def test_context_columns(parsed):
    ctx = {r["context_id"]: r for r in as_dicts(parsed, "context")}
    assert set(ctx) == {"C_inst", "C_dur", "C_pos", "C_scn"}
    c = ctx["C_inst"]
    assert (c["accession"], c["entity_scheme"], c["entity_identifier"]) == (
        ACC, "http://www.sec.gov/CIK", "0001234567")
    assert (c["period_type"], c["instant_date"], c["start_date"], c["end_date"], c["member_count"]) == (
        "instant", date(2023, 3, 31), None, None, 0)
    d = ctx["C_dur"]
    assert (d["period_type"], d["instant_date"], d["start_date"], d["end_date"]) == (
        "duration", None, date(2023, 1, 1), date(2023, 3, 31))
    assert ctx["C_scn"]["period_type"] == "forever"
    assert ctx["C_scn"]["member_count"] == 1
    assert ctx["C_pos"]["member_count"] == 2


def test_context_member_columns(parsed):
    mem = {(r["context_id"], r["axis"]): r for r in as_dicts(parsed, "context_member")}
    assert set(mem) == {
        ("C_pos", "us-gaap:StatementClassOfStockAxis"),
        ("C_pos", "custom:InvestmentIdentifierAxis"),
        ("C_scn", "custom:ScenarioAxis"),
    }
    e = mem[("C_pos", "us-gaap:StatementClassOfStockAxis")]
    assert (e["member_index"], e["member_kind"], e["member"], e["typed_element"], e["container"]) == (
        0, "explicit", "custom:CommonMember", None, "segment")
    t = mem[("C_pos", "custom:InvestmentIdentifierAxis")]
    assert t["member_index"] == 1 and t["member_kind"] == "typed"
    assert t["typed_element"] == "custom:InvestmentIdentifierAxis.domain"
    s = mem[("C_scn", "custom:ScenarioAxis")]
    assert (s["member_index"], s["container"], s["member"]) == (0, "scenario", "custom:BaseMember")


def test_typed_member_stored_exactly_as_filed(parsed):
    mem = {(r["context_id"], r["axis"]): r for r in as_dicts(parsed, "context_member")}
    assert mem[("C_pos", "custom:InvestmentIdentifierAxis")]["member"] == (
        "  Acme   Corp\n        Term    Loan  \n Maturity 1/1/2029 ")


def test_typed_members_differing_only_in_white_space_stay_distinct(tmp_path):
    head = (
        '<?xml version="1.0"?><xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
        'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:c="http://example.com/c">')

    def ctx(i, member):
        return (
            f'<xbrli:context id="{i}"><xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>'
            f'<xbrli:segment><xbrldi:typedMember dimension="us-gaap-supplement:InvestmentIdentifierAxis">'
            f'<c:d>{member}</c:d></xbrldi:typedMember><xbrldi:explicitMember dimension="c:Ax"> c:M </xbrldi:explicitMember>'
            f'</xbrli:segment></xbrli:entity><xbrli:period><xbrli:instant>2022-09-30</xbrli:instant>'
            f'</xbrli:period></xbrli:context>')
    text = head + ctx("a", "Apex LLC 1") + ctx("b", "Apex LLC  1") + ctx("c", "Apex LLC 1") \
        + ctx("d", " Apex LLC 1") + "</xbrli:xbrl>"
    p = tmp_path / "typed.xml"
    p.write_text(text, encoding="utf-8")
    rows = as_dicts(instance.parse_instance(p, accession=ACC), "context_member")
    got = {r["context_id"]: r["member"] for r in rows if r["member_kind"] == "typed"}
    assert got == {"a": "Apex LLC 1", "b": "Apex LLC  1", "c": "Apex LLC 1", "d": " Apex LLC 1"}
    assert len(set(got.values())) == 4
    assert {r["member"] for r in rows if r["member_kind"] == "explicit"} == {"c:M"}  # explicit members unchanged


def test_unit_columns(parsed):
    units = {r["unit_id"]: r for r in as_dicts(parsed, "unit")}
    assert (units["U_USD"]["numerator"], units["U_USD"]["denominator"]) == ("iso4217:USD", None)
    assert (units["U_USDshare"]["numerator"], units["U_USDshare"]["denominator"]) == (
        "iso4217:USD", "custom:share")


def facts(parsed):
    return {r["fact_id"]: r for r in as_dicts(parsed, "tagged_fact")}


def test_all_facts_and_no_linkbase_elements(parsed):
    assert len(parsed["tagged_fact"]) == 11


def test_numeric_fact_columns(parsed):
    f = facts(parsed)["f_fv"]
    assert f["accession"] == ACC
    assert f["fact_index"] == 5 and f["id_is_synthetic"] is False
    assert f["concept"] == "us-gaap:InvestmentOwnedAtFairValue"
    assert f["concept_namespace"] == "http://fasb.org/us-gaap/2023"
    assert f["concept_local"] == "InvestmentOwnedAtFairValue"
    assert (f["context_id"], f["unit_id"]) == ("C_pos", "U_USD")
    assert f["value_text"] == "1234000"
    assert f["value_numeric"] == Decimal("1234000")
    assert (f["decimals"], f["precision"]) == ("-3", None)
    assert f["is_nil"] is False
    assert f["value_length"] == 7
    assert f["value_sha256"] == hashlib.sha256(b"1234000").hexdigest()
    assert f["value_truncated"] is False


def test_value_trimmed_and_ratio_unit(parsed):
    f = facts(parsed)["f_nav"]
    assert f["value_text"] == "25.37" and f["value_numeric"] == Decimal("25.37")
    assert f["unit_id"] == "U_USDshare"


def test_missing_id_gets_synthetic(parsed):
    f = facts(parsed)["noid:6"]
    assert f["id_is_synthetic"] is True and f["fact_index"] == 6
    assert f["concept"] == "us-gaap:Assets"
    assert f["decimals"] == "INF" and f["value_numeric"] == Decimal("5.5")


def test_nil_fact(parsed):
    f = facts(parsed)["f_nil"]
    assert f["is_nil"] is True and f["value_numeric"] is None and f["value_text"] is None
    assert f["value_length"] == 0


def test_text_without_unit_has_no_numeric(parsed):
    f = facts(parsed)["f_cik"]
    assert f["unit_id"] is None
    assert f["value_text"] == "0001234567" and f["value_numeric"] is None


def test_long_text_truncated_with_length_and_hash(parsed):
    full = "ABCDEFGHIJ" * 500
    f = facts(parsed)["f_long"]
    assert f["value_text"] == full[:4000]
    assert f["value_truncated"] is True
    assert f["value_length"] == 5000
    assert f["value_sha256"] == hashlib.sha256(full.encode("utf-8")).hexdigest()
    assert f["value_numeric"] is None


def test_number_too_large_is_null_numeric_with_text_kept(parsed):
    f = facts(parsed)["f_big"]
    assert f["value_numeric"] is None
    assert f["value_text"] == "123456789012345678901234567890"
    assert f["value_truncated"] is False
    stats = dict(parsed["stats"])
    assert stats["numeric_not_fit"] == 1
    assert stats["synthetic_ids"] == 1


def test_negative_zero_has_no_sign_in_numeric_but_text_keeps_it(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8").replace(">  25.37  <", ">-0<")
    p = tmp_path / "z.xml"
    p.write_text(text, encoding="utf-8")
    f = {r["fact_id"]: r for r in as_dicts(instance.parse_instance(p, accession=ACC), "tagged_fact")}
    assert repr(f["f_nav"]["value_numeric"]) == repr(Decimal("0").quantize(Decimal("1e-10")))
    assert f["f_nav"]["value_text"] == "-0"


def test_numeric_with_text_that_is_not_a_number(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8").replace(">  25.37  <", ">n/a<")
    p = tmp_path / "x.xml"
    p.write_text(text, encoding="utf-8")
    f = {r["fact_id"]: r for r in as_dicts(instance.parse_instance(p, accession=ACC), "tagged_fact")}
    assert f["f_nav"]["value_numeric"] is None and f["f_nav"]["value_text"] == "n/a"


def test_accession_derived_from_file_name(tmp_path):
    p = tmp_path / "000123456723000001.xml"
    p.write_bytes(FIXTURE.read_bytes())
    t = instance.parse_instance(p)
    assert t["context"][0][0] == "0001234567-23-000001"


def _variant(tmp_path, insert):
    text = FIXTURE.read_text(encoding="utf-8").replace("</xbrl>", insert + "</xbrl>")
    p = tmp_path / "variant.xml"
    p.write_text(text, encoding="utf-8")
    return p


def test_f1_root_child_without_context_ref_fails(tmp_path):
    p = _variant(tmp_path, '<custom:Stray id="s1">5</custom:Stray>')
    with pytest.raises(instance.InstanceError) as e:
        instance.parse_instance(p, accession=ACC)
    assert "custom:Stray" in str(e.value)


def test_f1_nested_element_with_context_ref_fails(tmp_path):
    p = _variant(tmp_path, '<custom:Wrap><custom:Inner contextRef="C_inst" id="n1">5</custom:Inner></custom:Wrap>'
                           )
    with pytest.raises(instance.InstanceError) as e:
        instance.parse_instance(p, accession=ACC)
    assert "custom:Inner" in str(e.value)


def test_f1_message_names_at_most_five(tmp_path):
    p = _variant(tmp_path, "".join(f'<custom:Stray{i}>1</custom:Stray{i}>' for i in range(8)))
    with pytest.raises(instance.InstanceError) as e:
        instance.parse_instance(p, accession=ACC)
    assert str(e.value).count("custom:Stray") == 5


def test_f1_clean_fixture_still_parses(tmp_path):
    assert instance.parse_instance(FIXTURE, accession=ACC)["tagged_fact"]
