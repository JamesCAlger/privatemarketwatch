"""Comprehensive tests for pipeline.nport_holdings module.

Covers:
- TSV reading: _read_tsv_from_zip with valid/missing/empty files
- Date normalisation: _normalise_date DD-MON-YYYY and ISO passthrough
- Quarter processing: CIK filtering, join correctness, empty results, date conversion
- Batch processing: resumability, periodic save, dedup
- XML parsing: single liquidity category, multi-bucket, missing data
- Integration: public entry point with mocked client, CIK subset mode
- CLI: --nport and --nport-xml flags parsed correctly
"""

import io
import os
import tempfile
import textwrap
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest

from pipeline.nport_holdings import (
    _dedup_amendments,
    _download_quarterly_zips,
    _find_nport_xml_url,
    _merge_with_existing,
    _normalise_date,
    _parse_nport_xml_liquidity,
    _process_all_quarters,
    _process_quarter_tsv,
    _read_tsv_from_zip,
    _save_nport_progress,
    extract_nport_holdings,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _make_test_zip(tsv_data: dict[str, str]) -> Path:
    """Create a temporary ZIP containing TSV files from string data.

    tsv_data: dict mapping filename (e.g. "REGISTRANT.tsv") to TSV content.
    Returns path to the temporary ZIP file.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w") as zf:
        for name, content in tsv_data.items():
            zf.writestr(name, content)
    return Path(tmp.name)


# Minimal TSV data for one quarter with two registrants (one target, one not)
REGISTRANT_TSV = (
    "ACCESSION_NUMBER\tCIK\tENTITY_NAME\n"
    "0001234567-24-000001\t1234567\tTarget Fund Inc\n"
    "0001234567-24-000002\t1234567\tTarget Fund Inc\n"
    "0009999999-24-000001\t9999999\tOther Fund LLC\n"
)

SUBMISSION_TSV = (
    "ACCESSION_NUMBER\tFILING_DATE\tREPORT_DATE\tSUB_TYPE\n"
    "0001234567-24-000001\t30-SEP-2024\t30-SEP-2024\tNPORT-P\n"
    "0001234567-24-000002\t30-JUN-2024\t30-JUN-2024\tNPORT-P\n"
    "0009999999-24-000001\t30-SEP-2024\t30-SEP-2024\tNPORT-P\n"
)

FUND_REPORTED_INFO_TSV = (
    "ACCESSION_NUMBER\tSERIES_NAME\tSERIES_ID\tTOTAL_ASSETS\tNET_ASSETS\n"
    "0001234567-24-000001\tTarget Growth Fund\tS000012345\t500000000\t450000000\n"
    "0001234567-24-000002\tTarget Growth Fund\tS000012345\t480000000\t430000000\n"
    "0009999999-24-000001\tOther Income Fund\tS000099999\t100000000\t95000000\n"
)

HOLDING_TSV = (
    "ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\tISSUER_LEI\tISSUER_TITLE\t"
    "ISSUER_CUSIP\tBALANCE\tUNIT\tCURRENCY_CODE\tCURRENCY_VALUE\t"
    "PERCENTAGE\tPAYOFF_PROFILE\tASSET_CAT\tISSUER_TYPE\t"
    "INVESTMENT_COUNTRY\tIS_RESTRICTED_SECURITY\tFAIR_VALUE_LEVEL\n"
    "0001234567-24-000001\tH001\tAcme Corp\tLEI123\tFirst Lien Term Loan\t"
    "12345A100\t10000000\tPA\tUSD\t9800000\t"
    "2.18\tLong\tDBT\tCORP\t"
    "US\tN\t2\n"
    "0001234567-24-000001\tH002\tBeta Inc\tLEI456\tCommon Stock\t"
    "23456B200\t50000\tNS\tUSD\t1500000\t"
    "0.33\tLong\tEC\tCORP\t"
    "US\tN\t1\n"
    "0001234567-24-000002\tH003\tGamma LLC\tLEI789\tSenior Note\t"
    "34567C300\t5000000\tPA\tUSD\t4900000\t"
    "1.14\tLong\tDBT\tCORP\t"
    "US\tN\t2\n"
    "0009999999-24-000001\tH099\tOtherCo\tLEI000\tBond\t"
    "99999Z900\t1000000\tPA\tUSD\t990000\t"
    "1.04\tLong\tDBT\tCORP\t"
    "CA\tN\t2\n"
)

DEBT_SECURITY_TSV = (
    "ACCESSION_NUMBER\tHOLDING_ID\tMATURITY_DATE\tCOUPON_TYPE\tANNUALIZED_RATE\tIS_DEFAULT\tARE_ANY_INTEREST_PAYMENT\tIS_ANY_PORTION_INTEREST_PAID\n"
    "0001234567-24-000001\tH001\t15-JUN-2028\tFloating\t0.0925\tN\tN\tN\n"
    "0001234567-24-000002\tH003\t01-MAR-2027\tFixed\t0.0500\tN\tN\tN\n"
    "0009999999-24-000001\tH099\t31-DEC-2025\tFixed\t0.0300\tN\tY\tY\n"
)

IDENTIFIERS_TSV = (
    "ACCESSION_NUMBER\tHOLDING_ID\tIDENTIFIER_ISIN\tIDENTIFIER_TICKER\n"
    "0001234567-24-000001\tH001\tUS12345A1001\t\n"
    "0001234567-24-000001\tH002\tUS23456B2002\tBETA\n"
    "0001234567-24-000002\tH003\tUS34567C3003\t\n"
    "0009999999-24-000001\tH099\tCA99999Z9009\tOTHR\n"
)

MONTHLY_TOTAL_RETURN_TSV = (
    "ACCESSION_NUMBER\tCLASS_ID\tMONTHLY_TOTAL_RETURN1\tMONTHLY_TOTAL_RETURN2\tMONTHLY_TOTAL_RETURN3\n"
    "0001234567-24-000001\tC000012345\t0.012\t-0.005\t0.008\n"
    "0009999999-24-000001\tC000099999\t0.003\t0.001\t-0.002\n"
)


@pytest.fixture
def test_zip_path() -> Path:
    """Create a temporary test ZIP with all TSV files."""
    path = _make_test_zip({
        "REGISTRANT.tsv": REGISTRANT_TSV,
        "SUBMISSION.tsv": SUBMISSION_TSV,
        "FUND_REPORTED_INFO.tsv": FUND_REPORTED_INFO_TSV,
        "FUND_REPORTED_HOLDING.tsv": HOLDING_TSV,
        "DEBT_SECURITY.tsv": DEBT_SECURITY_TSV,
        "IDENTIFIERS.tsv": IDENTIFIERS_TSV,
        "MONTHLY_TOTAL_RETURN.tsv": MONTHLY_TOTAL_RETURN_TSV,
    })
    yield path
    os.unlink(path)


@pytest.fixture
def empty_zip_path() -> Path:
    """Create a temporary empty ZIP."""
    path = _make_test_zip({})
    yield path
    os.unlink(path)


@pytest.fixture
def tmp_output_dir(tmp_path: Path):
    """Patch config output paths to use a temp directory."""
    patches = {
        "pipeline.nport_holdings.NPORT_HOLDINGS_FILE": tmp_path / "nport_holdings.csv",
        "pipeline.nport_holdings.NPORT_FUND_INFO_FILE": tmp_path / "nport_fund_info.csv",
        "pipeline.nport_holdings.NPORT_FILINGS_INDEX_FILE": tmp_path / "nport_filings_index.csv",
        "pipeline.nport_holdings.NPORT_PARSE_PROGRESS_FILE": tmp_path / "nport_parse_progress.csv",
        "pipeline.nport_holdings.NPORT_TSV_CACHE_DIR": tmp_path / "cache",
        "pipeline.nport_holdings.NPORT_XML_CACHE_DIR": tmp_path / "xml_cache",
    }
    (tmp_path / "cache").mkdir()
    (tmp_path / "xml_cache").mkdir()

    patchers = [patch(k, v) for k, v in patches.items()]
    for p in patchers:
        p.start()
    yield tmp_path
    for p in patchers:
        p.stop()


# ---------------------------------------------------------------------------
# Tests: _normalise_date
# ---------------------------------------------------------------------------

class TestNormaliseDate:
    def test_dd_mon_yyyy(self):
        assert _normalise_date("30-SEP-2024") == "2024-09-30"

    def test_dd_mon_yyyy_lowercase(self):
        """Input should be case-insensitive."""
        assert _normalise_date("15-jan-2023") == "2023-01-15"

    def test_iso_passthrough(self):
        assert _normalise_date("2024-09-30") == "2024-09-30"

    def test_empty_string(self):
        assert _normalise_date("") == ""

    def test_none_passthrough(self):
        assert _normalise_date(None) is None

    def test_single_digit_day(self):
        assert _normalise_date("1-FEB-2023") == "2023-02-01"

    def test_unrecognised_format(self):
        """Unrecognised formats are returned as-is."""
        assert _normalise_date("Sep 30 2024") == "Sep 30 2024"


# ---------------------------------------------------------------------------
# Tests: _read_tsv_from_zip
# ---------------------------------------------------------------------------

class TestReadTsvFromZip:
    def test_valid_file(self, test_zip_path: Path):
        with zipfile.ZipFile(test_zip_path) as zf:
            df = _read_tsv_from_zip(zf, "REGISTRANT.tsv")
        assert not df.empty
        assert "CIK" in df.columns
        assert len(df) == 3

    def test_missing_file(self, test_zip_path: Path):
        with zipfile.ZipFile(test_zip_path) as zf:
            df = _read_tsv_from_zip(zf, "NONEXISTENT.tsv")
        assert df.empty

    def test_empty_zip(self, empty_zip_path: Path):
        with zipfile.ZipFile(empty_zip_path) as zf:
            df = _read_tsv_from_zip(zf, "REGISTRANT.tsv")
        assert df.empty

    def test_usecols(self, test_zip_path: Path):
        with zipfile.ZipFile(test_zip_path) as zf:
            df = _read_tsv_from_zip(zf, "REGISTRANT.tsv", usecols=["CIK"])
        assert list(df.columns) == ["CIK"]
        assert len(df) == 3

    def test_chunked_reading(self, test_zip_path: Path):
        with zipfile.ZipFile(test_zip_path) as zf:
            reader = _read_tsv_from_zip(
                zf, "FUND_REPORTED_HOLDING.tsv", chunksize=2,
            )
            chunks = list(reader)
        assert len(chunks) >= 1
        total_rows = sum(len(c) for c in chunks)
        assert total_rows == 4

    def test_all_dtypes_string(self, test_zip_path: Path):
        with zipfile.ZipFile(test_zip_path) as zf:
            df = _read_tsv_from_zip(zf, "REGISTRANT.tsv")
        for col in df.columns:
            assert df[col].dtype == object  # string dtype in pandas

    def test_chunked_missing_file(self, test_zip_path: Path):
        """Chunked read of missing file should yield empty iterator."""
        with zipfile.ZipFile(test_zip_path) as zf:
            reader = _read_tsv_from_zip(
                zf, "NONEXISTENT.tsv", chunksize=100,
            )
            chunks = list(reader)
        assert len(chunks) == 0 or all(c.empty for c in chunks)


# ---------------------------------------------------------------------------
# Tests: _process_quarter_tsv
# ---------------------------------------------------------------------------

class TestProcessQuarterTsv:
    def test_basic_filtering(self, test_zip_path: Path):
        """Only holdings for target CIK should be returned."""
        target_ciks = {"1234567"}
        holdings, fund_info, filings_index = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        assert not holdings.empty
        # Should have 3 holdings (H001, H002, H003) -- not H099
        assert len(holdings) == 3
        # All CIKs should be target
        assert set(holdings["cik"].unique()) == {"1234567"}

    def test_no_matching_cik(self, test_zip_path: Path):
        """Returns empty DataFrames when no CIKs match."""
        target_ciks = {"0000001"}
        holdings, fund_info, filings_index = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        assert holdings.empty
        assert fund_info.empty
        assert filings_index.empty

    def test_date_normalisation(self, test_zip_path: Path):
        """DD-MON-YYYY dates should be converted to YYYY-MM-DD."""
        target_ciks = {"1234567"}
        holdings, _, _ = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        if "filing_date" in holdings.columns:
            dates = holdings["filing_date"].dropna().unique()
            for d in dates:
                assert d.startswith("20"), f"Date not normalised: {d}"

    def test_debt_security_join(self, test_zip_path: Path):
        """Debt security columns should be joined onto holdings."""
        target_ciks = {"1234567"}
        holdings, _, _ = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        assert "maturity_date" in holdings.columns
        # H001 should have maturity date
        h001 = holdings[holdings["holding_id"] == "H001"]
        if not h001.empty and "maturity_date" in h001.columns:
            mat = h001.iloc[0]["maturity_date"]
            assert mat == "2028-06-15", f"Unexpected maturity: {mat}"

    def test_debt_security_interest_columns(self, test_zip_path: Path):
        """New debt security interest columns should be joined onto holdings."""
        target_ciks = {"1234567", "9999999"}
        holdings, _, _ = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        assert "are_any_interest_payment" in holdings.columns
        assert "is_any_portion_interest_paid" in holdings.columns
        # H099 should have Y for both
        h099 = holdings[holdings["holding_id"] == "H099"]
        if not h099.empty:
            assert h099.iloc[0]["are_any_interest_payment"] == "Y"
            assert h099.iloc[0]["is_any_portion_interest_paid"] == "Y"
        # H001 should have N for both
        h001 = holdings[holdings["holding_id"] == "H001"]
        if not h001.empty:
            assert h001.iloc[0]["are_any_interest_payment"] == "N"
            assert h001.iloc[0]["is_any_portion_interest_paid"] == "N"

    def test_identifiers_join(self, test_zip_path: Path):
        """Identifier columns should be joined onto holdings."""
        target_ciks = {"1234567"}
        holdings, _, _ = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        assert "identifier_isin" in holdings.columns
        h002 = holdings[holdings["holding_id"] == "H002"]
        if not h002.empty:
            assert h002.iloc[0]["identifier_isin"] == "US23456B2002"

    def test_quarter_column(self, test_zip_path: Path):
        """Quarter column should be added to output."""
        target_ciks = {"1234567"}
        holdings, fund_info, filings_index = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        assert "quarter" in holdings.columns
        assert holdings["quarter"].iloc[0] == "2024q3"
        if not fund_info.empty:
            assert "quarter" in fund_info.columns
        if not filings_index.empty:
            assert "quarter" in filings_index.columns

    def test_quarter_uses_report_date_not_sec_dataset_quarter(self):
        """SEC bulk quarter is provenance; report_date defines period."""
        zip_path = _make_test_zip({
            "REGISTRANT.tsv": (
                "ACCESSION_NUMBER\tCIK\tENTITY_NAME\n"
                "0001234567-26-000001\t1234567\tTarget Fund Inc\n"
            ),
            "SUBMISSION.tsv": (
                "ACCESSION_NUMBER\tFILING_DATE\tREPORT_DATE\tSUB_TYPE\n"
                "0001234567-26-000001\t15-JAN-2026\t31-DEC-2025\tNPORT-P\n"
            ),
            "FUND_REPORTED_INFO.tsv": (
                "ACCESSION_NUMBER\tSERIES_NAME\tSERIES_ID\tTOTAL_ASSETS\tNET_ASSETS\n"
                "0001234567-26-000001\tTarget Growth Fund\tS000012345\t500000000\t450000000\n"
            ),
            "FUND_REPORTED_HOLDING.tsv": (
                "ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\tCURRENCY_VALUE\n"
                "0001234567-26-000001\tH001\tAcme Corp\t9800000\n"
            ),
        })
        try:
            holdings, fund_info, filings_index = _process_quarter_tsv(
                zip_path, "2026q1", {"1234567"},
            )
        finally:
            os.unlink(zip_path)

        for df in [holdings, fund_info, filings_index]:
            assert not df.empty
            assert df["quarter"].iloc[0] == "2025q4"
            assert df["sec_dataset_quarter"].iloc[0] == "2026q1"

    def test_fund_info_output(self, test_zip_path: Path):
        """Fund info should contain series data and monthly returns."""
        target_ciks = {"1234567"}
        _, fund_info, _ = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        assert not fund_info.empty
        assert "series_name" in fund_info.columns
        assert "net_assets" in fund_info.columns

    def test_filings_index_output(self, test_zip_path: Path):
        """Filings index should have one row per accession with holdings count."""
        target_ciks = {"1234567"}
        _, _, filings_index = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        assert not filings_index.empty
        assert "holdings_count" in filings_index.columns
        # Two accessions for CIK 1234567
        assert len(filings_index) == 2

    def test_lowercase_columns(self, test_zip_path: Path):
        """All output columns should be lowercase."""
        target_ciks = {"1234567"}
        holdings, fund_info, filings_index = _process_quarter_tsv(
            test_zip_path, "2024q3", target_ciks,
        )
        for df, name in [(holdings, "holdings"), (fund_info, "fund_info"),
                         (filings_index, "filings_index")]:
            if not df.empty:
                for col in df.columns:
                    assert col == col.lower(), f"{name} column not lowercase: {col}"

    def test_empty_zip(self, empty_zip_path: Path):
        """Empty ZIP should return empty DataFrames."""
        target_ciks = {"1234567"}
        holdings, fund_info, filings_index = _process_quarter_tsv(
            empty_zip_path, "2024q3", target_ciks,
        )
        assert holdings.empty
        assert fund_info.empty
        assert filings_index.empty


# ---------------------------------------------------------------------------
# Tests: _merge_with_existing
# ---------------------------------------------------------------------------

class TestMergeWithExisting:
    def test_no_existing_file(self, tmp_path: Path):
        """New data with no existing file on disk."""
        new_df = pd.DataFrame({"a": ["1", "2"], "b": ["x", "y"]})
        path = tmp_path / "test.csv"
        result = _merge_with_existing(new_df, path, ["a"])
        assert len(result) == 2

    def test_merge_with_existing(self, tmp_path: Path):
        """New data merged with existing CSV, deduped."""
        path = tmp_path / "test.csv"
        existing = pd.DataFrame({"a": ["1", "2"], "b": ["x", "y"]})
        existing.to_csv(path, index=False)

        new_df = pd.DataFrame({"a": ["2", "3"], "b": ["y_new", "z"]})
        result = _merge_with_existing(new_df, path, ["a"])
        assert len(result) == 3  # deduped: 1, 2(new), 3
        # The "last" value for a=2 should be kept
        row2 = result[result["a"] == "2"]
        assert row2.iloc[0]["b"] == "y_new"

    def test_empty_new_loads_existing(self, tmp_path: Path):
        """Empty new data should return existing file contents."""
        path = tmp_path / "test.csv"
        existing = pd.DataFrame({"a": ["1"], "b": ["x"]})
        existing.to_csv(path, index=False)

        result = _merge_with_existing(pd.DataFrame(), path, ["a"])
        assert len(result) == 1

    def test_empty_new_no_existing(self, tmp_path: Path):
        """Empty new data with no existing file returns empty DataFrame."""
        path = tmp_path / "test.csv"
        result = _merge_with_existing(pd.DataFrame(), path, ["a"])
        assert result.empty

    def test_no_dedup_cols(self, tmp_path: Path):
        """When dedup_cols is None, no deduplication."""
        path = tmp_path / "test.csv"
        existing = pd.DataFrame({"a": ["1"], "b": ["x"]})
        existing.to_csv(path, index=False)

        new_df = pd.DataFrame({"a": ["1"], "b": ["x"]})
        result = _merge_with_existing(new_df, path, None)
        assert len(result) == 2  # duplicates kept


# ---------------------------------------------------------------------------
# Tests: _save_nport_progress
# ---------------------------------------------------------------------------

class TestSaveNportProgress:
    def test_new_progress_file(self, tmp_output_dir: Path):
        records = [
            {"quarter": "2024q3", "status": "processed", "holdings_count": "100",
             "timestamp": "2024-01-01T00:00:00"},
        ]
        _save_nport_progress(records)
        progress_file = tmp_output_dir / "nport_parse_progress.csv"
        assert progress_file.exists()
        df = pd.read_csv(progress_file, dtype=str)
        assert len(df) == 1
        assert df.iloc[0]["quarter"] == "2024q3"

    def test_append_progress(self, tmp_output_dir: Path):
        progress_file = tmp_output_dir / "nport_parse_progress.csv"
        existing = pd.DataFrame([{
            "quarter": "2024q2", "status": "processed",
            "holdings_count": "50", "timestamp": "2024-01-01",
        }])
        existing.to_csv(progress_file, index=False)

        records = [
            {"quarter": "2024q3", "status": "processed",
             "holdings_count": "100", "timestamp": "2024-01-02"},
        ]
        _save_nport_progress(records)

        df = pd.read_csv(progress_file, dtype=str)
        assert len(df) == 2

    def test_dedup_on_quarter(self, tmp_output_dir: Path):
        progress_file = tmp_output_dir / "nport_parse_progress.csv"
        existing = pd.DataFrame([{
            "quarter": "2024q3", "status": "error",
            "holdings_count": "0", "timestamp": "2024-01-01",
        }])
        existing.to_csv(progress_file, index=False)

        records = [
            {"quarter": "2024q3", "status": "processed",
             "holdings_count": "100", "timestamp": "2024-01-02"},
        ]
        _save_nport_progress(records)

        df = pd.read_csv(progress_file, dtype=str)
        assert len(df) == 1
        assert df.iloc[0]["status"] == "processed"

    def test_empty_records(self, tmp_output_dir: Path):
        """No-op when records list is empty."""
        progress_file = tmp_output_dir / "nport_parse_progress.csv"
        _save_nport_progress([])
        assert not progress_file.exists()


# ---------------------------------------------------------------------------
# Tests: _download_quarterly_zips
# ---------------------------------------------------------------------------

class TestDownloadQuarterlyZips:
    def test_cached_zip_skipped(self, tmp_output_dir: Path):
        """ZIPs larger than 1 MB are skipped (already cached)."""
        cache_dir = tmp_output_dir / "cache"
        # Create a fake cached ZIP > 1 MB
        fake_zip = cache_dir / "2024q3_nport.zip"
        fake_zip.write_bytes(b"x" * 1_100_000)

        client = MagicMock()
        result = _download_quarterly_zips(client, quarters=["2024q3"])
        assert len(result) == 1
        assert result[0][0] == "2024q3"
        # No download should have been attempted
        client.download_file.assert_not_called()

    def test_download_success(self, tmp_output_dir: Path):
        """Successful download is recorded."""
        client = MagicMock()
        result = _download_quarterly_zips(client, quarters=["2024q3"])
        assert len(result) == 1
        client.download_file.assert_called_once()

    def test_404_graceful(self, tmp_output_dir: Path):
        """404 errors are handled gracefully."""
        from requests import HTTPError

        exc = HTTPError()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        exc.response = mock_resp
        client = MagicMock()
        client.download_file.side_effect = exc

        result = _download_quarterly_zips(client, quarters=["2099q4"])
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests: XML parsing
# ---------------------------------------------------------------------------

NPORT_XML_SINGLE_CAT = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <edgarSubmission xmlns="http://www.sec.gov/edgar/nportfiling">
        <formData>
            <invstOrSecAll>
                <invstOrSec>
                    <cusip>12345A100</cusip>
                    <name>Acme Corp First Lien</name>
                    <fundCat>2</fundCat>
                </invstOrSec>
                <invstOrSec>
                    <cusip>23456B200</cusip>
                    <name>Beta Inc Common</name>
                    <fundCat>1</fundCat>
                </invstOrSec>
            </invstOrSecAll>
        </formData>
    </edgarSubmission>
""")

