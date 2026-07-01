"""Tests for leaf->lien recovery from BDC XBRL instance document order.

Covers the accept path (run reconciles to subtotal), the false-positive
guard (a non-reconciling subtotal must NOT yield an accepted lien), the
structure-absent case, and lien-only (no sector) subtotals.
"""
from pipeline.bdc_lien_hierarchy import extract_lien_for_filing

_NS = (
    'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:us-gaap="http://fasb.org/us-gaap/2024"'
)


def _ctx_leaf(cid, issuer, instant="2025-12-31"):
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
        f'<xbrli:segment><xbrldi:typedMember dimension="us-gaap:InvestmentIdentifierAxis">'
        f'<x>{issuer}</x></xbrldi:typedMember></xbrli:segment></xbrli:entity>'
        f'<xbrli:period><xbrli:instant>{instant}</xbrli:instant></xbrli:period></xbrli:context>'
    )


def _ctx_sub(cid, lien_member, sector_member=None, instant="2025-12-31"):
    seg = f'<xbrldi:explicitMember dimension="us-gaap:LienAxis">{lien_member}</xbrldi:explicitMember>'
    if sector_member:
        seg += f'<xbrldi:explicitMember dimension="us-gaap:SectorAxis">{sector_member}</xbrldi:explicitMember>'
    return (
        f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>'
        f'<xbrli:segment>{seg}</xbrli:segment></xbrli:entity>'
        f'<xbrli:period><xbrli:instant>{instant}</xbrli:instant></xbrli:period></xbrli:context>'
    )


def _fv(cref, val):
    return f'<us-gaap:InvestmentOwnedAtFairValue contextRef="{cref}" unitRef="u" decimals="0">{val}</us-gaap:InvestmentOwnedAtFairValue>'


def _write(tmp_path, contexts, facts):
    body = "".join(contexts) + "".join(facts)
    xml = f'<xbrli:xbrl {_NS}>{body}</xbrli:xbrl>'
    p = tmp_path / "inst.xml"
    p.write_text(xml, encoding="utf-8")
    return str(p)


def test_reconciling_group_assigns_lien(tmp_path):
    ctxs = [_ctx_leaf("l1", "Acme 1"), _ctx_leaf("l2", "Beta 1"),
            _ctx_sub("s1", "us-gaap:DebtSecuritiesFirstLienMember", "ex:SoftwareSectorMember")]
    facts = [_fv("l1", 100), _fv("l2", 200), _fv("s1", 300)]  # 100+200 == 300
    r = extract_lien_for_filing(_write(tmp_path, ctxs, facts))
    assert r.structure_present
    assert r.reconciled_groups == 1 and r.total_groups == 1
    assert abs(r.recovered_fv - 300) < 1e-6
    assert {lf.issuer: (lf.lien, lf.reconciled) for lf in r.leaves} == {
        "Acme 1": ("First Lien", True), "Beta 1": ("First Lien", True)}


def test_nonreconciling_subtotal_is_not_accepted(tmp_path):
    # leaves sum to 50 but subtotal claims 999 -> must be flagged, not assigned
    ctxs = [_ctx_leaf("l1", "Gamma 1"),
            _ctx_sub("s1", "us-gaap:DebtSecuritiesSecondLienMember", "ex:EnergySectorMember")]
    facts = [_fv("l1", 50), _fv("s1", 999)]
    r = extract_lien_for_filing(_write(tmp_path, ctxs, facts))
    assert r.reconciled_groups == 0
    assert abs(r.recovered_fv) < 1e-6
    assert abs(r.flagged_fv - 50) < 1e-6
    # lien split routes the unreconciled leaf to Unknown, NOT Second Lien
    assert r.lien_split_fv().get("Unknown") == 50
    assert "Second Lien" not in r.lien_split_fv()


def test_structure_absent_when_no_subtotals(tmp_path):
    ctxs = [_ctx_leaf("l1", "Delta 1"), _ctx_leaf("l2", "Eps 1")]
    facts = [_fv("l1", 10), _fv("l2", 20)]
    r = extract_lien_for_filing(_write(tmp_path, ctxs, facts))
    assert not r.structure_present
    assert r.recovered_fv == 0
    assert r.lien_split_fv().get("Unknown") == 30


def test_lien_only_subtotal_reconciles(tmp_path):
    # no sector dimension, just a lien-tier total closing the run
    ctxs = [_ctx_leaf("l1", "Zeta 1"), _ctx_leaf("l2", "Eta 1"),
            _ctx_sub("s1", "us-gaap:DebtSecuritiesFirstLienMember")]
    facts = [_fv("l1", 40), _fv("l2", 60), _fv("s1", 100)]
    r = extract_lien_for_filing(_write(tmp_path, ctxs, facts))
    assert r.n_lien_only_subtotals == 1 and r.n_sector_subtotals == 0
    assert r.reconciled_groups == 1
    assert r.lien_split_fv().get("First Lien") == 100


def test_two_sectors_independently_grouped(tmp_path):
    ctxs = [_ctx_leaf("l1", "A 1"), _ctx_leaf("l2", "B 1"),
            _ctx_sub("s1", "us-gaap:DebtSecuritiesFirstLienMember", "ex:SoftwareSectorMember"),
            _ctx_leaf("l3", "C 1"),
            _ctx_sub("s2", "us-gaap:DebtSecuritiesFirstLienMember", "ex:HealthcareSectorMember")]
    facts = [_fv("l1", 10), _fv("l2", 20), _fv("s1", 30),
             _fv("l3", 70), _fv("s2", 70)]
    r = extract_lien_for_filing(_write(tmp_path, ctxs, facts))
    assert r.reconciled_groups == 2
    assert abs(r.recovered_fv - 100) < 1e-6
    assert r.lien_split_fv().get("First Lien") == 100
