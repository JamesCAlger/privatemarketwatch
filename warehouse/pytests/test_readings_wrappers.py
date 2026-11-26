import pytest

from readings_loader.wrappers import LoadError, flatten

CIK = "0000000001"


def _flat(encodings, **extra):
    wrapper = {"source_encodings": encodings}
    wrapper.update(extra)
    return flatten(CIK, wrapper)


def _one(rows):
    assert len(rows) == 1
    return rows[0]


def test_convention_becomes_a_filer_rule():
    rules, corrections, not_loaded = _flat({"filed_rate_reading": ["all_in"]})
    r = _one(rules)
    assert (r["cik"], r["target"], r["action"], r["rule_class"]) == (CIK, "interest_rate", "rate_is_all_in", "convention")
    assert r["origin"] == "wrapper:filed_rate_reading"
    assert r["validity_basis"] == "assumed_all_quarters" and r["valid_from"] == "" and r["valid_to"] == ""
    assert r["priority"] == 20
    assert corrections == [] and not_loaded == []


def test_two_entries_of_one_key_are_two_rules():
    rules, _, _ = _flat({"pik_only_tag_reading": ["coupon", "margin"]})
    assert sorted(r["action"] for r in rules) == ["pik_only_is_coupon", "pik_only_is_margin"]
    assert {r["sel_feature"] for r in rules} == {"pik_tag_only"}
    assert {r["priority"] for r in rules} == {30}


def test_dates_in_a_reference_code_are_parsed():
    rules, _, _ = _flat({"reference_rate_codes": ["C=CDOR to 2025-03-31", "C=CORRA from 2025-06-30", "SN=SONIA"]})
    by_param = {r["parameter"]: r for r in rules}
    assert by_param["C=CDOR"]["valid_to"] == "2025-03-31" and by_param["C=CDOR"]["validity_basis"] == "stated"
    assert by_param["C=CORRA"]["valid_from"] == "2025-06-30" and by_param["C=CORRA"]["validity_basis"] == "stated"
    assert by_param["SN=SONIA"]["validity_basis"] == "assumed_all_quarters"
    assert {r["rule_class"] for r in rules} == {"vocabulary"}


def test_filing_inside_par_tagged_as_units_is_filing_scoped():
    rules, _, _ = _flat({"par_tagged_as_units": ["0001628280-26-033248", "rows_near_cost"]})
    by_class = {r["rule_class"]: r for r in rules}
    assert by_class["filing_scoped"]["sel_accession"] == "0001628280-26-033248"
    assert by_class["filing_scoped"]["priority"] == 30
    assert by_class["value_test"]["sel_feature"] == "rows_near_cost"
    assert by_class["value_test"]["sel_accession"] == ""


def test_filing_list_becomes_one_rule_per_filing():
    rules, _, _ = _flat({"bracketed_unsigned_values": ["0000950170-23-061985", "0000950170-24-031479"]})
    assert sorted(r["sel_accession"] for r in rules) == ["0000950170-23-061985", "0000950170-24-031479"]
    assert {r["rule_class"] for r in rules} == {"filing_scoped"}


def test_legal_entity_member_is_split_into_axis_member_and_name():
    rules, _, _ = _flat({"legal_entity_members": ["legalentityaxis=BCREDEmeraldJVLPMember -> Emerald JV LP"]})
    r = _one(rules)
    assert (r["sel_axis"], r["sel_member"], r["parameter"]) == ("legalentityaxis", "BCREDEmeraldJVLPMember", "Emerald JV LP")
    assert (r["target"], r["action"], r["rule_class"]) == ("scope", "set_scope", "scope")


def test_identifier_format_is_one_source_rule():
    rules, _, _ = flatten(CIK, {"source_encodings": {}, "identifier_format": {"delimiter": ", ", "field_order": ["a"]}})
    r = _one(rules)
    assert r["action"] == "identifier_format" and r["rule_class"] == "source"
    assert r["parameter"] == '{"delimiter":", ","field_order":["a"]}'


def test_procedure_keys_are_listed_not_loaded():
    rules, corrections, not_loaded = _flat({"gics_industry_carry_back": ["through 2025-09-30"]})
    assert rules == [] and corrections == []
    assert [n["wrapper_key"] for n in not_loaded] == ["gics_industry_carry_back"]
    assert all(n["reason"] == "needs_procedure" for n in not_loaded)