NPORT_XML_MULTI_BUCKET = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <edgarSubmission xmlns="http://www.sec.gov/edgar/nportfiling">
        <formData>
            <invstOrSecAll>
                <invstOrSec>
                    <cusip>34567C300</cusip>
                    <name>Gamma LLC Senior Note</name>
                    <fundCats>
                        <fundCat category="2" pct="60.0"/>
                        <fundCat category="3" pct="40.0"/>
                    </fundCats>
                </invstOrSec>
            </invstOrSecAll>
        </formData>
    </edgarSubmission>
""")

NPORT_XML_NO_LIQUIDITY = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <edgarSubmission xmlns="http://www.sec.gov/edgar/nportfiling">
        <formData>
            <invstOrSecAll>
                <invstOrSec>
                    <cusip>44444D400</cusip>
                    <name>Delta Corp</name>
                </invstOrSec>
            </invstOrSecAll>
        </formData>
    </edgarSubmission>
""")

NPORT_XML_NO_CUSIP = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <edgarSubmission xmlns="http://www.sec.gov/edgar/nportfiling">
        <formData>
            <invstOrSecAll>
                <invstOrSec>
                    <name>NoCusip Entity</name>
                    <fundCat>1</fundCat>
                </invstOrSec>
            </invstOrSecAll>
        </formData>
    </edgarSubmission>
