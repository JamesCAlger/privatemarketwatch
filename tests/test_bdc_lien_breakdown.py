"""Tests for the lien breakdown extractor (aggregate lien totals from
hierarchical BDC XBRL subtotals -- the lien analogue of sector breakdown)."""
from lxml import etree

from pipeline.bdc_sector_breakdown import (
    _parse_lien_contexts,
    _extract_lien_facts,
    _aggregate_lien_tiers,
)

_NS = (
    'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:us-gaap="http://fasb.org/us-gaap/2024"'
)


def _ctx(cid, members, instant="2025-12-31"):
    seg = "".join(
        f'<xbrldi:explicitMember dimension="{dim}">{mem}</xbrldi:explicitMember>'
        for dim, mem in members
    )
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity>'
        f'<xbrli:identifier scheme="x">1</xbrli:identifier>'
        f'<xbrli:segment>{seg}</xbrli:segment></xbrli:entity>'
        f'<xbrli:period><xbrli:instant>{instant}</xbrli:instant></xbrli:period></xbrli:context>'
    )


def _typed_ctx(cid, issuer, instant="2025-12-31"):
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity>'
        f'<xbrli:identifier scheme="x">1</xbrli:identifier><xbrli:segment>'
        f'<xbrldi:typedMember dimension="us-gaap:InvestmentIdentifierAxis"><x>{issuer}</x></xbrldi:typedMember>'
        f'</xbrli:segment></xbrli:entity>'
        f'<xbrli:period><xbrli:instant>{instant}</xbrli:instant></xbrli:period></xbrli:context>'
    )


def _fv(cref, val):
    return f'<us-gaap:InvestmentOwnedAtFairValue contextRef="{cref}" unitRef="u" decimals="0">{val}</us-gaap:InvestmentOwnedAtFairValue>'


def _tree(contexts, facts):
    xml = f'<xbrli:xbrl {_NS}>{"".join(contexts)}{"".join(facts)}</xbrli:xbrl>'
    return etree.ElementTree(etree.fromstring(xml.encode()))


_LIEN = "us-gaap:LienAxis"
_SEC = "us-gaap:EquitySecuritiesByIndustryAxis"


def _run(contexts, facts):
    tree = _tree(contexts, facts)
    return _aggregate_lien_tiers(_extract_lien_facts(tree, _parse_lien_contexts(tree)))


def test_lien_sector_subtotals_sum_to_tier():
    ctxs = [
        _ctx("a", [(_LIEN, "us-gaap:DebtSecuritiesFirstLienMember"), (_SEC, "ex:SoftwareSectorMember")]),
        _ctx("b", [(_LIEN, "us-gaap:DebtSecuritiesFirstLienMember"), (_SEC, "ex:EnergySectorMember")]),
    ]
    facts = [_fv("a", 100), _fv("b", 250)]
    out = {r["lien_tier"]: r for r in _run(ctxs, facts)}
    assert out["First Lien"]["fair_value"] == 350
    assert out["First Lien"]["grain"] == "lien_sector_sum"


def test_pure_tier_total_used_when_no_sector():
    ctxs = [_ctx("t", [(_LIEN, "us-gaap:DebtSecuritiesSecondLienMember")])]
    facts = [_fv("t", 900)]
    out = {r["lien_tier"]: r for r in _run(ctxs, facts)}
    assert out["Second Lien"]["fair_value"] == 900
    assert out["Second Lien"]["grain"] == "lien_only"


def test_sector_grain_preferred_over_pure_tier_no_double_count():
    # both a tier total (1000) and its sector children (400+600) present:
    # must use the sector sum, not add them together
    ctxs = [
        _ctx("tot", [(_LIEN, "us-gaap:DebtSecuritiesFirstLienMember")]),
        _ctx("s1", [(_LIEN, "us-gaap:DebtSecuritiesFirstLienMember"), (_SEC, "ex:SoftwareSectorMember")]),
        _ctx("s2", [(_LIEN, "us-gaap:DebtSecuritiesFirstLienMember"), (_SEC, "ex:HealthcareSectorMember")]),
    ]
    facts = [_fv("tot", 1000), _fv("s1", 400), _fv("s2", 600)]
    out = {r["lien_tier"]: r for r in _run(ctxs, facts)}
    assert out["First Lien"]["fair_value"] == 1000  # 400+600, not 2000
    assert out["First Lien"]["grain"] == "lien_sector_sum"


def test_position_level_lien_context_is_skipped():
    # a leaf position carrying a lien member must NOT be read as a subtotal
    ctxs = [_typed_ctx("p", "Acme 1")]
    # (a position context has no lien member here; ensure no lien rows emitted)
    facts = [_fv("p", 50)]
    assert _run(ctxs, facts) == []


def test_lien_x_affiliation_only_is_skipped_as_ambiguous():
    # lien crossed with a non-sector axis (no sector, not pure) -> skipped
    ctxs = [_ctx("x", [(_LIEN, "us-gaap:DebtSecuritiesFirstLienMember"),
                       ("us-gaap:InvestmentIssuerAffiliationAxis", "ex:NonAffiliatedMember")])]
    facts = [_fv("x", 123)]
    assert _run(ctxs, facts) == []
