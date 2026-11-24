"""Slice 5 Task 2: the agent stores loader (readings_loader/agent_stores.py). Invented funds only."""
import json

import pytest

from readings_loader import LoadError, agent_stores, cli, store

FUND = "0000000001"


def _write(base, folder, name, obj):
    path = base / folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return path


def _pik_leaf(**template):
    t = {"row_selector": {"row_id": "ROW-1"}, "cash_rate": 0.0, "pik_rate": 14.0, "set_interest_to_cash": True}
    t.update(template)
    return {"cik": FUND, "fix_class": "all_pik_normalization", "scope": {"quarters": ["2025-12-31"]},
            "template": {k: v for k, v in t.items() if v is not None}, "rationale": "why",
            "evidence_citations": [{"quoted_text": "14.00 % PIK"}]}


def _position(**over):
    p = {"cik": FUND, "report_date": "2025-03-31", "accession_number": "0000000001-25-000001",
         "src_context_id": "c-2", "issuer_name": "Acme", "fair_value": 5.0, "cost": 4.0,
         "bdc_dimensions_raw": "x=Acme", "source_row_id": "xbrl:c-1 + c-2"}
    p.update(over)
    return {k: v for k, v in p.items() if v is not None}


def _row_add(*positions):
    return {"cik": "1", "rule_id": "recover", "rule_type": "row_add", "action": "add",
            "scope": {"quarters": ["2025-03-31"]}, "positions": list(positions) or [_position()],
            "evidence": [{"source": "filing", "quote": "q"}], "rationale": "r"}


def test_pik_leaf_sets_what_the_production_applier_sets(tmp_path):
    _write(tmp_path, FUND, "all_pik_normalization.json", _pik_leaf())
    corrections, rules, hashes, skipped = agent_stores.read_agent_store("agent_b2_corrections", tmp_path, [FUND])
    got = {(c["field"], c["value"]) for c in corrections}
    assert got == {("pik_rate", "14.0"), ("interest_rate_cash", "0.0"), ("interest_rate_kind", "cash")}
    assert {(c["kind"], c["row_id"], c["report_date"], c["accession"]) for c in corrections} == {
        ("value", "ROW-1", "2025-12-31", "")}
    assert rules == [] and skipped == {}
    assert list(hashes) == [f"agent_b2_corrections/{FUND}/all_pik_normalization.json"]


def test_pik_leaf_without_set_cash_sets_only_the_pik_rate(tmp_path):
    _write(tmp_path, FUND, "all_pik_normalization.json", _pik_leaf(cash_rate=None, set_interest_to_cash=None))
    corrections = agent_stores.read_agent_store("agent_b2_corrections", tmp_path, [FUND])[0]
    assert [(c["field"], c["value"]) for c in corrections] == [("pik_rate", "14.0")]


def test_cash_rate_without_set_cash_stops_the_load(tmp_path):
    # production ignores it; loading it would set a value production does not
    _write(tmp_path, FUND, "all_pik_normalization.json", _pik_leaf(set_interest_to_cash=False))
    with pytest.raises(LoadError, match="cash_rate without"):
        agent_stores.read_agent_store("agent_b2_corrections", tmp_path, [FUND])


@pytest.mark.parametrize("selector", [{"issuer_name": "Acme"}, [{"row_id": "ROW-1"}], {}])
def test_a_selector_other_than_one_row_id_stops_the_load(tmp_path, selector):
    _write(tmp_path, FUND, "all_pik_normalization.json", _pik_leaf(row_selector=selector))
    with pytest.raises(LoadError, match="row_selector"):
        agent_stores.read_agent_store("agent_b2_corrections", tmp_path, [FUND])


def test_unknown_fix_class_stops_the_load(tmp_path):
    _write(tmp_path, FUND, "unit_rescale.json", {"cik": FUND, "fix_class": "unit_rescale", "template": {}})
    with pytest.raises(LoadError, match="unit_rescale"):
        agent_stores.read_agent_store("agent_b2_corrections", tmp_path, [FUND])


def test_comparative_filter_is_a_rule_not_a_correction(tmp_path):
    _write(tmp_path, FUND, "comparative_period_filter.json",
           {"cik": FUND, "fix_class": "comparative_period_filter", "template": {"report_date": "2025-12-31"}})
    corrections, rules, _, _ = agent_stores.read_agent_store("agent_b2_corrections", tmp_path, [FUND])
    assert corrections == []
    assert [(r["rule_type"], r["scope_quarters"], r["predicate_form"]) for r in rules] == [
        ("comparative_period_filter", "2025-12-31", "template")]


def test_row_add_gives_one_correction_per_field_keyed_by_context(tmp_path):
    _write(tmp_path, "1", "recover.json", _row_add(_position(), _position(src_context_id="c-4", fair_value=7)))
    corrections, rules, _, _ = agent_stores.read_agent_store("agent_investigate_rules", tmp_path, [FUND])
    assert rules == []
    groups = {c["add_group_id"] for c in corrections}
    assert groups == {"recover:0000000001-25-000001:c-2", "recover:0000000001-25-000001:c-4"}
    first = {c["field"]: c["value"] for c in corrections if c["context_id"] == "c-2"}
    # the four locating keys are the key, not fields
    assert first == {"issuer_name": "Acme", "fair_value": "5.0", "cost": "4.0", "bdc_dimensions_raw": "x=Acme",
                     "source_row_id": "xbrl:c-1 + c-2"}
    assert {(c["kind"], c["cik"], c["report_date"], c["store"]) for c in corrections} == {
        ("add_row", FUND, "2025-03-31", "agent_investigate_rules")}
    assert {c["value"] for c in corrections if c["context_id"] == "c-4" and c["field"] == "fair_value"} == {"7"}