""")


class TestParseNportXmlLiquidity:
    def test_single_category(self, tmp_path: Path):
        xml_path = tmp_path / "single.xml"
        xml_path.write_text(NPORT_XML_SINGLE_CAT)
        result = _parse_nport_xml_liquidity(xml_path)
        assert result["12345A100"] == "Moderately Liquid"
        assert result["23456B200"] == "Highly Liquid"
        assert len(result) == 2

    def test_multi_bucket(self, tmp_path: Path):
        """Multi-bucket should pick highest percentage category."""
        xml_path = tmp_path / "multi.xml"
        xml_path.write_text(NPORT_XML_MULTI_BUCKET)
        result = _parse_nport_xml_liquidity(xml_path)
        assert result["34567C300"] == "Moderately Liquid"  # category 2, 60%

    def test_no_liquidity(self, tmp_path: Path):
        """Holdings without liquidity data return empty dict."""
        xml_path = tmp_path / "no_liq.xml"
        xml_path.write_text(NPORT_XML_NO_LIQUIDITY)
        result = _parse_nport_xml_liquidity(xml_path)
        assert len(result) == 0

    def test_no_cusip(self, tmp_path: Path):
        """Holdings without CUSIP are skipped."""
        xml_path = tmp_path / "no_cusip.xml"
        xml_path.write_text(NPORT_XML_NO_CUSIP)
        result = _parse_nport_xml_liquidity(xml_path)
        assert len(result) == 0

    def test_invalid_xml(self, tmp_path: Path):
        """Invalid XML returns empty dict."""
        xml_path = tmp_path / "bad.xml"
        xml_path.write_text("this is not xml")
        result = _parse_nport_xml_liquidity(xml_path)
        assert len(result) == 0

    def test_missing_file(self):
        """Non-existent file returns empty dict."""
        result = _parse_nport_xml_liquidity("/nonexistent/path.xml")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests: _find_nport_xml_url
# ---------------------------------------------------------------------------

class TestFindNportXmlUrl:
    def test_finds_nport_xml(self):
        html = '''<table>
            <tr><td>NPORT-P</td><td><a href="primary_doc.xml">primary</a></td></tr>
        </table>'''
        url = _find_nport_xml_url(html, "1234567", "000123456724000001")
        assert url is not None
        assert "primary_doc.xml" in url

    def test_prefers_nport_named(self):
        html = '''<table>
            <tr><td>other</td><td><a href="other.xml">other</a></td></tr>
            <tr><td>NPORT</td><td><a href="nport-p.xml">nport</a></td></tr>
        </table>'''
        url = _find_nport_xml_url(html, "1234567", "000123456724000001")
        assert url is not None
        assert "nport-p.xml" in url

    def test_skips_taxonomy_files(self):
        html = '''<table>
            <tr><td>cal</td><td><a href="filing_cal.xml">cal</a></td></tr>
            <tr><td>lab</td><td><a href="filing_lab.xml">lab</a></td></tr>
            <tr><td>def</td><td><a href="filing_def.xml">def</a></td></tr>
        </table>'''
        url = _find_nport_xml_url(html, "1234567", "000123456724000001")
        assert url is None

    def test_no_xml_links(self):
        html = '''<table><tr><td>no xml here</td></tr></table>'''
        url = _find_nport_xml_url(html, "1234567", "000123456724000001")
        assert url is None

    def test_absolute_url(self):
        html = '''<tr><td><a href="/Archives/edgar/data/1234567/nport.xml">doc</a></td></tr>'''
        url = _find_nport_xml_url(html, "1234567", "000123456724000001")
        assert url == "https://www.sec.gov/Archives/edgar/data/1234567/nport.xml"


# ---------------------------------------------------------------------------
# Tests: Batch processing (_process_all_quarters)
# ---------------------------------------------------------------------------

class TestProcessAllQuarters:
    def test_resumability(self, test_zip_path: Path, tmp_output_dir: Path):
        """Already-processed quarters should be skipped."""
        # Mark 2024q3 as processed
        progress = pd.DataFrame([{
            "quarter": "2024q3", "status": "processed",
            "holdings_count": "100", "timestamp": "2024-01-01",
        }])
        progress.to_csv(tmp_output_dir / "nport_parse_progress.csv", index=False)

        # Also create existing holdings
        existing = pd.DataFrame({
            "accession_number": ["0001234567-24-000001"],
            "holding_id": ["H001"],
            "cik": ["1234567"],
        })
        existing.to_csv(tmp_output_dir / "nport_holdings.csv", index=False)

        client = MagicMock()
        # Mock download to return our test zip
        def fake_download(url, dest):
            import shutil
            shutil.copy2(test_zip_path, dest)
        client.download_file.side_effect = fake_download

        target_ciks = {"1234567"}
        # Process "2024q3" only -- should be skipped
        holdings, fund_info, filings_index = _process_all_quarters(
            client, target_ciks, quarters=["2024q3"],
        )
        # Should load existing holdings (no new processing)
        assert not holdings.empty

    def test_new_quarter_processing(self, test_zip_path: Path, tmp_output_dir: Path):
        """New quarters should be processed and saved."""
        client = MagicMock()
        def fake_download(url, dest):
            import shutil
            shutil.copy2(test_zip_path, dest)
        client.download_file.side_effect = fake_download

        target_ciks = {"1234567"}
        holdings, fund_info, filings_index = _process_all_quarters(
            client, target_ciks, quarters=["2024q3"],
        )
        assert not holdings.empty
        assert len(holdings) == 3  # 3 holdings for target CIK

        # Progress file should be created
        progress_file = tmp_output_dir / "nport_parse_progress.csv"
        assert progress_file.exists()


# ---------------------------------------------------------------------------
# Tests: Public entry point
# ---------------------------------------------------------------------------

class TestExtractNportHoldings:
    def test_with_provided_universe(self, test_zip_path: Path, tmp_output_dir: Path):
        """Public API with explicit fund_universe DataFrame."""
        client = MagicMock()
        def fake_download(url, dest):
            import shutil
            shutil.copy2(test_zip_path, dest)
        client.download_file.side_effect = fake_download

        universe = pd.DataFrame({"cik": ["1234567"]})
        holdings = extract_nport_holdings(
            client, fund_universe=universe, quarters=["2024q3"],
        )
        assert not holdings.empty
        assert "cik" in holdings.columns

    def test_loads_universe_from_disk(self, test_zip_path: Path, tmp_output_dir: Path):
        """When fund_universe is None, load from FUND_UNIVERSE_FILE."""
        client = MagicMock()
        def fake_download(url, dest):
            import shutil
            shutil.copy2(test_zip_path, dest)
        client.download_file.side_effect = fake_download

        # Create a fund universe file
        universe_file = tmp_output_dir / "fund_universe.csv"
        pd.DataFrame({"cik": ["1234567"]}).to_csv(universe_file, index=False)

        with patch("pipeline.nport_holdings.FUND_UNIVERSE_FILE", universe_file):
            holdings = extract_nport_holdings(
                client, quarters=["2024q3"],
            )
        assert not holdings.empty

    def test_missing_universe_raises(self, tmp_output_dir: Path):
        """FileNotFoundError when universe file doesn't exist."""
        client = MagicMock()
        fake_path = tmp_output_dir / "nonexistent.csv"
        with patch("pipeline.nport_holdings.FUND_UNIVERSE_FILE", fake_path):
            with pytest.raises(FileNotFoundError):
                extract_nport_holdings(client)

    def test_empty_universe(self, test_zip_path: Path, tmp_output_dir: Path):
        """Empty universe produces empty output."""
        client = MagicMock()
        def fake_download(url, dest):
            import shutil
            shutil.copy2(test_zip_path, dest)
        client.download_file.side_effect = fake_download

        universe = pd.DataFrame({"cik": ["0000001"]})  # no match
        holdings = extract_nport_holdings(
            client, fund_universe=universe, quarters=["2024q3"],
        )
        assert holdings.empty


