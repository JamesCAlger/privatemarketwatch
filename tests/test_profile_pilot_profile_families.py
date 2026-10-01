"""SP3 proper Task 4: spec 7.1 override-family disposition and the fail-closed scanner. tmp_path trees only."""
from __future__ import annotations

import json

import pytest

from scripts.profile_pilot import profile_families as pf

ARES, STELLUS, BCRED = "0001287750", "0001901037", "0001803498"
PILOT = (ARES, STELLUS, BCRED)


def write_tree(root, files):
    for rel, value in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = value if isinstance(value, str) else json.dumps(value, indent=2)
        path.write_text(text, encoding="utf-8")
    return root


def wrapper_v3(cik, **extra):
    body = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": cik, "entity_name": "Fund " + cik, "version": 1,
            "source": "bdc_xbrl",
            "dispatch": {"rule_prefix": "F" + cik[-4:], "prefix_rules": {"Second Lien": "debt", "First Lien": "debt"},
                         "aggregate_markers": ["total investments"]},
            "identifier_format": {"delimiter": " | "}}
    body.update(extra)
    return body


def base_tree(tmp_path):
    return write_tree(tmp_path / "overrides", {
        "bdc_xbrl_wrappers/" + ARES + ".json": wrapper_v3(ARES),
        "bdc_xbrl_wrappers/0009999999.json": wrapper_v3("0009999999"),
        "bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json": {"entries": [{"cik": ARES}]},
        "rate_convention/" + STELLUS + ".json": {"cik": STELLUS, "convention": "all_in", "target_quarter": "2026-03-31"},
        "agent_b2_corrections/" + ARES + "/comparative_period_filter.json":
            {"cik": ARES, "mechanism": "comparative_leak", "fix_class": "comparative_period_filter",
             "template": {"report_date": "2025-12-31"}},
        "agent_b2_corrections/" + ARES + "/_pulled_x_20260821/all_pik_normalization.json": {"cik": ARES},
        "agent_investigate_rules/1287750/exclude_x.json": {"cik": "1287750", "rule_id": "exclude_x"},
        "agent_investigate_rules/1803498/_retired_y.json": {"cik": "1803498"},
        "agent_anchor/1287750/2026-03-31.json": {"cik": "1287750"},
        "bdc_aggregate_row_overrides.json": {"overrides": [
            {"cik": "0001287032", "report_date": "2022-12-31", "match_text": "A"},
            {"cik": ARES, "report_date": "2025-09-30", "match_text": "Ivy Hill Asset Management, L.P."},
            {"cik": ARES, "report_date": "2025-12-31", "match_text": "Ivy Hill Asset Management, L.P."}]},
        "bdc_xbrl_oracle_exceptions.json": [{"cik": STELLUS, "report_date": "2025-12-31",
                                             "oracle_reason": "rate_outliers_detected", "confidence": 0.90}],
        "identifier_spread_corrections.json": {"corrections": [{"cik": "0001234567", "fv": 1287750}]},
        "conservation_scope/other.json": {"cik": "0001111111"}})


def test_scan_classifies_every_hit(tmp_path):
    hits = {h["path"]: h for h in pf.scan_overrides(base_tree(tmp_path), PILOT)}
    assert hits["bdc_xbrl_wrappers/" + ARES + ".json"]["action"] == "wrapper_block"
    assert hits["bdc_xbrl_wrappers/" + ARES + ".json"]["owner"] == ARES
    assert hits["bdc_xbrl_wrappers/unlisted_bdc_xbrl_reference.json"]["action"] == "excluded"
    assert hits["rate_convention/" + STELLUS + ".json"]["action"] == "entry"
    assert hits["agent_b2_corrections/" + ARES + "/comparative_period_filter.json"]["action"] == "correction"
    assert hits["agent_b2_corrections/" + ARES + "/_pulled_x_20260821/all_pik_normalization.json"]["action"] == "not_loaded"
    assert hits["agent_investigate_rules/1287750/exclude_x.json"]["owner"] == ARES
    assert hits["agent_investigate_rules/1803498/_retired_y.json"]["action"] == "not_loaded"
    assert hits["agent_anchor/1287750/2026-03-31.json"]["action"] == "excluded"
    assert hits["bdc_aggregate_row_overrides.json"]["ciks"] == [ARES] and hits["bdc_aggregate_row_overrides.json"]["owner"] is None
    assert "bdc_xbrl_wrappers/0009999999.json" not in hits
    assert "identifier_spread_corrections.json" not in hits   # 1287750 as a JSON number is not a mention


def test_unclassified_family_with_a_pilot_mention_fails_closed(tmp_path):
    root = base_tree(tmp_path)
    write_tree(root, {"brand_new_family/x.json": {"cik": ARES}})
    with pytest.raises(pf.FamilyError, match="unclassified"):
        pf.scan_overrides(root, PILOT)


def test_must_be_absent_family_with_a_pilot_mention_fails(tmp_path):
    root = base_tree(tmp_path)
    write_tree(root, {"identifier_spread_corrections.json": {"corrections": [{"cik": ARES}]}})
    with pytest.raises(pf.FamilyError, match="must not mention"):
        pf.scan_overrides(root, PILOT)


