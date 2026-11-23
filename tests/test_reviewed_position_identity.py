import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline import reviewed_position_identity as identity
from pipeline.position_matching import MATCH_COLUMNS, assign_position_ids
from pipeline.source_encodings import load_encodings
from tests.test_position_matching import _make_unified


CIK = "0001918712"
ACC = "0001918712-25-000001"


def frame(rows):
    result = _make_unified([
        dict(source="bdc", cik=CIK, entity_name="Fund", issuer_name="Cannon Bridge",
             fair_value="100", cost="95", principal_amount="100", asset_category="LOAN",
             index_classification="DIRECT_LENDING", accession_number=ACC, **row)
        for row in rows
    ])
    result["src_context_id"] = [row["src_context_id"] for row in rows]
    return result


def match(begin, end, begin_fv="100", end_fv="100", method="B2_exact_name", key="cannon bridge"):
    values = dict(cik=CIK, source="bdc", begin_report_date=begin, end_report_date=end,
                  begin_issuer_name="Cannon Bridge", end_issuer_name="Cannon Bridge",
                  begin_fair_value=begin_fv, end_fair_value=end_fv,
                  match_method=method, match_key=key, match_score="1", span_months="3")
    return pd.DataFrame([{column: values.get(column, "") for column in MATCH_COLUMNS}])


def configure(monkeypatch, mapping):
    monkeypatch.setattr(identity, "load_encodings", lambda: {
        CIK: {"position_identity_contexts": [f"{ACC} {context} => {key}" for context, key in mapping.items()]}
    })


def assign(tmp_path, rows, matches, **kwargs):
    return assign_position_ids(rows, matches, edges_file=tmp_path / "edges.csv", **kwargs)


def test_primary_wrong_tranche_dropped_from_ids_and_matches(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-1": "sofr-750", "c-2": "sofr-265"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2")])
    output, matches = assign(tmp_path, rows, match("2025-03-31", "2025-06-30"))
    assert output.position_id.nunique() == 2
    assert matches.empty
    assert pd.read_csv(tmp_path / "edges.csv").empty


@pytest.mark.parametrize("method,key", [("B2_exact_name", "cannon bridge"),
                                        ("B1b_position_key", "cannon bridge first lien loan")])
def test_supplementary_pass_cannot_recreate_rejected_tranche(monkeypatch, tmp_path, method, key):
    configure(monkeypatch, {"c-1": "sofr-750", "c-2": "sofr-265"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2")])
    rows["position_key"] = key
    output, _ = assign(tmp_path, rows, match("2025-03-31", "2025-06-30", method=method, key=key),
                       contested_assignment=True)
    assert output.position_id.nunique() == 2


def test_unreviewed_intermediate_cannot_bridge_distinct_keys(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-1": "loan", "c-3": "warrant"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2"),
                  dict(report_date="2025-09-30", src_context_id="c-3")])
    matches = pd.concat([match("2025-03-31", "2025-06-30"), match("2025-06-30", "2025-09-30")])
    output, kept = assign(tmp_path, rows, matches)
    assert output.position_id.nunique() == 3
    assert kept.empty


def test_reviewed_same_key_restores_unique_adjacent_pair_without_match(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-1": "term-sofr750", "c-2": "term-sofr750"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2")])
    rows["issuer_name"] = ["Cannon Old Name", "Cannon New Name"]
    output, kept = assign(tmp_path, rows, pd.DataFrame(columns=MATCH_COLUMNS))
    assert output.position_id.nunique() == 1
    edges = pd.read_csv(tmp_path / "edges.csv")
    assert edges.edge_type.tolist() == ["reviewed_context_identity"]
    assert kept.empty


@pytest.mark.parametrize("reviewed", [True, False])
def test_reviewed_tranche_precedes_different_key_principal_twin(monkeypatch, tmp_path, reviewed):
    configure(monkeypatch, {"c-1": "sofr-750", "c-2": "sofr-750", "c-3": "sofr-265"}
              if reviewed else {})
    rows = frame([dict(report_date="2025-06-30", src_context_id="c-1"),
                  dict(report_date="2025-09-30", src_context_id="c-2"),
                  dict(report_date="2025-09-30", src_context_id="c-3")])
    rows["principal_amount"] = ["52400", "53800", "52200"]
    rows["principal_amount_usd"] = rows["principal_amount"]
    rows["fair_value"] = ["52200", "53500", "52000"]
    rows["basis_spread"] = ["7.5", "7.5", "2.65"]
    rows["maturity_date"] = "2033-10-31"
    output, _ = assign(tmp_path, rows,
                       match("2025-06-30", "2025-09-30", "52200", "53500"),
                       contested_assignment=True)
    pids = output.set_index("src_context_id").position_id
    if reviewed:
        assert pids["c-1"] == pids["c-2"]
        assert pids["c-1"] != pids["c-3"]
        edges = pd.read_csv(tmp_path / "edges.csv")
        assert "reviewed_context_identity" in edges.edge_type.tolist()
    else:
        # Ordinary inference retains its principal-twin veto.
        assert pids["c-1"] != pids["c-2"]


