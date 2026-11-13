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
    # the line prints no 'CODE + margin' and the reader read none
    flags, _ = eng.resolve([_cand("agentA_spread_vs_xbrl")], [_ctx()], [_pub()],
                           _page(_bridge(printed_margin=None, printed_row="Vensure Employer Services, Inc. | "
                                         "First Lien Secured Debt - Delayed Draw | 3/26/2027 | 27,011 | 27,000")))
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
    assert (shadow / eng.PREVIOUS_NAME).read_text(encoding="utf-8") == "stale\n"  # kept for carry-forward (D1)

    def boom(argv=None):
        raise RuntimeError("engine failed")
    stale.write_text("stale\n", encoding="utf-8")
    monkeypatch.setattr(eng, "main", boom)
    with pytest.raises(RuntimeError):
        runner.run_agent_a()  # an engine failure stops the runner; no stale file is left to read
    assert not stale.exists()


# ---------------------------------------------------------------------------------------------
# Code review D1-D7 (2026-11-13)
# ---------------------------------------------------------------------------------------------

def _write_flags(path, rows):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=eng._FIELDS)
        w.writeheader()
        w.writerows(rows)


def test_d1_fund_leaving_cohort_keeps_its_flags(tmp_path, monkeypatch):
    prev = tmp_path / "prev.csv"
    old = dict(_cand("agentA_maturity_vs_xbrl"), cik="0001920453", mechanism="identifier_maturity_ne_structured")
    other = dict(_cand("agentA_spread_vs_xbrl"), cik="0000000099")
    _write_flags(prev, [old, other])
    monkeypatch.setattr(eng, "build_cohort", lambda parquet: (
        [], [("0001920453", "AFFIL SECDEBT REFRATE RATE MAT", "2026-06-30: completeness 89.8% < 90.0%")], []))
    monkeypatch.setattr(eng, "_quarters", lambda con, parquet, cik: ["2026-03-31"])
    out = tmp_path / "shadow"
    eng.run(bdc_holdings=tmp_path / "x.parquet", published=tmp_path / "y.parquet", out_dir=out,
            page=_page(), previous=prev)
    import csv
    flags = list(csv.DictReader(open(out / eng.FLAGS_NAME, encoding="utf-8")))
    assert sorted((f["cik"], f["rule_name"], f["mechanism"], f["printed_check"]) for f in flags) == [
        ("0001920453", "agentA_cohort_excluded", "held_out_fail", "cohort_excluded"),
        ("0001920453", "agentA_maturity_vs_xbrl", "identifier_maturity_ne_structured", "cohort_excluded")]
    rec = list(csv.DictReader(open(out / eng.EXCLUDED_NAME, encoding="utf-8")))
    assert rec[0]["cik"] == "0001920453" and rec[0]["carried_flags"] == "1" and "completeness" in rec[0]["reason"]


def test_d1_gate_error_is_excluded_and_carried(tmp_path):
    def gate(cik, sig, parquet):
        raise RuntimeError("boom")
    (tmp_path / "0000000007.json").write_text(
        json.dumps({"applies_to": {"regime": "flattened", "signature": "SIG"}}), encoding="utf-8")
    cohort, excluded, _ = eng.build_cohort("x", gate=gate, grammar_dir=tmp_path)
    assert cohort == [] and excluded[0][0] == "0000000007" and "gate error" in excluded[0][2]
    prev = tmp_path / "prev.csv"
    _write_flags(prev, [dict(_cand("agentA_spread_vs_xbrl"), cik="0000000007")])
    carried, records = eng.carry_forward(prev, excluded)
    assert len(carried) == 1 and records[0]["carried_flags"] == 1