def test_collect_override_inputs_splits_files_shared_and_disposition(tmp_path):
    root = base_tree(tmp_path)
    hits = pf.scan_overrides(root, PILOT)
    ares = pf.collect_override_inputs(root, ARES, hits)
    assert [f["path"] for f in ares["files"]["bdc_xbrl_wrappers"]] == ["bdc_xbrl_wrappers/" + ARES + ".json"]
    assert ares["files"]["bdc_xbrl_wrappers"][0]["content"]["dispatch"]["prefix_rules"] == \
        {"Second Lien": "debt", "First Lien": "debt"}
    assert list(ares["files"]["bdc_xbrl_wrappers"][0]["content"]["dispatch"]["prefix_rules"]) == \
        ["Second Lien", "First Lien"]
    assert [i for i, _ in ares["shared"]["bdc_aggregate_row_overrides.json"]["records"]] == [1, 2]
    actions = {d["path"]: d["action"] for d in ares["disposition"]}
    assert actions["agent_anchor/1287750/2026-03-31.json"] == "excluded"
    assert actions["agent_b2_corrections/" + ARES + "/_pulled_x_20260821/all_pik_normalization.json"] == "not_loaded"
    assert all(len(d["sha256"]) == 64 and d["targets"] == [] for d in ares["disposition"])
    stellus = pf.collect_override_inputs(root, STELLUS, hits)
    assert stellus["shared"]["bdc_xbrl_oracle_exceptions.json"]["records"][0][0] == 0
    assert "bdc_xbrl_wrappers" not in stellus["files"]


def test_foreign_owner_is_recorded_not_converted(tmp_path):
    root = base_tree(tmp_path)
    write_tree(root, {"bdc_xbrl_wrappers/0009999999.json": wrapper_v3("0009999999", note="peer of 0001287750")})
    hits = pf.scan_overrides(root, PILOT)
    ares = pf.collect_override_inputs(root, ARES, hits)
    row = next(d for d in ares["disposition"] if d["path"] == "bdc_xbrl_wrappers/0009999999.json")
    assert row["action"] == "foreign_mention"
    assert [f["path"] for f in ares["files"]["bdc_xbrl_wrappers"]] == ["bdc_xbrl_wrappers/" + ARES + ".json"]


def test_shared_mention_outside_a_record_cik_is_foreign(tmp_path):
    root = base_tree(tmp_path)
    write_tree(root, {"bdc_xbrl_oracle_exceptions.json": [
        {"cik": "0001111111", "report_date": "2025-12-31", "oracle_reason": "x", "evidence": "see 0001287750-23-1"}]})
    hits = pf.scan_overrides(root, PILOT)
    ares = pf.collect_override_inputs(root, ARES, hits)
    row = next(d for d in ares["disposition"] if d["path"] == "bdc_xbrl_oracle_exceptions.json")
    assert row["action"] == "foreign_mention" and "bdc_xbrl_oracle_exceptions.json" not in ares["shared"]


def test_helpers():
    assert pf.cik10("1287750") == ARES and pf.cik10(None) is None
    assert pf.owner_cik("agent_investigate_rules/1715933/1715933_twin_star.json") == "0001715933"
    assert pf.owner_cik("bdc_aggregate_row_overrides.json") is None
    assert pf.is_loaded("agent_investigate_rules/1803498/_retired_y.json") is False
    assert pf.is_loaded("agent_b2_corrections/0001287750/x.proposed.json") is False
    assert pf.is_loaded("rate_convention/0001860424.json") is True


# --- Controller amendment A13 (binding, not in the brief's Step 1 tests): the oversize position-registry
# file (position_id_registry/registry.csv is ~112 MB in production) always gets its OWN disposition row of
# `not_loaded` with its size recorded in `reason` -- overriding the family's default `excluded` action for
# that one path -- because its content is never read and absence of a mention cannot be proven, so it is
# recorded conservatively for every filer the scan was asked about. A small MAX_SCAN_BYTES is monkeypatched
# so the test does not need a real 20MB+ fixture.
def test_oversize_process_artifact_file_is_not_loaded_with_size_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "MAX_SCAN_BYTES", 32)
    root = write_tree(tmp_path / "overrides", {
        "position_id_registry/registry.csv": ("cik,position_id\n" + ("z" * 64) + "\n"),  # no pilot CIK, by content
        "position_id_registry/retirements.csv": "cik,position_id\n" + ARES + ",1\n"})
    hits = {h["path"]: h for h in pf.scan_overrides(root, PILOT)}
    big = hits["position_id_registry/registry.csv"]
    assert big["action"] == "not_loaded"
    assert big["cls"] == "process_artifact"
    assert big["ciks"] == sorted(PILOT)   # conservative: can't prove absence, so every queried filer is recorded
    size = (root / "position_id_registry/registry.csv").stat().st_size
    assert str(size) in big["reason"]
    # the small file in the same family is still content-scanned and keeps the family's normal action
    assert hits["position_id_registry/retirements.csv"]["action"] == "excluded"
    assert hits["position_id_registry/retirements.csv"]["ciks"] == [ARES]
    # every pilot filer's own disposition includes the oversize file's not_loaded row
    ares = pf.collect_override_inputs(root, ARES, pf.scan_overrides(root, PILOT))
    row = next(d for d in ares["disposition"] if d["path"] == "position_id_registry/registry.csv")
    assert row["action"] == "not_loaded" and str(size) in row["reason"]


def test_oversize_non_process_artifact_family_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "MAX_SCAN_BYTES", 32)
    root = write_tree(tmp_path / "overrides", {
        "rate_convention/" + ARES + ".json": json.dumps(
            {"cik": ARES, "convention": "all_in", "pad": "x" * 64})})
    with pytest.raises(pf.FamilyError, match="MAX_SCAN_BYTES"):
        pf.scan_overrides(root, PILOT)
