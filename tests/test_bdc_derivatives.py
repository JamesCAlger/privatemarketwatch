"""Tests for pipeline.bdc_derivatives -- derivative net-FV extraction + role classifier."""

from lxml import etree

from pipeline.bdc_derivatives import (
    _canon_type,
    _classify_role,
    _extract_filing,
)


# ---------------------------------------------------------------------------
# Type canonicalization
# ---------------------------------------------------------------------------

class TestCanonType:
    def test_interest_rate_swap(self):
        assert _canon_type("InterestRateSwapMember") == "INTEREST_RATE_SWAP"
        assert _canon_type("InterestRateSwap2029NotesMember") == "INTEREST_RATE_SWAP"

    def test_total_return_swap_before_swap(self):
        assert _canon_type("TotalReturnSwapMember") == "TOTAL_RETURN_SWAP"

    def test_fx_forward(self):
        assert _canon_type("ForeignExchangeForwardMember") == "FX_FORWARD"

    def test_floor_cap(self):
        assert _canon_type("InterestRateFloorOneMember") == "INTEREST_RATE_FLOOR"
        assert _canon_type("InterestRateCollarMember") == "INTEREST_RATE_CAP_COLLAR"

    def test_unknown(self):
        assert _canon_type("SomethingElseMember") is None


# ---------------------------------------------------------------------------
# Role classifier
# ---------------------------------------------------------------------------

class TestClassifyRole:
    def test_own_debt_is_financing_hedge(self):
        role, conf, mech = _classify_role("INTEREST_RATE_SWAP", 100.0, False, True, None)
        assert role == "financing_hedge" and mech == "names_own_debt" and conf >= 0.9

    def test_designated_is_financing_hedge(self):
        role, conf, mech = _classify_role("INTEREST_RATE_SWAP", 100.0, True, False, None)
        assert role == "financing_hedge" and mech == "asc815_designated"

    def test_trs_is_portfolio(self):
        role, _c, mech = _classify_role("TOTAL_RETURN_SWAP", 100.0, False, False, None)
        assert role == "portfolio" and mech == "type_prior_trs"

    def test_ir_notional_ties_debt(self):
        role, _c, mech = _classify_role("INTEREST_RATE_SWAP", 100.0, False, False, 0.5)
        assert role == "financing_hedge" and mech == "notional_ties_debt"

    def test_ir_notional_exceeds_debt_uncertain(self):
        role, _c, mech = _classify_role("INTEREST_RATE_SWAP", 100.0, False, False, 2.0)
        assert role == "uncertain" and mech == "notional_exceeds_debt"

    def test_ir_no_debt_prior(self):
        role, _c, mech = _classify_role("INTEREST_RATE_SWAP", 100.0, False, False, None)
        assert role == "financing_hedge" and mech == "type_prior_ir"

    def test_fx_forward_is_portfolio(self):
        role, _c, mech = _classify_role("FX_FORWARD", 100.0, False, False, None)
        assert role == "portfolio" and mech == "type_prior_fx"

    def test_option_is_portfolio(self):
        role, _c, _m = _classify_role("OPTION", 100.0, False, False, None)
        assert role == "portfolio"


# ---------------------------------------------------------------------------
# XBRL fixture: extraction + the floor-axis false-positive guard
# ---------------------------------------------------------------------------

_NS = (
    'xmlns="http://www.xbrl.org/2003/instance" '
    'xmlns:us-gaap="http://fasb.org/us-gaap/2024" '
    'xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
)


def _ctx(cid, members):
    seg = "".join(
        f'<xbrldi:explicitMember dimension="{dim}">{mem}</xbrldi:explicitMember>'
        for dim, mem in members
    )
    segblock = f"<segment>{seg}</segment>" if seg else ""
    return (
        f'<context id="{cid}"><entity>'
        f'<identifier scheme="http://www.sec.gov/CIK">0001234567</identifier>'
        f'{segblock}</entity>'
        f'<period><instant>2025-12-31</instant></period></context>'
    )


def _build_instance():
    DRA = "us-gaap:DerivativeInstrumentRiskAxis"
    FLOOR_AXIS = "us-gaap:InvestmentInterestRateFloorAxis"
    contexts = [
        _ctx("c_irs", [(DRA, "us-gaap:InterestRateSwapMember")]),
        _ctx("c_fx", [(DRA, "us-gaap:ForeignExchangeForwardMember")]),
        # loan with a rate-floor ATTRIBUTE -- must NOT be read as a derivative
        _ctx("c_loan", [(FLOOR_AXIS, "acme:InvestmentInterestRateFloorOneMember")]),
    ]
    facts = [
        # IR swap: net FV = 5 - 9 = -4M, notional 100M
        '<us-gaap:DerivativeFairValueOfDerivativeAsset contextRef="c_irs" unitRef="u">5000000</us-gaap:DerivativeFairValueOfDerivativeAsset>',
        '<us-gaap:DerivativeFairValueOfDerivativeLiability contextRef="c_irs" unitRef="u">9000000</us-gaap:DerivativeFairValueOfDerivativeLiability>',
        '<us-gaap:DerivativeNotionalAmount contextRef="c_irs" unitRef="u">100000000</us-gaap:DerivativeNotionalAmount>',
        # FX forward: net FV = 3M, notional 50M
        '<us-gaap:DerivativeFairValueOfDerivativeAsset contextRef="c_fx" unitRef="u">3000000</us-gaap:DerivativeFairValueOfDerivativeAsset>',
        '<us-gaap:DerivativeNotionalAmountToBeSold contextRef="c_fx" unitRef="u">50000000</us-gaap:DerivativeNotionalAmountToBeSold>',
        # loan investment at FV on the floor axis -- must be ignored
        '<us-gaap:InvestmentOwnedAtFairValue contextRef="c_loan" unitRef="u">78000000</us-gaap:InvestmentOwnedAtFairValue>',
    ]
    return (
        f'<xbrl {_NS}>'
        '<unit id="u"><measure>iso4217:USD</measure></unit>'
        + "".join(contexts) + "".join(facts) + "</xbrl>"
    )


class TestExtractFiling:
    def setup_method(self):
        self.data = _extract_filing(etree.fromstring(_build_instance().encode()), "2025-12-31")

    def test_per_type_net_fv(self):
        net = self.data["per_type_net"]
        assert abs(net["INTEREST_RATE_SWAP"] - (-4_000_000)) < 1
        assert abs(net["FX_FORWARD"] - 3_000_000) < 1

    def test_notional_separate_from_fv(self):
        assert abs(self.data["type_notional"]["INTEREST_RATE_SWAP"] - 100_000_000) < 1
        assert abs(self.data["type_notional"]["FX_FORWARD"] - 50_000_000) < 1

    def test_floor_axis_loan_not_a_derivative(self):
        # The InvestmentInterestRateFloorAxis loan ($78M) must NOT appear as a
        # derivative type, and must not leak into any net FV.
        assert "INTEREST_RATE_FLOOR" not in self.data["per_type_net"]
        assert "INTEREST_RATE_FLOOR" not in self.data["type_notional"]
        for v in self.data["per_type_net"].values():
            assert abs(v) < 60_000_000  # 78M loan never enters net FV
