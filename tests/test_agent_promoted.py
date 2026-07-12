"""Tests for pipeline.agent_promoted -- production consumers for promoted agent fixes
(gap 1): anchor overrides (Layer D), raw-staging corrections (Layer B), investigator
rules + application audit (Layer C)."""

from __future__ import annotations

import json
from unittest.mock import patch

import duckdb
import pandas as pd
import pytest

from pipeline import agent_promoted as ap


# --------------------------------------------------------------------------- helpers

def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _valid_rule(cik="123", rule_id="r1", predicate="issuer_name = 'Bad Row'",
                rule_type="row_exclusion", action="exclude", **extra):
    rule = {
        "cik": cik, "rule_id": rule_id, "rule_type": rule_type, "action": action,
        "predicate_sql": predicate, "scope": {"quarters": ["all"]},
        "evidence": [{"source": "filing", "quote": "test"}],
        "rationale": "test rule", "confidence": 0.9,
    }
    rule.update(extra)
    return rule


def _holdings_frame():
    return pd.DataFrame([
        {"cik": "0000000123", "source": "bdc", "report_date": "2025-06-30",
         "issuer_name": "Bad Row", "entity_name": "Fund A", "fair_value": 100.0,
         "bdc_dimensions_raw": "x=y"},
        {"cik": "0000000123", "source": "bdc", "report_date": "2025-06-30",
         "issuer_name": "Good Row", "entity_name": "Fund A", "fair_value": 200.0,
         "bdc_dimensions_raw": "x=y"},
        # Same CIK but N-PORT source: a promoted BDC rule must never touch it.
        {"cik": "0000000123", "source": "nport", "report_date": "2025-06-30",
         "issuer_name": "Bad Row", "entity_name": "Fund A", "fair_value": 300.0,
         "bdc_dimensions_raw": None},
        # Same issuer, different CIK: out of scope by construction.
        {"cik": "0000000456", "source": "bdc", "report_date": "2025-06-30",
         "issuer_name": "Bad Row", "entity_name": "Fund B", "fair_value": 400.0,
         "bdc_dimensions_raw": "x=y"},
    ])


# --------------------------------------------------------------------------- cik + anchors

def test_normalize_cik10():
    assert ap.normalize_cik10("1715933") == "0001715933"
    assert ap.normalize_cik10(1715933) == "0001715933"
    assert ap.normalize_cik10("0001715933") == "0001715933"
    assert ap.normalize_cik10(" CIK-123 ") == "0000000123"
    assert ap.normalize_cik10(None) == ""
    assert ap.normalize_cik10("") == ""


def test_load_anchor_overrides_reads_and_pads(tmp_path):
    _write_json(tmp_path / "1715933" / "2025-06-30.json",
                {"cik": "1715933", "target_quarter": "2025-06-30",
                 "grand_total": 1093518278.0, "method": "total_row"})
    out = ap.load_anchor_overrides(tmp_path)
    assert out == [{"cik": "0001715933", "report_date": "2025-06-30",
                    "anchor_value": 1093518278.0}]


def test_load_anchor_overrides_skips_malformed(tmp_path):
    _write_json(tmp_path / "111" / "2025-06-30.json", {"cik": "111"})  # no grand_total
    bad = tmp_path / "222" / "2025-09-30.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not json", encoding="utf-8")
    _write_json(tmp_path / "333" / "2025-12-31.json",
                {"cik": "333", "target_quarter": "2025-12-31", "grand_total": 5.0})
    out = ap.load_anchor_overrides(tmp_path)
    assert [o["cik"] for o in out] == ["0000000333"]


def test_load_anchor_overrides_missing_dir(tmp_path):
    assert ap.load_anchor_overrides(tmp_path / "nope") == []


# --------------------------------------------------------------------------- Layer B

def test_raw_staging_exclusions_filters_and_dedups():
    corrections = [
        {"cik": "1715933", "fix_class": "comparative_period_filter",
         "template": {"report_date": "2025-06-30"}},
        {"cik": "0001715933", "fix_class": "comparative_period_filter",
         "template": {"report_date": "2025-06-30"}},               # dup after cik pad
        {"cik": "1603480", "fix_class": "comparative_period_filter",
         "template": {"report_date": "2025-06-30"}},
        {"cik": "999", "fix_class": "subtotal_filter",
         "template": {"patterns": ["total x"]}},                    # not raw-staging
        {"cik": "888", "fix_class": "comparative_period_filter",
         "template": {}},                                           # no report_date
    ]
    out = ap.raw_staging_exclusions(corrections)
    assert out == [{"cik": "0001603480", "report_date": "2025-06-30"},
                   {"cik": "0001715933", "report_date": "2025-06-30"}]


