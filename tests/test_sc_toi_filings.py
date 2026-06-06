"""Tests for pipeline.sc_toi_filings module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pipeline.sc_toi_filings import (
    _ACCEPTED_ALL_RE,
    _OFFER_EXPIRED_RE,
    _OUTPUT_COLS,
    _PRICE_AT_RE,
    _PRICE_RE,
    _PRORATION_RE,
    _SC_TOI_FORM_TYPES,
    _SHARES_ACCEPTED_RE,
    _SHARES_OFFERED_RE,
    _SHARES_TENDERED_RE,
    _TABLE_PRICE_RE,
    _TENDERS_ACCEPTED_RE,
    _apply_guards,
    _collect_sc_toi_filings,
    _dedup_amendments,
    _extract_table_prices,
    _parse_date_text,
    _parse_float,
    _parse_int,
    _parse_repurchase_results,
    build_sc_toi_filings_index,
    download_sc_toi_filings,
    extract_sc_toi_results,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_sc_toi_html(
    narrative: str = "",
    table_html: str = "",
) -> str:
    """Build minimal SC TO-I HTML for testing."""
    return f"""<html><body>
    <p>{narrative}</p>
    {table_html}
    </body></html>"""


def _write_html(tmp_dir: Path, content: str, filename: str = "test.html") -> str:
    path = tmp_dir / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


# ===================================================================
# 1. Regex pattern tests
# ===================================================================

class TestSharesTenderedRegex:

    def test_basic_pattern(self):
        text = "1,234,567 Shares were validly tendered"
        m = _SHARES_TENDERED_RE.search(text)
        assert m is not None
        assert m.group(1) == "1,234,567"

    def test_lowercase(self):
        text = "500,000 shares tendered"
        m = _SHARES_TENDERED_RE.search(text)
        assert m is not None
        assert m.group(1) == "500,000"

    def test_without_were(self):
        text = "1,000 Shares validly tendered"
        m = _SHARES_TENDERED_RE.search(text)
        assert m is not None
        assert m.group(1) == "1,000"

    def test_no_commas(self):
        text = "50000 shares tendered"
        m = _SHARES_TENDERED_RE.search(text)
        assert m is not None
        assert m.group(1) == "50000"

    def test_fractional_shares(self):
        text = "296,318.49 Shares were tendered and not withdrawn"
        m = _SHARES_TENDERED_RE.search(text)
        assert m is not None
        assert m.group(1) == "296,318.49"

    def test_shares_of_the_fund(self):
        """Blackstone pattern: 'X Shares of the Fund were validly tendered'."""
        text = "480,314 Shares of the Fund were validly tendered and not withdrawn"
        m = _SHARES_TENDERED_RE.search(text)
        assert m is not None
        assert m.group(1) == "480,314"

    def test_no_match_prospective_offer_language(self):
        text = "the Fund will purchase up to 93,100,275 Shares that are tendered"
        m = _SHARES_TENDERED_RE.search(text)
        assert m is None

    def test_no_match_on_unrelated(self):
        text = "The tender offer expired on January 15, 2025"
        m = _SHARES_TENDERED_RE.search(text)
        assert m is None


class TestSharesAcceptedRegex:

    def test_accepted_for_purchase(self):
        text = "accepted for purchase 500,000 Shares"
        m = _SHARES_ACCEPTED_RE.search(text)
        assert m is not None
        val = m.group(1) or m.group(2)
        assert val == "500,000"

    def test_accepted_for_repurchase(self):
        text = "accepted for repurchase of 1,234 Shares"
        m = _SHARES_ACCEPTED_RE.search(text)
        assert m is not None
        val = m.group(1) or m.group(2)
        assert val == "1,234"

    def test_purchased_shares(self):
        text = "purchased a total of 750,000 Shares"
        m = _SHARES_ACCEPTED_RE.search(text)
        assert m is not None
        val = m.group(1) or m.group(2)
        assert val == "750,000"

    def test_purchased_all_fractional_shares(self):
        text = "the Company purchased all 4,880.906 Shares validly tendered"
        m = _SHARES_ACCEPTED_RE.search(text)
        assert m is not None
        val = m.group(1) or m.group(2)
        assert val == "4,880.906"

    def test_purchased_maximum_on_pro_rata_basis(self):
        text = "the Company purchased on a pro rata basis the maximum of 10,732 Shares"
        m = _SHARES_ACCEPTED_RE.search(text)
        assert m is not None
        val = m.group(1) or m.group(2)
        assert val == "10,732"

    def test_repurchased_all_such_shares(self):
        text = "the Company repurchased all such 3,670,134 Shares at a price"
        m = _SHARES_ACCEPTED_RE.search(text)
        assert m is not None
        val = m.group(1) or m.group(2)
        assert val == "3,670,134"

    def test_repurchased_shares(self):
        text = "repurchased 100,000 shares"
        m = _SHARES_ACCEPTED_RE.search(text)
        assert m is not None
        val = m.group(1) or m.group(2)
        assert val == "100,000"

    def test_accepted_for_payment(self):
        text = "accepted for payment 250,000 Shares"
        m = _SHARES_ACCEPTED_RE.search(text)
        assert m is not None
        val = m.group(1) or m.group(2)
        assert val == "250,000"


class TestAcceptedAllRegex:

    def test_accepted_100_pct(self):
        """Blackstone pattern: 'accepted for purchase 100% of the Shares'."""
        text = "The Fund accepted for purchase 100% of the Shares of the Fund"
        m = _ACCEPTED_ALL_RE.search(text)
        assert m is not None

    def test_accepted_100_pct_repurchase(self):
        text = "accepted for repurchase 100% of the Shares"
        m = _ACCEPTED_ALL_RE.search(text)
        assert m is not None

    def test_no_match_partial_pct(self):
        text = "accepted for purchase 85% of the Shares"
        m = _ACCEPTED_ALL_RE.search(text)
        assert m is None

    def test_no_match_numeric_shares(self):
        """Normal numeric pattern should NOT match this regex."""
        text = "accepted for purchase 500,000 Shares"
        m = _ACCEPTED_ALL_RE.search(text)
        assert m is None


class TestTendersAcceptedRegex:

    def test_tenders_accepted_for_purchase(self):
        """Early Blackstone pattern: 'tenders were accepted for purchase by the Fund'."""
        text = "promissory notes respectively issued to the Shareholders whose tenders were accepted for purchase by the Fund in accordance with"
        m = _TENDERS_ACCEPTED_RE.search(text)
        assert m is not None

    def test_tender_singular(self):
        text = "whose tender was accepted for purchase by the Fund"
        m = _TENDERS_ACCEPTED_RE.search(text)
        assert m is not None

    def test_tenders_accepted_for_repurchase(self):
        text = "tenders were accepted for repurchase by the Fund"
        m = _TENDERS_ACCEPTED_RE.search(text)
        assert m is not None

    def test_no_match_future_tense(self):
        """Should not match future/conditional language."""
        text = "tenders will be accepted for purchase"
        m = _TENDERS_ACCEPTED_RE.search(text)
        assert m is None

    def test_no_match_unrelated(self):
        text = "The tender offer expired on January 15, 2025"
        m = _TENDERS_ACCEPTED_RE.search(text)
        assert m is None


class TestProrationRegex:

    def test_representing_approximately(self):
        text = "representing approximately 43.1% of the Shares"
        m = _PRORATION_RE.search(text)
        assert m is not None
        assert m.group(1) == "43.1"

    def test_representing_exact(self):
        text = "representing 100% of the outstanding Shares"
        m = _PRORATION_RE.search(text)
        assert m is not None
        assert m.group(1) == "100"

    def test_pro_rata(self):
        text = "on a pro rata basis, approximately 22.8%"
        m = _PRORATION_RE.search(text)
        assert m is not None
        assert m.group(1) == "22.8"

    def test_prorated_at(self):
        text = "prorated at 85.5%"
        m = _PRORATION_RE.search(text)
        assert m is not None
        assert m.group(1) == "85.5"


class TestPriceRegex:

    def test_repurchase_price_per_share_of(self):
        text = "repurchase price per share of $25.47"
        m = _PRICE_RE.search(text)
        assert m is not None
        assert m.group(1) == "25.47"

    def test_purchase_price_was(self):
        text = "purchase price was $10.00"
        m = _PRICE_RE.search(text)
        assert m is not None
        assert m.group(1) == "10.00"

    def test_tender_price_equal_to(self):
        text = "tender price per Share equal to $32.15"
        m = _PRICE_RE.search(text)
        assert m is not None
        assert m.group(1) == "32.15"

    def test_table_price_pattern(self):
        text = "$25.47 per Share"
        m = _TABLE_PRICE_RE.search(text)
        assert m is not None
        assert m.group(1) == "25.47"

    def test_price_at_pattern(self):
        text = "repurchased at a price of $25.93 per Share"
        m = _PRICE_AT_RE.search(text)
        assert m is not None
        assert m.group(1) == "25.93"

    def test_price_at_equal_to_pattern(self):
        text = "purchased a total of 108,904 Shares at a price equal to $9.36 per Share"
        m = _PRICE_AT_RE.search(text)
        assert m is not None
        assert m.group(1) == "9.36"

    def test_price_equal_to_net_offering_price_determined_of(self):
        text = (
            "purchased all 49,814,200 Shares validly tendered and not "
            "withdrawn at a price equal to the net offering price per Share "
            "determined as of October 4, 2017 of $11.1549"
        )
        m = _PRICE_AT_RE.search(text)
        assert m is not None
        assert m.group(1) == "11.1549"


class TestOfferExpiredRegex:

    def test_basic_pattern(self):
        text = "The Offer expired at 11:59 p.m., Eastern Time, on November 30, 2021."
        m = _OFFER_EXPIRED_RE.search(text)
        assert m is not None
        assert "November 30" in m.group(1)

    def test_simple_pattern(self):
        text = "The Offer expired on January 15, 2025."
        m = _OFFER_EXPIRED_RE.search(text)
        assert m is not None
        assert "January 15" in m.group(1)

    def test_offer_terminated_pattern(self):
        text = "The Offer terminated at 5:00 P.M., Eastern Time, on March 25, 2014."
        m = _OFFER_EXPIRED_RE.search(text)
        assert m is not None
        assert "March 25" in m.group(1)


class TestSharesOfferedRegex:

    def test_basic_pattern(self):
        text = "offer to purchase up to 16,352,313 of its outstanding shares"
        m = _SHARES_OFFERED_RE.search(text)
        assert m is not None
        assert m.group(1) == "16,352,313"

    def test_common_shares(self):
        text = "repurchase up to 5,000,000 common shares"
        m = _SHARES_OFFERED_RE.search(text)
        assert m is not None
        assert m.group(1) == "5,000,000"


class TestParseDateText:

    def test_full_month(self):
        assert _parse_date_text("November 30, 2021") == "2021-11-30"

    def test_no_comma(self):
        assert _parse_date_text("November 30 2021") == "2021-11-30"

    def test_abbreviated(self):
        assert _parse_date_text("Nov 30 2021") == "2021-11-30"

    def test_empty(self):
        assert _parse_date_text("") is None

    def test_none(self):
        assert _parse_date_text(None) is None


# ===================================================================
# 2. Parsing helpers
# ===================================================================

class TestParseInt:

    def test_with_commas(self):
        assert _parse_int("1,234,567") == 1234567

    def test_without_commas(self):
        assert _parse_int("50000") == 50000

    def test_empty(self):
        assert _parse_int("") is None

    def test_none(self):
        assert _parse_int(None) is None

    def test_invalid(self):
        assert _parse_int("abc") is None


class TestParseFloat:

    def test_basic(self):
        assert _parse_float("25.47") == 25.47

    def test_with_commas(self):
        assert _parse_float("1,234.56") == 1234.56

    def test_empty(self):
        assert _parse_float("") is None

    def test_none(self):
        assert _parse_float(None) is None


# ===================================================================
# 3. Full HTML parsing
# ===================================================================

class TestParseRepurchaseResults:

    def test_full_narrative(self):
        narrative = (
            "A total of 5,000,000 Shares were validly tendered. "
            "The Fund accepted for purchase 2,150,000 Shares on a "
            "pro rata basis, representing approximately 43.0% of "
            "the tendered Shares. The repurchase price per share "
            "of $25.47 was determined as of January 31, 2025."
        )
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert len(results) == 1
        rec = results[0]
        assert rec["shares_tendered"] == 5000000
        assert rec["shares_accepted"] == 2150000
        assert rec["proration_pct"] == 43.0
        assert rec["repurchase_price_per_share"] == 25.47
        assert abs(rec["oversubscription_rate"] - 5000000 / 2150000) < 0.001
        assert rec["parse_method"] == "narrative_regex"

    def test_no_results_in_html(self):
        html = _build_sc_toi_html(
            narrative="This is a preliminary tender offer notice."
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert results == []

    def test_prospective_offer_does_not_create_result_row(self):
        html = _build_sc_toi_html(
            narrative=(
                "The Fund will purchase up to 93,100,275 Shares that are "
                "tendered by Shareholders. The purchase price of a Share "
                "tendered will be its net asset value."
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert results == []

    def test_partial_data_shares_only(self):
        narrative = "1,000,000 Shares were validly tendered and all were accepted for purchase."
        # This won't match accepted pattern cleanly, but tendered will match
        html = _build_sc_toi_html(narrative="1,000,000 Shares were tendered")
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert len(results) == 1
        assert results[0]["shares_tendered"] == 1000000

    def test_price_from_table(self):
        table = """
        <table>
        <tr><th>Class</th><th>Repurchase Price Per Share</th></tr>
        <tr><td>Class I</td><td>$25.47</td></tr>
        </table>
        """
        html = _build_sc_toi_html(
            narrative="500,000 shares tendered",
            table_html=table,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert len(results) == 1
        assert results[0]["repurchase_price_per_share"] == 25.47

    def test_100_pct_acceptance(self):
        narrative = (
            "2,000,000 Shares were validly tendered. "
            "The Fund purchased 2,000,000 Shares, "
            "representing 100% of the outstanding Shares."
        )
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert len(results) == 1
        rec = results[0]
        assert rec["shares_tendered"] == 2000000
        assert rec["shares_accepted"] == 2000000
        assert rec["oversubscription_rate"] == 1.0

    def test_implicit_acceptance_early_blackstone(self):
        """Early Blackstone: 'tenders were accepted for purchase' (no count/pct)."""
        narrative = (
            "11,488,257 Shares of the Fund were validly tendered "
            "and not withdrawn prior to the expiration of the Offer. "
            "The payment of the purchase price of the Shares tendered "
            "was made in the form of non-interest bearing, non-transferable "
            "promissory notes respectively issued to the Shareholders "
            "whose tenders were accepted for purchase by the Fund in "
            "accordance with the terms of the Offer. "
            "The Shares were repurchased at a price of $24.80 per Share."
        )
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert len(results) == 1
        rec = results[0]
        assert rec["shares_tendered"] == 11488257
        assert rec["shares_accepted"] == 11488257
        assert rec["oversubscription_rate"] == 1.0
        assert rec["repurchase_price_per_share"] == 24.80

    def test_100_pct_acceptance_blackstone_pattern(self):
        """Blackstone: 'accepted for purchase 100% of the Shares'."""
        narrative = (
            "47,129,537 Shares of the Fund were validly tendered "
            "and not withdrawn prior to the expiration of the Offer. "
            "The Fund accepted for purchase 100% of the Shares of "
            "the Fund that were validly tendered. "
            "The Shares were repurchased at a price of $24.59 per Share."
        )
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert len(results) == 1
        rec = results[0]
        assert rec["shares_tendered"] == 47129537
        assert rec["shares_accepted"] == 47129537
        assert rec["oversubscription_rate"] == 1.0
        assert rec["repurchase_price_per_share"] == 24.59


# ===================================================================
# 4. Table price extraction
# ===================================================================

class TestExtractTablePrices:

    def test_price_in_table(self):
        from bs4 import BeautifulSoup
        html = """
        <table>
        <tr><td>Repurchase Price Per Share</td><td>$25.47</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        prices = _extract_table_prices(soup)
        assert prices == [25.47]

    def test_no_price_table(self):
        from bs4 import BeautifulSoup
        html = "<table><tr><td>No pricing info</td></tr></table>"
        soup = BeautifulSoup(html, "html.parser")
        prices = _extract_table_prices(soup)
        assert prices == []

    def test_rejects_unreasonable_price(self):
        from bs4 import BeautifulSoup
        html = """
        <table>
        <tr><td>Price per share</td><td>$0.001</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        prices = _extract_table_prices(soup)
        assert prices == []


# ===================================================================
# 5. Guards
# ===================================================================

class TestApplyGuards:

    def test_proration_too_high(self):
        df = pd.DataFrame({"proration_pct": ["150"]})
        result = _apply_guards(df)
        assert pd.isna(result["proration_pct"].iloc[0])

    def test_proration_negative(self):
        df = pd.DataFrame({"proration_pct": ["-5"]})
        result = _apply_guards(df)
        assert pd.isna(result["proration_pct"].iloc[0])

    def test_proration_valid(self):
        df = pd.DataFrame({"proration_pct": ["43.1"]})
        result = _apply_guards(df)
        assert result["proration_pct"].iloc[0] == "43.1"

    def test_negative_shares(self):
        df = pd.DataFrame({"shares_tendered": ["-100"], "shares_accepted": ["500"]})
        result = _apply_guards(df)
        assert pd.isna(result["shares_tendered"].iloc[0])
        assert result["shares_accepted"].iloc[0] == "500"

    def test_decimal_rendered_with_comma_in_accepted_shares(self):
        df = pd.DataFrame({
            "shares_tendered": ["49814.2"],
            "shares_accepted": ["49814200"],
        })
        result = _apply_guards(df)
        assert float(result["shares_accepted"].iloc[0]) == 49814.2

    def test_negative_price(self):
        df = pd.DataFrame({"repurchase_price_per_share": ["-1.5"]})
        result = _apply_guards(df)
        assert pd.isna(result["repurchase_price_per_share"].iloc[0])

    def test_zero_price(self):
        df = pd.DataFrame({"repurchase_price_per_share": ["0"]})
        result = _apply_guards(df)
        assert pd.isna(result["repurchase_price_per_share"].iloc[0])

    def test_par_value_not_price(self):
        df = pd.DataFrame({"repurchase_price_per_share": ["0.001"]})
        result = _apply_guards(df)
        assert pd.isna(result["repurchase_price_per_share"].iloc[0])

    def test_oversubscription_below_one(self):
        df = pd.DataFrame({"oversubscription_rate": ["0.5"]})
        result = _apply_guards(df)
        assert pd.isna(result["oversubscription_rate"].iloc[0])

    def test_oversubscription_valid(self):
        df = pd.DataFrame({"oversubscription_rate": ["2.3"]})
        result = _apply_guards(df)
        assert result["oversubscription_rate"].iloc[0] == "2.3"

    def test_empty_df(self):
        df = pd.DataFrame()
        result = _apply_guards(df)
        assert result.empty


# ===================================================================
# 6. Dedup amendments
# ===================================================================

class TestDedupAmendments:

    def test_amendment_supersedes_original(self):
        df = pd.DataFrame({
            "cik": ["123", "123"],
            "report_date": ["", ""],
            "offer_expiration_date": ["2025-01-31", "2025-01-31"],
            "form_type": ["SC TO-I", "SC TO-I/A"],
            "filing_date": ["2025-01-01", "2025-03-15"],
            "shares_tendered": ["1000", "5000"],
            "shares_accepted": [None, "2000"],
            "proration_pct": [None, "40"],
            "repurchase_price_per_share": [None, "25.47"],
        })
        result = _dedup_amendments(df)
        assert len(result) == 1
        assert result.iloc[0]["form_type"] == "SC TO-I/A"
        assert result.iloc[0]["shares_tendered"] == "5000"

    def test_different_offer_dates_kept(self):
        df = pd.DataFrame({
            "cik": ["123", "123"],
            "report_date": ["", ""],
            "offer_expiration_date": ["2025-01-31", "2025-04-30"],
            "form_type": ["SC TO-I/A", "SC TO-I/A"],
            "filing_date": ["2025-03-15", "2025-06-15"],
            "shares_tendered": ["5000", "3000"],
            "shares_accepted": ["2000", "1500"],
            "proration_pct": ["40", "50"],
            "repurchase_price_per_share": ["25.47", "26.00"],
        })
        result = _dedup_amendments(df)
        assert len(result) == 2

    def test_empty_df(self):
        df = pd.DataFrame(columns=["cik", "report_date", "form_type"])
        result = _dedup_amendments(df)
        assert result.empty

    def test_prefers_more_complete_record(self):
        df = pd.DataFrame({
            "cik": ["123", "123"],
            "report_date": ["", ""],
            "offer_expiration_date": ["2025-01-31", "2025-01-31"],
            "form_type": ["SC TO-I/A", "SC TO-I/A"],
            "filing_date": ["2025-03-01", "2025-03-15"],
            "shares_tendered": [None, "5000"],
            "shares_accepted": [None, "2000"],
            "proration_pct": [None, "40"],
            "repurchase_price_per_share": [None, "25.47"],
        })
        result = _dedup_amendments(df)
        assert len(result) == 1
        # Latest filing_date wins
        assert result.iloc[0]["filing_date"] == "2025-03-15"

    def test_no_dedup_when_no_key(self):
        """Rows with no offer_expiration_date or report_date are kept."""
        df = pd.DataFrame({
            "cik": ["123", "123"],
            "report_date": ["", ""],
            "form_type": ["SC TO-I/A", "SC TO-I/A"],
            "filing_date": ["2025-03-01", "2025-06-15"],
            "shares_tendered": ["5000", "3000"],
        })
        result = _dedup_amendments(df)
        assert len(result) == 2


# ===================================================================
# 7. Filing discovery (mocked)
# ===================================================================

class TestCollectScToiFilings:

    def test_collects_sc_toi_forms(self):
        records: list = []
        recent = {
            "form": ["10-K", "SC TO-I", "SC TO-I/A", "8-K"],
            "filingDate": ["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01"],
            "accessionNumber": ["acc-1", "acc-2", "acc-3", "acc-4"],
            "primaryDocument": ["doc1.htm", "doc2.htm", "doc3.htm", "doc4.htm"],
            "reportDate": ["2024-12-31", "2025-01-31", "2025-01-31", "2025-03-31"],
        }
        _collect_sc_toi_filings(records, "1803498", "Test Corp", recent)
        assert len(records) == 2
        assert records[0]["form_type"] == "SC TO-I"
        assert records[1]["form_type"] == "SC TO-I/A"

    def test_no_sc_toi_forms(self):
        records: list = []
        recent = {
            "form": ["10-K", "10-Q", "8-K"],
            "filingDate": ["2025-01-01", "2025-02-01", "2025-03-01"],
            "accessionNumber": ["acc-1", "acc-2", "acc-3"],
            "primaryDocument": ["doc1.htm", "doc2.htm", "doc3.htm"],
            "reportDate": ["2024-12-31", "2025-01-31", "2025-03-31"],
        }
        _collect_sc_toi_filings(records, "1803498", "Test Corp", recent)
        assert len(records) == 0

    def test_sc_tot_forms_also_collected(self):
        records: list = []
        recent = {
            "form": ["SC TO-T", "SC TO-T/A"],
            "filingDate": ["2025-01-01", "2025-02-01"],
            "accessionNumber": ["acc-1", "acc-2"],
            "primaryDocument": ["doc1.htm", "doc2.htm"],
            "reportDate": ["2024-12-31", "2025-01-31"],
        }
        _collect_sc_toi_filings(records, "1803498", "Test Corp", recent)
        assert len(records) == 2


class TestBuildScToiFilingsIndex:

    @patch("pipeline.sc_toi_filings.SC_TOI_FILINGS_INDEX_FILE")
    def test_builds_index_from_submissions(self, mock_path):
        mock_path.exists.return_value = False

        client = MagicMock()
        client.get_company_submissions.return_value = {
            "name": "Test Fund",
            "filings": {
                "recent": {
                    "form": ["SC TO-I", "SC TO-I/A"],
                    "filingDate": ["2025-02-01", "2025-03-15"],
                    "accessionNumber": ["0001-25-000001", "0001-25-000002"],
                    "primaryDocument": ["doc1.htm", "doc2.htm"],
                    "reportDate": ["2025-01-31", "2025-01-31"],
                },
                "files": [],
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            index_file = Path(tmp) / "sc_toi_filings_index.csv"
            with patch("pipeline.sc_toi_filings.SC_TOI_FILINGS_INDEX_FILE", index_file):
                df = build_sc_toi_filings_index(client, ["1803498"])

        assert len(df) == 2
        assert set(df["form_type"]) == {"SC TO-I", "SC TO-I/A"}


# ===================================================================
# 8. Resumability
# ===================================================================

class TestResumability:

    def test_progress_file_respected(self):
        """Already-parsed accessions should be skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Create a progress file with one accession already done
            progress_file = tmp_path / "progress.csv"
            pd.DataFrame({
                "accession_number": ["acc-001"],
                "status": ["ok"],
                "count": ["1"],
            }).to_csv(progress_file, index=False)

            # Create results file
            results_file = tmp_path / "results.csv"
            pd.DataFrame({
                "cik": ["123"],
                "entity_name": ["Test"],
                "accession_number": ["acc-001"],
                "form_type": ["SC TO-I/A"],
                "filing_date": ["2025-03-15"],
                "report_date": ["2025-01-31"],
                "shares_tendered": ["5000"],
                "shares_accepted": ["2000"],
                "proration_pct": ["40"],
                "repurchase_price_per_share": ["25.47"],
                "oversubscription_rate": ["2.5"],
                "parse_method": ["narrative_regex"],
            }).to_csv(results_file, index=False)

            # Create a filings index with the already-parsed accession
            filings_index = pd.DataFrame({
                "cik": ["123"],
                "entity_name": ["Test"],
                "accession_number": ["acc-001"],
                "form_type": ["SC TO-I/A"],
                "filing_date": ["2025-03-15"],
                "report_date": ["2025-01-31"],
                "html_local_path": ["/nonexistent/path.html"],
            })

            with (
                patch("pipeline.sc_toi_filings.SC_TOI_PARSE_PROGRESS_FILE", progress_file),
                patch("pipeline.sc_toi_filings.SC_TOI_RESULTS_FILE", results_file),
            ):
                result = extract_sc_toi_results(filings_index)

            # Should load from cache, not reparse
            assert len(result) == 1
            assert result.iloc[0]["shares_tendered"] == "5000"


