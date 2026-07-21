"""Tests for pipeline.convention_validation (the un-gameable verify step)."""

from pipeline.anchor_validation import HIGH, MEDIUM
from pipeline.convention_validation import verify_convention


def _leaf(convention="all_in", citations=None, **kw):
    base = {
        "cik": "1812554", "target_quarter": "2025-12-31",
        "convention": convention,
        "citations": citations if citations is not None else [
            {"kind": "header", "quote": "Interest Rate (2)", "where": "SOI"},
            {"kind": "position", "issuer": "Acme Corp",
             "quote": "12.50% (incl. 3.00% PIK)", "printed_total": 12.50, "printed_pik": 3.00},
            {"kind": "position", "issuer": "Beta LLC",
             "quote": "10.00% (incl. 2.00% PIK)", "printed_total": 10.00, "printed_pik": 2.00},
        ],
        "rationale": "...", "confidence": 0.9,
    }
    base.update(kw)
    return base


# stored rates consistent with ALL-IN storage of the cited positions
ALL_IN_STORED = {"acme corp": [(12.50, 3.00)], "beta llc": [(10.00, 2.00)]}
# stored rates consistent with CASH-LEG storage of the same printed text
CASH_STORED = {"acme corp": [(9.50, 3.00)], "beta llc": [(8.00, 2.00)]}
NEUTRAL_STATS = {"n_dual": 40, "n_viol": 0, "n_nearcap": 0}


def test_all_in_verdict_reconciles_and_passes():
    chk = verify_convention(_leaf(), ALL_IN_STORED, NEUTRAL_STATS)
    assert chk.ok and chk.n_reconciled == 2 and chk.tier == HIGH


def test_opposite_convention_reconciliation_is_hard_fail():
    # verdict says all_in but the stored rates fit cash_leg (ir = total - pik)
    chk = verify_convention(_leaf(), CASH_STORED, NEUTRAL_STATS)
    assert not chk.ok and chk.n_opposite == 2


def test_cash_leg_verdict_reconciles_via_total_minus_pik():
    chk = verify_convention(_leaf(convention="cash_leg"), CASH_STORED, NEUTRAL_STATS)
    assert chk.ok and chk.n_reconciled == 2


def test_cash_leg_verdict_reconciles_via_printed_cash():
    cits = [
        {"kind": "footnote", "quote": "PIK column reflects...", "where": "SOI"},
        {"kind": "position", "issuer": "Acme Corp", "quote": "9.50% Cash, 3.00% PIK",
         "printed_cash": 9.50, "printed_pik": 3.00},
        {"kind": "position", "issuer": "Beta LLC", "quote": "8.00% Cash, 2.00% PIK",
         "printed_cash": 8.00, "printed_pik": 2.00},
    ]
    chk = verify_convention(_leaf(convention="cash_leg", citations=cits),
                            CASH_STORED, NEUTRAL_STATS)
    assert chk.ok and chk.n_reconciled == 2


def test_needs_two_reconciled_citations():
    stored = {"acme corp": [(12.50, 3.00)]}      # Beta unmatched
    chk = verify_convention(_leaf(), stored, NEUTRAL_STATS)
    assert not chk.ok and chk.n_reconciled == 1 and chk.n_unmatched == 1


def test_multi_tranche_issuer_reconciles_if_any_fits():
    stored = {"acme corp": [(7.0, 0.0), (12.50, 3.00)],
              "beta llc": [(10.00, 2.00)]}
    chk = verify_convention(_leaf(), stored, NEUTRAL_STATS)
    assert chk.ok and chk.n_reconciled == 2


def test_contradiction_gate_cash_leg_vs_ceiling():
    stats = {"n_dual": 200, "n_viol": 0, "n_nearcap": 20}     # ceiling signature
    chk = verify_convention(_leaf(convention="cash_leg"), CASH_STORED, stats)
    assert not chk.ok
    assert any("refused_contradiction" in r for r in chk.reasons)


def test_contradiction_gate_all_in_vs_violations():
    stats = {"n_dual": 100, "n_viol": 20, "n_nearcap": 0}     # S1 convicts
    chk = verify_convention(_leaf(), ALL_IN_STORED, stats)
    assert not chk.ok
    assert any("refused_contradiction" in r for r in chk.reasons)


