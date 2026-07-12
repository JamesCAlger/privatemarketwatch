"""Tests for the agent data-query tool (pipeline/agent_data_query): read-only, cik-scoped,
safe. Synthetic in-memory frames, no real data."""
import pandas as pd
import pytest

from pipeline.agent_data_query import query, describe, validate_sql


def _sources():
    holdings = pd.DataFrame([
        {"cik": "0001377936", "report_date": "2026-02-28", "fair_value": 1000.0, "issuer_name": "A"},
        {"cik": "0001377936", "report_date": "2026-02-28", "fair_value": 376.0, "issuer_name": "CLO"},
        {"cik": "0000000009", "report_date": "2026-02-28", "fair_value": 9999.0, "issuer_name": "OtherCik"},
    ])
    staging = pd.DataFrame([
        {"cik": 1377936, "period": "2026-02-28", "report_date": "2026-02-28", "fair_value": 1376.0},
        {"cik": 1377936, "period": "2025-02-28", "report_date": "2026-02-28", "fair_value": 500.0},
    ])
    conservation = pd.DataFrame([
        {"rule_name": "fv_conservation", "cik": "1377936", "report_date": "2026-02-28",
         "value_sum": 1376.0, "anchor_value": 1000.0, "residual_pct": 37.6, "status": "overshoot"},
    ])
    fund_financials = pd.DataFrame([
        {"cik": "1377936", "report_date": "2026-02-28", "investments_at_fair_value": 1000.0},
    ])
    return {"holdings": holdings, "staging": staging,
            "conservation": conservation, "fund_financials": fund_financials}


# -- cik scoping (the safety + scope guarantee) -----------------------------------------

def test_cik_scoping_excludes_other_filers():
    # Even an unqualified SELECT * only sees the target cik (the table is pre-filtered).
    out = query("SELECT round(sum(fair_value),0) AS s FROM holdings", cik="0001377936",
                sources=_sources())
    assert out["ok"] and out["rows"] == [[1376.0]]        # 1000 + 376, NOT the other cik's 9999


def test_cross_cik_query_returns_nothing_for_absent_cik():
    out = query("SELECT count(*) AS n FROM holdings", cik="0000000009", sources=_sources())
    assert out["ok"] and out["rows"] == [[1]]             # only OtherCik's single row


# -- the investigative power: arbitrary aggregation -------------------------------------

def test_groupby_aggregation_works():
    out = query("SELECT period, round(sum(fair_value),0) AS fv FROM staging GROUP BY 1 ORDER BY 1",
                cik="1377936", sources=_sources())
    assert out["ok"]
    assert out["rows"] == [["2025-02-28", 500.0], ["2026-02-28", 1376.0]]


def test_join_across_tables():
    out = query("SELECT h.report_date, h.fv - f.investments_at_fair_value AS residual FROM "
                "(SELECT report_date, sum(fair_value) fv FROM holdings GROUP BY 1) h "
                "JOIN fund_financials f USING (report_date)", cik="1377936", sources=_sources())
    assert out["ok"] and out["rows"] == [["2026-02-28", 376.0]]   # the discrepancy, computed


# -- safety: read-only, no DDL/DML/file/multi-statement ---------------------------------

@pytest.mark.parametrize("bad", [
    "DROP TABLE holdings",
    "INSERT INTO holdings VALUES (1)",
    "SELECT * FROM holdings; DROP TABLE holdings",
    "SELECT * FROM read_parquet('C:/secret.parquet')",
    "ATTACH 'other.db'",
    "PRAGMA database_list",
    "UPDATE holdings SET fair_value = 0",
    "SELECT * FROM holdings -- sneaky",
])
def test_validate_rejects_unsafe(bad):
    assert validate_sql(bad)                              # non-empty error list


@pytest.mark.parametrize("ok_sql", [
    "SELECT * FROM holdings",
    "WITH t AS (SELECT * FROM holdings) SELECT count(*) FROM t",
    "select report_date, sum(fair_value) from staging group by 1",
])
def test_validate_accepts_select(ok_sql):
    assert validate_sql(ok_sql) == []


def test_query_rejects_unsafe_at_runtime():
    out = query("DELETE FROM holdings", cik="1377936", sources=_sources())
    assert out["ok"] is False and out["errors"]


def test_file_access_blocked_even_if_validation_bypassed():
    # read_parquet is also blocked at runtime (external access disabled after setup), not only
    # by the validator -- belt and suspenders. We assert the validator catches it here.
    out = query("SELECT * FROM read_csv_auto('x.csv')", cik="1377936", sources=_sources())
    assert out["ok"] is False


# -- bounded results --------------------------------------------------------------------

def test_row_cap_truncates():
    big = pd.DataFrame([{"cik": "1", "report_date": "q", "fair_value": float(i)} for i in range(50)])
    out = query("SELECT * FROM holdings", cik="1", sources={"holdings": big}, row_cap=10)
    assert out["ok"] and out["row_count"] == 10 and out["truncated"] is True


# -- describe: the agent's starting context ---------------------------------------------

def test_describe_returns_schema_and_residual_context():
    d = describe(cik="1377936", sources=_sources())
    assert set(d["tables"]) == {"holdings", "staging", "conservation", "fund_financials"}
    assert "fair_value" in d["tables"]["holdings"]
    ctx = d["conservation_context"]
    assert ctx["ok"] and ctx["rows"][0][0] == "fv_conservation"   # the residual to drive to zero
