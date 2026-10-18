"""pipeline.printed_sections: class by the printed schedule section (opt-in per wrapper)."""
import json
import re

import pandas as pd

from pipeline import printed_sections as ps

CIK = "0001803498"
ACC = "0001803498-25-000021"
RD = "2024-12-31"
SPEC = {"heading": re.compile(r"(?i)^(first lien|structured finance|equity)"),
        "structured": re.compile(r"(?i)^structured finance obligations"),
        "equity": re.compile(r"(?i)^structured finance obligations\s*-\s*equity instruments")}


def _row(ctx, name, fv):
    return (f"<tr><td>{name}</td><td><ix:nonFraction name='us-gaap:InvestmentOwnedAtFairValue' contextRef='{ctx}'>"
            f"{fv}</ix:nonFraction></td></tr>")


def _page(tmp_path):
    body = "".join([
        "<tr><td>First Lien Debt - non-controlled/non-affiliated</td></tr>",
        "<tr><td>Software</td></tr>",
        _row("c-1", "Acme Software, Inc.", "1,000"),
        "<tr><td>Structured Finance Obligations - Debt Instruments - non-controlled/non-affiliated</td></tr>",
        "<tr><td>Financial Services</td></tr>",
        _row("c-2", "Octagon 55, Ltd", "11,000"),
        "<tr><td>Structured Finance Obligations - Equity Instruments - non-controlled/non-affiliated</td></tr>",
        _row("c-3", "Rad CLO 25 Ltd - Subordinated Notes", "4,269"),
        "<tr><td>Equity - non-controlled/non-affiliated</td></tr>",
        _row("c-4", "Zoro - Common Equity", "12,557"),
    ])
    ctx = "".join(f"<xbrli:context id='c-{i}'><xbrli:period><xbrli:instant>{RD}</xbrli:instant></xbrli:period></xbrli:context>"
                  for i in range(1, 5))
    html = (f"<html xmlns:ix='http://www.xbrl.org/2013/inlineXBRL' xmlns:xbrli='http://www.xbrl.org/2003/instance'>"
            f"<body><div>{ctx}</div><table>{body}</table></body></html>")
    folder = tmp_path / CIK.lstrip("0")
    folder.mkdir()
    (folder / (ACC.replace("-", "") + ".html")).write_text(html, encoding="utf-8")
    return tmp_path


def _frame(cik=CIK):
    return pd.DataFrame([
        {"cik": cik, "source": "bdc", "accession_number": ACC, "report_date": RD, "src_context_id": f"c-{i}",
         "asset_category": cat, "index_classification": idx, "asset_class": ac, "lien_position": lien}
        for i, cat, idx, ac, lien in [
            (1, "LOAN", "DIRECT_LENDING", "PRIVATE_CREDIT", "First Lien"),
            (2, "LOAN", "DIRECT_LENDING", "PRIVATE_CREDIT", None),
            (3, "LOAN", "STRUCTURED_CREDIT", "STRUCTURED_CREDIT", None),
            (4, "EQUITY_COMMON", "COMMON_EQUITY", "PRIVATE_EQUITY", None)]])


def test_rows_under_structured_headings_are_reclassed(tmp_path):
    html_dir = _page(tmp_path)
    ps.sections_of_filing.cache_clear()
    out = ps.apply_structured_sections(_frame(), {CIK: SPEC}, html_dir)
    assert out["index_classification"].tolist() == ["DIRECT_LENDING", "STRUCTURED_CREDIT", "STRUCTURED_CREDIT", "COMMON_EQUITY"]
    assert out["asset_category"].tolist() == ["LOAN", "LOAN", "EQUITY_COMMON", "EQUITY_COMMON"]
    assert out.loc[1, "asset_class"] == "STRUCTURED_CREDIT"
    assert out.loc[0, "lien_position"] == "First Lien"


def test_equity_tranche_publishes_the_tagged_unit_count(tmp_path):
    html_dir = _page(tmp_path)
    ps.sections_of_filing.cache_clear()
    frame = _frame()
    frame["principal_amount"] = [1000.0, 11000.0, 5000000.0, None]
    frame["shares_held"] = [None, None, None, 1195880.0]
    frame["src_transforms"] = ["", "", "principal_amount:from_shares_tag", ""]
    out = ps.apply_structured_sections(frame, {CIK: SPEC}, html_dir)
    assert out.loc[2, "shares_held"] == 5000000.0 and out.loc[2, "principal_amount"] == 5000000.0
    assert pd.isna(out.loc[1, "shares_held"])  # a debt tranche keeps no unit count
    assert out.loc[3, "shares_held"] == 1195880.0


def test_fund_without_the_setting_is_unchanged(tmp_path):
    """False-positive guard: another fund's rows on the same page layout are not touched."""
    html_dir = _page(tmp_path)
    ps.sections_of_filing.cache_clear()
    frame = _frame(cik="0000000200")
    out = ps.apply_structured_sections(frame.copy(), {CIK: SPEC}, html_dir)
    pd.testing.assert_frame_equal(out, frame)


def test_industry_subheading_does_not_end_the_section(tmp_path):
    html_dir = _page(tmp_path)
    ps.sections_of_filing.cache_clear()
    found = ps.sections_of_filing(str(html_dir / CIK.lstrip("0") / (ACC.replace("-", "") + ".html")), RD, SPEC["heading"].pattern)
    assert found["c-2"] == "Structured Finance Obligations - Debt Instruments"
    assert found["c-4"] == "Equity"


def test_section_settings_reads_wrapper(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"cik": CIK, "dispatch": {"structured_credit_sections": {
        "heading_re": "^x", "structured_re": "^s", "equity_re": "^e"}}}))
    (tmp_path / "b.json").write_text(json.dumps({"cik": "0000000001", "dispatch": {}}))
    assert list(ps.section_settings(tmp_path)) == [CIK]
