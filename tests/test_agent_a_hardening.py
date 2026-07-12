"""Tests for the post-trial hardening: self-screen schema-conformance + anti-degeneracy (#1,#2),
the pre-dispatch rate-target floor (#3), and the A3-FAIL remediation emission."""

import json

import scripts.agent_a.run_quarter as rq
from scripts.agent_a import validate_proposal as vp
from scripts.agent_a.sample_variant import _era_stratified_pick


def _row(ident, rd):
    # build_bundle row tuple: ident,nm,int,spread,pik,mat,acc,rd  (rd at index 7)
    return (ident, "Acme", None, None, None, None, "acc-" + rd, rd)


def test_era_stratified_pick_covers_every_era():
    # 3 eras; the OLD era must be represented even though most rows are recent (the 2023 drift
    # bug: single-quarter sampling never showed the agent the old format).
    rows = ([_row(f"new {i}", "2025-12-31") for i in range(20)]
            + [_row("mid", "2024-06-30")]
            + [_row("old", "2023-03-31")])
    picked = _era_stratified_pick(rows, n_per_era=3)
    eras = {r[7] for r in picked}
    assert eras == {"2025-12-31", "2024-06-30", "2023-03-31"}   # every era covered
    assert sum(1 for r in picked if r[7] == "2025-12-31") == 3  # capped at n_per_era
    assert picked[0][7] == "2025-12-31"                          # newest era first


def test_flattened_shape_separates_breadcrumb_from_plain():
    # The Goldman pathology: a hierarchy breadcrumb (NAV %s before the issuer) is prepended to a
    # real position line. punctuation_shape over-fragments here; flattened_shape must put the
    # breadcrumb variant in a DIFFERENT class than the plain one so both get sampled.
    from scripts.agent_a import sample_variant as sv
    plain = ("CFS Management, LLC Industry Health Care Interest Rate 11.86% "
             "Reference Rate and Spread S + 6.25 Maturity 07/01/24")
    bc = ("Investment Debt Investments - 204.80% United States - 197.87% 1st Lien/Senior "
          "Secured Debt - 195.60% " + plain)
    assert sv.flattened_shape(plain).startswith("bc0")    # no % before the issuer
    assert sv.flattened_shape(bc).startswith("bc1")        # breadcrumb % before the issuer
    assert sv.flattened_shape(plain) != sv.flattened_shape(bc)


def test_shape_stratified_pick_surfaces_rare_layout():
    # 20 plain rows + 1 breadcrumb row in one era. Head selection (first n_per_era) drops the
    # rare breadcrumb -> held-out completeness FAIL; shape-stratified must surface it.
    from scripts.agent_a import sample_variant as sv
    plain = [_row(f"Issuer{i} LLC Interest Rate 10.0% Reference Rate and Spread S + 5.0 "
                  f"Maturity 1/1/30", "2025-12-31") for i in range(20)]
    bc = [_row("Debt Investments - 150.0% United States - 80.0% Issuer99 LLC Interest Rate "
               "10.0% Reference Rate and Spread S + 5.0 Maturity 1/1/30", "2025-12-31")]
    rows = plain + bc
    bc_shape = sv.flattened_shape(bc[0][0])
    head_shapes = {sv.flattened_shape(r[0]) for r in sv._era_stratified_pick(rows, 3)}
    shaped_shapes = {sv.flattened_shape(r[0]) for r in sv._shape_stratified_pick(rows, 3)}
    assert bc_shape not in head_shapes      # head selection never shows the worker the breadcrumb
    assert bc_shape in shaped_shapes        # shape-stratified does


def _write(tmp_path, grammar, anchors=None, samples=None):
    (tmp_path / "agent_a" / "proposals").mkdir(parents=True, exist_ok=True)
    (tmp_path / "agent_a" / "proposals" / "X.grammar.json").write_text(
        json.dumps(grammar), encoding="utf-8")
    (tmp_path / "agent_a" / "proposals" / "X.anchors.json").write_text(
        json.dumps(anchors or {"cik": "X", "anchors": [{"label": "SECDEBT", "regex": "secured debt"}]}),
        encoding="utf-8")
    b = tmp_path / "b.json"
    variants = [{"signature": "SECDEBT", "samples": samples}] if samples else []
    b.write_text(json.dumps({"top_variants": variants, "none_examples": []}), encoding="utf-8")
    return str(b)


def _good_grammar():
    return {"extractors": [{"field": "basis_spread", "regex": "([0-9.]+)%", "group": 1, "type": "pct"}],
            "required_fields": ["basis_spread"],
            "applies_to": {"regime": "flattened", "signature": "SECDEBT"},
            "invariants": [{"name": "spread_vs_twin", "kind": "pct_agree",
                            "parsed": "basis_spread", "twin": "basis_spread", "tol": 0.05}]}


_SAMPLE = [{"identifier": "Acme First Lien Secured Debt 5.00% Maturity 1/1/2030",
            "twins": {"basis_spread": 0.05}}]


def test_screen_fails_on_nonschema_key(tmp_path, monkeypatch):
    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    g = _good_grammar()
    g["extractors"][0]["source"] = "source_table"     # the Main Street hallucination
    g["extractors"][0]["unit"] = "pct"
    fails, warns, _ = vp.screen("X", _write(tmp_path, g))
    assert any("non-schema key" in f for f in fails)


