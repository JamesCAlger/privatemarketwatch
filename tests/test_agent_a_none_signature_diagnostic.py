import json

import duckdb

from scripts.agent_a import diagnose_none_signature as diag


def test_residual_family_requires_acquisition_date_for_equity_anchor_candidates():
    assert diag.residual_family("Common Equity (5% of class)") != "common_equity_acquisition_date"
    assert diag.residual_family(
        "TRU Taj Trust Retail Security Common Equity Acquisition Date 07/21/2017"
    ) == "common_equity_acquisition_date"
    assert diag.residual_family(
        "Eagle Point Credit Company Inc Common Stock Initial Acquisition Date 08/18/2022"
    ) == "common_stock_initial_acquisition_date"
    assert diag.residual_family(
        "Ruby Tuesday Operations LLC Warrants Initial Acquisition Date 02/24/2021"
    ) == "warrants_initial_acquisition_date"
    assert diag.residual_family(
        "Investments in Special Purpose Acquisition Companies (SPAC) AdTheorent Warrants "
        "Initial Acquisition Date 02/26/2021"
    ) == "spac_warrants_initial_acquisition_date"


def test_build_diagnostic_counts_none_rows_by_quarter_and_bounds_examples():
    anchors = diag.load_anchor_spec_from_dict({"anchors": [{"label": "RATE", "regex": "Interest Rate"}]})
    rows = [
        ("2023-03-31", "Acme LLC Interest Rate 10.0%"),
        ("2023-03-31", "TRU Taj Trust Common Equity Acquisition Date 07/21/2017"),
        ("2023-03-31", "Ruby Tuesday Warrants Initial Acquisition Date 02/24/2021"),
        ("2023-06-30", "Ruby Tuesday Warrants Initial Acquisition Date 02/24/2021"),
        ("2023-06-30", "Universal Fiber Warrants Initial Acquisition Date 09/30/2021"),
    ]

    quarter_rows, family_rows = diag.build_diagnostic(rows, anchors, examples_per_family=1)

    by_q = {r["quarter"]: r for r in quarter_rows}
    assert by_q["2023-03-31"]["none_rows"] == 2
    assert by_q["2023-03-31"]["none_pct"] == 66.7
    assert by_q["2023-06-30"]["none_rows"] == 2
    by_family = {r["family"]: r for r in family_rows}
    assert by_family["warrants_initial_acquisition_date"]["none_rows"] == 3
    assert by_family["warrants_initial_acquisition_date"]["examples"].count("||") == 0


def test_main_uses_staged_anchors_and_writes_bounded_outputs(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    monkeypatch.setattr(diag.config, "OUTPUT_DIR", output_dir)
    proposals = output_dir / "agent_a" / "proposals"
    proposals.mkdir(parents=True)
    (proposals / "0001.anchors.json").write_text(
        json.dumps({"anchors": [{"label": "EQUITYACQ", "regex": "Common Equity Acquisition Date"}]}),
        encoding="utf-8")

    parquet = tmp_path / "holdings.parquet"
    con = duckdb.connect()
    con.execute("""
        CREATE TABLE holdings (
            cik VARCHAR,
            report_date VARCHAR,
            period VARCHAR,
            investment_identifier VARCHAR
        )
    """)
    con.execute(
        "INSERT INTO holdings VALUES "
        "('0001', '2023-03-31', '2023-03-31', 'TRU Common Equity Acquisition Date 01/01/2020'),"
        "('0001', '2023-03-31', '2023-03-31', 'Ruby Warrants Initial Acquisition Date 01/01/2020')"
    )
    con.execute(f"COPY holdings TO '{parquet}' (FORMAT PARQUET)")
    con.close()

    rc = diag.main([
        "--cik", "0001",
        "--quarter", "2025-12-31",
        "--staged",
        "--parquet", str(parquet),
        "--top", "5",
        "--examples", "2",
    ])

    assert rc == 0
    csv_path = output_dir / "agent_a" / "quarter" / "2025-12-31" / "diagnostics" / "0001_none_signature_residuals.csv"
    md_path = csv_path.with_suffix(".md")
    assert csv_path.exists()
    assert md_path.exists()
    text = csv_path.read_text(encoding="utf-8")
    assert "warrants_initial_acquisition_date" in text
    assert "common_equity_acquisition_date" not in text
