"""Tests for the V1 DuckDB validation rules engine."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from pipeline import config
from pipeline.validation_rules import (
    AGGREGATE_COLUMNS,
    DETAIL_COLUMNS,
    RULE_REGISTRY,
    run_all,
)


def _write_csv(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _base_holding(**overrides) -> dict:
    row = {
        "cik": "100",
        "quarter": "2024q1",
        "report_date": "2024-03-31",
        "issuer_name": "Acme",
        "position_id": "P0",
        "instrument_description": "First lien term loan",
        "cusip": "123456AA1",
        "source": "bdc",
        "fair_value": "1000000",
        "cost": "1000000",
        "pct_of_net_assets": "5",
        "index_classification": "DIRECT_LENDING",
        "asset_category": "LOAN",
        "interest_rate": "8",
        "basis_spread": "",
        "pik_rate": "",
        "maturity_date": "2028-03-31",
        "coupon_type": "Floating",
        "principal_amount": "1000000",
        "shares_held": "",
        "exposure_type": "DIRECT",
        "asset_class": "PRIVATE_CREDIT",
        "entity_id": "E001",
        "gics_sub_industry": "Diversified Financial Services",
        "entity_name": "Test BDC",
    }
    row.update(overrides)
    return row


def _base_universe(**overrides) -> dict:
    row = {
        "cik": "100",
        "entity_name": "Test BDC",
        "vehicle_type": "bdc",
        "status": "active",
    }
    row.update(overrides)
    return row


def _base_match(**overrides) -> dict:
    row = {
        "cik": "100",
        "source": "bdc",
        "begin_quarter": "2024q1",
        "end_quarter": "2024q2",
        "begin_issuer_name": "Acme Corp",
        "end_issuer_name": "Acme Corp",
        "begin_fair_value": "1000000",
        "end_fair_value": "1010000",
        "match_method": "exact_name",
        "position_id": "P0",
    }
    row.update(overrides)
    return row


def _base_filing(**overrides) -> dict:
    row = {
        "cik": "100",
        "entity_name": "Test BDC",
        "form_type": "10-K",
        "filing_date": "2024-04-15",
        "report_date": "2024-03-31",
    }
    row.update(overrides)
    return row


def _base_entity(**overrides) -> dict:
    row = {
        "entity_id": "E001",
        "canonical_name": "Acme Corp",
        "issuer_name_variant": "Acme Corp LLC",
        "cusip": "123456AA1",
    }
    row.update(overrides)
    return row


def _base_position(**overrides) -> dict:
    row = {
        "cik": "100",
        "entity_name": "BDC",
        "source": "bdc",
        "begin_quarter": "2024q1",
        "end_quarter": "2024q2",
        "issuer_name": "Acme",
        "index_classification": "DIRECT_LENDING",
        "asset_category": "LOAN",
        "begin_fair_value": "1000000",
        "end_fair_value": "1010000",
        "begin_cost": "1000000",
        "end_cost": "1000000",
        "begin_principal_amount": "1000000",
        "end_principal_amount": "1000000",
        "begin_interest_rate": "8",
        "begin_basis_spread": "",
        "income_rate": "8",
        "income_return": "0.02",
        "capital_return": "0.01",
        "total_return": "0.03",
        "quarterly_total_return": "0.03",
        "position_id": "P0",
        "span_months": "3",
    }
    row.update(overrides)
    return row


def _fixtures(tmp_path: Path, *, bad_index: bool = False) -> dict[str, Path]:
    holdings = _write_csv(tmp_path / "private_markets_holdings.csv", [_base_holding()])
    pos_rows = []
    for i in range(10):
        pos_rows.append(_base_position(**{
            "cik": str(100 + i),
            "issuer_name": f"Issuer {i}",
            "position_id": f"P{i}",
        }))
    pos_rows.append({
        **pos_rows[0],
        "issuer_name": "Negative cost guarded out of cost weighting",
        "begin_cost": "-1000000",
        "position_id": "NEG-COST",
    })
    pos_rows.append({
        **pos_rows[0],
        "issuer_name": "Micro position guarded out of index",
        "begin_fair_value": "1000",
        "end_fair_value": "1000",
        "position_id": "MICRO",
    })
    position_returns = _write_csv(tmp_path / "position_returns.csv", pos_rows)
    expected_return = "0.04" if bad_index else "0.03"
    index_returns = _write_csv(tmp_path / "index_returns.csv", [{
        "index_classification": "DIRECT_LENDING",
        "quarter": "2024q2",
        "fv_weighted_return": expected_return,
        "equal_weighted_return": "0.03",
        "cost_weighted_return": expected_return,
        "constituent_count": "10" if bad_index else "11",
        "total_begin_fv": "10000000" if bad_index else "11000000",
        "total_end_fv": "10100000" if bad_index else "11110000",
        "index_level_fv": "103",
        "index_level_equal": "103",
        "index_level_cost": "103",
    }])
    fee_uplift = _write_csv(tmp_path / "fee_uplift.csv", [{
        "cik": "100", "quarter": "2024q1", "effective_uplift": "1",
    }])
    fund_financials = _write_csv(tmp_path / "fund_financials.csv", [{
        "cik": "100",
        "report_date": "2024-03-31",
        "quarter": "2024q1",
        "total_assets": "2000000",
    }])
    combined_universe = _write_csv(tmp_path / "combined_universe.csv", [_base_universe()])
    position_matches = _write_csv(tmp_path / "position_matches.csv", [_base_match()])
    bdc_filings_index = _write_csv(tmp_path / "bdc_filings_index.csv", [_base_filing()])
    entity_lookup = _write_csv(tmp_path / "entity_lookup.csv", [_base_entity()])
    return {
        "holdings": holdings,
        "position_returns": position_returns,
        "index_returns": index_returns,
        "fee_uplift": fee_uplift,
        "fund_financials": fund_financials,
        "combined_universe": combined_universe,
        "position_matches": position_matches,
        "bdc_filings_index": bdc_filings_index,
        "entity_lookup": entity_lookup,
    }


def test_registry_contains_all_rules():
    assert len(RULE_REGISTRY) == 88
    expected = set()
    expected.update(f"PC{i:02d}" for i in range(1, 13))
    expected.update(f"IDX{i:02d}" for i in range(1, 16))
    expected.update(f"T{i:02d}" for i in range(1, 11))
    expected.update(f"S{i:02d}" for i in range(1, 11))
    expected.update(f"R{i:02d}" for i in range(1, 16))
    expected.update(f"XS{i:02d}" for i in range(1, 7))
    expected.update(f"F{i:02d}" for i in range(1, 11))
    expected.update(f"M{i:02d}" for i in range(1, 11))
    assert set(RULE_REGISTRY) == expected


def test_all_sql_executes_on_minimal_fixtures(tmp_path):
    aggregate, detail = run_all(table_paths=_fixtures(tmp_path), write=False)

    assert list(aggregate.columns) == AGGREGATE_COLUMNS
    assert list(detail.columns) == DETAIL_COLUMNS
    assert len(aggregate) == 88
    assert set(aggregate["status"]).issubset({"PASS", "WARN", "FAIL", "SKIPPED"})


def test_promoted_fail_rules_trigger_and_zero_hit(tmp_path):
    good_aggregate, _ = run_all(table_paths=_fixtures(tmp_path / "good"), write=False)
    assert good_aggregate.set_index("rule_id").loc["PC02", "status"] == "PASS"
    assert good_aggregate.set_index("rule_id").loc["PC03", "status"] == "PASS"

    bad_aggregate, detail = run_all(
        table_paths=_fixtures(tmp_path / "bad", bad_index=True),
        write=False,
    )
    by_rule = bad_aggregate.set_index("rule_id")
    assert by_rule.loc["PC02", "status"] == "FAIL"
    assert by_rule.loc["PC03", "status"] == "FAIL"
    assert set(detail["rule_id"]) >= {"PC02", "PC03"}


def test_pc02_pc03_reconcile_index_guard_not_raw_row_presence(tmp_path):
    aggregate, _ = run_all(table_paths=_fixtures(tmp_path), write=False)
    by_rule = aggregate.set_index("rule_id")

    assert by_rule.loc["PC02", "hit_count"] == 0
    assert by_rule.loc["PC03", "hit_count"] == 0


def test_missing_optional_tables_produce_skipped_rows(tmp_path):
    paths = _fixtures(tmp_path)
    paths["fee_uplift"] = tmp_path / "missing_fee_uplift.csv"

    aggregate, _ = run_all(table_paths=paths, write=False)
    pc10 = aggregate.set_index("rule_id").loc["PC10"]

    assert pc10["status"] == "SKIPPED"
    assert "missing file" in pc10["skipped_reason"]


def test_cli_entrypoint_writes_stable_schema(tmp_path, monkeypatch):
    paths = _fixtures(tmp_path / "inputs")
    aggregate_path = tmp_path / "validation_rules_aggregate.csv"
    detail_path = tmp_path / "validation_rules_detail.csv"

    import pipeline.validation_rules as vr
    from pipeline import main as pipeline_main

    monkeypatch.setattr(vr, "TABLE_PATHS", paths)
    monkeypatch.setattr(pipeline_main, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(config, "VALIDATION_RULES_AGGREGATE_FILE", aggregate_path)
    monkeypatch.setattr(config, "VALIDATION_RULES_DETAIL_FILE", detail_path)
    monkeypatch.setattr(sys, "argv", [
        "pipeline.main", "--validate-rules", "--rules-category", "PC",
    ])

    pipeline_main.main()

    assert aggregate_path.exists()
    assert detail_path.exists()
    with aggregate_path.open(newline="", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == AGGREGATE_COLUMNS
    with detail_path.open(newline="", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == DETAIL_COLUMNS


def test_pc06_uses_instrument_and_cusip_in_duplicate_key(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["holdings"], [
        _base_holding(issuer_name="Same Borrower", instrument_description="First lien", cusip="111111AA1", position_id="A"),
        _base_holding(issuer_name="Same Borrower", instrument_description="Second lien", cusip="222222BB2", position_id="B"),
        _base_holding(issuer_name="True Duplicate", instrument_description="Term loan", cusip="333333CC3", position_id="C"),
        _base_holding(issuer_name="True Duplicate", instrument_description="Term loan", cusip="333333CC3", position_id="D"),
    ])

    aggregate, detail = run_all(categories=["PC"], table_paths=paths, write=False)
    pc06 = aggregate.set_index("rule_id").loc["PC06"]
    pc06_detail = detail[detail["rule_id"] == "PC06"]

    assert pc06["hit_count"] == 1
    assert len(pc06_detail) == 1
    assert pc06_detail.iloc[0]["issuer_name"] == "true duplicate"


def test_pc07_pct_sum_high_keeps_known_residual_annotation(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["holdings"], [
        _base_holding(cik="0001786835", issuer_name=f"Issuer {i}", position_id=f"P{i}", pct_of_net_assets="100")
        for i in range(3)
    ])

    aggregate, detail = run_all(categories=["PC"], table_paths=paths, write=False)
    pc07 = aggregate.set_index("rule_id").loc["PC07"]
    pc07_detail = detail[detail["rule_id"] == "PC07"].iloc[0]

    assert pc07["hit_count"] == 1
    assert pc07_detail["hit_rate"] == 300.0
    assert "Known multi-entity BDC residual" in pc07_detail["evidence_hint"]


def test_idx06_concentration_threshold_is_above_50_percent(tmp_path):
    paths = _fixtures(tmp_path)
    # Need >= 20 constituents for IDX06 to fire (min constituent guard)
    positions = [
        _base_position(issuer_name="Large", position_id="LARGE", begin_fair_value="6000000", end_fair_value="6000000"),
    ] + [
        _base_position(issuer_name=f"Small{i}", position_id=f"S{i}", begin_fair_value="200000", end_fair_value="200000")
        for i in range(20)
    ]
    _write_csv(paths["position_returns"], positions)

    aggregate, detail = run_all(categories=["IDX"], table_paths=paths, write=False)
    idx06 = aggregate.set_index("rule_id").loc["IDX06"]
    idx06_detail = detail[detail["rule_id"] == "IDX06"]

    assert idx06["hit_count"] == 1
    assert idx06_detail.iloc[0]["position_id"] == "LARGE"
    # Large has 6M / (6M + 20*200K) = 6M / 10M = 0.6
    assert abs(idx06_detail.iloc[0]["hit_rate"] - 0.6) < 0.01


def test_idx09_uses_span_adjusted_quarter_equivalent_income(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["position_returns"], [
        _base_position(issuer_name="High Quarter Income", position_id="HI", income_return="0.25", span_months="3"),
        _base_position(issuer_name="Long Span Income", position_id="LONG", income_return="0.60", span_months="12"),
    ])

    aggregate, detail = run_all(categories=["IDX"], table_paths=paths, write=False)
    idx09 = aggregate.set_index("rule_id").loc["IDX09"]
    idx09_detail = detail[detail["rule_id"] == "IDX09"]

    assert idx09["hit_count"] == 1
    assert idx09_detail.iloc[0]["position_id"] == "HI"
    assert idx09_detail.iloc[0]["hit_rate"] == 0.25


def test_t01_position_count_change_from_10_to_20_fires(tmp_path):
    paths = _fixtures(tmp_path)
    rows = [
        _base_holding(quarter="2024q1", report_date="2024-03-31", issuer_name=f"Old {i}", position_id=f"O{i}", fair_value=str(1000000 + i))
        for i in range(10)
    ] + [
        _base_holding(quarter="2024q2", report_date="2024-06-30", issuer_name=f"New {i}", position_id=f"N{i}", fair_value=str(1000000 + i))
        for i in range(20)
    ]
    _write_csv(paths["holdings"], rows)

    aggregate, detail = run_all(categories=["T"], table_paths=paths, write=False)
    t01 = aggregate.set_index("rule_id").loc["T01"]
    t01_detail = detail[detail["rule_id"] == "T01"].iloc[0]

    assert t01["hit_count"] == 1
    assert t01_detail["quarter"] == "2024q2"
    assert t01_detail["hit_rate"] == 1.0


def test_t02_total_fv_change_from_1m_to_4m_fires(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["holdings"], [
        _base_holding(quarter="2024q1", report_date="2024-03-31", issuer_name="Old", position_id="OLD", fair_value="1000000"),
        _base_holding(quarter="2024q2", report_date="2024-06-30", issuer_name="New", position_id="NEW", fair_value="4000000"),
    ])

    aggregate, detail = run_all(categories=["T"], table_paths=paths, write=False)
    t02 = aggregate.set_index("rule_id").loc["T02"]
    t02_detail = detail[detail["rule_id"] == "T02"].iloc[0]

    assert t02["hit_count"] == 1
    assert t02_detail["quarter"] == "2024q2"
    assert t02_detail["hit_rate"] == 4.0


def test_m02_begin_end_fv_ratio_15x_fires(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["position_returns"], [
        _base_position(position_id="EXTREME", begin_fair_value="1000000", end_fair_value="15000000"),
    ])

    aggregate, detail = run_all(categories=["M"], table_paths=paths, write=False)
    m02 = aggregate.set_index("rule_id").loc["M02"]
    m02_detail = detail[detail["rule_id"] == "M02"].iloc[0]

    assert m02["hit_count"] == 1
    assert m02_detail["position_id"] == "EXTREME"
    assert m02_detail["hit_rate"] == 15.0


def test_finding_key_is_deterministic_across_run_ids(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["holdings"], [
        _base_holding(cik="0001786835", issuer_name=f"Issuer {i}", position_id=f"P{i}", pct_of_net_assets="100")
        for i in range(3)
    ])

    _, detail_a = run_all(categories=["PC"], table_paths=paths, run_id="run-a", write=False)
    _, detail_b = run_all(categories=["PC"], table_paths=paths, run_id="run-b", write=False)

    keys_a = set(detail_a.loc[detail_a["rule_id"] == "PC07", "finding_key"])
    keys_b = set(detail_b.loc[detail_b["rule_id"] == "PC07", "finding_key"])
    assert keys_a == keys_b


def test_small_fixture_hit_count_equals_detail_rows(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["holdings"], [
        _base_holding(issuer_name="Dup", position_id="D1"),
        _base_holding(issuer_name="Dup", position_id="D2"),
    ])

    aggregate, detail = run_all(categories=["PC"], table_paths=paths, write=False)
    pc06 = aggregate.set_index("rule_id").loc["PC06"]
    pc06_detail = detail[detail["rule_id"] == "PC06"]

    assert pc06["hit_count"] == len(pc06_detail) == 1


def test_detail_rows_never_exceed_aggregate_hit_count_when_capped(tmp_path):
    paths = _fixtures(tmp_path)
    rows = []
    for i in range(10005):
        rows.append(_base_holding(issuer_name=f"Dup {i}", position_id=f"A{i}", fair_value=str(1000000 + i)))
        rows.append(_base_holding(issuer_name=f"Dup {i}", position_id=f"B{i}", fair_value=str(1000000 + i)))
    _write_csv(paths["holdings"], rows)

    aggregate, detail = run_all(categories=["PC"], table_paths=paths, write=False)
    pc06 = aggregate.set_index("rule_id").loc["PC06"]
    pc06_detail = detail[detail["rule_id"] == "PC06"]

    assert len(pc06_detail) == 10000
    assert len(pc06_detail) <= pc06["hit_count"]
    assert pc06["hit_count"] == 10005


def test_t04_classification_shift_fires(tmp_path):
    paths = _fixtures(tmp_path)
    rows = []
    for i in range(20):
        rows.append(_base_holding(
            quarter="2024q1", report_date="2024-03-31",
            issuer_name=f"Issuer {i}", position_id=f"P{i}",
            index_classification="DIRECT_LENDING",
        ))
    for i in range(20):
        rows.append(_base_holding(
            quarter="2024q2", report_date="2024-06-30",
            issuer_name=f"Issuer {i}", position_id=f"P{i}",
            index_classification="COMMON_EQUITY" if i < 5 else "DIRECT_LENDING",
        ))
    _write_csv(paths["holdings"], rows)

    aggregate, detail = run_all(categories=["T"], table_paths=paths, write=False)
    t04 = aggregate.set_index("rule_id").loc["T04"]
    assert t04["hit_count"] == 1


def test_s02_bdc_equity_overweight_fires(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["combined_universe"], [_base_universe(cik="100", vehicle_type="bdc")])
    rows = [
        _base_holding(index_classification="COMMON_EQUITY", fair_value="6000000"),
        _base_holding(issuer_name="Loan", position_id="P1", index_classification="DIRECT_LENDING", fair_value="4000000"),
    ]
    _write_csv(paths["holdings"], rows)

    aggregate, detail = run_all(categories=["S"], table_paths=paths, write=False)
    s02 = aggregate.set_index("rule_id").loc["S02"]
    assert s02["hit_count"] == 1


def test_r14_interest_rate_over_50_fires(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["holdings"], [
        _base_holding(interest_rate="850", fair_value="500000"),
    ])

    aggregate, detail = run_all(categories=["R"], table_paths=paths, write=False)
    r14 = aggregate.set_index("rule_id").loc["R14"]
    assert r14["hit_count"] == 1


def test_xs01_fv_divergence_fires(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["holdings"], [
        _base_holding(source="bdc", fair_value="1000000"),
        _base_holding(source="nport", fair_value="500000", position_id="NP0", cusip="999999ZZ9"),
    ])

    aggregate, detail = run_all(categories=["XS"], table_paths=paths, write=False)
    xs01 = aggregate.set_index("rule_id").loc["XS01"]
    assert xs01["hit_count"] == 1


def test_idx10_constituent_count_drop_fires(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["index_returns"], [
        {
            "index_classification": "DIRECT_LENDING", "quarter": "2024q1",
            "fv_weighted_return": "0.03", "equal_weighted_return": "0.03",
            "cost_weighted_return": "0.03", "constituent_count": "100",
            "total_begin_fv": "10000000", "total_end_fv": "10300000",
            "index_level_fv": "100", "index_level_equal": "100", "index_level_cost": "100",
        },
        {
            "index_classification": "DIRECT_LENDING", "quarter": "2024q2",
            "fv_weighted_return": "0.03", "equal_weighted_return": "0.03",
            "cost_weighted_return": "0.03", "constituent_count": "50",
            "total_begin_fv": "5000000", "total_end_fv": "5150000",
            "index_level_fv": "103", "index_level_equal": "103", "index_level_cost": "103",
        },
    ])

    aggregate, detail = run_all(categories=["IDX"], table_paths=paths, write=False)
    idx10 = aggregate.set_index("rule_id").loc["IDX10"]
    assert idx10["hit_count"] == 1


def test_f06_fund_financials_coverage_fires(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["holdings"], [
        _base_holding(cik="200"),
    ])
    _write_csv(paths["fund_financials"], [{
        "cik": "100", "report_date": "2024-03-31", "quarter": "2024q1", "total_assets": "2000000",
    }])

    aggregate, detail = run_all(categories=["F"], table_paths=paths, write=False)
    f06 = aggregate.set_index("rule_id").loc["F06"]
    assert f06["hit_count"] == 1


def test_m01_cusip_collision_fires(tmp_path):
    paths = _fixtures(tmp_path)
    _write_csv(paths["holdings"], [
        _base_holding(cusip="AAAAAA001", issuer_name="Alpha Corp", position_id="P1"),
        _base_holding(cusip="AAAAAA001", issuer_name="Zeta Industries International", position_id="P2"),
    ])

    aggregate, detail = run_all(categories=["M"], table_paths=paths, write=False)
    m01 = aggregate.set_index("rule_id").loc["M01"]
    assert m01["hit_count"] == 1


def test_category_isolation_t_only_loads_needed_tables(tmp_path):
    """T-category rules only require holdings and position_matches tables."""
    paths = _fixtures(tmp_path)
    # Remove tables not needed by T rules
    del paths["index_returns"]
    del paths["fee_uplift"]
    del paths["entity_lookup"]

    aggregate, _ = run_all(categories=["T"], table_paths=paths, write=False)
    t_rules = aggregate[aggregate["rule_id"].str.startswith("T")]
    assert len(t_rules) == 10
    # T rules that don't need position_matches should not be skipped
    t01 = aggregate.set_index("rule_id").loc["T01"]
    assert t01["status"] != "SKIPPED"


def test_r03_excludes_nport_proxy_cost(tmp_path):
    """R03 excludes N-PORT rows since their cost is always proxy-derived."""
    paths = _fixtures(tmp_path)
    holdings_rows = [
        # CIK 100 (BDC): normal row, no extreme ratio
        _base_holding(cik="100", fair_value="1000000", cost="900000",
                      source="bdc", position_id="P-BDC"),
        # CIK 200 (N-PORT): extreme cost/FV divergence from proxy cost
        _base_holding(cik="200", fair_value="500000", cost="5000000",
                      source="nport", position_id="P-NPORT1"),
        _base_holding(cik="200", fair_value="600000", cost="600000",
                      source="nport", position_id="P-NPORT2"),
    ]
    paths["holdings"] = _write_csv(tmp_path / "holdings_r03.csv", holdings_rows)
    aggregate, detail = run_all(categories=["R"], table_paths=paths, write=False)
    r03_detail = detail[detail["rule_id"] == "R03"]
    ciks_hit = set(r03_detail["cik"].dropna().astype(str))
    assert "200" not in ciks_hit, "N-PORT CIK 200 should be excluded from R03"


def test_r03_keeps_bdc_with_extreme_ratio(tmp_path):
    """R03 still flags BDC-sourced positions with extreme cost/FV ratio."""
    paths = _fixtures(tmp_path)
    holdings_rows = [
        # CIK 300 (BDC): one normal, one extreme
        _base_holding(cik="300", fair_value="1000000", cost="800000",
                      source="bdc", position_id="P-NORM"),
        _base_holding(cik="300", fair_value="200000", cost="1000000",
                      source="bdc", position_id="P-EXTREME"),
    ]
    paths["holdings"] = _write_csv(tmp_path / "holdings_r03b.csv", holdings_rows)
    aggregate, detail = run_all(categories=["R"], table_paths=paths, write=False)
    r03_detail = detail[detail["rule_id"] == "R03"]
    ciks_hit = set(r03_detail["cik"].dropna().astype(str))
    assert "300" in ciks_hit, "BDC CIK 300 with extreme ratio should be flagged by R03"
