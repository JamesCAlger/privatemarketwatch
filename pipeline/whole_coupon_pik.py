"""Whole-coupon PIK read from the printed row (owner ruling D-232, extraction rule 2026-11-04).

A loan printed '<benchmark> + <margin> PIK <coupon> %' ('S + 1075 PIK 15.66 %', 'S + 12.00 % PIK
16.58 %', 'EURIBOR | 10.00% PIK | 13.25%') pays its whole floating coupon in kind: pik_rate is the
printed coupon and the cash leg is 0. Evidence for the reading (D-232, D-246): on the loans read so
far the par grows each quarter by coupon/4 (AX VI semi-annually by coupon/2), not by margin/4.

The printed form alone cannot tell that reading from a loan that pays the benchmark in cash and
the margin in kind: both print 'S + 650 PIK 11.93 %' and both tag rate 11.93 / PIK 6.50. Par growth
tells them apart, and it needs the position chain, which exists only after matching, so it is not
available here. The rule is therefore on only for funds whose wrapper declares the reading
(``source_encodings.pik_margin_reading: ["whole_coupon"]``), after par growth was read for that
filer. Rows it changes carry ``pik_rate:whole_coupon_printed`` in src_transforms. A row of such a fund
whose par grows by margin/4 is listed after the reading as "not ACCESSION CONTEXT" and left as filed.

Not read (left as filed): a fixed cash leg after the PIK margin ('SOFR + 2.00 % PIK + 5.00 % 12.30 %',
D-218), a PIK part inside a bracket ('S + 650 (including 75 PIK)'), a toggle, a row that names cash
or prints two such forms, no benchmark before the margin (Continental Battery '7.00 % PIK 11.29 %'),
and a bare margin under 25 (a bare figure is read as basis points only).

The check pik_printed (pipeline/candidate_rules.py) parses the same printed form with its own
grammar on purpose: the check must not pass because it shares the extractor's parser.
"""
from __future__ import annotations

import pandas as pd

TRANSFORM = "pik_rate:whole_coupon_printed"
TOL = 0.011
# A benchmark is at most this far below the coupon (the printed coupon less the margin).
MAX_BENCHMARK = 8.0

_BENCH = ("(?:TERMSOFR|TSOFR|EURIBOR|LIB1M|LIB3M|LIBOR|SONIA|CORRA|PRIME|SOFR|TSF|EUR|LIB|SF|SO|PR|S|L|E|P)")
_NUM = r"(\d+(?:\.\d+)?|\.\d+)"
# floors, footnote marks and reset periods between the PIK word and the coupon: '(100 Floor)', '(6)'
_TAIL = (r"(?:\s*,\s*\d+(?:\.\d+)?\s*%?\s*floor)?(?:[\s|]*\([^()|]{0,30}\))*[\s|]*"
         r"(\d+(?:\.\d+)?)\s*%")
# '<code> [(tenor)] + m [%] PIK'
# a floor may sit between the margin and the PIK word (Commonwealth Kent 'SOFR + 10.00% (1.00% floor) PIK')
_FLOOR = r"(?:\s*\(\s*\d+(?:\.\d+)?\s*%?\s*floor\s*\))?"
_PLUS = (r"(?i)(?<![A-Za-z0-9])" + _BENCH + r"[\s|]*(?:\(\s*[A-Za-z0-9]{1,3}\s*\)[\s|]*)?\+[\s|]*"
         + _NUM + r"(\s*%)?" + _FLOOR + r"\s*PIK\b" + _TAIL)
