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
    rules, corrections, not_loaded = _flat({"rate_only_contexts": ["adopt_adjacent"], "gics_industry_carry_back": ["through 2025-09-30"]})
    assert rules == [] and corrections == []
    assert sorted(n["wrapper_key"] for n in not_loaded) == ["gics_industry_carry_back", "rate_only_contexts"]
    assert all(n["reason"] == "needs_procedure" for n in not_loaded)


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