def test_screen_fails_on_malformed_invariant_missing_keys(tmp_path, monkeypatch):
    # Regression: a pct_agree invariant without "parsed"/"twin" KeyError'd evaluate_invariants
    # over the whole population. The screen must reject it so the agent fixes it first.
    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    g = _good_grammar()
    g["invariants"] = [{"name": "spread_vs_twin", "kind": "pct_agree"}]   # missing parsed/twin
    fails, _, _ = vp.screen("X", _write(tmp_path, g))
    assert any("missing key(s)" in f and "parsed" in f for f in fails)


def test_screen_fails_on_group_index_exceeding_capture_groups(tmp_path, monkeypatch):
    # Regression: 0001987221's pik_terms_flag declared "group": 1 on a non-capturing regex
    # (0 capture groups). It compiled, so the old screen passed it, then crashed the engine.
    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    g = _good_grammar()
    g["extractors"].append({"field": "pik_terms_flag", "type": "text", "group": 1,
                            "regex": r"Interest Rate\s+[0-9]+(?:\.[0-9]+)?%\s+PIK\b"})
    fails, _, _ = vp.screen("X", _write(tmp_path, g))
    assert any("declares group 1" in f and "capture group" in f for f in fails)


def test_screen_fails_on_degenerate_required_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    g = _good_grammar()
    g["required_fields"] = ["investment_type"]          # no substantive rate field
    fails, _, _ = vp.screen("X", _write(tmp_path, g))
    assert any("DEGENERATE" in f and "substantive" in f for f in fails)


def test_screen_fails_on_rate_extractors_without_invariants(tmp_path, monkeypatch):
    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    g = _good_grammar()
    g["invariants"] = []                                # extracts rates but validates nothing
    fails, _, _ = vp.screen("X", _write(tmp_path, g))
    assert any("ZERO invariants" in f for f in fails)


def test_screen_passes_conformant_grammar(tmp_path, monkeypatch):
    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    fails, _, metrics = vp.screen("X", _write(tmp_path, _good_grammar(), samples=_SAMPLE))
    assert fails == []   # schema-conformant, substantive required, has invariant
    assert metrics["sample_completeness_pct"] == 100.0


def test_screen_fails_when_anchors_label_plurality_none(tmp_path, monkeypatch):
    # The Great Elm / TCW Star pathology: the agent's anchors classify the MODAL sampled
    # identifier as '(none)', so 'sample_completeness' is measured on a 1-row sliver and
    # passes vacuously (1/1 = 100%). The screen must reject this regardless of completeness.
    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    samples = [
        {"identifier": "Acme First Lien Secured Debt 5.00% Maturity 1/1/2030",
         "twins": {"basis_spread": 0.05}},                 # -> SECDEBT (the dom): the sliver
        {"identifier": "Beta Holdings bare issuer line", "twins": {}},   # -> (none)
        {"identifier": "Gamma Corp plain text only", "twins": {}},       # -> (none)
        {"identifier": "Delta LLC no structure here", "twins": {}},      # -> (none)
    ]
    fails, _, metrics = vp.screen("X", _write(tmp_path, _good_grammar(), samples=samples))
    assert metrics["actual_top_sig_in_sample"] == "(none)"
    assert metrics["sample_completeness_pct"] == 100.0      # vacuous pass on 1 dom row
    assert any("PLURALITY" in f and "(none)" in f for f in fails)


def test_screen_does_not_flag_none_when_dom_is_modal(tmp_path, monkeypatch):
    # Control / false-positive guard: a legit proposal whose dominant signature IS the modal
    # sampled signature must NOT trip the (none)-plurality fail, even with a minority of
    # unsignatured (e.g. equity/warrant) rows present.
    monkeypatch.setattr(vp.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(vp.config, "DATA_DIR", tmp_path)
    samples = [
        {"identifier": f"Issuer{i} First Lien Secured Debt 5.00% Maturity 1/1/2030",
         "twins": {"basis_spread": 0.05}} for i in range(3)
    ] + [{"identifier": "Epsilon equity co-invest warrant", "twins": {}}]   # lone (none) minority
    fails, _, metrics = vp.screen("X", _write(tmp_path, _good_grammar(), samples=samples))
    assert metrics["actual_top_sig_in_sample"] == "SECDEBT"
    assert not any("PLURALITY" in f for f in fails)


# --- #3 pre-dispatch rate-target floor ---
def test_rate_target_floor_separates_main_street_from_real_targets():
    # Main Street rate_embed 0.2 is below the floor; the lowest real target (MS-DL 27.1) is above
    assert 0.2 < rq.MIN_RATE_EMBED_PCT < 27.0


# --- A3 FAIL -> remediation emission ---
def test_emit_remediation_writes_worklist(tmp_path, monkeypatch):
    monkeypatch.setattr(rq.config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(rq, "build_bundle", lambda cik, **k: {"n_rows": 0})  # no bundle write
    results = [
        {"cik": "0001", "entity_name": "Fail Co", "verdict": "FAIL",
         "remediate_quarters": "2024-12-31", "reason": "completeness dip"},
        {"cik": "0002", "entity_name": "Pass Co", "verdict": "PASS", "remediate_quarters": ""},
    ]
    n = rq._emit_remediation("2025-12-31", results)
    assert n == 1   # only the FAIL is queued
    wl = tmp_path / "agent_a" / "quarter" / "2025-12-31" / "remediation_worklist.csv"
    assert wl.exists()
    assert "0001" in wl.read_text(encoding="utf-8")
    assert "0002" not in wl.read_text(encoding="utf-8")
