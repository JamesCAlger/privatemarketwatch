import pandas as pd

from pipeline.bdc_sector_reconciliation import reconcile_bdc_sector_breakdown


def _holdings(cik: str, report_date: str, values: list[float]) -> list[dict[str, str]]:
    return [
        {
            "source": "bdc",
            "cik": cik,
            "report_date": report_date,
            "issuer_name": f"Issuer {i}",
            "fair_value": str(value),
        }
        for i, value in enumerate(values)
    ]


def _sector(cik: str, report_date: str, values: list[float]) -> list[dict[str, str]]:
    return [
        {
            "cik": cik,
            "entity_name": f"BDC {cik}",
            "report_date": report_date,
            "industry_sector": f"sector {i}",
            "investment_type": "",
            "fair_value": str(value),
            "cost": "",
            "pct_of_net_assets": "",
            "gics_sub_industry": "Software",
        }
        for i, value in enumerate(values)
    ]


def _run(sector_rows: list[dict[str, str]], holding_rows: list[dict[str, str]]):
    return reconcile_bdc_sector_breakdown(
        sector_df=pd.DataFrame(sector_rows),
        holdings_df=pd.DataFrame(holding_rows),
        write=False,
    )


def test_exact_match_passes():
    reconciliation, _ = _run(
        _sector("0001", "2025-03-31", [40_000_000, 60_000_000]),
        _holdings("0001", "2025-03-31", [100_000_000]),
    )

    assert reconciliation.loc[0, "reconciliation_status"] == "PASS"
    assert reconciliation.loc[0, "absolute_delta"] == 0


def test_ten_percent_mismatch_scales():
    reconciliation, reconciled = _run(
        _sector("0001", "2025-03-31", [44_000_000, 66_000_000]),
        _holdings("0001", "2025-03-31", [100_000_000]),
    )

    assert reconciliation.loc[0, "reconciliation_status"] == "SCALE"
    assert round(reconciled["reconciled_fair_value"].sum(), 6) == 100_000_000


def test_fifty_percent_mismatch_fails_review():
    reconciliation, reconciled = _run(
        _sector("0001", "2025-03-31", [150_000_000]),
        _holdings("0001", "2025-03-31", [100_000_000]),
    )

    assert reconciliation.loc[0, "reconciliation_status"] == "FAIL_REVIEW"
    assert reconciled.empty


def test_holdings_with_no_sector_rows_is_holdings_only():
    reconciliation, reconciled = _run(
        [],
        _holdings("0001", "2025-03-31", [100_000_000]),
    )

    assert reconciliation.loc[0, "reconciliation_status"] == "HOLDINGS_ONLY"
    assert reconciled.empty


def test_sector_rows_with_no_holdings_are_sector_only():
    reconciliation, reconciled = _run(
        _sector("0001", "2025-03-31", [100_000_000]),
        [],
    )

    assert reconciliation.loc[0, "reconciliation_status"] == "SECTOR_ONLY"
    assert reconciled.empty


def test_scaling_preserves_per_cik_holdings_fair_value():
    _, reconciled = _run(
        _sector("0001", "2025-03-31", [55_000_000, 33_000_000, 22_000_000]),
        _holdings("0001", "2025-03-31", [70_000_000, 30_000_000]),
    )

    assert abs(reconciled["reconciled_fair_value"].sum() - 100_000_000) < 1e-6