def _bdc_raw_con():
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE bdc_raw AS SELECT * FROM (VALUES
            ('1715933', '2025-06-30', '2025-06-30', 100.0),
            ('1715933', '2025-06-30', '2025-03-31', 200.0),
            ('1715933', '2025-06-30', NULL,         300.0),
            ('1715933', '2025-03-31', NULL,         400.0),
            ('456',     '2025-06-30', NULL,         500.0)
        ) AS t(cik, report_date, period, fair_value)
    """)
    return con


def test_apply_raw_staging_exclusions_scoped_delete():
    con = _bdc_raw_con()
    audits = ap.apply_raw_staging_exclusions(
        con, [{"cik": "0001715933", "report_date": "2025-06-30"}])
    remaining = con.execute(
        "SELECT cik, report_date, fair_value FROM bdc_raw ORDER BY fair_value").fetchall()
    # Dropped: the 2025-03-31-period comparative AND the NULL-period leak (200, 300).
    # Kept: the current-period row, the other quarter, the other CIK.
    assert remaining == [("1715933", "2025-06-30", 100.0),
                         ("1715933", "2025-03-31", 400.0),
                         ("456", "2025-06-30", 500.0)]
    assert len(audits) == 1
    a = audits[0]
    assert a["status"] == "ok" and a["rows_changed"] == 2 and a["fv_affected"] == 500.0
    assert a["layer"] == "raw_bdc_staging" and a["drift"] == ""


def test_apply_raw_staging_exclusions_noop_flagged():
    con = _bdc_raw_con()
    audits = ap.apply_raw_staging_exclusions(
        con, [{"cik": "0000000999", "report_date": "2025-06-30"}])
    assert audits[0]["rows_changed"] == 0
    assert audits[0]["drift"] == "noop"
    assert con.execute("SELECT COUNT(*) FROM bdc_raw").fetchone()[0] == 5


def test_apply_raw_staging_exclusions_missing_period_column():
    con = duckdb.connect()
    con.execute("CREATE TABLE bdc_raw AS SELECT '1' AS cik, '2025-06-30' AS report_date, 1.0 AS fair_value")
    audits = ap.apply_raw_staging_exclusions(
        con, [{"cik": "0000000001", "report_date": "2025-06-30"}])
    assert audits[0]["status"] == "error"
    assert con.execute("SELECT COUNT(*) FROM bdc_raw").fetchone()[0] == 1


# --------------------------------------------------------------------------- Layer C loaders

def test_load_promoted_rules_structure(tmp_path):
    _write_json(tmp_path / "1715933" / "b_second.json", _valid_rule(cik="1715933", rule_id="b"))
    _write_json(tmp_path / "1715933" / "a_first.json", _valid_rule(cik="1715933", rule_id="a"))
    _write_json(tmp_path / "456" / "c.json", _valid_rule(cik="456", rule_id="c"))
    bad = tmp_path / "789" / "bad.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{oops", encoding="utf-8")
    out = ap.load_promoted_rules(tmp_path)
    assert set(out) == {"0001715933", "0000000456"}
    # sorted-filename order within a CIK (gate-time application order parity)
    assert [r["rule_id"] for r in out["0001715933"]] == ["a", "b"]


def test_load_promoted_rules_missing_dir(tmp_path):
    assert ap.load_promoted_rules(tmp_path / "nope") == {}


# --------------------------------------------------------------------------- Layer C apply

def test_apply_promoted_rules_scoped_to_cik_and_bdc_source():
    df = _holdings_frame()
    out, audits = ap.apply_promoted_rules(df, {"0000000123": [_valid_rule()]})
    # Only the (cik=123, source=bdc, Bad Row) row is dropped.
    assert len(out) == 3
    assert not ((out["cik"] == "0000000123") & (out["source"] == "bdc")
                & (out["issuer_name"] == "Bad Row")).any()
    assert ((out["cik"] == "0000000123") & (out["source"] == "nport")).sum() == 1
    assert (out["cik"] == "0000000456").sum() == 1
    assert list(out.columns) == list(df.columns)
    assert len(audits) == 1
    assert audits[0]["rows_changed"] == 1 and audits[0]["status"] == "ok"
    assert audits[0]["drift"] == ""  # no measured_impact -> only noop can flag


def test_apply_promoted_rules_no_rows_for_cik():
    df = _holdings_frame()
    out, audits = ap.apply_promoted_rules(df, {"0000000999": [_valid_rule(cik="999")]})
    assert len(out) == len(df)
    assert audits[0]["status"] == "no_rows" and audits[0]["drift"] == "noop"


def test_apply_promoted_rules_noop_rule_flagged():
    df = _holdings_frame()
    rule = _valid_rule(predicate="issuer_name = 'Nonexistent'")
    out, audits = ap.apply_promoted_rules(df, {"0000000123": [rule]})
    assert len(out) == len(df)
    assert audits[0]["rows_changed"] == 0 and audits[0]["drift"] == "noop"


def test_apply_promoted_rules_row_drift():
    rows = [{"cik": "0000000123", "source": "bdc", "report_date": "2025-06-30",
             "issuer_name": f"Bad Row", "entity_name": "Fund A", "fair_value": 10.0,
             "bdc_dimensions_raw": "x=y"} for _ in range(15)]
    df = pd.DataFrame(rows)
    rule = _valid_rule(measured_impact={"2025-06-30": {"rows": 1, "fv": 10.0}})
    out, audits = ap.apply_promoted_rules(df, {"0000000123": [rule]})
    assert len(out) == 0
    assert audits[0]["rows_changed"] == 15
    assert audits[0]["authoring_rows"] == 1
    assert audits[0]["drift"] == "row_drift"


def test_apply_promoted_rules_row_add_fills_identity():
    df = _holdings_frame()
    rule = _valid_rule(
        rule_type="row_add", action="add", predicate=None,
        positions=[{"report_date": "2025-06-30", "issuer_name": "Recovered Co",
                    "fair_value": 999.0, "bdc_dimensions_raw": "axis=Recovered",
                    "source_row_id": "accession 0001 table 2 row 9"}])
    del rule["predicate_sql"]
    out, audits = ap.apply_promoted_rules(df, {"0000000123": [rule]})
    added = out[out["issuer_name"] == "Recovered Co"]
    assert len(added) == 1
    assert added.iloc[0]["cik"] == "0000000123"
    assert added.iloc[0]["source"] == "bdc"
    assert added.iloc[0]["entity_name"] == "Fund A"
    assert audits[0]["rows_changed"] == 1


def test_apply_promoted_rules_invalid_rule_audited_not_applied():
    df = _holdings_frame()
    rule = _valid_rule()
    del rule["evidence"]
    out, audits = ap.apply_promoted_rules(df, {"0000000123": [rule]})
    assert len(out) == len(df)
    assert audits[0]["status"] == "invalid"
    assert "evidence" in audits[0]["message"]


def test_apply_promoted_rules_empty_inputs():
    df = _holdings_frame()
    out, audits = ap.apply_promoted_rules(df, {})
    assert out is df and audits == []
    out2, audits2 = ap.apply_promoted_rules(pd.DataFrame(), {"0000000123": [_valid_rule()]})
    assert len(out2) == 0 and audits2 == []


# --------------------------------------------------------------------------- audit artifact

def test_write_application_audit(tmp_path):
    rows = [{"layer": "unified_agent_rules", "cik": "0000000123", "rule_id": "r1",
             "rule_type": "row_exclusion", "status": "ok", "rows_changed": 2,
             "fv_affected": 300.0, "authoring_rows": 2, "authoring_fv": 300.0,
             "drift": "", "message": ""}]
    path = tmp_path / "audit" / "agent_fix_application_audit.csv"
    ap.write_application_audit(rows, path)
    df = pd.read_csv(path)
    assert list(df.columns) == ap.AUDIT_COLUMNS
    assert len(df) == 1 and df.iloc[0]["rows_changed"] == 2


# --------------------------------------------------------------------------- Layer D

def test_fv_conservation_verified_override_is_top_priority():
    import scripts.shadow_conservation_engine as sce
    fv = next(r for r in sce.RULES if r.name == "fv_conservation")
    assert fv.anchors[0].kind == "verified_override"
    assert fv.anchors[0].label == "verified_override"


def test_engine_prefers_verified_override(monkeypatch, tmp_path):
    import scripts.shadow_conservation_engine as sce
    from pipeline import config as cfg

    anchor_dir = tmp_path / "agent_anchor"
    _write_json(anchor_dir / "1715933" / "2025-06-30.json",
                {"cik": "1715933", "target_quarter": "2025-06-30",
                 "grand_total": 1000.0})
    monkeypatch.setattr(cfg, "AGENT_ANCHOR_OVERRIDES_DIR", anchor_dir)

    con = duckdb.connect()
    con.execute("CREATE TABLE wrapped(cik VARCHAR)")
    con.executemany("INSERT INTO wrapped VALUES (?)",
                    [("0001715933",), ("0000000456",)])
    # unified holdings stand-in: sums match the override for A, the schedule for B
    con.execute("""
        CREATE TABLE unified_tbl AS SELECT * FROM (VALUES
            ('0001715933', '2025-06-30', 1000.0, 'x=y', 'LOAN'),
            ('0000000456', '2025-06-30', 500.0,  'x=y', 'LOAN')
        ) AS t(cik, report_date, fair_value, bdc_dimensions_raw, asset_category)
    """)
    # raw bdc stand-in with printed schedule totals (the LOWER-priority anchor)
    con.execute("""
        CREATE TABLE bdc_tbl AS SELECT * FROM (VALUES
            ('0001715933', '2025-06-30', '2025-06-30', 'Total Investments', 700.0),
            ('0000000456', '2025-06-30', '2025-06-30', 'Total Investments', 500.0)
        ) AS t(cik, report_date, period, investment_identifier, fair_value)
    """)
    monkeypatch.setattr(sce, "_unified", lambda: "unified_tbl")
    monkeypatch.setattr(sce, "_bdc", lambda: "bdc_tbl")

    n = sce.ensure_anchor_overrides(con)
    assert n == 1

    rule = sce.ConservationRule(
        name="fv_test", value_column="fair_value",
        anchors=(sce.Anchor("verified_override", "verified_override", "grand_total"),
                 sce.Anchor("schedule_total", "schedule_total", "fair_value")))
    sce.run_rule(con, rule)
    rows = {r[0]: r for r in con.execute(
        "SELECT cik, anchor_value, anchor_used, status FROM result_fv_test").fetchall()}
    # CIK with an adjudicated grand total: override wins over the schedule total.
    assert rows["0001715933"][1:] == (1000.0, "verified_override", "reconciles")
    # CIK without an override falls through to the schedule total.
    assert rows["0000000456"][1:] == (500.0, "schedule_total", "reconciles")


# --------------------------------------------------------------------------- integration

@pytest.mark.integration
def test_build_unified_holdings_applies_promoted_fixes(tmp_path):
    """Layers B + C end-to-end through build_unified_holdings, with the audit artifact."""
    from pipeline.unified_holdings import build_unified_holdings

    bdc_df = pd.DataFrame([
        {
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Acme Corp - First Lien Term Loan",
            "fair_value": 1000000.0, "cost": 990000.0,
            "principal_amount": 1000000.0, "interest_rate": 8.5,
            "basis_spread": 3.5, "reference_rate_type": "SOFR",
            "maturity_date": "2028-01-15", "pct_of_net_assets": 0.05,
            "pik_rate": None, "shares_held": None,
            "unrealized_gain_loss": 10000.0, "dimensions_raw": "x=y",
            "investment_type": "", "industry": "", "affiliation": "",
            "period": "2023-03-31",
        },
        {
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Widget Inc - Second Lien Term Loan",
            "fair_value": 500000.0, "cost": 450000.0,
            "principal_amount": 500000.0, "interest_rate": 10.0,
            "basis_spread": 5.0, "reference_rate_type": "SOFR",
            "maturity_date": "2027-01-15", "pct_of_net_assets": 0.025,
            "pik_rate": None, "shares_held": None,
            "unrealized_gain_loss": 5000.0, "dimensions_raw": "x=y",
            "investment_type": "", "industry": "", "affiliation": "",
            "period": "2023-03-31",
        },
        # NULL-period comparative leak: staging's generic pre-filter keeps it;
        # the promoted Layer B correction drops it.
        {
            "cik": "123", "entity_name": "Test BDC",
            "accession_number": "0001-23", "form_type": "10-K",
            "filing_date": "2023-06-01", "report_date": "2023-03-31",
            "investment_identifier": "Stale Comparative Co - First Lien Term Loan",
            "fair_value": 777000.0, "cost": 777000.0,
            "principal_amount": 777000.0, "interest_rate": 9.0,
            "basis_spread": 4.0, "reference_rate_type": "SOFR",
            "maturity_date": "2026-01-15", "pct_of_net_assets": 0.03,
            "pik_rate": None, "shares_held": None,
            "unrealized_gain_loss": 0.0, "dimensions_raw": "x=y",
            "investment_type": "", "industry": "", "affiliation": "",
            "period": None,
        },
    ])

    corrections_dir = tmp_path / "b2_corrections"
    _write_json(corrections_dir / "0000000123" / "comparative_period_filter.json",
                {"cik": "0000000123", "fix_class": "comparative_period_filter",
                 "template": {"report_date": "2023-03-31"}})
    rules_dir = tmp_path / "agent_rules"
    _write_json(rules_dir / "123" / "exclude_widget.json",
                _valid_rule(cik="123", rule_id="exclude_widget",
                            predicate="issuer_name = 'Widget Inc'",
                            measured_impact={"2023-03-31": {"rows": 1, "fv": 500000.0}}))

    out_file = tmp_path / "unified.csv"
    # Patch UNIFIED_HOLDINGS_FILE so the universe gate resolves to tmp (and is
    # skipped) -- CIK 123 is a fixture, not a real universe member.
    with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE", out_file):
        result = build_unified_holdings(
            bdc_df=bdc_df, nport_df=pd.DataFrame(),
            output_file=out_file, orphan_file=tmp_path / "orphan.csv",
            agent_rules_dir=rules_dir, b2_corrections_dir=corrections_dir)

    names = set(result["issuer_name"])
    assert "Acme Corp" in names
    assert "Widget Inc" not in names                 # Layer C exclusion
    assert not any("Stale Comparative" in n for n in names)  # Layer B raw filter

    audit_path = tmp_path / "agent_fix_application_audit.csv"
    assert audit_path.exists()
    audit = pd.read_csv(audit_path)
    layers = set(audit["layer"])
    assert layers == {"raw_bdc_staging", "unified_agent_rules"}
    rule_row = audit[audit["rule_id"] == "exclude_widget"].iloc[0]
    assert rule_row["rows_changed"] == 1 and rule_row["status"] == "ok"
    raw_row = audit[audit["layer"] == "raw_bdc_staging"].iloc[0]
    assert raw_row["rows_changed"] == 1


@pytest.mark.integration
def test_build_unified_holdings_empty_stores_no_audit(tmp_path):
    """Empty promoted stores: no behavior change, no audit artifact."""
    from pipeline.unified_holdings import build_unified_holdings

    bdc_df = pd.DataFrame([{
        "cik": "123", "entity_name": "Test BDC",
        "accession_number": "0001-23", "form_type": "10-K",
        "filing_date": "2023-06-01", "report_date": "2023-03-31",
        "investment_identifier": "Acme Corp - First Lien Term Loan",
        "fair_value": 1000000.0, "cost": 990000.0,
        "principal_amount": 1000000.0, "interest_rate": 8.5,
        "basis_spread": 3.5, "reference_rate_type": "SOFR",
        "maturity_date": "2028-01-15", "pct_of_net_assets": 0.05,
        "pik_rate": None, "shares_held": None,
        "unrealized_gain_loss": 10000.0, "dimensions_raw": "x=y",
        "investment_type": "", "industry": "", "affiliation": "",
        "period": "2023-03-31",
    }])
    out_file = tmp_path / "unified.csv"
    with patch("pipeline.unified_holdings.UNIFIED_HOLDINGS_FILE", out_file):
        result = build_unified_holdings(
            bdc_df=bdc_df, nport_df=pd.DataFrame(),
            output_file=out_file, orphan_file=tmp_path / "orphan.csv",
            agent_rules_dir=tmp_path / "empty_rules",
            b2_corrections_dir=tmp_path / "empty_corrections")
    assert len(result) == 1
    assert not (tmp_path / "agent_fix_application_audit.csv").exists()