# '<code> | [dash cell |] m % PIK' (the benchmark printed in its own cell, no '+')
_CELL = (r"(?i)(?:^|\|)\s*" + _BENCH + r"\s*(?:\|\s*[-–—]*\s*)*\|\s*" + _NUM + r"(\s*%)\s*PIK\b" + _TAIL)
# the coupon printed in a column before the margin (Silver Capital 'Wine.com | 16.58 % | S + 12.00 % PIK |
# 04/03/27'); not when a percent follows the margin
_BEFORE = (r"(?i)(?<![\d.])(\d+(?:\.\d+)?)\s*%[\s|]*" + _BENCH + r"[\s|]*(?:\(\s*[A-Za-z0-9]{1,3}\s*\)[\s|]*)?\+[\s|]*"
           + _NUM + r"(\s*%)?\s*PIK\b(?![\s|]*(?:\([^()|]{0,30}\)[\s|]*)*\d+(?:\.\d+)?\s*%)")
_EXCLUDE = r"(?i)toggle|incl|\bcash\b"


def _clean(text: pd.Series) -> pd.Series:
    # the page reader splits '13.25 | %' over two cells
    return text.astype("string").fillna("").astype(object).str.replace(r"(\d)\s*\|\s*%", r"\1 %", regex=True)


def parse(printed_row: pd.Series) -> pd.DataFrame:
    """Columns ``margin`` and ``coupon`` (percent) where the row prints the whole-coupon PIK form once, else NaN."""
    text = _clean(printed_row)
    out = pd.DataFrame({"margin": float("nan"), "coupon": float("nan")}, index=printed_row.index)
    hits = text.str.count(_PLUS) + text.str.count(_CELL) + text.str.count(_BEFORE)
    # (pattern, margin group, percent-sign group, coupon group)
    for pattern, gm, gp, gc in ((_PLUS, 0, 1, 2), (_CELL, 0, 1, 2), (_BEFORE, 1, 2, 0)):
        got = text.str.extract(pattern)
        margin = pd.to_numeric(got[gm], errors="coerce").astype("float64")
        has_pct = got[gp].notna()
        # a bare figure is basis points from 25 up; below that it is not read
        margin = margin.where(has_pct, (margin / 100.0).where(margin >= 25))
        coupon = pd.to_numeric(got[gc], errors="coerce").astype("float64")
        take = out["margin"].isna() & margin.notna() & coupon.notna()
        out.loc[take, "margin"] = margin[take]
        out.loc[take, "coupon"] = coupon[take]
    bad = (hits != 1) | text.str.contains(_EXCLUDE, regex=True) | ~(
        (out["coupon"] - out["margin"] > 0) & (out["coupon"] - out["margin"] <= MAX_BENCHMARK))
    out.loc[bad.fillna(True), ["margin", "coupon"]] = float("nan")
    return out


def printed_rows(status_path, ciks) -> pd.DataFrame:
    """Current-period printed rows that name PIK, for the given funds, from the field-status artifact
    (CSV or Parquet), one per member key; a member printed with two different rows is left out."""
    import duckdb
    path = str(status_path).replace("\\", "/").replace("'", "''")
    source = f"read_parquet('{path}')" if path.endswith(".parquet") else f"read_csv('{path}', all_varchar=true, header=true)"
    with duckdb.connect(config={"threads": 2, "memory_limit": "2GB"}) as con:
        con.register("funds", pd.DataFrame({"cik": sorted(ciks)}))
        cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()}
        if "printed_row" not in cols:
            return pd.DataFrame(columns=["_k", "printed_row"])
        current = "AND coalesce(CAST(period_role AS VARCHAR), 'current') = 'current'" if "period_role" in cols else ""
        return con.execute(f"""
            SELECT lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik,
                   trim(CAST(accession_number AS VARCHAR)) AS accession_number,
                   trim(CAST(report_date AS VARCHAR)) AS report_date,
                   lower(trim(CAST(raw_id_lower AS VARCHAR))) AS raw_id_lower,
                   min(CAST(printed_row AS VARCHAR)) AS printed_row
            FROM {source}
            WHERE lpad(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') IN (SELECT cik FROM funds)
              AND regexp_matches(coalesce(CAST(printed_row AS VARCHAR), ''), '(?i)PIK') {current}
            GROUP BY 1, 2, 3, 4
            HAVING count(DISTINCT CAST(printed_row AS VARCHAR)) = 1""").fetchdf()