def test_rate_only_contexts_adopt_adjacent_is_a_filer_rule():
    # slice 5 Task 4: the structural rule built in int_rate_adjacent, selected by the declaration alone (no list of
    # contexts), so it applies to every filing of the fund
    rules, corrections, not_loaded = _flat({"rate_only_contexts": ["adopt_adjacent"]})
    r = _one(rules)
    assert (r["target"], r["action"], r["rule_class"], r["priority"]) == (
        "interest_rate", "adopt_adjacent_rate_context", "convention", 20)
    assert r["origin"] == "wrapper:rate_only_contexts" and r["parameter"] == "" and r["sel_accession"] == ""
    assert corrections == [] and not_loaded == []


def test_rate_only_contexts_other_entry_names_its_own_action():
    # an entry other than adopt_adjacent becomes an action the seed does not list; dbt's relationship test on
    # stg_reading_rule.action fails the build, so it is never silently applied
    rules, _, _ = _flat({"rate_only_contexts": ["keep_separate"]})
    assert _one(rules)["action"] == "keep_separate_rate_context"


def test_pik_margin_reading_splits_into_procedure_and_exceptions():
    _, corrections, not_loaded = _flat({"pik_margin_reading": ["whole_coupon", "not 0001628280-26-020206 c-841"]})
    assert _one(not_loaded)["entry"] == "whole_coupon"
    c = _one(corrections)
    assert (c["accession"], c["context_id"], c["kind"], c["field"]) == ("0001628280-26-020206", "c-841", "exception", "pik_margin_reading")
    assert c["store"] == "wrapper:pik_margin_reading"


def test_untagged_value_is_a_value_correction():
    _, corrections, _ = _flat({"untagged_values": ["0001803498-25-000021 c-1227 principal_amount 1875000"]})
    c = _one(corrections)
    assert (c["accession"], c["context_id"], c["field"], c["value"], c["kind"]) == (
        "0001803498-25-000021", "c-1227", "principal_amount", "1875000", "value")


def test_untagged_value_may_carry_a_unit():
    _, corrections, _ = _flat({"untagged_values": ["0000950170-24-094137 C_01 principal_amount 40000000 EUR"]})
    c = _one(corrections)
    assert (c["value"], c["value_unit"]) == ("40000000", "EUR")


def test_relabelled_context_keeps_old_and_new_label():
    _, corrections, _ = _flat({"relabelled_contexts": ["0001812554-26-000027 c-686 :: Old Co | Loan :: New Co | Loan"]})
    c = _one(corrections)
    assert (c["kind"], c["field"], c["expected_value"], c["value"]) == ("relabel", "identifier", "Old Co | Loan", "New Co | Loan")


def test_rate_anchor_is_evidence_only():
    anchor = {"accession": "0001287750-22-000052", "context": "c-1", "field": "interest_rate",
              "source_context": "c-2", "source_concept": "X", "source_units": "fraction", "evidence": "printed line"}
    _, corrections, _ = _flat({"rate_verification_anchors": [anchor]})
    c = _one(corrections)
    assert (c["kind"], c["field"], c["value"], c["evidence"]) == ("evidence", "interest_rate", "", "printed line")
    assert "source_context=c-2" in c["reason"]


def test_unknown_key_stops_the_load():
    with pytest.raises(LoadError, match="unknown wrapper key"):
        _flat({"some_new_key": ["x"]})


@pytest.mark.parametrize("encodings", [
    {"untagged_values": ["0001803498-25-000021 c-1227 principal_amount"]},
    {"relabelled_contexts": ["0001812554-26-000027 c-686 :: only one side"]},
    {"legal_entity_members": ["no arrow here"]},
    {"bracketed_unsigned_values": ["not-an-accession"]},
    {"filed_rate_reading": [{"a": 1}]},
    {"filed_rate_reading": "all_in"},
])
def test_malformed_entry_stops_the_load(encodings):
    with pytest.raises(LoadError):
        _flat(encodings)


