"""Foreign-currency principal converted with the admitted Federal Reserve quotes (wrapper opt-in).

Same date rule as the fair-value conversion: the quote on the report date, or the latest one
within seven days before it.
"""
import json

import duckdb
import pytest

from pipeline import source_encodings
from pipeline.monetary_fx import principal_reference_table

HPS = "0001838126"
OPTED = {HPS: {"principal_usd_reference": ["fred_h10"]}}


def _quote(day, **rates):
    return dict(date=day, quote_id="q-" + day, provider="FRED", usd_per_unit=rates, source_sha256="0" * 64)


QUOTES = [_quote("2026-03-27", EUR=1.07, GBP=1.25), _quote("2026-03-31", EUR=1.08), _quote("2026-04-01", EUR=9.99)]


def _raw(rows):
    con = duckdb.connect()
    con.execute("CREATE TABLE bdc_raw (cik VARCHAR, report_date VARCHAR, principal_amount_unit VARCHAR)")
    con.executemany("INSERT INTO bdc_raw VALUES (?, ?, ?)", rows)
    return con


def _table(con):
    return {(c, cur, d): rate for c, cur, d, rate in con.execute(
        "SELECT cik, currency, rate_date, usd_per_currency FROM fx_reference").fetchall()}


def test_opted_in_fund_gets_the_report_date_quote():
    con = _raw([("1838126", "2026-03-31", "eur")])
    counts = principal_reference_table(con, encodings=OPTED, quotes=QUOTES)
    assert _table(con) == {(HPS, "EUR", "2026-03-31"): pytest.approx(1.08)}
    assert counts == {HPS: 1}


def test_falls_back_to_the_latest_quote_within_seven_days_and_never_looks_ahead():
    con = _raw([(HPS, "2026-03-31", "iso4217:GBP")])
    principal_reference_table(con, encodings=OPTED, quotes=QUOTES)
    assert _table(con) == {(HPS, "GBP", "2026-03-31"): pytest.approx(1.25)}


def test_stale_or_missing_quotes_leave_the_pair_out():
    con = _raw([(HPS, "2026-06-30", "eur"), (HPS, "2026-03-31", "sek"), (HPS, "2026-03-31", "usd"), (HPS, "2026-03-31", "")])
    principal_reference_table(con, encodings=OPTED, quotes=QUOTES)
    assert _table(con) == {}


def test_a_fund_that_has_not_opted_in_gets_nothing():
    con = _raw([("0001287750", "2026-03-31", "eur")])
    assert principal_reference_table(con, encodings=OPTED, quotes=QUOTES) == {}
    assert _table(con) == {}
    con = _raw([(HPS, "2026-03-31", "eur")])
    assert principal_reference_table(con, encodings={}, quotes=QUOTES) == {}
    assert _table(con) == {}


def _wrapper(tmp_path, encoding):
    (tmp_path / "0001838126.json").write_text(json.dumps(
        {"schema_version": "bdc-xbrl-wrapper.v3", "cik": HPS, "source_encodings": encoding}), encoding="utf-8")
    return tmp_path


def test_loader_accepts_the_reference_setting(tmp_path):
    loaded = source_encodings.load_encodings(_wrapper(tmp_path, {"principal_usd_reference": ["fred_h10"]}))
    assert loaded[HPS]["principal_usd_reference"] == ["fred_h10"]


@pytest.mark.parametrize("value", [["ecb"], ["fred_h10", "fred_h10"], []])
def test_loader_rejects_any_other_reference(tmp_path, value):
    with pytest.raises(ValueError):
        source_encodings.load_encodings(_wrapper(tmp_path, {"principal_usd_reference": value}))


def test_the_five_sample_funds_opt_in():
    # Started as the five v0.5 funds only (74beff5, 2026-10-06). The setting was rolled out per fund from
    # 2026-10-08 (1cfe335, 8bf71b0, fb441d8 and the fund-clearing runs), so the guard now checks that the
    # five are still opted in, not that no other fund is.
    from pathlib import Path
    store = Path(__file__).resolve().parents[1] / "data" / "overrides" / "bdc_xbrl_wrappers"
    opted = {cik for cik, enc in source_encodings.load_encodings(store).items() if "principal_usd_reference" in enc}
    assert {"0001287750", "0001803498", "0001812554", "0001837532", "0001838126"} <= opted
    assert HPS in opted
