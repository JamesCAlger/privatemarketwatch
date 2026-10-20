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


# ---- Liquid-fund / cash-equivalent source admission ----
# Verdicts BDCSRC_0001899996_2025-12-31 and BDCSRC_0001950976_2025-12-31:
# money market sweep positions tagged on CashAndCashEquivalentsAxis explicit
# members (instead of the typed InvestmentIdentifierAxis) must reach the
# reconciliation source set when they carry current-period fair-value facts.


_XML_HEADER = (
    '<xbrl xmlns="http://www.xbrl.org/2003/instance" '
    'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:us-gaap="http://fasb.org/us-gaap/2025" '
    'xmlns:test="http://example.com/test">'
)


def _cash_equivalents_context(ctx_id: str, member: str, instant: str = "2025-03-31") -> str:
    return f"""
        <xbrli:context id="{ctx_id}">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">100</xbrli:identifier>
                <xbrli:segment>
                    <xbrldi:explicitMember dimension="us-gaap:CashAndCashEquivalentsAxis">test:{member}</xbrldi:explicitMember>
                    <xbrldi:explicitMember dimension="us-gaap:InvestmentTypeAxis">us-gaap:ShortTermInvestmentsMember</xbrldi:explicitMember>
                </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>{instant}</xbrli:instant></xbrli:period>
        </xbrli:context>
    """


_FILING_META = {
    "cik": "100",
    "entity_name": "Test BDC",
    "accession_number": "acc-mm",
    "form_type": "10-K",
    "filing_date": "2025-05-01",
    "report_date": "2025-03-31",
}


def _extract(tmp_path, xml_body: str):
    path = tmp_path / "mm.xml"
    path.write_text(_XML_HEADER + xml_body + "</xbrl>", encoding="utf-8")
    return sr._extract_single_xbrl_source_file(path, dict(_FILING_META))


def test_liquid_fund_member_context_admitted_with_investment_owned_facts(tmp_path):
    # 1950976 shape: standard InvestmentOwned* facts on a cash-equivalents
    # member context (no InvestmentIdentifierAxis).
    body = _cash_equivalents_context(
        "ctx_mm", "DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember"
    ) + (
        '<us-gaap:InvestmentOwnedAtCost contextRef="ctx_mm" unitRef="usd" decimals="-3">65057000</us-gaap:InvestmentOwnedAtCost>'
        '<us-gaap:InvestmentOwnedAtFairValue contextRef="ctx_mm" unitRef="usd" decimals="-3">65057000</us-gaap:InvestmentOwnedAtFairValue>'
        '<us-gaap:InvestmentInterestRate contextRef="ctx_mm" unitRef="pure" decimals="4">0.0365</us-gaap:InvestmentInterestRate>'
    )

    rows = _extract(tmp_path, body)

    assert len(rows) == 1
    row = rows[0]
    assert row["investment_identifier"] == (
        "Dreyfus Treasury Obligations Cash Management Money Market Fund"
    )
    assert row["fair_value"] == 65057000.0
    assert row["cost"] == 65057000.0
    assert row["interest_rate"] == 0.0365
    assert "cashandcashequivalentsaxis=" in row["dimensions_raw"]


def test_liquid_fund_custom_money_market_concepts_mapped(tmp_path):
    # 1899996 shape: custom MoneyMarketFundsAtFairValue / AtCarryingValue
    # concepts; carrying value doubles as cost basis.
    body = _cash_equivalents_context(
        "ctx_ss", "StateStreetInstitutionalTreasuryPlusMoneyMarketFundMember"
    ) + (
        '<us-gaap:MoneyMarketFundsAtCarryingValue contextRef="ctx_ss" unitRef="usd" decimals="0">19087624</us-gaap:MoneyMarketFundsAtCarryingValue>'
        '<test:MoneyMarketFundsAtFairValue contextRef="ctx_ss" unitRef="usd" decimals="0">19087624</test:MoneyMarketFundsAtFairValue>'
        '<us-gaap:InvestmentOwnedBalanceShares contextRef="ctx_ss" unitRef="shares" decimals="0">19087624</us-gaap:InvestmentOwnedBalanceShares>'
    )

    rows = _extract(tmp_path, body)

    assert len(rows) == 1
    row = rows[0]
    assert row["investment_identifier"] == (
        "State Street Institutional Treasury Plus Money Market Fund"
    )
    assert row["fair_value"] == 19087624.0
    assert row["cost"] == 19087624.0
    assert row["shares_held"] == 19087624.0