def test_ids_are_stable_and_distinct():
    enc = {"filed_rate_reading": ["all_in"], "reference_rate_codes": ["C=CORRA", "S=SONIA"],
           "untagged_values": ["0001803498-25-000021 c-1227 principal_amount 1875000"]}
    a, b = _flat(enc), _flat(enc)
    assert [r["rule_id"] for r in a[0]] == [r["rule_id"] for r in b[0]]
    assert len({r["rule_id"] for r in a[0]}) == 3
    assert a[1][0]["correction_id"] == b[1][0]["correction_id"]
    assert all(len(r["rule_id"]) == 16 for r in a[0])


def test_same_declaration_for_another_fund_has_another_id():
    a, _, _ = flatten("0000000001", {"source_encodings": {"filed_rate_reading": ["all_in"]}})
    b, _, _ = flatten("0000000002", {"source_encodings": {"filed_rate_reading": ["all_in"]}})
    assert a[0]["rule_id"] != b[0]["rule_id"]


# New-style fund rules: the wrapper copy's top-level reading_rules list (slice 2, Task 5).

_CONCEPT_RULE = {"target": "fair_value", "action": "concept_is_fair_value",
                 "concept_namespace": "http://filer.example/*", "concept_local": "FilerFairValue",
                 "evidence": "0000000001-26-000001: 3 facts"}


def test_reading_rule_becomes_a_fund_rule_row():
    rules, corrections, not_loaded = flatten(CIK, {"reading_rules": [_CONCEPT_RULE]})
    r = _one(rules)
    assert (r["target"], r["action"], r["rule_class"], r["origin"]) == (
        "fair_value", "concept_is_fair_value", "fund_rule", "wrapper:reading_rules")
    assert (r["sel_concept_namespace"], r["sel_concept_local"]) == ("http://filer.example/*", "FilerFairValue")
    assert r["evidence"] == "0000000001-26-000001: 3 facts"
    assert r["priority"] == 30 and r["validity_basis"] == "assumed_all_quarters"
    assert corrections == [] and not_loaded == []


def test_reading_rule_without_selector_is_a_filer_rule_and_dates_are_stated():
    rule = {"target": "role", "action": "subtotal_on_fair_value", "evidence": "D12", "valid_from": "2023-06-30"}
    r = _one(flatten(CIK, {"reading_rules": [rule]})[0])
    assert r["priority"] == 20 and r["valid_from"] == "2023-06-30" and r["validity_basis"] == "stated"


def test_reading_rules_sit_beside_source_encodings():
    rules, _, _ = flatten(CIK, {"source_encodings": {"filed_rate_reading": ["all_in"]}, "reading_rules": [_CONCEPT_RULE]})
    assert sorted(r["origin"] for r in rules) == ["wrapper:filed_rate_reading", "wrapper:reading_rules"]


def test_reading_rule_object_parameter_is_canonical_json():
    # loader version 8 (text slice R phase 3): an object parameter is stored as JSON with sorted keys, no spaces, so
    # the same rule written with its keys in another order has the same id
    a = {"target": "rate_text", "action": "rate_code", "evidence": "owner item 2",
         "parameter": {"rate": "SOFR", "code": "S", "source_grade": "owner"}}
    b = dict(a, parameter={"source_grade": "owner", "code": "S", "rate": "SOFR"})
    ra, rb = _one(flatten(CIK, {"reading_rules": [a]})[0]), _one(flatten(CIK, {"reading_rules": [b]})[0])
    assert ra["parameter"] == '{"code":"S","rate":"SOFR","source_grade":"owner"}'
    assert ra["rule_id"] == rb["rule_id"]


def test_two_reading_rules_on_one_concept_have_distinct_ids():
    term = dict(_CONCEPT_RULE, target="term_fact", action="concept_is_term_fact")
    rules, _, _ = flatten(CIK, {"reading_rules": [_CONCEPT_RULE, term]})
    assert len({r["rule_id"] for r in rules}) == 2


