"""Tests for the instrument-type breakdown extractor -- the XBRL-member
instrument-type analogue of the lien breakdown, sharing the same
parse/aggregate/reconciliation machinery (revolver / delayed draw / term loan /
unitranche)."""
from lxml import etree

from pipeline.bdc_lien_hierarchy import (
    _instrument_type,
    _lien_tier,
    recover_instrument_type,
)
from pipeline.bdc_sector_breakdown import (
    _parse_instrument_contexts,
    _extract_lien_facts,
    _aggregate_instrument_types,
)

_NS = (
    'xmlns:xbrli="http://www.xbrl.org/2003/instance" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
    'xmlns:us-gaap="http://fasb.org/us-gaap/2024"'
)
_TYPE = "us-gaap:InvestmentTypeAxis"
_LIEN = "us-gaap:LienAxis"
_SEC = "us-gaap:EquitySecuritiesByIndustryAxis"


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
    return (f'<us-gaap:InvestmentOwnedAtFairValue contextRef="{cref}" unitRef="u" '
            f'decimals="0">{val}</us-gaap:InvestmentOwnedAtFairValue>')


def _tree(contexts, facts):
    xml = f'<xbrli:xbrl {_NS}>{"".join(contexts)}{"".join(facts)}</xbrli:xbrl>'
    return etree.ElementTree(etree.fromstring(xml.encode()))


def _run(contexts, facts):
    tree = _tree(contexts, facts)
    return _aggregate_instrument_types(_extract_lien_facts(tree, _parse_instrument_contexts(tree)))


# --------------------------------------------------------------- mapper tests
def test_mapper_basic_types():
    assert _instrument_type("RevolverMember") == "Revolver"
    assert _instrument_type("RevolvingCreditFacilityMember") == "Revolver"
    assert _instrument_type("DelayedDrawTermLoanMember") == "Delayed Draw Term Loan"
    assert _instrument_type("TermLoanMember") == "Term Loan"
    assert _instrument_type("UnitrancheDebtMember") == "Unitranche"


def test_mapper_excludes_rate_index_buckets():
    # rate-index sub-buckets of term loans must NOT be counted (double-count guard)
    assert _instrument_type("TermLoanPrimeIndexOneMember") is None
    assert _instrument_type("TermLoanPrimeIndexTwoMember") is None


def test_mapper_no_type_on_pure_lien_members():
    assert _instrument_type("DebtSecuritiesFirstLienMember") is None
    assert _instrument_type("SecondLienDebtMember") is None
    assert _instrument_type("UnsecuredDebtMember") is None


def test_combined_member_yields_both_lien_and_type():
    # The non-negotiable false-positive guard: one combined member must resolve
    # to BOTH the correct lien tier AND the correct instrument type.
    m = "FirstLienSeniorSecuredTermLoanMember"
    assert _lien_tier(m) == "First Lien"
    assert _instrument_type(m) == "Term Loan"
    m2 = "DebtSecuritiesFirstLienSeniorSecuredLoansUnitrancheMember"
    assert _lien_tier(m2) == "First Lien"
    assert _instrument_type(m2) == "Unitranche"


# ----------------------------------------------------------- breakdown tests
def test_type_sector_subtotals_sum_to_type():
    ctxs = [
        _ctx("a", [(_TYPE, "us-gaap:TermLoanMember"), (_SEC, "ex:SoftwareSectorMember")]),
        _ctx("b", [(_TYPE, "us-gaap:TermLoanMember"), (_SEC, "ex:EnergySectorMember")]),
    ]
    facts = [_fv("a", 100), _fv("b", 250)]
    out = {r["instrument_type"]: r for r in _run(ctxs, facts)}
    assert out["Term Loan"]["fair_value"] == 350
    assert out["Term Loan"]["grain"] == "type_sector_sum"