def test_non_money_market_cash_member_admitted_via_investment_path(tmp_path):
    # v3: filer-extension cash-axis members are full investment contexts in
    # the SHARED parser -- no money-market keyword gate. The v2 gate caused
    # real pipeline_only blockers on names without a keyword ("First American
    # Government Obligation Fund") and filer typos ("Mone Market"). Symmetry
    # with pipeline.bdc_filings keeps both sides consistent: whatever the
    # pipeline ingests, the source side sees too, so admission cannot create
    # one-sided blockers.
    body = _cash_equivalents_context("ctx_ops", "OperatingCashAccountMember") + (
        '<us-gaap:InvestmentOwnedAtFairValue contextRef="ctx_ops" unitRef="usd" decimals="0">123456</us-gaap:InvestmentOwnedAtFairValue>'
    )

    rows = _extract(tmp_path, body)

    assert len(rows) == 1
    assert rows[0]["investment_identifier"] == "Operating Cash Account"
    assert rows[0]["fair_value"] == 123456.0


def test_zero_fair_value_liquid_fund_member_admitted(tmp_path):
    # v3: zero-FV cash rows are admitted like any investment-context row; the
    # pipeline side ingests the same context through the same parser, so both
    # sides stay symmetric (zero-FV BDC rows are a known, retained class).
    body = _cash_equivalents_context(
        "ctx_zero", "DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember"
    ) + (
        '<us-gaap:InvestmentOwnedAtFairValue contextRef="ctx_zero" unitRef="usd" decimals="0">0</us-gaap:InvestmentOwnedAtFairValue>'
    )

    rows = _extract(tmp_path, body)

    assert len(rows) == 1
    assert rows[0]["fair_value"] == 0.0


def test_footnote_only_money_market_mention_not_admitted(tmp_path):
    # False positive guard (verdict 0001950976): a money-market fund named
    # only in narrative/footnote text has no cash-equivalents member context
    # and must not become a source row -- numeric truth comes only through
    # the audited dimensioned-fact path.
    body = (
        """
        <xbrli:context id="ctx_plain">
            <xbrli:entity>
                <xbrli:identifier scheme="http://www.sec.gov/CIK">100</xbrli:identifier>
            </xbrli:entity>
            <xbrli:period><xbrli:instant>2025-03-31</xbrli:instant></xbrli:period>
        </xbrli:context>
        """
        '<test:InvestmentCompanyFootnoteTextBlock contextRef="ctx_plain">'
        'Dreyfus Treasury Obligations Cash Management Money Market Fund 3.65% 65,057'
        '</test:InvestmentCompanyFootnoteTextBlock>'
    )

    rows = _extract(tmp_path, body)

    assert rows == []


def test_source_fact_extraction_version_participates_in_metadata_hash(monkeypatch):
    filing = dict(_FILING_META)
    before = sr._filing_metadata_hash(filing)
    monkeypatch.setattr(sr, "_SOURCE_FACT_EXTRACTION_VERSION", "test-bump")
    after = sr._filing_metadata_hash(filing)
    assert before != after


# ---- thousands_scale_filings on the source side (Varagon VGA-R1) ----
# The extractor reads a listed filing's decimals-0 facts at thousands; reconciliation must read the
# same facts the same way, or every rescaled row shows as a 1,000x mismatch (SRC_BDC03 / A01).


