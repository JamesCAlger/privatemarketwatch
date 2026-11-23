"""Explicit numbered legal trusts retain distinct entity identities."""
import pandas as pd
import pytest

from pipeline.entity_resolution import (
    _TrustSeriesUnionFind, _cross_source_link, _exact_dedup, _fuzzy_cluster,
    _strip_trailing_number, extract_company_name, normalise_entity_name,
)


def variants(names, sources=None, **columns):
    frame = pd.DataFrame(dict(issuer_name=names, source=sources or ["bdc"] * len(names),
                              occurrence_count=[1] * len(names)))
    for column in ("cusip", "lei", "bdc_investment_identifier"):
        frame[column] = columns.get(column, [""] * len(names))
    return _exact_dedup(frame)


@pytest.mark.parametrize("suffix", ["No. 1", "No.1", "No 1", "No1", "Number 1", "No. 01"])
def test_explicit_trust_series_survives_extraction_and_normalizes_spelling(suffix):
    name = "Pallas NZ Funding Trust " + suffix
    assert extract_company_name(name) == name
    assert normalise_entity_name(extract_company_name(name)) == "pallas nz funding trust no1"


@pytest.mark.parametrize("name,expected", [("Acme LLC 1", "Acme LLC"),
    ("Acme LLC (2)", "Acme LLC"), ("Pallas Funding Trust 1", "Pallas Funding Trust"),
    ("Pallas Funding Trust No. 1 (2)", "Pallas Funding Trust No. 1")])
def test_ordinary_instrument_suffix_still_removed(name, expected):
    assert _strip_trailing_number(name) == expected


def test_actual_pallas_geographic_variants_do_not_merge_different_trusts():
    frame = variants(["Pallas NZ Funding Trust No. 1", "Pallas Funding Trust No. 2"])
    output = _fuzzy_cluster(frame)
    assert output.entity_num.nunique() == 2


def test_same_series_punctuation_variants_exact_dedup():
    frame = variants(["Pallas Funding Trust No.1", "Pallas Funding Trust Number 1"])
    assert frame.entity_num.nunique() == 1


@pytest.mark.parametrize("reverse", [False, True])
def test_unnumbered_component_cannot_bridge_different_series(reverse):
    frame = variants(["Pallas Funding Trust No. 1", "Pallas Funding Trust", "Pallas Funding Trust No. 2"])
    ids = dict(zip(frame.issuer_name, frame.entity_num))
    a, bridge, b = [ids[name] for name in frame.issuer_name]
    if reverse:
        a, b = b, a
    uf = _TrustSeriesUnionFind(frame)
    assert uf.union(a, bridge)
    assert not uf.union(bridge, b)
    assert uf.find(a) != uf.find(b)


def test_fuzzy_bridge_cannot_join_known_conflicting_series():
    frame = variants(["Pallas Funding Trust No. 1", "Pallas Funding Trust", "Pallas NZ Funding Trust No. 2"])
    output = _fuzzy_cluster(frame, threshold=80)
    numbered = output.loc[output.issuer_name.str.contains("No.", regex=False)]
    assert numbered.entity_num.nunique() == 2


@pytest.mark.parametrize("identifier", ["cusip", "lei", "fuzzy"])
def test_cross_source_paths_preserve_distinct_trusts(identifier):
    columns = {} if identifier == "fuzzy" else {identifier: ["shared-instrument-id"] * 2}
    frame = variants(["Pallas NZ Funding Trust No. 1", "Pallas Funding Trust No. 2"],
                     sources=["bdc", "nport"], **columns)
    assert _cross_source_link(frame).entity_num.nunique() == 2


def test_cross_source_same_trust_identifier_match_remains_allowed():
    frame = variants(["Pallas NZ Funding Trust No. 1", "Pallas Funding Trust No. 1"],
                     sources=["bdc", "nport"], cusip=["same-id"] * 2)
    assert _cross_source_link(frame).entity_num.nunique() == 1


def test_cross_source_preserves_series_hidden_by_unnumbered_component_representative():
    frame = variants(["Pallas Funding Trust", "Pallas NZ Funding Trust No. 1", "Pallas Funding Trust No. 2"],
                     sources=["bdc", "bdc", "nport"], cusip=["same-id"] * 3)
    first = frame.loc[frame.issuer_name == "Pallas Funding Trust", "entity_num"].iloc[0]
    frame.loc[frame.source == "bdc", "entity_num"] = first
    output = _cross_source_link(frame)
    assert output.loc[output.source == "bdc", "entity_num"].iloc[0] != output.loc[
        output.source == "nport", "entity_num"].iloc[0]