def apply(result: pd.DataFrame, status_path, funds=None, exclusions=None) -> pd.DataFrame:
    """Staging step: for funds that declare pik_margin_reading whole_coupon, publish the printed coupon as
    pik_rate on loan rows printed in the whole-coupon PIK form whose tags agree with the page.

    ``exclusions`` ({(cik10, accession, context)}; default: the wrapper's "not ACCESSION CONTEXT" entries)
    are rows of an opted-in fund whose par grows by margin/4: they are left as filed."""
    from pathlib import Path
    from pipeline.bdc_xbrl_html_bridge import _norm_text, normalize_cik, overlay_member_key
    needed = {"cik", "accession_number", "report_date", "bdc_investment_identifier", "interest_rate", "pik_rate",
              "basis_spread", "asset_category", "src_transforms"}
    if result.empty or not needed <= set(result.columns) or not Path(status_path).exists():
        return result
    if funds is None:
        from pipeline.source_encodings import whole_coupon_pik_funds
        funds = whole_coupon_pik_funds()
    ciks = result["cik"].map(normalize_cik)
    in_fund = ciks.isin(set(funds))
    if not in_fund.any():
        return result
    pages = printed_rows(status_path, set(ciks[in_fund]))
    if pages.empty:
        return result
    sub = result[in_fund]
    key = (ciks[in_fund] + "|" + sub["accession_number"].map(_norm_text) + "|" + sub["report_date"].map(_norm_text)
           + "|" + overlay_member_key(sub))
    page_key = (pages["cik"] + "|" + pages["accession_number"].map(_norm_text) + "|" + pages["report_date"].map(_norm_text)
                + "|" + pages["raw_id_lower"].map(_norm_text).str.lower())
    printed = key.map(dict(zip(page_key, pages["printed_row"])))
    parsed = parse(printed)
    # a row already at the coupon is marked too: the finalizer reads the mark as the all-in kind
    take = eligible(sub, parsed)
    if exclusions is None:
        from pipeline.source_encodings import whole_coupon_pik_exclusions
        exclusions = whole_coupon_pik_exclusions()
    if exclusions and "src_context_id" in sub.columns:
        listed = pd.Series(list(zip(ciks[in_fund], sub["accession_number"].map(_norm_text),
                                    sub["src_context_id"].map(_norm_text))), index=sub.index).isin(set(exclusions))
        take &= ~listed
    if not take.any():
        return result
    out = result.copy()
    idx = take[take].index
    out.loc[idx, "pik_rate"] = pd.to_numeric(out.loc[idx, "interest_rate"], errors="coerce")
    events = out.loc[idx, "src_transforms"].astype("string").fillna("")
    marked = (events.where(events == "", events + ";") + TRANSFORM).where(~events.str.contains(TRANSFORM, regex=False), events)
    out.loc[idx, "src_transforms"] = marked.astype(object).values
    return out


def eligible(frame: pd.DataFrame, printed: pd.DataFrame) -> pd.Series:
    """Rows whose tags agree with a parsed printed form: a loan, the rate tag is the printed coupon,
    the PIK tag (if any) is the printed margin or already the coupon, the spread tag (if any) the margin."""
    rate = pd.to_numeric(frame["interest_rate"], errors="coerce")
    pik = pd.to_numeric(frame["pik_rate"], errors="coerce")
    spread = pd.to_numeric(frame["basis_spread"], errors="coerce")
    m, c = printed["margin"], printed["coupon"]
    return ((frame["asset_category"].astype("string").fillna("") == "LOAN")
            & m.notna() & ((rate - c).abs() <= TOL)
            & (pik.isna() | ((pik - m).abs() <= TOL) | ((pik - c).abs() <= TOL))
            & (spread.isna() | ((spread - m).abs() <= TOL))).fillna(False)