# ===================================================================
# 9. False positive tests
# ===================================================================

class TestFalsePositives:

    def test_preliminary_offer_notice(self):
        """Preliminary SC TO-I (not amendment) typically has no results."""
        narrative = (
            "This tender offer statement relates to the offer by "
            "the Fund to purchase up to 5% of its outstanding shares."
        )
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)
        assert results == []

    def test_mention_tender_in_unrelated_context(self):
        """Text that mentions 'tender' but isn't a results filing."""
        narrative = (
            "The Board of Directors has authorized a tender offer "
            "for up to 5% of outstanding shares. The offer will "
            "commence on February 1, 2025."
        )
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)
        assert results == []

    def test_legal_boilerplate(self):
        """Legal boilerplate about tender offers should not trigger."""
        narrative = (
            "Under the terms of the Declaration of Trust, the Fund "
            "may, from time to time, offer to repurchase shares at "
            "net asset value."
        )
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)
        assert results == []


# ===================================================================
# 10. Form types
# ===================================================================

class TestFormTypes:

    def test_expected_form_types(self):
        assert "SC TO-I" in _SC_TOI_FORM_TYPES
        assert "SC TO-I/A" in _SC_TOI_FORM_TYPES
        assert "SC TO-T" in _SC_TOI_FORM_TYPES
        assert "SC TO-T/A" in _SC_TOI_FORM_TYPES
        assert "10-K" not in _SC_TOI_FORM_TYPES


