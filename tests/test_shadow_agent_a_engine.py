"""Tests for the Agent A shadow engine verdict->status + cohort derivation."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import shadow_agent_a_engine as eng  # noqa: E402


def test_verdict_to_status_mapping():
    # 'neither' (internally-inconsistent filing) is the strongest flag -> fail
    assert eng._STATUS["neither"] == "fail"
    # all other verdicts are advisory warns (B prioritises via the mechanism)
    for v in ("agentA", "xbrl", "both", "undeterminable"):
        assert eng._STATUS[v] == "warn"


def test_seed_targets_documented():
    # the original hand-verified four are retained as a regression anchor
    assert {c for c, _ in eng.SEED_TARGETS} == {
        "0001993402", "0001278752", "0001655050", "0001633336"}


def test_candidate_grammars_have_rate_signatures():
    # runs over the real committed grammar dir (JSON-only, no parquet)
    candidates, skipped = eng.candidate_grammars()
    assert candidates, "expected committed rate grammars to exist"
    # every candidate declares a non-empty flattened signature
    assert all(sig for _, sig, _ in candidates)
    # the cohort is genuinely wider than the original four
    assert len(candidates) > len(eng.SEED_TARGETS)
    # every skipped entry explains itself (no silent drops)
    assert all(reason for *_, reason in skipped)


def test_build_cohort_gates_on_held_out_pass(tmp_path):
    # synthetic grammars: one flattened-PASS, one flattened-FAIL, one non-rate
    (tmp_path / "0000000001.json").write_text(
        json.dumps({"applies_to": {"regime": "flattened", "signature": "SIG A"}}),
        encoding="utf-8")
    (tmp_path / "0000000002.json").write_text(
        json.dumps({"applies_to": {"regime": "flattened", "signature": "SIG B"}}),
        encoding="utf-8")
    (tmp_path / "0000000003.json").write_text(
        json.dumps({"applies_to": {"regime": "delimited"}}), encoding="utf-8")

    class _V:
        def __init__(self, verdict, confidence="high"):
            self.verdict, self.confidence, self.reasons = verdict, confidence, ["because"]

    def fake_gate(cik, sig, parquet):
        return _V("PASS", "narrow") if cik == "0000000001" else _V("FAIL")

    cohort, excluded, skipped = eng.build_cohort("x", gate=fake_gate, grammar_dir=tmp_path)
    assert cohort == [("0000000001", "SIG A", "narrow")]            # PASS enrolled w/ confidence
    assert [c for c, *_ in excluded] == ["0000000002"]              # held-out FAIL excluded
    assert [c for c, *_ in skipped] == ["0000000003"]               # non-flattened skipped


# ---------------------------------------------------------------------------------------------
# Check repair REQ-APZ-1 (owner ruling DC-shared-83c62c0bdb, 2026-11-13): compare the published
# row with its own printed line; fail closed; unpublished contexts to coverage; whole identifier.
# ---------------------------------------------------------------------------------------------

CIK = "0001837532"
RD = "2024-06-30"
ACC = "0000950170-24-094137"
STALE = ("IT Services Vensure Vensure Employer Services, Inc. Investment Type First Lien Secured Debt "
         "Interest Rate S+525, 0.75% Floor Maturity Date 3/29/2027")
ALL_RULES = ("agentA_maturity_vs_xbrl", "agentA_spread_vs_xbrl", "agentA_reference_uncorroborated")


def _cand(rule, ident=STALE, rd=RD):
    return eng._flag(rule, CIK, rd, "warn", "m", ident)


def _ctx(ident=STALE, ctx="C_1", fv=27_000_000.0, cost=26_700_000.0, rd=RD):
    return {"identifier": ident, "report_date": rd, "accession_number": ACC, "src_context_id": ctx,
            "fair_value": fv, "cost": cost}


def _pub(ident=STALE, ctx="C_1", row_id="ROW-1", **fields):
    row = {"row_id": row_id, "identifier": ident, "report_date": RD, "accession_number": ACC,
           "src_context_id": ctx, "maturity_date": "2027-03-26", "basis_spread": 5.25,
           "reference_rate_type": "SOFR", "instrument_type": "Delayed Draw Term Loan", "record_class": ""}
    row.update(fields)
    return row


def _bridge(ident=STALE, ctx="C_1", **fields):
    b = {"raw_id_lower": ident.lower(), "maturity_date": "2027-03-26", "maturity_status": "value",
         "reference_rate_type": "SOFR", "reference_rate_status": "value", "printed_margin": 5.25,
         "printed_row": "Vensure Employer Services, Inc. | First Lien Secured Debt - Delayed Draw | "
                        "S+525, 0.75% Floor | 3/26/2027 | 27,011 | 26,728 | 27,000",
         "match_evidence": {"context_ref": ctx}}
    b.update(fields)
    return b


def _page(*bridges, raise_exc=False):
    calls = []

    def reader(*, cik, accession_number, report_date):
        calls.append((cik, accession_number, report_date))
        if raise_exc:
            raise OSError("page missing")
        return {"bridges": list(bridges)}
    page = eng.PageReader(reader)
    page.calls = calls
    return page


def test_stale_label_with_correct_published_values_does_not_fire():
    # label says 3/29/2027; published and printed both say 3/26/2027 -> no flag on any rule
    for rule in ALL_RULES:
        flags, cov = eng.resolve([_cand(rule)], [_ctx()], [_pub()], _page(_bridge()))
        assert flags == [] and cov == [], rule


def test_real_error_published_differs_from_printed_still_fires():
    cases = {
        "agentA_maturity_vs_xbrl": ({"maturity_date": "2027-03-29"}, "maturity_date"),
        "agentA_spread_vs_xbrl": ({"basis_spread": 5.75}, "basis_spread"),
        "agentA_reference_uncorroborated": ({"reference_rate_type": "LIBOR"}, "reference_rate_type"),
    }
    for rule, (wrong, field) in cases.items():
        flags, _ = eng.resolve([_cand(rule)], [_ctx()], [_pub(**wrong)], _page(_bridge()))
        assert len(flags) == 1, rule
        assert flags[0]["printed_check"] == "mismatch" and field in flags[0]["mismatch_fields"]
        assert flags[0]["row_id"] == "ROW-1" and flags[0]["mechanism"] == "m"  # mechanism unchanged (review id)


def test_other_field_wrong_on_flagged_row_still_fires():
    # Apollo D-265: maturity equal, but the published instrument_type contradicts the printed line
    flags, _ = eng.resolve([_cand("agentA_maturity_vs_xbrl")], [_ctx()], [_pub(instrument_type=None)],
                           _page(_bridge()))
    assert [f["mismatch_fields"] for f in flags] == ["instrument_type"]
    # published SOFR where the line prints a code the reader cannot confirm (SARON) -> stays flagged
    flags, _ = eng.resolve([_cand("agentA_maturity_vs_xbrl")], [_ctx()], [_pub()],
                           _page(_bridge(reference_rate_type="", reference_rate_status="validation_needed")))
    assert flags[0]["printed_check"] == "field_unreadable"


def test_printed_line_not_found_stays_flagged():
    for bridges, exc in (((), False), ((_bridge(printed_row=""),), False), ((), True)):
        flags, _ = eng.resolve([_cand("agentA_maturity_vs_xbrl")], [_ctx()], [_pub()],
                               _page(*bridges, raise_exc=exc))
        assert [f["printed_check"] for f in flags] == ["line_not_found"]


def test_rule_field_not_printed_stays_flagged():
    flags, _ = eng.resolve([_cand("agentA_spread_vs_xbrl")], [_ctx()], [_pub()],
                           _page(_bridge(printed_margin=None)))
    assert [f["printed_check"] for f in flags] == ["field_not_printed"]


def test_line_found_by_own_context_not_member_text():
    # the bridge's member text differs (label renamed) but the context is the row's own
    b = _bridge(ident="something else entirely", ctx="C_1")
    flags, _ = eng.resolve([_cand("agentA_maturity_vs_xbrl")], [_ctx()], [_pub()], _page(b))
    assert flags == []


def test_unpublished_contexts_raise_no_row_finding_and_money_goes_to_coverage():
    sub = "Total Pharmaceuticals"
    # zero-value undrawn line: nothing published, nothing carried -> no flag, no coverage
    flags, cov = eng.resolve([_cand("agentA_subtotal_candidate", ident=sub)],
                             [_ctx(ident=sub, ctx="C_9", fv=0.0, cost=0.0)], [], _page())
    assert flags == [] and cov == []
    # subtotal context carrying fair value and cost -> coverage row, not a finding
    flags, cov = eng.resolve([_cand("agentA_subtotal_candidate", ident=sub)],
                             [_ctx(ident=sub, ctx="C_9", fv=199_251_000.0, cost=199_673_000.0)], [], _page())
    assert flags == []
    assert [(c["identifier"], c["reason"], c["fair_value"]) for c in cov] == [(sub, "not_published", 199_251_000.0)]
    # a JV look-through row is retained, not published: coverage says so
    flags, cov = eng.resolve([_cand("agentA_maturity_vs_xbrl")], [_ctx()],
                             [_pub(record_class="underlying_schedule")], _page(_bridge()))
    assert flags == [] and [c["reason"] for c in cov] == ["underlying_schedule"]
    # ... also when the look-through row's member text differs but the context is the same
    flags, cov = eng.resolve([_cand("agentA_maturity_vs_xbrl")], [_ctx()],
                             [_pub(ident="JV schedule text", record_class="underlying_schedule")], _page(_bridge()))
    assert flags == [] and [c["reason"] for c in cov] == ["underlying_schedule"]


def test_subtotal_rule_on_published_row():
    ident = "Communications Equipment Mitel Networks Mitel Networks Investment Type Common Equity - Stock"
    pos = _bridge(ident=ident, printed_row="Mitel Networks | Common Equity - Stock | N/A | 733,019 Shares | 3,465 | 5,829")
    flags, _ = eng.resolve([_cand("agentA_subtotal_candidate", ident=ident)], [_ctx(ident=ident)],
                           [_pub(ident=ident)], _page(pos))
    assert flags == []  # its own line is a position line
    tot = _bridge(ident=ident, printed_row="Total Communications Equipment | 3,465 | 5,829")
    flags, _ = eng.resolve([_cand("agentA_subtotal_candidate", ident=ident)], [_ctx(ident=ident)],
                           [_pub(ident=ident)], _page(tot))
    assert [f["printed_check"] for f in flags] == ["subtotal_line"]
    flags, _ = eng.resolve([_cand("agentA_subtotal_candidate", ident=ident)], [_ctx(ident=ident)],
                           [_pub(ident=ident)], _page())
    assert [f["printed_check"] for f in flags] == ["line_not_found"]


def test_identifier_over_300_characters_kept_whole_and_joins_to_row():
    long_ident = "Wand Newco 3, Inc. " + "Investment Type First Lien Secured Debt - Term Loan " * 7
    assert len(long_ident) > 300
    assert eng._flag("agentA_maturity_vs_xbrl", CIK, RD, "warn", "m", long_ident)["identifier"] == long_ident
    flags, _ = eng.resolve([_cand("agentA_maturity_vs_xbrl", ident=long_ident)], [_ctx(ident=long_ident)],
                           [_pub(ident=long_ident, row_id="ROW-6a9dd3ea538799f3", maturity_date="2030-01-01")],
                           _page(_bridge(ident=long_ident)))
    assert [(f["row_id"], f["identifier"]) for f in flags] == [("ROW-6a9dd3ea538799f3", long_ident)]


def test_candidate_without_context_fails_closed():
    flags, _ = eng.resolve([_cand("agentA_spread_vs_xbrl")], [], [], _page())
    assert [f["printed_check"] for f in flags] == ["no_context"]


def test_printed_instrument_class_and_field_rules():
    assert eng.printed_instrument_class("First Lien Secured Debt - Delayed Draw Term Loan") == "delayed_draw"
    assert eng.printed_instrument_class("First lien senior secured revolving loan") == "revolver"
    assert eng.printed_instrument_class("First Lien Secured Debt - Corporate Bond | 6.75%") == "bond"
    assert eng.printed_instrument_class("Common Equity - Stock") is None
    assert not eng.field_differs("instrument_type", None, "bond")  # a bond publishes no loan class
    assert eng.field_differs("instrument_type", "Delayed Draw Term Loan", "bond")
    assert not eng.field_differs("instrument_type", "Unitranche", "term_loan")  # not comparable
    assert not eng.field_differs("reference_rate_type", None, "")  # fixed rate: no reference printed
    assert eng.field_differs("basis_spread", 9.5, None)
    assert not eng.field_differs("basis_spread", 5.2549, 5.25)


def test_page_read_once_per_filing():
    page = _page(_bridge())
    eng.resolve([_cand(r) for r in ALL_RULES], [_ctx()], [_pub()], page)
    assert page.calls == [(CIK, ACC, RD)]


def test_shadow_runner_regenerates_flags_before_reading(tmp_path, monkeypatch):
    import pytest
    import shadow_validation_runner as runner

    shadow = tmp_path / "shadow"
    shadow.mkdir()
    stale = shadow / eng.FLAGS_NAME
    stale.write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(runner, "OUTPUT_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(eng, "main", lambda argv=None: calls.append(argv) or 0)
    runner.run_agent_a()
    assert calls == [[]] and not stale.exists()

    def boom(argv=None):
        raise RuntimeError("engine failed")
    stale.write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(eng, "main", boom)
    with pytest.raises(RuntimeError):
        runner.run_agent_a()  # an engine failure stops the runner; no stale file is left to read
    assert not stale.exists()