def test_d2_outputs_are_byte_identical_whatever_the_input_order(tmp_path):
    import random
    rows = [dict(_cand(r, ident=f"{STALE} {i}"), mechanism=m)
            for i in range(6) for r in ALL_RULES for m in ("reconcile_both", "reconcile_xbrl")]
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    eng.write_outputs(tmp_path / "a", rows, [], rows, [])
    eng.write_outputs(tmp_path / "b", shuffled, [], list(reversed(rows)), [])
    for name in (eng.FLAGS_NAME, eng.AUDIT_NAME, eng.COVERAGE_NAME, eng.EXCLUDED_NAME):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_d3_reference_rule_keeps_flag_when_spread_missing_and_line_prints_margin():
    # VetStrategy shape: reference matches, published spread blank, line prints 'C + 700 (100 Floor)'
    b = _bridge(printed_row="VetStrategy | Senior Secured First Lien Term Loan | C + 700 (100 Floor) | 10.59 % | 08/2027",
                reference_rate_type="CDOR", printed_margin=None)
    p = _pub(reference_rate_type="CDOR", basis_spread=None, instrument_type="Term Loan")
    flags, _ = eng.resolve([_cand("agentA_reference_uncorroborated")], [_ctx()], [p], _page(b))
    # read as a D-031 margin (7.00 over CDOR, published blank) -> mismatch; spread_missing covers a
    # margin the D-031 reader cannot place
    assert [(f["printed_check"], f["mismatch_fields"]) for f in flags] == [("mismatch", "basis_spread")]
    assert eng.compare_row("agentA_reference_uncorroborated", p,
                           dict(b, printed_row="VetStrategy | Term Loan | 3M SOFR+565 | 08/2027", printed_margin=5.65,
                                reference_rate_type="SOFR"))[0] in ("spread_missing", "mismatch")
    # PIK-only margins: under D-031 the spread is the cash + PIK total, so a blank published spread
    # differs from the printed total and the flag stays; the published total clears it
    for line, total in (("X | Term Loan | S + 1000 PIK | 3/26/2027", 10.0),
                        ("X | Term Loan | ( S + 0.00 %; 0.75 % Floor; 5.75 % PIK) | 3/26/2027", 5.75)):
        b = _bridge(printed_row=line, printed_margin=None)
        assert eng.compare_row("agentA_reference_uncorroborated", _pub(basis_spread=None, instrument_type="Term Loan"),
                               b) == ("mismatch", ["basis_spread"])
        assert eng.compare_row("agentA_reference_uncorroborated", _pub(basis_spread=total, instrument_type="Term Loan"),
                               b) == ("equal", [])


def test_d4_zero_width_prefixed_total_line_is_a_subtotal():
    ident = "Total First Lien Debt Leaked"
    b = _bridge(ident=ident, printed_row="​ | ​ |   | Total First Lien Debt | 1,234 | 1,456")
    flags, _ = eng.resolve([_cand("agentA_subtotal_candidate", ident=ident)], [_ctx(ident=ident)],
                           [_pub(ident=ident)], _page(b))
    assert [f["printed_check"] for f in flags] == ["subtotal_line"]
    assert eng.first_cell("​ | ​ | Acme Corp | Term Loan") == "Acme Corp"


def test_d5_member_fallback_needs_a_single_context():
    b = _bridge(ctx="C_OTHER")  # the bridge is keyed to another context of the same member
    # member has one context: fallback accepted, method recorded
    audit = []
    flags, _ = eng.resolve([_cand("agentA_maturity_vs_xbrl")], [_ctx()], [_pub()], _page(b), audit)
    assert flags == [] and audit[0]["line_match"] == "member"
    # member has two contexts (e.g. an unfunded line with an extra axis): fail closed
    flags, _ = eng.resolve([_cand("agentA_maturity_vs_xbrl")], [_ctx(), _ctx(ctx="C_2", fv=0.0, cost=0.0)],
                           [_pub()], _page(b))
    assert [(f["printed_check"], f["line_match"]) for f in flags] == [("line_not_found", "member_ambiguous")]
    # by context: recorded as such
    audit = []
    eng.resolve([_cand("agentA_maturity_vs_xbrl")], [_ctx()], [_pub()], _page(_bridge()), audit)
    assert audit[0]["line_match"] == "context"


def test_d6_runner_regenerates_before_adapters_read():
    import inspect
    import shadow_validation_runner as runner
    src = inspect.getsource(runner.main)
    assert 0 <= src.index("run_agent_a()") < src.index("adp.adapter_selects()")


_FIXTURE = """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:us-gaap="http://fasb.org/us-gaap/2024"><body>
<ix:header><ix:resources>
<xbrli:context id="C_1"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
<xbrli:segment><xbrldi:typedMember dimension="us-gaap:InvestmentIdentifierAxis"><x>Acme Corp First Lien Term Loan S + 525 Maturity 3/29/2027</x></xbrldi:typedMember></xbrli:segment></xbrli:entity>
<xbrli:period><xbrli:instant>2024-06-30</xbrli:instant></xbrli:period></xbrli:context>
</ix:resources></ix:header>
<table>
<tr><td>Company</td><td>Investment</td><td>Reference Rate and Spread</td><td>Maturity Date</td><td>Par</td><td>Cost</td><td>Fair Value</td></tr>
<tr><td>Acme Corp</td><td>First Lien Term Loan</td><td>S + 525</td><td>3/26/27</td><td>1,000</td>
<td><ix:nonFraction name="us-gaap:InvestmentOwnedAtCost" contextRef="C_1" unitRef="usd" decimals="-3" scale="3">990</ix:nonFraction></td>
<td><ix:nonFraction name="us-gaap:InvestmentOwnedAtFairValue" contextRef="C_1" unitRef="usd" decimals="-3" scale="3">995</ix:nonFraction></td></tr>
</table></body></html>"""