def test_duplicate_quarter_keys_fail_closed_before_primary_union(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-1": "loan", "c-2": "loan", "c-3": "loan"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-03-31", src_context_id="c-2"),
                  dict(report_date="2025-06-30", src_context_id="c-3")])
    with pytest.raises(ValueError, match="ambiguous within a quarter"):
        assign(tmp_path, rows, match("2025-03-31", "2025-06-30"))


def test_missing_quarter_does_not_create_reviewed_edge():
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-09-30", src_context_id="c-2")])
    assert identity.adjacent_identity_pairs(rows, {0: "loan", 1: "loan"}, ["same"] * 2) == []


def test_accounting_scope_still_blocks_reviewed_same_key(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-1": "loan", "c-2": "loan"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2")])
    rows["is_subsidiary"] = ["0", "1"]
    rows["jv_subsidiary"] = "Y"
    output, kept = assign(tmp_path, rows, match("2025-03-31", "2025-06-30"))
    assert output.position_id.nunique() == 2
    assert kept.empty


def test_no_config_preserves_normal_pair_and_other_fund(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-else": "loan"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2")])
    output, kept = assign(tmp_path, rows, match("2025-03-31", "2025-06-30"))
    assert output.position_id.nunique() == 1
    assert len(kept) == 1


def test_reviewed_compatible_primary_match_is_retained(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-1": "loan", "c-2": "loan"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2")])
    output, kept = assign(tmp_path, rows, match("2025-03-31", "2025-06-30"))
    assert output.position_id.nunique() == 1
    assert len(kept) == 1


def test_other_fund_is_unaffected_by_identical_context_labels(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-1": "loan", "c-2": "warrant"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2")])
    rows["cik"] = "0000000123"
    pairs = match("2025-03-31", "2025-06-30")
    pairs["cik"] = "0000000123"
    output, kept = assign(tmp_path, rows, pairs)
    assert output.position_id.nunique() == 1
    assert len(kept) == 1


def test_configured_fund_missing_provenance_fails(monkeypatch):
    configure(monkeypatch, {"c-1": "loan"})
    with pytest.raises(ValueError, match="provenance"):
        identity.context_identity_keys(pd.DataFrame({"cik": [CIK]}))


def test_missing_primary_endpoint_is_not_assigned_to_reviewed_position(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-2": "loan"})
    rows = frame([dict(report_date="2025-06-30", src_context_id="c-2")])
    _, kept = assign(tmp_path, rows, match("2025-03-31", "2025-06-30"))
    assert kept.empty


def test_empty_matches_do_not_activate_unreviewed_fund_links(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-1": "loan", "c-2": "loan"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2"),
                  dict(report_date="2025-03-31", src_context_id="c-3"),
                  dict(report_date="2025-06-30", src_context_id="c-4")])
    rows.loc[2:, "cik"] = "0000000123"
    output, _ = assign(tmp_path, rows, pd.DataFrame(columns=MATCH_COLUMNS))
    assert output.loc[output.cik == CIK, "position_id"].nunique() == 1
    assert output.loc[output.cik == "0000000123", "position_id"].nunique() == 2


def test_exact_accession_context_and_bdc_source_only():
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-1")])
    rows.loc[1, "accession_number"] = "0001918712-25-000002"
    encodings = {CIK: {"position_identity_contexts": [f"{ACC} c-1 => loan"]}}
    assert identity.context_identity_keys(rows, encodings) == {0: CIK + ":loan"}
    rows.loc[0, "source"] = "nport"
    assert identity.context_identity_keys(rows, encodings) == {}


@pytest.mark.parametrize("values", [[f"{ACC} c-1 => loan", f"{ACC} c-1 => warrant"], ["bad"]])
def test_invalid_declarations_rejected(tmp_path, values):
    (tmp_path / "wrapper.json").write_text(json.dumps({"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK,
        "source_encodings": {"position_identity_contexts": values}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_encodings(tmp_path)


def test_valid_declaration_schema_and_parser(tmp_path):
    import jsonschema

    values = [f"{ACC} c-1 => first-lien-term"]
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK,
               "entity_name": "Fund", "version": 1, "source": "bdc_xbrl",
               "source_encodings": {"position_identity_contexts": values}}
    schema_path = Path(__file__).resolve().parents[1] / "schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(wrapper)
    (tmp_path / "wrapper.json").write_text(json.dumps(wrapper), encoding="utf-8")
    assert load_encodings(tmp_path)[CIK]["position_identity_contexts"] == values


def test_assignment_deterministic_when_rows_and_matches_shuffled(monkeypatch, tmp_path):
    configure(monkeypatch, {"c-1": "loan", "c-2": "loan", "c-3": "warrant"})
    rows = frame([dict(report_date="2025-03-31", src_context_id="c-1"),
                  dict(report_date="2025-06-30", src_context_id="c-2"),
                  dict(report_date="2025-09-30", src_context_id="c-3")])
    matches = pd.concat([match("2025-03-31", "2025-06-30"), match("2025-06-30", "2025-09-30")])
    first, _ = assign(tmp_path, rows, matches)
    second, _ = assign(tmp_path, rows.sample(frac=1, random_state=8), matches.sample(frac=1, random_state=9))
    assert first.set_index("src_context_id").position_id.to_dict() == second.set_index("src_context_id").position_id.to_dict()
