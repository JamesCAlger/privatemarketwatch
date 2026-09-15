"""E4 must not call a replay pass or an ambiguous source value accurate."""
from decimal import Decimal

import duckdb
import pytest

from pipeline.field_assessment import (comparison_sql, field_for, precision_bound,
                                        read_field_document, source_meaning)


def instance(tmp_path, facts, extra=""):
    path = tmp_path / "instance.xml"
    path.write_text('''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso="http://www.xbrl.org/2003/iso4217" xmlns:g="http://fasb.org/us-gaap/2025"
      xmlns:fake="https://example.test/not-a-currency" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
      <xbrli:context id="position"><xbrli:entity><xbrli:identifier scheme="sec">123</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:instant>2026-03-31</xbrli:instant></xbrli:period></xbrli:context>
      <xbrli:context id="comparative"><xbrli:entity><xbrli:identifier scheme="sec">123</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
      <xbrli:unit id="usd"><xbrli:measure>iso:USD</xbrli:measure></xbrli:unit>
      <xbrli:unit id="fake"><xbrli:measure>fake:USD</xbrli:measure></xbrli:unit>
      <xbrli:unit id="pure"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
      <xbrli:unit id="shares"><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unit>
      ''' + extra + facts + "</xbrli:xbrl>", encoding="utf-8")
    return path


def fact(concept="InvestmentOwnedAtFairValue", value="1000", *, unit="usd", decimals="-3", context="position"):
    return (f'<g:{concept} contextRef="{context}" unitRef="{unit}" decimals="{decimals}" id="anchor">'
            f'{value}</g:{concept}>')


def test_reader_keeps_raw_scale_source_precision_and_comparative_period(tmp_path):
    result = read_field_document(instance(tmp_path, fact() + fact(value="-15", context="comparative", decimals="0")), "0000000123")
    assert result["complete"]
    current, comparative = result["facts"]
    assert (current["raw"], current["rounding_bound"], current["currency"]) == ("1000", "5E+2", "USD")
    assert comparative["raw"] == "-15"
    assert comparative["quarter"] == "2025-12-31"
    assert comparative["fact_id"] == "anchor"


def test_unknown_namespace_cannot_masquerade_as_usd(tmp_path):
    result = read_field_document(instance(tmp_path, fact(unit="fake")), "0000000123")
    assert result["facts"][0]["reason"] == "unresolved_monetary_unit"


@pytest.mark.parametrize("value,expected", [("INF","0"),("2","0.005"),(None,None),("bad",None),("12",None)])
def test_precision_is_disclosed_not_a_configurable_tolerance(value, expected):
    assert precision_bound(value) == expected


def test_rate_floor_is_not_interest_and_generic_rate_does_not_establish_cash_kind():
    assert field_for("InvestmentInterestRateFloor") is None
    assert field_for("InvestmentInterestRatePaidInKind") == "pik_rate"
    assert source_meaning("interest_rate", "InvestmentInterestRate", "pure", ".1")[0] == "unresolved_cash_or_all_in_kind"
    assert source_meaning("interest_rate", "InvestmentInterestRatePaidInCash", "pure", ".1") == ("ready", 100)
    assert source_meaning("basis_spread", "InvestmentBasisSpreadVariableRate", "pure", "5")[0] == "ambiguous_rate_scale"


def test_rate_and_share_unit_kinds_are_not_interchangeable(tmp_path):
    result = read_field_document(instance(tmp_path,
        fact("InvestmentInterestRatePaidInKind", ".02", unit="pure", decimals="4") +
        fact("InvestmentOwnedBalanceShares", "15", unit="pure", decimals="0")), "0000000123")
    assert result["facts"][0]["multiplier"] == 100
    assert result["facts"][0]["reason"] == "ready"
    assert result["facts"][1]["reason"] == "unresolved_share_unit"


def test_entity_mismatch_and_missing_context_do_not_become_valid_evidence(tmp_path):
    path = instance(tmp_path, fact() + fact(context="absent"))
    result = read_field_document(path, "0000000456")
    assert not result["complete"]
    assert result["facts"][0]["reason"] == "reporting_entity_mismatch"
    assert "missing context" in result["errors"][0]


