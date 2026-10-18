"""source_encodings.net_assets_concepts: which cached fact a fund's net assets must equal for the calculated percent.

TCW Direct Lending VIII, 10-Q 2026-03-31: 'Common Unitholders capital 879,986 ... Total Members Capital 815,597';
us-gaap:MembersCapital 879,986,000 (paid-in), us-gaap:MembersEquity 815,597,000 (total).
"""
import json

import pandas as pd
import pytest

from pipeline.financial_context import compatible_nav
from pipeline.source_encodings import load_encodings

CIK = "0001825265"
OTHER = "0001715933"


def _fact(val):
    return {"units": {"USD": [{"end": "2026-03-31", "filed": "2026-05-14", "accn": "0001193125-26-221923", "val": val}]}}


def _setup(tmp_path, net_assets):
    cf = tmp_path / "cf"
    cf.mkdir()
    for cik in (CIK, OTHER):
        (cf / (cik + ".json")).write_text(json.dumps({"cik": int(cik), "facts": {"us-gaap": {
            "MembersCapital": _fact(879986000), "MembersEquity": _fact(815597000)}}}), encoding="utf-8")
    fin = tmp_path / "ff.csv"
    pd.DataFrame([{"cik": c, "report_date": "2026-03-31", "source": "companyfacts", "net_assets": net_assets}
                  for c in (CIK, OTHER)]).to_csv(fin, index=False)
    holdings = pd.DataFrame([{"cik": c, "report_date": "2026-03-31", "source": "bdc"} for c in (CIK, OTHER)])
    return holdings, fin, cf


def _encodings(tmp_path):
    w = tmp_path / "w"
    w.mkdir()
    (w / (CIK + ".json")).write_text(json.dumps({"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK,
                                                  "source_encodings": {"net_assets_concepts": ["MembersEquity"]}}), encoding="utf-8")
    return load_encodings(w)


def _status(audit, cik):
    return audit.loc[audit["cik"] == cik, "status"].iloc[0]


def test_listed_fund_checks_total_capital_concept(tmp_path):
    holdings, fin, cf = _setup(tmp_path, 815597000)
    nav, audit = compatible_nav(holdings, fin, cf, encodings=_encodings(tmp_path))
    assert _status(audit, CIK) == "compatible"
    assert nav.loc[nav["cik"] == CIK, "net_assets"].iloc[0] == 815597000
    # unlisted fund, same facts: the shared list holds MembersCapital only, so 815,597,000 disagrees
    assert _status(audit, OTHER) == "fund_nav_disagrees_with_source"


def test_listed_fund_rejects_the_paid_in_figure(tmp_path):
    # false-positive guard: with the setting on, the paid-in line no longer passes
    holdings, fin, cf = _setup(tmp_path, 879986000)
    nav, audit = compatible_nav(holdings, fin, cf, encodings=_encodings(tmp_path))
    assert _status(audit, CIK) == "fund_nav_disagrees_with_source"
    assert _status(audit, OTHER) == "compatible"


def test_loader_rejects_a_prefixed_concept(tmp_path):
    w = tmp_path / "w2"
    w.mkdir()
    (w / (CIK + ".json")).write_text(json.dumps({"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK,
                                                  "source_encodings": {"net_assets_concepts": ["us-gaap:MembersEquity"]}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_encodings(w)