@pytest.mark.parametrize("rules", [
    [],
    "not a list",
    ["text entry"],
    [dict(_CONCEPT_RULE, colour="red")],                                   # unknown field
    [{k: v for k, v in _CONCEPT_RULE.items() if k != "evidence"}],         # evidence required
    [dict(_CONCEPT_RULE, evidence=" ")],
    [{k: v for k, v in _CONCEPT_RULE.items() if k != "concept_namespace"}],  # local name alone (ruling 12)
    [{k: v for k, v in _CONCEPT_RULE.items() if k != "concept_local"}],      # namespace alone
    [dict(_CONCEPT_RULE, concept_namespace="http://*.example/2026")],      # wildcard in the host
    [dict(_CONCEPT_RULE, concept_namespace="*")],
    [dict(_CONCEPT_RULE, concept_local="ns:FilerFairValue")],              # a prefix
    [dict(_CONCEPT_RULE, valid_to="31/03/2026")],
    [dict(_CONCEPT_RULE, accession="not-an-accession")],
    [dict(_CONCEPT_RULE, target=1)],
])
def test_malformed_reading_rule_stops_the_load(rules):
    with pytest.raises(LoadError):
        flatten(CIK, {"reading_rules": rules})


# Fund rule position_without_term_fact (slice 2, Task 6): a label pattern and an optional feature.

_POSITION_RULE = {"target": "role", "action": "position_without_term_fact",
                  "label_pattern": ".+, first lien senior secured revolving loan", "feature": "fair_value_zero",
                  "evidence": "0000000001-22-000001: 29 undrawn revolvers printed with a dash"}


def test_label_pattern_rule_becomes_a_fund_rule_row():
    r = _one(flatten(CIK, {"reading_rules": [_POSITION_RULE]})[0])
    assert (r["target"], r["action"], r["rule_class"], r["priority"]) == ("role", "position_without_term_fact", "fund_rule", 30)
    assert r["sel_label_pattern"] == ".+, first lien senior secured revolving loan"
    assert r["sel_feature"] == "fair_value_zero"
    assert r["sel_label"] == "" and r["sel_concept_local"] == ""


def test_label_pattern_is_part_of_the_rule_id():
    a = _one(flatten(CIK, {"reading_rules": [_POSITION_RULE]})[0])
    b = _one(flatten(CIK, {"reading_rules": [dict(_POSITION_RULE, label_pattern=".+, revolving loan")]})[0])
    assert a["rule_id"] != b["rule_id"]


@pytest.mark.parametrize("pattern", [
    "",                       # empty
    " ",                      # blank
    "(unclosed",              # not a regular expression
    "(?=look)ahead",          # look-around: RE2 has none
    "(?<!x)behind",
    r"(a)\1",                 # back-reference
])
def test_bad_label_pattern_stops_the_load(pattern):
    with pytest.raises(LoadError):
        flatten(CIK, {"reading_rules": [dict(_POSITION_RULE, label_pattern=pattern)]})


def test_label_pattern_key_is_not_a_label_key():
    with pytest.raises(LoadError, match="unknown field"):
        flatten(CIK, {"reading_rules": [dict(_POSITION_RULE, label_regex=".+")]})


def test_label_examples_are_rows_beside_the_rule_and_not_part_of_its_id():
    from readings_loader.wrappers import label_examples
    plain = dict(_POSITION_RULE)
    listed = dict(_POSITION_RULE, label_examples_match=["Acme, First lien senior secured revolving loan"],
                  label_examples_no_match=["Acme", " Acme, second lien loan "])
    rule = _one(flatten(CIK, {"reading_rules": [listed]})[0])
    assert rule["rule_id"] == _one(flatten(CIK, {"reading_rules": [plain]})[0])["rule_id"]
    got = sorted((e["label"], e["expected_match"], e["rule_id"] == rule["rule_id"], e["cik"])
                 for e in label_examples(CIK, {"reading_rules": [listed]}))
    assert got == [("Acme", False, True, CIK), ("Acme, First lien senior secured revolving loan", True, True, CIK),
                   ("Acme, second lien loan", False, True, CIK)]
    assert label_examples(CIK, {"source_encodings": {}}) == []


@pytest.mark.parametrize("extra", [
    {"label_examples_match": []},                     # empty list
    {"label_examples_match": "Acme"},                 # not a list
    {"label_examples_no_match": ["Acme", ""]},        # an empty label
    {"label_examples_no_match": [3]},
])
def test_bad_label_examples_stop_the_load(extra):
    with pytest.raises(LoadError):
        flatten(CIK, {"reading_rules": [dict(_POSITION_RULE, **extra)]})


def test_label_examples_need_a_label_pattern():
    with pytest.raises(LoadError, match="needs a label_pattern"):
        flatten(CIK, {"reading_rules": [dict(_CONCEPT_RULE, label_examples_no_match=["Acme"])]})