def _thousands_body():
    return _cash_equivalents_context("ctx_k", "DelRealTermLoanMember") + (
        '<us-gaap:InvestmentOwnedAtCost contextRef="ctx_k" unitRef="usd" decimals="-3">3451000</us-gaap:InvestmentOwnedAtCost>'
        '<us-gaap:InvestmentOwnedAtFairValue contextRef="ctx_k" unitRef="usd" decimals="0">3478</us-gaap:InvestmentOwnedAtFairValue>'
    )


def _list_thousands(monkeypatch, accessions):
    from pipeline import source_encodings
    monkeypatch.setitem(source_encodings._THOUSANDS_CACHE, "listed",
                        {"0000000100": frozenset(accessions)})


def test_declared_thousands_filing_is_scaled_on_source_side(tmp_path, monkeypatch):
    _list_thousands(monkeypatch, [_FILING_META["accession_number"]])
    rows = _extract(tmp_path, _thousands_body())
    assert len(rows) == 1
    assert rows[0]["fair_value"] == 3478000.0
    assert rows[0]["cost"] == 3451000.0


def test_undeclared_filing_is_not_scaled_on_source_side(tmp_path, monkeypatch):
    # false-positive guard: same facts, filing not listed (another accession of the same filer is)
    _list_thousands(monkeypatch, ["0000950170-23-021632"])
    rows = _extract(tmp_path, _thousands_body())
    assert len(rows) == 1
    assert rows[0]["fair_value"] == 3478.0
    assert rows[0]["cost"] == 3451000.0


def test_listing_a_thousands_filing_changes_only_its_metadata_hash(monkeypatch):
    listed = dict(_FILING_META)
    other = {**_FILING_META, "accession_number": "acc-other"}
    _list_thousands(monkeypatch, [])
    before_listed, before_other = sr._filing_metadata_hash(listed), sr._filing_metadata_hash(other)
    _list_thousands(monkeypatch, [listed["accession_number"]])
    assert sr._filing_metadata_hash(listed) != before_listed
    assert sr._filing_metadata_hash(other) == before_other


def _mm_reconcile(source_rows, output_rows):
    source_df = pd.DataFrame(source_rows, columns=sr.SOURCE_FACT_COLUMNS)
    holdings_df = pd.DataFrame(output_rows)
    return sr.reconcile_bdc_source_to_holdings(
        source_df,
        holdings_df,
        enable_bdc_xbrl_wrappers=False,
        audited_value_rescales=pd.DataFrame(columns=["cik", "field", "factor"]),
    )


def test_named_money_market_source_row_matches_output_position():
    # 1899996 shape: the named member row matches the pipeline row (which has
    # a filer-suffixed identifier) while generic bucket rows stay documented.
    named = _make_source_row(
        "State Street Institutional Treasury Plus Money Market Fund", 19087624.0
    )
    named["cost"] = 19087624.0
    generic_a = _make_source_row("Money Market Funds", 19087624.0)
    generic_a["context_id"] = "c2"
    generic_b = _make_source_row("Money Market Funds", 19087624.0)
    generic_b["context_id"] = "c3"
    output = _make_output_row(
        "State Street Institutional Treasury Plus Money Market Fund - 3.66% Investor Class Units",
        19087624.0,
        issuer_name="State Street Institutional Treasury Plus Money Market Fund",
    )
    output["cost"] = 19087624.0

    detail, metrics = _mm_reconcile([named, generic_a, generic_b], [output])

    named_rows = detail[detail["raw_investment_identifier"].str.contains("State Street", na=False)]
    assert len(named_rows) == 1
    assert named_rows.iloc[0]["status"] == "matched"
    assert int(metrics.iloc[0]["blocking_issue_count"]) == 0
    generic_rows = detail[detail["raw_investment_identifier"].eq("Money Market Funds")]
    assert len(generic_rows) >= 1
    assert not generic_rows["blocking_issue"].astype(bool).any()