def test_dtd_is_rejected_without_entity_expansion(tmp_path):
    path = tmp_path / "dtd.xml"
    path.write_text('<!DOCTYPE xbrl [<!ENTITY custom "99">]><xbrl/>')
    result = read_field_document(path, "0000000123")
    assert not result["complete"]
    assert "DTD" in result["errors"][0]


def compare(**changes):
    source = dict(cik="123", quarter="2026-03-31", accession="a", context_id="p", field="fair_value",
        source_complete=True, fact_count=1, variants=1, reason="ready", source_role="confirmed_position",
        correspondence_status="ready", reference_value=Decimal("1000"), precision_bound=Decimal(".5"), currency="USD")
    published = dict(cik="123",quarter="2026-03-31",accession="a",context_id="p",field="fair_value",
        candidate_rows=1,published=Decimal("1000"),published_currency="USD")
    for key, value in changes.items():
        (published if key in ("candidate_rows", "published", "published_currency") else source)[key] = value
    with duckdb.connect() as con:
        for name, row in (("source_fields", source),("published",published)):
            con.execute("CREATE TABLE " + name + " AS SELECT " + ",".join("? AS " + k for k in row), list(row.values()))
        return con.execute(comparison_sql()).fetchall()[0][-2:]


@pytest.mark.parametrize("value,category", [("1000.5","correct"),("1000.500001","incorrect"),("999.5","correct"),("998","incorrect")])
def test_comparison_uses_only_source_precision(value, category):
    assert compare(published=Decimal(value))[0] == category


@pytest.mark.parametrize("changes,category,reason", [
    ({"published_currency":"EUR"},"incorrect","wrong_currency"),
    ({"published_currency":""},"disclosed_unassessable","unresolved_candidate_currency"),
    ({"published":None},"missing_output","missing_value_or_row"),
    ({"candidate_rows":0},"missing_output","missing_value_or_row"),
    ({"candidate_rows":2},"disclosed_unassessable","ambiguous_candidate_context_join"),
    ({"variants":2},"disclosed_unassessable","conflicting_source_facts"),
    ({"source_complete":False},"disclosed_unassessable","incomplete_source"),
    ({"fact_count":0},"not_disclosed","no_numeric_tag_disclosed"),
    ({"source_role":"aggregate"},"disclosed_unassessable","unresolved_position_role"),
    ({"correspondence_status":"unresolved_source_candidate_correspondence"},"disclosed_unassessable","unresolved_source_candidate_correspondence"),
])
def test_missingness_and_ambiguity_are_not_trivial_passes(changes, category, reason):
    assert compare(**changes) == (category, reason)


def test_exact_zero_negative_and_no_rounding_cases():
    assert compare(reference_value=Decimal("0"), published=Decimal("0"), precision_bound=Decimal("0"))[0] == "correct"
    assert compare(reference_value=Decimal("-1"), published=Decimal("-1"), precision_bound=Decimal("0"))[0] == "correct"
    assert compare(published=Decimal("1000.000001"), precision_bound=Decimal("0"))[0] == "incorrect"


def test_all_in_reference_uses_same_context_disclosed_pik_and_source_precision():
    from scripts.run_field_assessment import normalize_coupon_references
    with duckdb.connect() as con:
        con.execute("""CREATE TABLE fact_groups AS SELECT '123' AS cik,'a' AS accession,'2026-03-31' AS quarter,
          * FROM (VALUES
          ('cash','interest_rate',1,1,10.0,0.01,'ready'),('cash','pik_rate',1,1,2.0,0.02,'ready'),
          ('zero','interest_rate',1,1,10.0,0.01,'ready'),('zero','pik_rate',1,1,0.0,0.0,'ready'),
          ('absent','interest_rate',1,1,10.0,0.01,'ready'),
          ('ambiguous','interest_rate',1,1,10.0,0.01,'ready'),('ambiguous','pik_rate',2,2,2.0,0.02,'ready'),
          ('generic','interest_rate',1,1,10.0,0.01,'unresolved_cash_or_all_in_kind'),
          ('generic','pik_rate',1,1,2.0,0.02,'ready'))
          t(context_id,field,fact_count,variants,reference_value,precision_bound,reason)""")
        normalize_coupon_references(con)
        values={r[0]:r[1:] for r in con.execute("SELECT context_id,reference_value,precision_bound,reason FROM fact_groups WHERE field='interest_rate'").fetchall()}
        assert values['cash']==(Decimal('12'),Decimal('.03'),'ready')
        assert values['zero']==(Decimal('10'),Decimal('.01'),'ready')
        assert values['absent'][2]==values['ambiguous'][2]=='unresolved_pik_for_all_in_reference'
        assert values['generic'][2]=='unresolved_cash_or_all_in_kind'