def test_pure_type_total_used_when_no_sector():
    ctxs = [_ctx("a", [(_TYPE, "us-gaap:RevolverMember")])]
    facts = [_fv("a", 500)]
    out = {r["instrument_type"]: r for r in _run(ctxs, facts)}
    assert out["Revolver"]["fair_value"] == 500
    assert out["Revolver"]["grain"] == "type_only"


def test_sector_sum_preferred_over_pure_when_both_present():
    ctxs = [
        _ctx("p", [(_TYPE, "us-gaap:TermLoanMember")]),                                  # pure tier total
        _ctx("s1", [(_TYPE, "us-gaap:TermLoanMember"), (_SEC, "ex:SoftwareSectorMember")]),
        _ctx("s2", [(_TYPE, "us-gaap:TermLoanMember"), (_SEC, "ex:EnergySectorMember")]),
    ]
    facts = [_fv("p", 999), _fv("s1", 100), _fv("s2", 250)]
    out = {r["instrument_type"]: r for r in _run(ctxs, facts)}
    assert out["Term Loan"]["grain"] == "type_sector_sum"
    assert out["Term Loan"]["fair_value"] == 350   # sector-sum, not the 999 pure total


def test_position_axis_context_excluded():
    # a per-position context (typed Investment member) must not be read as a subtotal
    ctxs = [_typed_ctx("pos", "Acme Term Loan")]
    facts = [_fv("pos", 42)]
    assert _run(ctxs, facts) == []


def test_combined_member_subtotal_classified_as_type():
    ctxs = [_ctx("a", [(_LIEN, "us-gaap:FirstLienSeniorSecuredTermLoanMember")])]
    facts = [_fv("a", 700)]
    out = {r["instrument_type"]: r for r in _run(ctxs, facts)}
    assert out["Term Loan"]["fair_value"] == 700


def test_no_instrument_type_member_yields_no_rows():
    # a pure lien subtotal carries no instrument type -> not in the type breakdown
    ctxs = [_ctx("a", [(_LIEN, "us-gaap:DebtSecuritiesFirstLienMember")])]
    facts = [_fv("a", 700)]
    assert _run(ctxs, facts) == []


# ---------------------------------------- per-position recovery (document order)
_D = "2025-12-31"


def _ctxs(*specs):
    """specs: (cid, issuer, itype, lien). Returns contexts dict."""
    out = {}
    for cid, issuer, itype, lien in specs:
        out[cid] = {"issuer": issuer, "itype": itype, "lien": lien,
                    "sector": None, "instant": _D}
    return out


def test_recover_direct_typed_leaf():
    ctx = _ctxs(("a", "Acme TL", "Term Loan", "First Lien"))
    out = recover_instrument_type(ctx, [("a", 100.0)], period=_D)
    assert out == [("Acme TL", 100.0, "Term Loan", True)]


def test_recover_run_closed_by_reconciling_type_subtotal():
    ctx = _ctxs(("l1", "Acme", None, None), ("l2", "Beta", None, None),
                ("sub", None, "Term Loan", "First Lien"))
    facts = [("l1", 100.0), ("l2", 250.0), ("sub", 350.0)]
    out = recover_instrument_type(ctx, facts, period=_D)
    assert ("Acme", 100.0, "Term Loan", True) in out
    assert ("Beta", 250.0, "Term Loan", True) in out


def test_recover_nonreconciling_run_gets_no_type():
    ctx = _ctxs(("l1", "Acme", None, None), ("sub", None, "Term Loan", "First Lien"))
    facts = [("l1", 100.0), ("sub", 999.0)]   # 100 != 999 -> not reconciled
    out = recover_instrument_type(ctx, facts, period=_D)
    assert out == [("Acme", 100.0, None, False)]


def test_recover_lien_only_subtotal_flushes_untyped():
    ctx = _ctxs(("l1", "Acme", None, None), ("sub", None, None, "First Lien"))
    facts = [("l1", 100.0), ("sub", 100.0)]   # lien-only boundary -> no type
    out = recover_instrument_type(ctx, facts, period=_D)
    assert out == [("Acme", 100.0, None, False)]