def test_short_term_investment_row_add_rescued_by_admitted_source_row():
    # 1950976 shape: the audited row_add output row has no accession_number;
    # the admitted short-term-investment source row carries the identity and
    # fair value, so the output row is not a blocking pipeline-only extra.
    source = _make_source_row(
        "Dreyfus Treasury Obligations Cash Management Money Market Fund", 65057000.0
    )
    output = _make_output_row(
        "Short-Term Investments | Dreyfus Treasury Obligations Cash Management Money Market Fund",
        65057000.0,
        issuer_name="Dreyfus Treasury Obligations Cash Management Money Market Fund",
    )
    output["accession_number"] = ""
    output["bdc_form_type"] = ""
    output["filing_date"] = ""

    detail, metrics = _mm_reconcile([source], [output])

    assert "extra_in_pipeline" not in set(detail["status"])
    source_rows = detail[detail["source_row_id"].astype(str) != ""]
    assert set(source_rows["status"]) == {"excluded_money_market_fund"}
    assert int(metrics.iloc[0]["blocking_issue_count"]) == 0


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


# --- MLF-R5 (D-222): a wrapper edit recomputes that fund's partition ----------------------

def _two_fund_run(monkeypatch, tmp_path):
    """Patch a two-fund cached run; returns (run, calls, wrapper_dir)."""
    import json
    from pipeline import bdc_xbrl_wrapper
    _patch_cache_paths(monkeypatch, tmp_path)
    wrapper_dir = tmp_path / "wrappers"
    wrapper_dir.mkdir()
    for cik in ("0000000123", "0000000456"):
        (wrapper_dir / f"{cik}.json").write_text(json.dumps({
            "schema_version": "bdc-xbrl-wrapper.v3", "cik": cik,
            "dispatch": {"category_marker_re": r"^(Senior loans|Equity)$"}}), encoding="utf-8")
    monkeypatch.setattr(bdc_xbrl_wrapper, "_WRAPPER_DEFINITIONS_DIR", wrapper_dir)
    source_manifest = pd.DataFrame([
        {"accession_number": acc, "cik": cik, "file_hash": "source-" + acc, "filing_metadata_hash": "meta",
         "parse_status": "ok", "fact_row_count": "1"}
        for acc, cik in (("0001", "0000000123"), ("0002", "0000000456"))])
    source_df = pd.DataFrame([
        {**{col: "" for col in sr.SOURCE_FACT_COLUMNS}, "cik": "123", "accession_number": "0001"},
        {**{col: "" for col in sr.SOURCE_FACT_COLUMNS}, "cik": "456", "accession_number": "0002"},
    ], columns=sr.SOURCE_FACT_COLUMNS)
    unified_df = pd.DataFrame([{"source": "BDC", "cik": "123", "report_date": "2025-03-31"},
                               {"source": "BDC", "cik": "456", "report_date": "2025-03-31"}])
    holdings_hashes = pd.DataFrame([{"cik": "0000000123", "holdings_hash": "h-a", "holdings_row_count": 1},
                                    {"cik": "0000000456", "holdings_hash": "h-b", "holdings_row_count": 1}])
    calls: list[str] = []

    def fake_reconcile(source_part, holdings_part):
        calls.append(str(source_part["cik"].iloc[0]))
        return pd.DataFrame(columns=sr.DETAIL_COLUMNS), pd.DataFrame(columns=sr.METRIC_COLUMNS)

    monkeypatch.setattr(sr, "extract_bdc_source_facts_cached", lambda **_: (source_df, source_manifest))
    monkeypatch.setattr(sr, "compute_bdc_holdings_hashes", lambda _: holdings_hashes)
    monkeypatch.setattr(sr, "compute_reconciliation_logic_hash", lambda: "logic-a")
    monkeypatch.setattr(sr, "_compute_override_hash", lambda: "override-a")
    monkeypatch.setattr(sr, "reconcile_bdc_source_to_holdings", fake_reconcile)
    return (lambda: sr.run_bdc_source_reconciliation_cached(unified_df=unified_df)), calls, wrapper_dir


