from __future__ import annotations

from pathlib import Path

import pandas as pd

from pipeline import source_reconciliation as sr


def _patch_cache_paths(monkeypatch, tmp_path: Path) -> None:
    source_dir = tmp_path / "cache" / "bdc_source_facts"
    recon_dir = tmp_path / "cache" / "source_reconciliation"
    monkeypatch.setattr(sr, "BDC_SOURCE_FACTS_CACHE_DIR", source_dir)
    monkeypatch.setattr(sr, "BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE", source_dir / "manifest.csv")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR", recon_dir / "detail_by_cik")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_METRICS_BY_CIK_DIR", recon_dir / "metrics_by_cik")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_CACHE_MANIFEST_FILE", recon_dir / "manifest.csv")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_CACHE_STATUS_FILE", recon_dir / "cache_status.csv")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_DETAIL_FILE", tmp_path / "source_reconciliation_detail.csv")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_METRICS_FILE", tmp_path / "source_reconciliation_metrics.csv")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_CALIBRATION_REVIEW_FILE", tmp_path / "source_reconciliation_calibration_review.csv")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE", tmp_path / "source_reconciliation_residual_classification.csv")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_MD_FILE", tmp_path / "source_reconciliation_residual_classification.md")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE", tmp_path / "source_reconciliation_source_only_detail.csv")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE", tmp_path / "source_reconciliation_source_only_clusters.csv")
    monkeypatch.setattr(sr, "SOURCE_RECONCILIATION_SOURCE_ONLY_CLASSIFICATION_MD_FILE", tmp_path / "source_reconciliation_source_only_classification.md")
    monkeypatch.setattr(
        sr,
        "LEGACY_RECONCILIATION_OUTPUTS",
        [
            tmp_path / "source_reconciliation_detail.csv",
            tmp_path / "source_reconciliation_metrics.csv",
            tmp_path / "source_reconciliation_calibration_review.csv",
            tmp_path / "source_reconciliation_residual_classification.csv",
            tmp_path / "source_reconciliation_residual_classification.md",
            tmp_path / "source_reconciliation_source_only_detail.csv",
            tmp_path / "source_reconciliation_source_only_clusters.csv",
            tmp_path / "source_reconciliation_source_only_classification.md",
        ],
    )


def _filings_index(xml_path: Path, accession: str = "0001") -> pd.DataFrame:
    return pd.DataFrame([{
        "cik": "123",
        "entity_name": "BDC",
        "accession_number": accession,
        "form_type": "10-Q",
        "filing_date": "2025-05-01",
        "report_date": "2025-03-31",
        "xbrl_local_path": str(xml_path),
    }])


def _source_fact(accession: str = "0001") -> pd.DataFrame:
    row = {col: "" for col in sr.SOURCE_FACT_COLUMNS}
    row.update({
        "cik": "123",
        "entity_name": "BDC",
        "accession_number": accession,
        "form_type": "10-Q",
        "filing_date": "2025-05-01",
        "report_date": "2025-03-31",
        "context_id": "c1",
        "period": "2025-03-31",
        "investment_identifier": "Alpha LLC First Lien",
        "fair_value": 100.0,
    })
    return pd.DataFrame([row], columns=sr.SOURCE_FACT_COLUMNS)


def test_source_facts_cache_reuses_unchanged_accession(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)
    xml_path = tmp_path / "filing.xml"
    xml_path.write_text("<xbrl/>", encoding="utf-8")
    calls = {"count": 0}

    def fake_extract(path, filing):
        calls["count"] += 1
        return _source_fact(str(filing["accession_number"])), "ok"

    monkeypatch.setattr(sr, "_extract_single_xbrl_source_file_cached", fake_extract)
    first, first_manifest = sr.extract_bdc_source_facts_cached(filings_index_df=_filings_index(xml_path))
    second, second_manifest = sr.extract_bdc_source_facts_cached(filings_index_df=_filings_index(xml_path))

    assert calls["count"] == 1
    assert len(first) == 1
    assert len(second) == 1
    assert first_manifest.iloc[0]["parse_status"] == "ok"
    assert second_manifest.iloc[0]["fact_row_count"] == "1"