def test_no_header_citation_caps_tier_medium():
    cits = [c for c in _leaf()["citations"] if c["kind"] == "position"]
    chk = verify_convention(_leaf(citations=cits), ALL_IN_STORED, NEUTRAL_STATS)
    assert chk.ok and chk.tier == MEDIUM


def test_applies_from_before_sample_caps_tier_medium():
    chk = verify_convention(_leaf(applies_from="2022-03-31"), ALL_IN_STORED, NEUTRAL_STATS)
    assert chk.ok and chk.tier == MEDIUM


def test_indeterminate_passes_without_reconciliation():
    chk = verify_convention(_leaf(convention="indeterminate", citations=[],
                                  search_trail=["checked SOI"]),
                            {}, NEUTRAL_STATS)
    assert chk.ok and chk.tier == MEDIUM


def test_pik_only_partial_reconciliation_accepted_with_medium_cap():
    # Blue Owl shape: stored interest_rate is NULL on PIK rows; pik magnitude
    # corroborates -> accepted at MEDIUM, never HIGH
    stored = {"acme corp": [(None, 3.00)], "beta llc": [(None, 2.00)]}
    chk = verify_convention(_leaf(), stored, NEUTRAL_STATS)
    assert chk.ok and chk.n_pik_only == 2 and chk.tier == MEDIUM


def test_pik_only_with_wrong_pik_magnitude_refused():
    stored = {"acme corp": [(None, 9.99)], "beta llc": [(None, 9.99)]}
    chk = verify_convention(_leaf(), stored, NEUTRAL_STATS)
    assert not chk.ok


# --------------------------------------------------------------------- S0 gate

CASH_LEAF_CITS = [
    {"kind": "header", "quote": "Cash Rate / PIK Rate", "where": "SOI"},
    {"kind": "position", "issuer": "Acme Corp",
     "quote": "9.50% Cash, 3.00% PIK", "printed_cash": 9.50, "printed_pik": 3.00},
    {"kind": "position", "issuer": "Beta LLC",
     "quote": "8.00% Cash, 2.00% PIK", "printed_cash": 8.00, "printed_pik": 2.00},
]


def test_s0_gate_refuses_cash_leg_against_arithmetic_all_in_proof():
    s0 = {"s0_vote": "all_in", "s0_confidence": "high", "s0_mixed": False}
    chk = verify_convention(
        _leaf(convention="cash_leg", citations=CASH_LEAF_CITS),
        CASH_STORED, NEUTRAL_STATS, s0=s0)
    assert not chk.ok
    assert any("refused_contradiction" in r and "bare rate == cash + PIK" in r
               for r in chk.reasons)


def test_s0_gate_refuses_all_in_against_high_cash_concept_dominance():
    s0 = {"s0_vote": "cash_leg", "s0_confidence": "high", "s0_mixed": False}
    chk = verify_convention(_leaf(), ALL_IN_STORED, NEUTRAL_STATS, s0=s0)
    assert not chk.ok
    assert any("PaidInCash" in r for r in chk.reasons)


def test_s0_medium_cash_disagreement_caps_tier_not_refuses():
    # unguarded-label S0 (First Eagle failure mode exists) -> cap, don't refuse
    s0 = {"s0_vote": "cash_leg", "s0_confidence": "medium", "s0_mixed": False}
    chk = verify_convention(_leaf(), ALL_IN_STORED, NEUTRAL_STATS, s0=s0)
    assert chk.ok
    assert chk.tier == MEDIUM
    assert any("unguarded" in r for r in chk.reasons)


def test_s0_mixed_semantics_caps_tier():
    s0 = {"s0_vote": None, "s0_confidence": None, "s0_mixed": True}
    chk = verify_convention(_leaf(), ALL_IN_STORED, NEUTRAL_STATS, s0=s0)
    assert chk.ok
    assert chk.tier == MEDIUM
    assert any("per-row provenance" in r for r in chk.reasons)


def test_s0_agreement_leaves_verdict_untouched():
    s0 = {"s0_vote": "all_in", "s0_confidence": "high", "s0_mixed": False}
    chk = verify_convention(_leaf(), ALL_IN_STORED, NEUTRAL_STATS, s0=s0)
    assert chk.ok
    assert chk.tier == HIGH


def test_no_s0_behaves_exactly_as_before():
    chk = verify_convention(_leaf(), ALL_IN_STORED, NEUTRAL_STATS)
    assert chk.ok
    assert chk.tier == HIGH