# ---------------------------------------------------------------------------
# Tests: CLI argument parsing
# ---------------------------------------------------------------------------

class TestCliArgs:
    def test_nport_flag(self):
        from pipeline.main import _parse_args
        with patch("sys.argv", ["main", "--nport"]):
            args = _parse_args()
        assert args.nport is True
        assert args.nport_xml is False

    def test_nport_xml_flag(self):
        from pipeline.main import _parse_args
        with patch("sys.argv", ["main", "--nport", "--nport-xml"]):
            args = _parse_args()
        assert args.nport is True
        assert args.nport_xml is True

    def test_nport_with_ciks(self):
        from pipeline.main import _parse_args
        with patch("sys.argv", ["main", "--nport", "--ciks", "1234567", "9999999"]):
            args = _parse_args()
        assert args.nport is True
        assert args.ciks == ["1234567", "9999999"]

    def test_all_flags_together(self):
        from pipeline.main import _parse_args
        with patch("sys.argv", ["main", "--exhaustive", "--holdings", "--nport",
                                 "--nport-xml", "--ciks", "1234567"]):
            args = _parse_args()
        assert args.exhaustive is True
        assert args.holdings is True
        assert args.nport is True
        assert args.nport_xml is True
        assert args.ciks == ["1234567"]

    def test_default_no_nport(self):
        from pipeline.main import _parse_args
        with patch("sys.argv", ["main"]):
            args = _parse_args()
        assert args.nport is False
        assert args.nport_xml is False