def test_d6_real_page_reader_on_a_fixture(tmp_path):
    """The real reader (propose_field_bridges_from_ixbrl) on a small inline-XBRL page: context-keyed
    bridge, two-digit-year maturity, basis-point margin. Stale label (3/29/2027) vs printed 3/26/27."""
    from pipeline.bdc_xbrl_html_bridge import propose_field_bridges_from_ixbrl
    html = tmp_path / "f.html"
    html.write_text(_FIXTURE, encoding="utf-8")

    def reader(*, cik, accession_number, report_date):
        return propose_field_bridges_from_ixbrl(cik=cik, accession_number=accession_number,
                                                report_date=report_date, html_path=html, encodings={})
    ident = "Acme Corp First Lien Term Loan S + 525 Maturity 3/29/2027"
    page = eng.PageReader(reader)
    b, method = page.lookup_with_method("0000000001", ACC, RD, "C_1", ident)
    assert method == "context" and b and "Acme Corp" in b["printed_row"]
    pub = _pub(ident=ident, maturity_date="2027-03-26", instrument_type="Term Loan")
    flags, _ = eng.resolve([_cand("agentA_maturity_vs_xbrl", ident=ident)], [_ctx(ident=ident)], [pub], page)
    assert flags == []  # published equals the printed line
    flags, _ = eng.resolve([_cand("agentA_maturity_vs_xbrl", ident=ident)], [_ctx(ident=ident)],
                           [dict(pub, maturity_date="2027-03-29")], page)
    assert [f["printed_check"] for f in flags] == ["mismatch"]  # published carries the stale label's date


# D-031 in the engine (orchestrator 2026-11-13): the published spread is the cash + PIK total
GTY = ("GTY Technology Holdings Inc. | First Lien Delayed Draw Term Loan | SOFR(Q) | 1.00 % | 2.50 % Cash + "
       "4.13 % PIK | 10.30 % | 7/9/2029 | $ 1,134,951 | 1,121,283 | 1,120,846")


def test_d031_cash_only_published_where_line_prints_cash_plus_pik_still_fires():
    # RVQ_BLK_7a79fc2cbff8 (BlackRock Private Credit 2025-12-31): GTY publishes the cash 2.50, not 6.63
    b = _bridge(printed_row=GTY, printed_margin=None, maturity_date="2029-07-09")
    p = _pub(maturity_date="2029-07-09", basis_spread=2.50, instrument_type="Delayed Draw Term Loan")
    for rule in ("agentA_reference_uncorroborated", "agentA_spread_vs_xbrl"):
        flags, _ = eng.resolve([_cand(rule)], [_ctx()], [p], _page(b))
        assert [(f["printed_check"], f["mismatch_fields"]) for f in flags] == [("mismatch", "basis_spread")], rule
    # the floor is not the margin either
    flags, _ = eng.resolve([_cand("agentA_spread_vs_xbrl")], [_ctx()], [dict(p, basis_spread=1.00)], _page(b))
    assert flags[0]["mismatch_fields"] == "basis_spread"
    # the total clears
    flags, _ = eng.resolve([_cand("agentA_spread_vs_xbrl")], [_ctx()], [dict(p, basis_spread=6.63)], _page(b))
    assert flags == []


def test_d031_ambiguous_margin_fails_closed():
    line = "Madison Logic | First Lien Term Loan | SOFR(M) | 1.00 % | 4.73 % | 10.72 % | 12/29/2028 | 2,274,371"
    b = _bridge(printed_row=line, printed_margin=4.73, maturity_date="2028-12-29")
    p = _pub(maturity_date="2028-12-29", basis_spread=4.73, instrument_type="Term Loan")
    flags, _ = eng.resolve([_cand("agentA_spread_vs_xbrl")], [_ctx()], [p], _page(b))
    assert [(f["printed_check"], f["mismatch_fields"]) for f in flags] == [("field_unreadable", "basis_spread")]