# ===================================================================
# 11. Output columns
# ===================================================================

class TestOutputColumns:

    def test_required_columns_present(self):
        required = {
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "offer_expiration_date",
            "shares_offered", "shares_tendered",
            "shares_accepted", "proration_pct",
            "repurchase_price_per_share", "oversubscription_rate",
            "tx_valuation", "parse_method",
        }
        assert set(_OUTPUT_COLS) == required


# ===================================================================
# 12. Download function
# ===================================================================

class TestDownloadScToiFilings:

    def test_empty_index(self):
        client = MagicMock()
        df = pd.DataFrame(columns=[
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "report_date", "primary_document",
        ])
        result = download_sc_toi_filings(client, df)
        assert "download_status" in result.columns
        assert "html_local_path" in result.columns
        assert result.empty

    def test_cached_file_skipped(self):
        """Files already on disk should be marked 'cached'."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cache_dir = tmp_path / "1803498"
            cache_dir.mkdir()
            # Accession "0001803498-25-000001" -> stripped "000180349825000001"
            cached_file = cache_dir / "000180349825000001.html"
            cached_file.write_text("<html>cached</html>" * 200, encoding="utf-8")

            client = MagicMock()
            df = pd.DataFrame({
                "cik": ["1803498"],
                "entity_name": ["Test"],
                "accession_number": ["0001803498-25-000001"],
                "form_type": ["SC TO-I/A"],
                "filing_date": ["2025-03-15"],
                "report_date": ["2025-01-31"],
                "primary_document": ["doc.htm"],
            })

            with (
                patch("pipeline.sc_toi_filings.SC_TOI_HTML_CACHE_DIR", tmp_path),
                patch("pipeline.sc_toi_filings.SC_TOI_FILINGS_INDEX_FILE",
                       tmp_path / "index.csv"),
            ):
                result = download_sc_toi_filings(client, df)

            assert result.iloc[0]["download_status"] == "cached"
            client.download_file.assert_not_called()


# ===================================================================
# 13. Oversubscription rate computation
# ===================================================================

class TestOversubscriptionRate:

    def test_oversubscribed(self):
        narrative = (
            "10,000,000 Shares were validly tendered. "
            "The Fund accepted for repurchase of 2,280,000 Shares."
        )
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert len(results) == 1
        rate = results[0]["oversubscription_rate"]
        expected = round(10000000 / 2280000, 4)
        assert rate == expected

    def test_no_oversubscription(self):
        narrative = (
            "500,000 Shares were validly tendered. "
            "The Fund purchased 500,000 Shares."
        )
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert len(results) == 1
        assert results[0]["oversubscription_rate"] == 1.0

    def test_no_rate_when_accepted_missing(self):
        narrative = "500,000 Shares were validly tendered."
        html = _build_sc_toi_html(narrative=narrative)
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_html(Path(tmp), html)
            results = _parse_repurchase_results(path)

        assert len(results) == 1
        assert "oversubscription_rate" not in results[0]