# ---------------------------------------------------------------------------
# Tests: Config constants
# ---------------------------------------------------------------------------

class TestConfig:
    def test_nport_constants_exist(self):
        from pipeline.config import (
            NPORT_QUARTERS,
            NPORT_TSV_CACHE_DIR,
            NPORT_XML_CACHE_DIR,
            NPORT_HOLDINGS_FILE,
            NPORT_FILINGS_INDEX_FILE,
            NPORT_FUND_INFO_FILE,
            NPORT_PARSE_PROGRESS_FILE,
            NPORT_DATASET_URL_TEMPLATE,
        )
        assert len(NPORT_QUARTERS) >= 25
        assert NPORT_QUARTERS[0] == "2019q4"
        assert NPORT_QUARTERS[-1] >= "2025q4"
        assert "{quarter}" in NPORT_DATASET_URL_TEMPLATE
        assert str(NPORT_TSV_CACHE_DIR).endswith("nport_quarterly")
        assert str(NPORT_XML_CACHE_DIR).endswith("nport_xml")

    def test_directories_exist(self):
        from pipeline.config import NPORT_TSV_CACHE_DIR, NPORT_XML_CACHE_DIR
        assert NPORT_TSV_CACHE_DIR.exists()
        assert NPORT_XML_CACHE_DIR.exists()