def test_complete_e4_sql_joins_replay_source_and_exports_without_losing_rows(tmp_path, monkeypatch):
    from scripts import run_field_assessment as e4
    source = tmp_path / "source_facts.csv"
    source.write_text("cik,accession,quarter,context_id,field,raw,rounding_bound,multiplier,currency,unit_kind,reason,nil\n"
        "0000000123,a,2026-03-31,p,fair_value,1000,0.5,1,USD,monetary,ready,false\n"
        "0000000123,a,2026-03-31,p,cost,990,0.5,1,USD,monetary,ready,false\n"
        "0000000456,b,2026-03-31,missing,fair_value,-5,0,1,USD,monetary,ready,false\n")
    reconciliation = tmp_path / "reconciliation.csv"
    reconciliation.write_text("cik,period,accession_number,context_id,output_row_id\n"
                             "123,2026-03-31,a,p,row1\n123,2026-03-31,a,p,row1\n")
    monkeypatch.setattr(e4, "RECONCILIATION", reconciliation)
    with duckdb.connect() as con:
        values = dict(cik="123",report_date="2026-03-31",accession_number="a",src_context_id="p",row_id="row1",
                      fair_value=1000,cost=980,principal_amount=1100,shares_held=None,interest_rate=None,
                      pik_rate=None,basis_spread=None,pct_of_net_assets=None,fair_value_currency="USD",
                      cost_currency="USD",principal_amount_currency="USD")
        con.execute("CREATE TABLE candidate AS SELECT " + ",".join("? AS " + k for k in values), list(values.values()))
        con.execute("""CREATE TABLE contexts AS SELECT * FROM (VALUES
          ('0000000123','2026-03-31','a','p','confirmed_position',1000,'USD'),
          ('0000000456','2026-03-31','b','missing','confirmed_position',-5,'USD'))
          t(cik,quarter,accession,context_id,source_role,source_fv,currency)""")
        con.execute("CREATE TABLE sources AS SELECT DISTINCT cik,quarter,accession,true AS source_complete FROM contexts")
        con.execute("CREATE TABLE obligations AS SELECT DISTINCT cik FROM contexts")
        con.execute("CREATE TABLE document_status AS SELECT DISTINCT cik,accession,true AS complete FROM contexts")
        class PlannedConnection:
            def execute(self, query):
                plan = con.execute("EXPLAIN " + query).fetchone()[1]
                # On the full cohort a filtered ANTI JOIN predicate became
                # quadratic. Keep role filtering before the equality join.
                assert "BLOCKWISE_NL_JOIN" not in plan
                return con.execute(query)
        e4.assemble_reference(PlannedConnection())
        e4.assemble_comparisons(con, tmp_path)
        e4.export_summaries(con, tmp_path)
        assert con.execute("SELECT count(*) FROM assessments").fetchone()[0] == 16
        assert con.execute("SELECT category FROM assessments WHERE cik='0000000456' AND field='fair_value'").fetchone()[0] == "missing_output"
        assert con.execute("SELECT category FROM assessments WHERE cik='0000000123' AND field='cost'").fetchone()[0] == "incorrect"
        # Duplicate reconciliation results must not duplicate a candidate row.
        assert con.execute("SELECT candidate_rows,category FROM assessments WHERE cik='0000000123' AND field='fair_value'").fetchone() == (1,"correct")
        assert con.execute("SELECT sum(absolute_source_context_fv) FROM read_csv(?) WHERE category='missing_output'", [str(tmp_path / "categories.csv")]).fetchone()[0] == 5
        assert (tmp_path / "assessability.csv").exists()
        assert (tmp_path / "assessments.parquet").exists()