def test_changing_a_wrappers_dispatch_recomputes_only_that_fund(tmp_path, monkeypatch):
    import json
    run, calls, wrapper_dir = _two_fund_run(monkeypatch, tmp_path)
    run()
    assert calls == ["123", "456"]
    # unchanged wrappers: both funds stay clean
    calls.clear()
    _, _, status = run()
    assert calls == [] and int(status.iloc[0]["dirty_cik_count"]) == 0
    # Manulife mlff: dropping a category_marker_re alternative left 4 false A01 findings in the cache
    path = wrapper_dir / "0000000123.json"
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    wrapper["dispatch"]["category_marker_re"] = r"^(Senior loans)$"
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    plan = sr.plan_dirty_reconciliation_ciks(*sr.extract_bdc_source_facts_cached()[1:],
                                             sr.compute_bdc_holdings_hashes(None), "logic-a", "override-a")
    by_cik = plan.set_index("cik")
    assert by_cik.loc["0000000123", "dirty_reason"] == "wrapper_hash"
    assert not by_cik.loc["0000000456", "dirty"]
    _, _, status = run()
    assert calls == ["123"]
    # a full invalidation is not triggered by one fund's wrapper
    assert status.iloc[0]["full_invalidation"] in (False, "False")
    calls.clear()
    run()
    assert calls == []


def test_a_source_encodings_edit_or_a_removed_wrapper_recomputes_that_fund(tmp_path, monkeypatch):
    import json
    run, calls, wrapper_dir = _two_fund_run(monkeypatch, tmp_path)
    run()
    calls.clear()
    path = wrapper_dir / "0000000456.json"
    wrapper = json.loads(path.read_text(encoding="utf-8"))
    wrapper["source_encodings"] = {"unfunded_rows": ["net_of_other_commitment"]}
    path.write_text(json.dumps(wrapper), encoding="utf-8")
    run()
    assert calls == ["456"]
    calls.clear()
    path.unlink()
    run()
    assert calls == ["456"]


def test_a_manifest_from_before_the_wrapper_hash_recomputes_funds_with_a_wrapper_once(tmp_path, monkeypatch):
    run, calls, wrapper_dir = _two_fund_run(monkeypatch, tmp_path)
    (wrapper_dir / "0000000456.json").unlink()
    run()
    calls.clear()
    manifest = pd.read_csv(sr.SOURCE_RECONCILIATION_CACHE_MANIFEST_FILE, dtype=str).drop(columns=["wrapper_hash"])
    manifest.to_csv(sr.SOURCE_RECONCILIATION_CACHE_MANIFEST_FILE, index=False)
    run()
    # 123 has a wrapper file, 456 has none ('' both before and after)
    assert calls == ["123"]
    calls.clear()
    run()
    assert calls == []


def test_wrapper_hash_is_empty_without_a_wrapper_file(tmp_path, monkeypatch):
    from pipeline import bdc_xbrl_wrapper
    monkeypatch.setattr(bdc_xbrl_wrapper, "_WRAPPER_DEFINITIONS_DIR", tmp_path)
    assert sr.compute_wrapper_hash("123") == ""
    (tmp_path / "0000000123.json").write_text("{}", encoding="utf-8")
    assert len(sr.compute_wrapper_hash("123")) == 64 and sr.compute_wrapper_hash("") == ""


# --- MAI-R2: instances with a >10 MB text node (huge_tree) ---------------------------

# libxml2's default limit on one text node is 10,000,000 bytes.
_HUGE_TEXT = "x" * 10_500_000