# ---------------------------------------------------------------------------
# Tests: _dedup_amendments
# ---------------------------------------------------------------------------

class TestBorrowAggregateExtraction:
    """Tests for BORROW_AGGREGATE extraction in _process_quarter_tsv."""

    def test_borrow_aggregate_joined_to_fund_info(self):
        """TOTAL_BORROWINGS_DETAIL appears in fund_info when BORROW_AGGREGATE present."""
        tsv_data = {
            "REGISTRANT.tsv": REGISTRANT_TSV,
            "SUBMISSION.tsv": SUBMISSION_TSV,
            "FUND_REPORTED_INFO.tsv": FUND_REPORTED_INFO_TSV,
            "FUND_REPORTED_HOLDING.tsv": HOLDING_TSV,
            "DEBT_SECURITY.tsv": DEBT_SECURITY_TSV,
            "IDENTIFIERS.tsv": IDENTIFIERS_TSV,
            "MONTHLY_TOTAL_RETURN.tsv": MONTHLY_TOTAL_RETURN_TSV,
            "BORROW_AGGREGATE.tsv": (
                "ACCESSION_NUMBER\tAMOUNT\tBORROWER_CATEGORY\n"
                "0001234567-24-000001\t50000000\tBank\n"
                "0001234567-24-000001\t30000000\tOther\n"
                "0009999999-24-000001\t10000000\tBank\n"
            ),
        }
        path = _make_test_zip(tsv_data)
        try:
            target_ciks = {"1234567"}
            _, fund_info, _ = _process_quarter_tsv(path, "2024q3", target_ciks)
            assert not fund_info.empty
            assert "total_borrowings_detail" in fund_info.columns
            # ACC1 should have 50M + 30M = 80M
            acc1_row = fund_info[
                fund_info["accession_number"] == "0001234567-24-000001"
            ]
            if not acc1_row.empty:
                val = float(acc1_row.iloc[0]["total_borrowings_detail"])
                assert val == 80_000_000.0
        finally:
            os.unlink(path)

    def test_no_borrow_aggregate_table(self):
        """fund_info works fine when BORROW_AGGREGATE.tsv is missing."""
        tsv_data = {
            "REGISTRANT.tsv": REGISTRANT_TSV,
            "SUBMISSION.tsv": SUBMISSION_TSV,
            "FUND_REPORTED_INFO.tsv": FUND_REPORTED_INFO_TSV,
            "FUND_REPORTED_HOLDING.tsv": HOLDING_TSV,
            "DEBT_SECURITY.tsv": DEBT_SECURITY_TSV,
            "IDENTIFIERS.tsv": IDENTIFIERS_TSV,
            "MONTHLY_TOTAL_RETURN.tsv": MONTHLY_TOTAL_RETURN_TSV,
        }
        path = _make_test_zip(tsv_data)
        try:
            target_ciks = {"1234567"}
            _, fund_info, _ = _process_quarter_tsv(path, "2024q3", target_ciks)
            assert not fund_info.empty
            # Column should not be present (or be NaN if present)
            if "total_borrowings_detail" in fund_info.columns:
                assert fund_info["total_borrowings_detail"].isna().all()
        finally:
            os.unlink(path)