def test_r2_2_fresh_sandbox_excluded_fund_reaches_the_ledger_as_findings(tmp_path, monkeypatch):
    """A fund sandbox has no previous flags file. An excluded fund still gets one fund-level flag per
    quarter, and the shadow adapter + review queue turn each into a review item (a ledger finding)."""
    import shadow_adapter as adp
    from pipeline.review_queue import _queue_item
    import duckdb

    monkeypatch.setattr(eng, "build_cohort", lambda parquet: (
        [], [("0001920453", "AFFIL SECDEBT REFRATE RATE MAT", "2026-06-30: completeness 89.8% < 90.0%"),
             ("0000000007", "SIG", "gate error: boom")], []))
    monkeypatch.setattr(eng, "_quarters", lambda con, parquet, cik: ["2025-12-31", "2026-03-31"])
    sandbox = tmp_path / "sandbox_output"
    out = sandbox / "shadow"
    eng.run(bdc_holdings=tmp_path / "x.parquet", published=tmp_path / "y.parquet", out_dir=out,
            page=_page(), previous=out / eng.PREVIOUS_NAME)  # does not exist
    monkeypatch.setattr(adp, "OUTPUT_DIR", sandbox)
    con = duckdb.connect()
    rows = con.execute(f"SELECT * FROM ({adp._agent_a_select()})").fetchdf().astype(str).to_dict("records")
    items = [_queue_item(r) for r in rows]
    got = sorted((i["cik"], i["report_date"], i["rule_name"], i["mechanism"], i["lane"]) for i in items if i)
    assert got == [("0000000007", "2025-12-31", "agentA_cohort_excluded", "gate_error", "blocker"),
                   ("0000000007", "2026-03-31", "agentA_cohort_excluded", "gate_error", "blocker"),
                   ("0001920453", "2025-12-31", "agentA_cohort_excluded", "held_out_fail", "blocker"),
                   ("0001920453", "2026-03-31", "agentA_cohort_excluded", "held_out_fail", "blocker")]
    import csv
    rec = {r["cik"]: r for r in csv.DictReader(open(out / eng.EXCLUDED_NAME, encoding="utf-8"))}
    assert rec["0001920453"]["carried_flags"] == "0" and rec["0001920453"]["fund_level_flags"] == "2"


def test_r3_1_fund_level_rows_are_regenerated_not_carried(tmp_path, monkeypatch):
    """Two consecutive builds, the second reading the first's file as previous: the fund-level
    agentA_cohort_excluded rows stay at one per fund-quarter, and the carried row is not duplicated."""
    import csv
    import shutil
    monkeypatch.setattr(eng, "build_cohort", lambda parquet: (
        [], [("0001920453", "SIG", "2026-06-30: completeness 89.8% < 90.0%")], []))
    monkeypatch.setattr(eng, "_quarters", lambda con, parquet, cik: ["2025-12-31", "2026-03-31"])
    out = tmp_path / "shadow"
    prev = out / eng.PREVIOUS_NAME
    out.mkdir()
    _write_flags(prev, [dict(_cand("agentA_maturity_vs_xbrl"), cik="0001920453")])
    counts = []
    for _ in range(3):
        eng.run(bdc_holdings=tmp_path / "x.parquet", published=tmp_path / "y.parquet", out_dir=out,
                page=_page(), previous=prev)
        flags = list(csv.DictReader(open(out / eng.FLAGS_NAME, encoding="utf-8")))
        counts.append((sum(f["rule_name"] == eng.COHORT_EXCLUDED_RULE for f in flags), len(flags)))
        shutil.copyfile(out / eng.FLAGS_NAME, prev)  # what the shadow runner does between builds
    assert counts == [(2, 3), (2, 3), (2, 3)]


def test_r2_1_thousands_separator_bp_margin_in_the_engine():
    # 0001383414 PRA Events 2023-03-31: '3M L+1,050' with a published 1.0 spread is a mismatch, not equal
    b = _bridge(printed_row="PRA Events | First Lien | 3M L+1,050 | 17.00 % | 3/26/2027 | 1,234", printed_margin=None,
                reference_rate_type="LIBOR")
    p = _pub(basis_spread=1.0, reference_rate_type="LIBOR", instrument_type=None)
    assert eng.compare_row("agentA_reference_uncorroborated", p, b) == ("mismatch", ["basis_spread"])
    assert eng.compare_row("agentA_reference_uncorroborated", dict(p, basis_spread=10.5), b) == ("equal", [])