def test_row_add_position_without_a_context_stops_the_load(tmp_path):
    _write(tmp_path, "1", "recover.json", _row_add(_position(src_context_id=None)))
    with pytest.raises(LoadError, match="src_context_id"):
        agent_stores.read_agent_store("agent_investigate_rules", tmp_path, [FUND])


def test_row_add_position_outside_the_rule_scope_stops_the_load(tmp_path):
    _write(tmp_path, "1", "recover.json", _row_add(_position(report_date="2025-06-30")))
    with pytest.raises(LoadError, match="outside"):
        agent_stores.read_agent_store("agent_investigate_rules", tmp_path, [FUND])


def test_row_exclusion_is_a_rule_with_its_predicate(tmp_path):
    _write(tmp_path, "1", "exclude_x.json", {"rule_id": "exclude_x", "rule_type": "row_exclusion",
                                             "action": "exclude", "scope": {"quarters": ["all"]},
                                             "predicate_sql": " asset_category = 'CASH' "})
    corrections, rules, _, _ = agent_stores.read_agent_store("agent_investigate_rules", tmp_path, [FUND])
    assert corrections == []
    assert [(r["rule_id"], r["scope_quarters"], r["predicate"], r["predicate_form"], r["source_file"]) for r in rules] == [
        ("exclude_x", "all", "asset_category = 'CASH'", "sql", "agent_investigate_rules/1/exclude_x.json")]


def test_unknown_rule_type_stops_the_load(tmp_path):
    _write(tmp_path, "1", "r.json", {"rule_type": "value_expression", "predicate_sql": "true"})
    with pytest.raises(LoadError, match="value_expression"):
        agent_stores.read_agent_store("agent_investigate_rules", tmp_path, [FUND])


def test_retired_pulled_proposed_and_review_files_are_skipped_but_hashed(tmp_path):
    for name in ("_retired_x.json", "x.proposed.json", "x.review.json"):
        _write(tmp_path, "1", name, "not even json")
    _write(tmp_path, "_pulled_1_2026", "r.json", "not json")  # a pulled folder at the top: not a fund folder
    _write(tmp_path, "2", "r.json", "not json")  # another fund: not read at all
    corrections, rules, hashes, skipped = agent_stores.read_agent_store("agent_investigate_rules", tmp_path, [FUND])
    assert corrections == [] and rules == []
    assert sorted(skipped) == sorted(hashes) == [
        "agent_investigate_rules/1/_retired_x.json", "agent_investigate_rules/1/x.proposed.json",
        "agent_investigate_rules/1/x.review.json"]


def test_an_admission_manifest_stops_the_load(tmp_path):
    _write(tmp_path, ".", "admission_manifest.json", {"format_version": 1, "entries": {}})
    with pytest.raises(LoadError, match="admission_manifest"):
        agent_stores.read_agent_store("agent_investigate_rules", tmp_path, [FUND])


def test_a_leaf_naming_another_fund_stops_the_load(tmp_path):
    leaf = _pik_leaf()
    leaf["cik"] = "0000000002"
    _write(tmp_path, FUND, "all_pik_normalization.json", leaf)
    with pytest.raises(LoadError, match="folder's fund"):
        agent_stores.read_agent_store("agent_b2_corrections", tmp_path, [FUND])


def test_hash_reads_crlf_as_lf(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_bytes(b'{"rule_type": "row_exclusion"}\n')
    b.write_bytes(b'{"rule_type": "row_exclusion"}\r\n')
    assert store.text_sha256(a) == store.text_sha256(b)
    c = tmp_path / "c.json"
    c.write_bytes(b'{"rule_type": "row_exclusion" }\n')
    assert store.text_sha256(a) != store.text_sha256(c)


def test_cli_load_writes_rules_corrections_and_manifest_hashes(tmp_path):
    wrappers = tmp_path / "wrappers"
    wrappers.mkdir()
    (wrappers / f"{FUND}.json").write_text(json.dumps({"source_encodings": {}}), encoding="utf-8")
    b2 = tmp_path / "b2"
    rules = tmp_path / "rules"
    _write(b2, FUND, "all_pik_normalization.json", _pik_leaf())
    _write(rules, "1", "recover.json", _row_add())
    _write(rules, "1", "_retired_y.json", "{}")
    tables, inputs = cli.load([FUND], wrappers, [], None, [("agent_b2_corrections", b2),
                                                           ("agent_investigate_rules", rules)])
    manifest = store.write(tmp_path / "out", tables, inputs)
    assert manifest["loader_version"] == "6"
    assert manifest["tables"]["correction"]["rows"] == 3 + 5
    assert manifest["tables"]["correction_rule"]["rows"] == 0
    assert sorted(manifest["agent_store_sha256"]) == [
        f"agent_b2_corrections/{FUND}/all_pik_normalization.json", "agent_investigate_rules/1/_retired_y.json",
        "agent_investigate_rules/1/recover.json"]
    assert list(manifest["agent_store_skipped"]) == ["agent_investigate_rules/1/_retired_y.json"]