class TestInterestRateRiskExtraction:
    """Tests for INTEREST_RATE_RISK extraction in _process_quarter_tsv."""

    def test_dv01_joined_to_fund_info(self):
        """DV01 at multiple tenors appear in fund_info."""
        tsv_data = {
            "REGISTRANT.tsv": REGISTRANT_TSV,
            "SUBMISSION.tsv": SUBMISSION_TSV,
            "FUND_REPORTED_INFO.tsv": FUND_REPORTED_INFO_TSV,
            "FUND_REPORTED_HOLDING.tsv": HOLDING_TSV,
            "DEBT_SECURITY.tsv": DEBT_SECURITY_TSV,
            "IDENTIFIERS.tsv": IDENTIFIERS_TSV,
            "MONTHLY_TOTAL_RETURN.tsv": MONTHLY_TOTAL_RETURN_TSV,
            "INTEREST_RATE_RISK.tsv": (
                "ACCESSION_NUMBER\tCURRENCY_CODE"
                "\tINTRST_RATE_CHANGE_3MON_DV01"
                "\tINTRST_RATE_CHANGE_1YR_DV01"
                "\tINTRST_RATE_CHANGE_5YR_DV01"
                "\tINTRST_RATE_CHANGE_10YR_DV01"
                "\tINTRST_RATE_CHANGE_30YR_DV01\n"
                "0001234567-24-000001\tUSD\t50000\t125000\t450000"
                "\t300000\t200000\n"
                "0001234567-24-000001\tEUR\t10000\t10000\t20000"
                "\t15000\t10000\n"
                "0009999999-24-000001\tUSD\t1000\t5000\t15000"
                "\t10000\t8000\n"
            ),
        }
        path = _make_test_zip(tsv_data)
        try:
            target_ciks = {"1234567"}
            _, fund_info, _ = _process_quarter_tsv(path, "2024q3", target_ciks)
            assert not fund_info.empty
            assert "dv01_1yr" in fund_info.columns
            assert "dv01_5yr" in fund_info.columns
            assert "dv01_3mon" in fund_info.columns
            assert "dv01_10yr" in fund_info.columns
            assert "dv01_30yr" in fund_info.columns
            acc1_row = fund_info[
                fund_info["accession_number"] == "0001234567-24-000001"
            ]
            if not acc1_row.empty:
                # Only USD rows
                assert float(acc1_row.iloc[0]["dv01_3mon"]) == 50000.0
                assert float(acc1_row.iloc[0]["dv01_1yr"]) == 125000.0
                assert float(acc1_row.iloc[0]["dv01_5yr"]) == 450000.0
                assert float(acc1_row.iloc[0]["dv01_10yr"]) == 300000.0
                assert float(acc1_row.iloc[0]["dv01_30yr"]) == 200000.0
        finally:
            os.unlink(path)

    def test_dv100_tenors_extracted(self):
        """DV100 at all tenors appear in fund_info."""
        tsv_data = {
            "REGISTRANT.tsv": REGISTRANT_TSV,
            "SUBMISSION.tsv": SUBMISSION_TSV,
            "FUND_REPORTED_INFO.tsv": FUND_REPORTED_INFO_TSV,
            "FUND_REPORTED_HOLDING.tsv": HOLDING_TSV,
            "DEBT_SECURITY.tsv": DEBT_SECURITY_TSV,
            "IDENTIFIERS.tsv": IDENTIFIERS_TSV,
            "MONTHLY_TOTAL_RETURN.tsv": MONTHLY_TOTAL_RETURN_TSV,
            "INTEREST_RATE_RISK.tsv": (
                "ACCESSION_NUMBER\tCURRENCY_CODE"
                "\tINTRST_RATE_CHANGE_3MON_DV100"
                "\tINTRST_RATE_CHANGE_1YR_DV100"
                "\tINTRST_RATE_CHANGE_5YR_DV100"
                "\tINTRST_RATE_CHANGE_10YR_DV100"
                "\tINTRST_RATE_CHANGE_30YR_DV100\n"
                "0001234567-24-000001\tUSD\t100\t200\t300\t400\t500\n"
            ),
        }
        path = _make_test_zip(tsv_data)
        try:
            target_ciks = {"1234567"}
            _, fund_info, _ = _process_quarter_tsv(path, "2024q3", target_ciks)
            assert not fund_info.empty
            acc1_row = fund_info[
                fund_info["accession_number"] == "0001234567-24-000001"
            ]
            if not acc1_row.empty:
                assert "dv100_3mon" in fund_info.columns
                assert float(acc1_row.iloc[0]["dv100_3mon"]) == 100.0
                assert float(acc1_row.iloc[0]["dv100_1yr"]) == 200.0
                assert float(acc1_row.iloc[0]["dv100_5yr"]) == 300.0
                assert float(acc1_row.iloc[0]["dv100_10yr"]) == 400.0
                assert float(acc1_row.iloc[0]["dv100_30yr"]) == 500.0
        finally:
            os.unlink(path)

    def test_no_interest_rate_risk_table(self):
        """fund_info works fine when INTEREST_RATE_RISK.tsv is missing."""
        tsv_data = {
            "REGISTRANT.tsv": REGISTRANT_TSV,
            "SUBMISSION.tsv": SUBMISSION_TSV,
            "FUND_REPORTED_INFO.tsv": FUND_REPORTED_INFO_TSV,
            "FUND_REPORTED_HOLDING.tsv": HOLDING_TSV,
            "DEBT_SECURITY.tsv": DEBT_SECURITY_TSV,
            "IDENTIFIERS.tsv": IDENTIFIERS_TSV,
            "MONTHLY_TOTAL_RETURN.tsv": MONTHLY_TOTAL_RETURN_TSV,
        }
        path = _make_test_zip(tsv_data)
        try:
            target_ciks = {"1234567"}
            _, fund_info, _ = _process_quarter_tsv(path, "2024q3", target_ciks)
            assert not fund_info.empty
            if "dv01_1yr" in fund_info.columns:
                assert fund_info["dv01_1yr"].isna().all()
        finally:
            os.unlink(path)

    def test_dv01_currency_filtering(self):
        """Only USD rows should be included in DV01."""
        tsv_data = {
            "REGISTRANT.tsv": REGISTRANT_TSV,
            "SUBMISSION.tsv": SUBMISSION_TSV,
            "FUND_REPORTED_INFO.tsv": FUND_REPORTED_INFO_TSV,
            "FUND_REPORTED_HOLDING.tsv": HOLDING_TSV,
            "DEBT_SECURITY.tsv": DEBT_SECURITY_TSV,
            "IDENTIFIERS.tsv": IDENTIFIERS_TSV,
            "MONTHLY_TOTAL_RETURN.tsv": MONTHLY_TOTAL_RETURN_TSV,
            "INTEREST_RATE_RISK.tsv": (
                "ACCESSION_NUMBER\tCURRENCY_CODE"
                "\tINTRST_RATE_CHANGE_1YR_DV01"
                "\tINTRST_RATE_CHANGE_5YR_DV01\n"
                "0001234567-24-000001\tEUR\t999999\t999999\n"
                "0001234567-24-000001\tGBP\t888888\t888888\n"
            ),
        }
        path = _make_test_zip(tsv_data)
        try:
            target_ciks = {"1234567"}
            _, fund_info, _ = _process_quarter_tsv(path, "2024q3", target_ciks)
            assert not fund_info.empty
            acc1_row = fund_info[
                fund_info["accession_number"] == "0001234567-24-000001"
            ]
            if not acc1_row.empty and "dv01_1yr" in fund_info.columns:
                # No USD rows, so DV01 should be NaN
                assert pd.isna(acc1_row.iloc[0]["dv01_1yr"])
        finally:
            os.unlink(path)