def _mm_body_with_huge_text_node() -> str:
    return _cash_equivalents_context(
        "ctx_mm", "DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember"
    ) + (
        '<us-gaap:InvestmentOwnedAtFairValue contextRef="ctx_mm" unitRef="usd" decimals="-3">65057000</us-gaap:InvestmentOwnedAtFairValue>'
        f'<us-gaap:RiskFactorsTextBlock contextRef="ctx_mm">{_HUGE_TEXT}</us-gaap:RiskFactorsTextBlock>'
    )


def test_huge_text_node_instance_is_read(tmp_path):
    import pytest
    from lxml import etree

    path = tmp_path / "mm.xml"
    path.write_text(_XML_HEADER + _mm_body_with_huge_text_node() + "</xbrl>", encoding="utf-8")
    with pytest.raises(etree.XMLSyntaxError):  # the fixture really exceeds the default limit
        etree.parse(str(path))

    rows = sr._extract_single_xbrl_source_file(path, dict(_FILING_META))
    assert len(rows) == 1
    assert rows[0]["fair_value"] == 65057000.0

    facts, status = sr._extract_single_xbrl_source_file_cached(path, dict(_FILING_META))
    assert status == "ok"
    assert len(facts) == 1


def test_huge_text_node_instance_missing_row_still_reported(tmp_path):
    # A huge-text instance with no investment fact yields no source rows (no_facts),
    # not a phantom row.
    body = _cash_equivalents_context(
        "ctx_mm", "DreyfusTreasuryObligationsCashManagementMoneyMarketFundMember"
    ) + f'<us-gaap:RiskFactorsTextBlock contextRef="ctx_mm">{_HUGE_TEXT}</us-gaap:RiskFactorsTextBlock>'
    path = tmp_path / "mm.xml"
    path.write_text(_XML_HEADER + body + "</xbrl>", encoding="utf-8")

    facts, status = sr._extract_single_xbrl_source_file_cached(path, dict(_FILING_META))
    assert status == "no_facts"
    assert facts.empty


def test_cached_parse_failure_is_retried_but_ok_is_reused(tmp_path, monkeypatch):
    _patch_cache_paths(monkeypatch, tmp_path)
    xml_a = tmp_path / "a.xml"
    xml_b = tmp_path / "b.xml"
    xml_a.write_text("<xbrl>a</xbrl>", encoding="utf-8")
    xml_b.write_text("<xbrl>b</xbrl>", encoding="utf-8")
    index = pd.concat([_filings_index(xml_a, "0001"), _filings_index(xml_b, "0002")],
                      ignore_index=True)
    calls: list[str] = []
    status_by_file = {"a.xml": "ok", "b.xml": "parse_failed"}

    def fake_extract(path, filing):
        name = Path(path).name
        calls.append(name)
        if status_by_file[name] == "parse_failed":
            return pd.DataFrame(columns=sr.SOURCE_FACT_COLUMNS), "parse_failed"
        return _source_fact(str(filing["accession_number"])), "ok"

    monkeypatch.setattr(sr, "_extract_single_xbrl_source_file_cached", fake_extract)
    sr.extract_bdc_source_facts_cached(filings_index_df=index)
    status_by_file["b.xml"] = "ok"  # the parser now reads it
    facts, manifest = sr.extract_bdc_source_facts_cached(filings_index_df=index)

    assert calls == ["a.xml", "b.xml", "b.xml"]
    assert set(manifest["parse_status"]) == {"ok"}
    assert len(facts) == 2
    # the changed parse_status moves the CIK's source_hash, so its partition recomputes
    first_hash = sr._compute_source_hashes(pd.DataFrame([
        {**manifest.iloc[1].to_dict(), "parse_status": "parse_failed", "fact_row_count": "0"},
    ]))
    second_hash = sr._compute_source_hashes(manifest.iloc[[1]])
    assert first_hash.iloc[0]["source_hash"] != second_hash.iloc[0]["source_hash"]