def test_source_facts_cache_reparses_changed_file_hash_only(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)
    xml_a = tmp_path / "a.xml"
    xml_b = tmp_path / "b.xml"
    xml_a.write_text("<xbrl>a</xbrl>", encoding="utf-8")
    xml_b.write_text("<xbrl>b</xbrl>", encoding="utf-8")
    calls: list[str] = []

    def fake_extract(path, filing):
        calls.append(Path(path).name)
        return _source_fact(str(filing["accession_number"])), "ok"

    monkeypatch.setattr(sr, "_extract_single_xbrl_source_file_cached", fake_extract)
    sr.extract_bdc_source_facts_cached(
        filings_index_df=pd.concat([
            _filings_index(xml_a, "0001"),
            _filings_index(xml_b, "0002"),
        ], ignore_index=True)
    )
    xml_b.write_text("<xbrl>changed</xbrl>", encoding="utf-8")
    sr.extract_bdc_source_facts_cached(
        filings_index_df=pd.concat([
            _filings_index(xml_a, "0001"),
            _filings_index(xml_b, "0002"),
        ], ignore_index=True)
    )

    assert calls == ["a.xml", "b.xml", "b.xml"]


def test_source_facts_cache_records_parse_failure(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<xbrl>", encoding="utf-8")

    facts, manifest = sr.extract_bdc_source_facts_cached(filings_index_df=_filings_index(bad_xml))

    assert facts.empty
    assert manifest.iloc[0]["parse_status"] == "parse_failed"
    assert manifest.iloc[0]["fact_row_count"] == "0"


def test_dirty_reconciliation_planning_hashes_and_missing_artifacts(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)
    source_manifest = pd.DataFrame([{
        "accession_number": "0001",
        "cik": "0000000123",
        "file_hash": "source-a",
        "filing_metadata_hash": "meta-a",
        "parse_status": "ok",
        "fact_row_count": "1",
    }])
    holdings_hashes = pd.DataFrame([{
        "cik": "0000000123",
        "holdings_hash": "holdings-a",
        "holdings_row_count": 1,
    }])
    plan = sr.plan_dirty_reconciliation_ciks(source_manifest, holdings_hashes, "logic-a", "override-a")
    assert plan.iloc[0]["dirty"]
    assert "missing_manifest" in plan.iloc[0]["dirty_reason"]

    detail = tmp_path / "cache" / "source_reconciliation" / "detail_by_cik" / "0000000123.parquet"
    metrics = tmp_path / "cache" / "source_reconciliation" / "metrics_by_cik" / "0000000123.parquet"
    sr._write_df_parquet_atomic(pd.DataFrame(columns=sr.DETAIL_COLUMNS), detail, sr.DETAIL_COLUMNS)
    sr._write_df_parquet_atomic(pd.DataFrame(columns=sr.METRIC_COLUMNS), metrics, sr.METRIC_COLUMNS)
    manifest = pd.DataFrame([{
        "cik": "0000000123",
        "source_hash": plan.iloc[0]["source_hash"],
        "holdings_hash": "holdings-a",
        "logic_hash": "logic-a",
        "override_hash": "override-a",
        "detail_row_count": "0",
        "metrics_row_count": "0",
        "detail_artifact_path": str(detail),
        "metrics_artifact_path": str(metrics),
        "computed_at": "now",
    }], columns=sr.RECONCILIATION_MANIFEST_COLUMNS)
    sr._write_csv_atomic(manifest, sr.SOURCE_RECONCILIATION_CACHE_MANIFEST_FILE, sr.RECONCILIATION_MANIFEST_COLUMNS)

    clean = sr.plan_dirty_reconciliation_ciks(source_manifest, holdings_hashes, "logic-a", "override-a")
    assert not clean.iloc[0]["dirty"]
    changed_holdings = holdings_hashes.copy()
    changed_holdings.loc[0, "holdings_hash"] = "holdings-b"
    assert "holdings_hash" in sr.plan_dirty_reconciliation_ciks(source_manifest, changed_holdings, "logic-a", "override-a").iloc[0]["dirty_reason"]
    assert "logic_hash" in sr.plan_dirty_reconciliation_ciks(source_manifest, holdings_hashes, "logic-b", "override-a").iloc[0]["dirty_reason"]
    detail.unlink()
    assert "missing_detail_artifact" in sr.plan_dirty_reconciliation_ciks(source_manifest, holdings_hashes, "logic-a", "override-a").iloc[0]["dirty_reason"]
    assert "force" in sr.plan_dirty_reconciliation_ciks(source_manifest, holdings_hashes, "logic-a", "override-a", force=True).iloc[0]["dirty_reason"]


def _make_source_row(identifier, fair_value, cik="123", accession="0001"):
    """Helper to build a single source fact row."""
    row = {col: "" for col in sr.SOURCE_FACT_COLUMNS}
    row.update({
        "cik": cik,
        "entity_name": "BDC",
        "accession_number": accession,
        "form_type": "10-Q",
        "filing_date": "2025-05-01",
        "report_date": "2025-03-31",
        "context_id": "c1",
        "period": "2025-03-31",
        "investment_identifier": identifier,
        "fair_value": fair_value,
    })
    return row


def _make_output_row(identifier, fair_value, issuer_name="", cik="123", accession="0001"):
    """Helper to build a single holdings output row."""
    return {
        "source": "BDC",
        "cik": cik,
        "entity_name": "BDC",
        "report_date": "2025-03-31",
        "period": "2025-03-31",
        "accession_number": accession,
        "filing_date": "2025-05-01",
        "bdc_form_type": "10-Q",
        "bdc_investment_identifier": identifier,
        "bdc_dimensions_raw": "",
        "issuer_name": issuer_name,
        "instrument_description": "",
        "index_classification": "",
        "asset_category": "LOAN",
        "issuer_category": "",
        "maturity_date": "",
        "fair_value": fair_value,
        "cost": "",
        "principal_amount": "",
        "shares_held": "",
        "interest_rate": "",
        "basis_spread": "",
        "pik_rate": "",
    }


# ---- Issuer subtotal arithmetic clearing tests ----


def test_issuer_subtotal_arithmetic_basic_clearing():
    """Source uses different identifier format than output children -> cleared by arithmetic.

    The source identifier "Debt Investments - Acme Corp LLC" will NOT be a prefix
    of output identifiers like "Acme Corp LLC - First Lien Term Loan SOFR+500 07/2028",
    so the existing rollup_exact CTE won't match. The new issuer subtotal arithmetic
    CTE extracts "acme corp llc" from both and matches by FV arithmetic.
    """
    source_df = pd.DataFrame([
        _make_source_row("Debt Investments - Acme Corp LLC", 300.0),
    ], columns=sr.SOURCE_FACT_COLUMNS)
    holdings_df = pd.DataFrame([
        _make_output_row("Acme Corp LLC - First Lien Term Loan SOFR+500 07/2028", 100.0, issuer_name="Acme Corp LLC"),
        _make_output_row("Acme Corp LLC - Second Lien Term Loan SOFR+800 07/2028", 100.0, issuer_name="Acme Corp LLC"),
        _make_output_row("Acme Corp LLC - Revolver SOFR+500 07/2028", 100.0, issuer_name="Acme Corp LLC"),
    ])
    detail, _ = sr.reconcile_bdc_source_to_holdings(source_df, holdings_df, enable_bdc_xbrl_wrappers=False)
    source_rows = detail[detail["source_row_id"].astype(str) != ""]
    acme_row = source_rows[source_rows["raw_investment_identifier"].str.contains("Acme Corp LLC", na=False)]
    assert len(acme_row) == 1
    assert acme_row.iloc[0]["status"] == "documented_source_issuer_subtotal_arithmetic"
    assert acme_row.iloc[0]["blocking_issue"] == False  # noqa: E712


def test_issuer_subtotal_arithmetic_fv_mismatch_stays_blocking():
    """Source FV=400 but children sum=300 -> NOT cleared (stays blocking)."""
    source_df = pd.DataFrame([
        _make_source_row("Debt Investments - Beta Holdings Inc", 400.0),
    ], columns=sr.SOURCE_FACT_COLUMNS)
    holdings_df = pd.DataFrame([
        _make_output_row("Beta Holdings Inc - First Lien SOFR+500 07/2028", 100.0, issuer_name="Beta Holdings Inc"),
        _make_output_row("Beta Holdings Inc - Second Lien SOFR+800 07/2028", 100.0, issuer_name="Beta Holdings Inc"),
        _make_output_row("Beta Holdings Inc - Revolver SOFR+500 07/2028", 100.0, issuer_name="Beta Holdings Inc"),
    ])
    detail, _ = sr.reconcile_bdc_source_to_holdings(source_df, holdings_df, enable_bdc_xbrl_wrappers=False)
    source_rows = detail[detail["source_row_id"].astype(str) != ""]
    beta_row = source_rows[source_rows["raw_investment_identifier"].str.contains("Beta Holdings", na=False)]
    assert len(beta_row) == 1
    assert beta_row.iloc[0]["status"] != "documented_source_issuer_subtotal_arithmetic"
    assert beta_row.iloc[0]["blocking_issue"] == True  # noqa: E712


def test_issuer_subtotal_arithmetic_single_child_not_cleared():
    """Source FV=100 with only ONE output child FV=100 -> NOT cleared (require >= 2)."""
    source_df = pd.DataFrame([
        _make_source_row("Debt Investments - Gamma Corp", 100.0),
    ], columns=sr.SOURCE_FACT_COLUMNS)
    holdings_df = pd.DataFrame([
        _make_output_row("Gamma Corp - First Lien SOFR+500 07/2028", 100.0, issuer_name="Gamma Corp"),
    ])
    detail, _ = sr.reconcile_bdc_source_to_holdings(source_df, holdings_df, enable_bdc_xbrl_wrappers=False)
    source_rows = detail[detail["source_row_id"].astype(str) != ""]
    gamma_row = source_rows[source_rows["raw_investment_identifier"].str.contains("Gamma Corp", na=False)]
    # Either matched directly or blocking, but NOT cleared by issuer subtotal arithmetic
    for _, row in gamma_row.iterrows():
        assert row["status"] != "documented_source_issuer_subtotal_arithmetic"


def test_issuer_subtotal_arithmetic_position_signal_not_cleared():
    """Source with position keywords should NOT be cleared even if FV matches.

    "Delta LLC First Lien Term Loan" has position signals (first lien, term loan)
    so even though its FV matches the sum of children, it should not be treated
    as an issuer-level subtotal.
    """
    source_df = pd.DataFrame([
        _make_source_row("Delta LLC First Lien Term Loan", 200.0),
    ], columns=sr.SOURCE_FACT_COLUMNS)
    holdings_df = pd.DataFrame([
        _make_output_row("Delta LLC - First Lien Term Loan A SOFR+500 07/2028", 100.0, issuer_name="Delta LLC"),
        _make_output_row("Delta LLC - First Lien Term Loan B SOFR+500 07/2028", 100.0, issuer_name="Delta LLC"),
    ])
    detail, _ = sr.reconcile_bdc_source_to_holdings(source_df, holdings_df, enable_bdc_xbrl_wrappers=False)
    source_rows = detail[detail["source_row_id"].astype(str) != ""]
    delta_row = source_rows[source_rows["raw_investment_identifier"].str.contains("Delta LLC First Lien", na=False)]
    assert len(delta_row) >= 1
    # Should not be cleared by issuer subtotal arithmetic because "First Lien Term Loan" is a position signal
    for _, row in delta_row.iterrows():
        assert row["status"] != "documented_source_issuer_subtotal_arithmetic"


def test_issuer_subtotal_arithmetic_pipe_delimited():
    """Pipe-delimited source 'Investments | Debt | Epsilon Holdings Inc' -> cleared."""
    source_df = pd.DataFrame([
        _make_source_row("Investments | Debt | Epsilon Holdings Inc", 500.0),
    ], columns=sr.SOURCE_FACT_COLUMNS)
    holdings_df = pd.DataFrame([
        _make_output_row("Epsilon Holdings Inc First Lien", 250.0, issuer_name="Epsilon Holdings Inc"),
        _make_output_row("Epsilon Holdings Inc Revolver", 250.0, issuer_name="Epsilon Holdings Inc"),
    ])
    detail, _ = sr.reconcile_bdc_source_to_holdings(source_df, holdings_df, enable_bdc_xbrl_wrappers=False)
    source_rows = detail[detail["source_row_id"].astype(str) != ""]
    epsilon_row = source_rows[source_rows["raw_investment_identifier"].str.contains("Epsilon Holdings", na=False)]
    assert len(epsilon_row) == 1
    assert epsilon_row.iloc[0]["status"] == "documented_source_issuer_subtotal_arithmetic"
    assert epsilon_row.iloc[0]["blocking_issue"] == False  # noqa: E712


def test_forced_reconciliation_recomputes_each_cik_partition(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)
    source_manifest = pd.DataFrame([
        {
            "accession_number": "0001",
            "cik": "0000000123",
            "file_hash": "source-a",
            "filing_metadata_hash": "meta-a",
            "parse_status": "ok",
            "fact_row_count": "1",
        },
        {
            "accession_number": "0002",
            "cik": "0000000456",
            "file_hash": "source-b",
            "filing_metadata_hash": "meta-b",
            "parse_status": "ok",
            "fact_row_count": "1",
        },
    ])
    source_df = pd.DataFrame([
        {**{col: "" for col in sr.SOURCE_FACT_COLUMNS}, "cik": "123", "accession_number": "0001"},
        {**{col: "" for col in sr.SOURCE_FACT_COLUMNS}, "cik": "456", "accession_number": "0002"},
    ], columns=sr.SOURCE_FACT_COLUMNS)
    unified_df = pd.DataFrame([
        {"source": "BDC", "cik": "123", "report_date": "2025-03-31"},
        {"source": "BDC", "cik": "456", "report_date": "2025-03-31"},
        {"source": "NPORT", "cik": "456", "report_date": "2025-03-31"},
    ])
    holdings_hashes = pd.DataFrame([
        {"cik": "0000000123", "holdings_hash": "holdings-a", "holdings_row_count": 1},
        {"cik": "0000000456", "holdings_hash": "holdings-b", "holdings_row_count": 1},
    ])
    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def fake_reconcile(source_part, holdings_part):
        calls.append((
            tuple(sorted(source_part["cik"].astype(str).unique())),
            tuple(sorted(holdings_part["cik"].astype(str).unique())),
        ))
        return pd.DataFrame(columns=sr.DETAIL_COLUMNS), pd.DataFrame(columns=sr.METRIC_COLUMNS)

    monkeypatch.setattr(sr, "extract_bdc_source_facts_cached", lambda **_: (source_df, source_manifest))
    monkeypatch.setattr(sr, "compute_bdc_holdings_hashes", lambda _: holdings_hashes)
    monkeypatch.setattr(sr, "compute_reconciliation_logic_hash", lambda: "logic-a")
    monkeypatch.setattr(sr, "_compute_override_hash", lambda: "override-a")
    monkeypatch.setattr(sr, "reconcile_bdc_source_to_holdings", fake_reconcile)

    _, _, status = sr.run_bdc_source_reconciliation_cached(unified_df=unified_df, force=True)

    assert status.iloc[0]["run_mode"] == "force"
    assert int(status.iloc[0]["dirty_cik_count"]) == 2
    assert calls == [(("123",), ("123",)), (("456",), ("456",))]