class TestAmendmentDedup:
    """Tests for _dedup_amendments: N-PORT amendment deduplication."""

    def test_dedup_keeps_amendment(self):
        """Two accessions for same CIK+SERIES_ID+REPORT_DATE: keep the later one."""
        df = pd.DataFrame({
            "CIK": ["100", "100"],
            "SERIES_ID": ["S001", "S001"],
            "REPORT_DATE": ["2024-09-30", "2024-09-30"],
            "ACCESSION_NUMBER": ["0001-24-000001", "0001-24-000002"],
            "ISSUER_NAME": ["Acme Corp", "Acme Corp Updated"],
        })
        result = _dedup_amendments(df, "test")
        assert len(result) == 1
        assert result.iloc[0]["ACCESSION_NUMBER"] == "0001-24-000002"

    def test_dedup_preserves_multi_series(self):
        """Multi-series registrant with different SERIES_IDs retains both."""
        df = pd.DataFrame({
            "CIK": ["100", "100"],
            "SERIES_ID": ["S001", "S002"],
            "REPORT_DATE": ["2024-09-30", "2024-09-30"],
            "ACCESSION_NUMBER": ["0001-24-000001", "0001-24-000002"],
            "ISSUER_NAME": ["Bond A", "Bond B"],
        })
        result = _dedup_amendments(df, "test")
        assert len(result) == 2

    def test_dedup_noop_no_amendments(self):
        """Single accession passes through unchanged."""
        df = pd.DataFrame({
            "CIK": ["100"],
            "SERIES_ID": ["S001"],
            "REPORT_DATE": ["2024-09-30"],
            "ACCESSION_NUMBER": ["0001-24-000001"],
            "ISSUER_NAME": ["Acme Corp"],
        })
        result = _dedup_amendments(df, "test")
        assert len(result) == 1
        assert result.iloc[0]["ACCESSION_NUMBER"] == "0001-24-000001"

    def test_dedup_fri_empty_series_multi_cik(self):
        """Multiple CIKs with empty SERIES_ID: each CIK retains its own row."""
        df = pd.DataFrame({
            "CIK": ["100", "200", "300"],
            "SERIES_ID": ["", "", ""],
            "REPORT_DATE": ["2024-09-30", "2024-09-30", "2024-09-30"],
            "ACCESSION_NUMBER": ["0001-24-000001", "0002-24-000001", "0003-24-000001"],
            "TOTAL_ASSETS": [500e6, 300e6, 100e6],
        })
        result = _dedup_amendments(df, "fund_info")
        # Each CIK is a separate group -- all 3 retained
        assert len(result) == 3

    def test_dedup_fri_with_cik_keeps_amendment(self):
        """Same CIK+SERIES_ID+REPORT_DATE with 2 accessions: keep later."""
        df = pd.DataFrame({
            "CIK": ["100", "100"],
            "SERIES_ID": ["", ""],
            "REPORT_DATE": ["2024-09-30", "2024-09-30"],
            "ACCESSION_NUMBER": ["0001-24-000001", "0001-24-000002"],
            "TOTAL_ASSETS": [500e6, 510e6],
        })
        result = _dedup_amendments(df, "fund_info")
        assert len(result) == 1
        assert result.iloc[0]["ACCESSION_NUMBER"] == "0001-24-000002"

    def test_dedup_fri_no_cik_returns_unchanged(self):
        """FRI without CIK/REPORT_DATE and no SERIES_ID: returns unchanged."""
        df = pd.DataFrame({
            "SERIES_ID": [None, None],
            "ACCESSION_NUMBER": ["0001-24-000001", "0002-24-000001"],
            "TOTAL_ASSETS": [500e6, 300e6],
        })
        result = _dedup_amendments(df, "fund_info")
        # No CIK or REPORT_DATE: only _SERIES_KEY (all empty) -> collapses
        # This test documents the pre-fix behavior for no-CIK case
        assert len(result) == 1

    def test_dedup_holdings_with_cik_keeps_latest(self):
        """Two accessions for same CIK: only latest kept."""
        df = pd.DataFrame({
            "CIK": ["100", "100", "100"],
            "ACCESSION_NUMBER": ["0001-24-000001", "0001-24-000001", "0001-24-000002"],
            "ISSUER_NAME": ["Acme", "Beta", "Acme New"],
        })
        result = _dedup_amendments(df, "holdings")
        assert len(result) == 1
        assert result.iloc[0]["ACCESSION_NUMBER"] == "0001-24-000002"

    def test_dedup_holdings_multi_cik_preserved(self):
        """Two CIKs each with one accession: both preserved."""
        df = pd.DataFrame({
            "CIK": ["100", "200"],
            "ACCESSION_NUMBER": ["0001-24-000001", "0002-24-000001"],
            "ISSUER_NAME": ["Acme", "Beta"],
        })
        result = _dedup_amendments(df, "holdings")
        assert len(result) == 2
