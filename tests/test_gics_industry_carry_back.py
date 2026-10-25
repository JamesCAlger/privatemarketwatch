"""Opt-in carry-back of a filer's later printed GICS industry heading (D-232, HPS Corporate Capital Solutions)."""
import pandas as pd

from pipeline import unified_holdings as uh

FUND, OTHER = "0001989817", "0001111111"
HIER = {
    "Health Care Technology": {"sector": "Health Care", "industry_group": "x", "industry": "Health Care Technology"},
    "Pharmaceuticals": {"sector": "Health Care", "industry_group": "x", "industry": "Pharmaceuticals"},
    "Restaurants": {"sector": "Consumer Discretionary", "industry_group": "x", "industry": "Hotels, Restaurants & Leisure"},
    "Hotels, Resorts & Cruise Lines": {"sector": "Consumer Discretionary", "industry_group": "x",
                                       "industry": "Hotels, Restaurants & Leisure"},
    "Application Software": {"sector": "IT", "industry_group": "x", "industry": "Software"},
}
ENC = {FUND: {"gics_industry_carry_back": ["through 2025-09-30"]}}


def _frame(cik=FUND):
    rows = [
        # AthenaHealth: earlier label in another industry; later heading 'Health Care Technology'
        ("2024-06-30", "AthenaHealth Group Inc.", "Health Care Providers", "Pharmaceuticals"),
        ("2025-12-31", "AthenaHealth Group Inc", "Health Care Technology", "Health Care Technology"),
        # ONE Group: earlier sub-industry already inside the later industry -> kept
        ("2024-06-30", "The ONE Group Hospitality, Inc.", "Travel and Leisure", "Restaurants"),
        ("2025-12-31", "The ONE Group Hospitality, Inc.", "Hotels, Restaurants & Leisure", "Hotels, Resorts & Cruise Lines"),
        # Uncovered earlier row of a company printed later under 'Software' -> filled with the later rows' label
        ("2024-09-30", "Finastra USA, Inc.", "Software and Computer Services", ""),
        ("2026-03-31", "Finastra USA, Inc.", "Software", "Application Software"),
        # A company with no later heading stays uncovered
        ("2024-06-30", "Gone Company LLC", "General Industrials", ""),
        # A later row under a heading that is not a GICS industry does not count
        ("2024-06-30", "Alp CFO 2025, L.P.", "Structured Finance", ""),
        ("2025-12-31", "Alp CFO 2025, L.P.", "Structured Finance", ""),
        # A name that differs beyond punctuation (legal form) is not matched
        ("2024-06-30", "Corza Medical S.A R.L.", "Medical Equipment and Services", ""),
        ("2025-12-31", "Corza Medical Srl", "Health Care Technology", "Health Care Technology"),
    ]
    return pd.DataFrame([{"source": "bdc", "cik": cik, "report_date": q, "issuer_name": n, "extracted_industry": e,
                          "gics_sub_industry": g, "index_classification": "DIRECT_LENDING"} for q, n, e, g in rows])


def _run(frame, monkeypatch, enc=ENC):
    monkeypatch.setattr(uh, "printed_industry_gics", lambda labels: {
        "Health Care Technology": ("Health Care Technology", "exact"),
        "Hotels, Restaurants & Leisure": ("Hotels, Resorts & Cruise Lines", "alias"),
        "Software": ("Application Software", "alias")})
    monkeypatch.setattr("pipeline.staging_bdc.industry_label_gics_maps", lambda: {})
    return uh._carry_back_gics_industry(frame.copy(), encodings=enc, hierarchy=HIER)


def _sub(out, q, name):
    return out[(out["report_date"] == q) & (out["issuer_name"] == name)]["gics_sub_industry"].iloc[0]


def test_carries_later_heading_and_fills_uncovered(monkeypatch):
    out = _run(_frame(), monkeypatch)
    assert _sub(out, "2024-06-30", "AthenaHealth Group Inc.") == "Health Care Technology"
    assert _sub(out, "2024-09-30", "Finastra USA, Inc.") == "Application Software"
    # the printed heading of the row's own quarter is not touched
    assert out.loc[0, "extracted_industry"] == "Health Care Providers"


def test_keeps_sub_industry_inside_the_later_industry(monkeypatch):
    out = _run(_frame(), monkeypatch)
    assert _sub(out, "2024-06-30", "The ONE Group Hospitality, Inc.") == "Restaurants"


def test_false_positives_stay_uncovered(monkeypatch):
    out = _run(_frame(), monkeypatch)
    assert _sub(out, "2024-06-30", "Gone Company LLC") == ""
    assert _sub(out, "2024-06-30", "Alp CFO 2025, L.P.") == ""
    assert _sub(out, "2024-06-30", "Corza Medical S.A R.L.") == ""
    # later quarters are not changed
    assert _sub(out, "2025-12-31", "The ONE Group Hospitality, Inc.") == "Hotels, Resorts & Cruise Lines"


def test_company_key_ignores_punctuation_only():
    assert uh._company_key("Atlas Intermediate III, L.L.C.") == uh._company_key("Atlas Intermediate III LLC")
    assert uh._company_key("Alp CFO 2025, L.P.") == "alp cfo 2025 lp"
    assert uh._company_key("Orthrus Limited") != uh._company_key("Orthrus Ltd")


def test_company_with_two_later_headings_is_left(monkeypatch):
    frame = pd.concat([_frame(), pd.DataFrame([{"source": "bdc", "cik": FUND, "report_date": "2026-06-30",
                                                "issuer_name": "AthenaHealth Group Inc.", "extracted_industry": "Software",
                                                "gics_sub_industry": "Application Software",
                                                "index_classification": "DIRECT_LENDING"}])], ignore_index=True)
    out = _run(frame, monkeypatch)
    assert _sub(out, "2024-06-30", "AthenaHealth Group Inc.") == "Pharmaceuticals"


def test_fund_without_the_key_is_unchanged(monkeypatch):
    frame = _frame(cik=OTHER)
    out = _run(frame, monkeypatch)
    pd.testing.assert_frame_equal(out, frame)
    out = _run(_frame(), monkeypatch, enc={})
    pd.testing.assert_frame_equal(out, _frame())
