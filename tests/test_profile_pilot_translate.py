"""Filer-profile pilot Task 7: profile -> wrapper v3 adapter (measurement only, never promoted).

Synthetic profiles are built with the real Task 2 envelope writers; base wrappers are
either small synthetic v3 wrappers or the tracked HEAD wrapper (read-only). Every file
the adapter writes goes to a fake run root under tmp_path. The one `needs_cache` test
reads a real Task 6 profile through PROFILE_PILOT_DATA_ROOT and writes only to tmp_path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
from pathlib import Path

import pytest

from pipeline import bdc_xbrl_wrapper
from scripts.profile_pilot import envelope, m1, translate, translate_run
from tests.test_profile_pilot_paths import CODE_ROOT, fake_paths

CIK = "0001901037"
Q = "2023-03-31"
NOW = "2026-09-29T12:00:00Z"
LATER = "2026-09-29T13:00:00Z"
SCHEMA = json.loads((CODE_ROOT / "schemas" / "bdc_xbrl_wrapper" / "wrapper_v3.schema.json")
                    .read_text(encoding="utf-8"))
PROFILE_RUN_ID = "stageb-profile-20260929t015742z"


# ---------------------------------------------------------------- builders

def base_wrapper(**extra):
    wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK, "entity_name": "Stellus Private Credit BDC",
               "version": 4, "source": "bdc_xbrl",
               "dispatch": {"rule_prefix": "STELLUS",
                            "prefix_rules": {"Second Lien": "debt", "First Lien": "debt", "Equity": "equity"},
                            "aggregate_markers": ["total investments", "subtotal"]},
               "identifier_format": {"delimiter": ", ", "field_order": ["issuer_name", "instrument"]},
               "invariants": {"fv_reconciliation": {"source_field": "investments_at_fair_value",
                                                    "tolerance_pct": 0.05, "tolerance_abs": 5000000}}}
    wrapper.update(extra)
    return wrapper


def entry(key, value, *, applies_to=None, form_type=None, valid_from=Q, valid_to=None, provenance="derived",
          inherited_from=None):
    return dict(key=key, value=value, applies_to=applies_to, form_type=form_type, valid_from=valid_from,
                valid_to=valid_to, provenance=provenance, inherited_from=inherited_from)


def make_profile(entries=(), stubs=(), report_date=Q, form_type="10-Q", recorded_at=NOW):
    events = []
    for e in entries:
        events = envelope.make_assertion(
            events, cik=CIK, key=e["key"], value=e["value"], valid_from=e["valid_from"], valid_to=e["valid_to"],
            recorded_at=recorded_at, support=dict(kind="prevalence", numerator=1, denominator=1),
            evidence=[dict(kind="test")], applies_to=e["applies_to"], form_type=e["form_type"],
            provenance=e["provenance"], inherited_from=e["inherited_from"])
    return dict(cik=CIK, era="q1", report_date=report_date, form_type=form_type, recorded_at=recorded_at,
                events=events, entries=envelope.materialize_entries(events), packet_stubs=list(stubs))


BASIC = (entry("fund_level_concepts.entity_cik", CIK),
         entry("fund_level_concepts.entity_registrant_name", "STELLUS PRIVATE CREDIT BDC"),
         entry("identifier_format.delimiter", " | "))


def leaves(value, pointer=""):
    if isinstance(value, dict) and value:
        out = {}
        for key, child in value.items():
            out.update(leaves(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1")))
        return out
    return {pointer: value}


def vhash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()


def by_key(items, key):
    return [i for i in items if i["profile_key"] == key]


# ---------------------------------------------------------------- translation scope

def test_translation_targets_are_production_schema_fields_and_agree_with_m1():
    for spec in translate.TRANSLATIONS:
        node = SCHEMA
        for part in spec["wrapper_path"]:
            assert part in node["properties"], spec
            node = node["properties"][part]
        family = next(f for f in m1.FAMILIES if ".".join(spec["wrapper_path"]) in f["match"][0].get("exact", ()))
        assert family.get("profile_key") == spec["profile_key"], spec


def test_translates_only_expressible_entries_and_keeps_order():
    prof = make_profile(BASIC + (entry("column_contract.fair_value", {"concept": "x"}),))
    base = base_wrapper()
    out = translate.to_wrapper_v3(prof, base, Q, "10-Q")
    wrapper, sidecar = out["wrapper"], out["sidecar"]
    assert wrapper["entity_name"] == "STELLUS PRIVATE CREDIT BDC"
    assert wrapper["identifier_format"]["delimiter"] == " | "
    assert list(wrapper) == list(base)
    assert list(wrapper["dispatch"]["prefix_rules"]) == ["Second Lien", "First Lien", "Equity"]
    assert {t["wrapper_pointer"] for t in sidecar["translated"]} == {"/cik", "/entity_name",
                                                                    "/identifier_format/delimiter"}
    assert [n["profile_key"] for n in sidecar["no_wrapper_field"]] == ["column_contract.fair_value"]
    assert sidecar["sections_translated"] == ["fund_level_concepts", "identifier_format"]
    assert sidecar["entries_used"] == 3
    assert base == base_wrapper()  # the base wrapper object is never mutated


def test_fv_source_field_via_the_inherited_equivalence_table_is_flagged():
    prof = make_profile((entry("fund_level_concepts.investments_at_fair_value_concept",
                               "us-gaap:InvestmentOwnedAtFairValue"),))
    out = translate.to_wrapper_v3(prof, base_wrapper(), Q, "10-Q")
    item = out["sidecar"]["translated"][0]
    assert item["wrapper_pointer"] == "/invariants/fv_reconciliation/source_field"
    assert item["via"] == "inherited_equivalence" and item["equivalence_source"] == "pipeline/extract_companyfacts.py"
    assert out["sidecar"]["coverage"]["profile_driven_via_inherited"] == 1


def test_unmappable_concept_is_not_expressible_and_base_is_kept():
    prof = make_profile((entry("fund_level_concepts.investments_at_fair_value_concept", "abc:SomethingElse"),))
    out = translate.to_wrapper_v3(prof, base_wrapper(), Q, "10-Q")
    [item] = out["sidecar"]["not_expressible"]
    assert item["reasons"] == ["no_wrapper_representation"]
    assert out["wrapper"]["invariants"]["fv_reconciliation"]["source_field"] == "investments_at_fair_value"


# ---------------------------------------------------------------- dates, forms, partitions

def test_entries_outside_the_report_date_or_retracted_are_not_used():
    later = entry("fund_level_concepts.entity_registrant_name", "NEW NAME", valid_from="2024-01-01")
    prof = make_profile((later,))
    out = translate.to_wrapper_v3(prof, base_wrapper(), Q, "10-Q")
    assert out["wrapper"]["entity_name"] == "Stellus Private Credit BDC"
    assert out["sidecar"]["entries_used"] == 0
    fresh = make_profile((entry("fund_level_concepts.entity_registrant_name", "OLD"),))
    retracted = fresh["events"] + [dict(event="retract", event_id="retract:" + fresh["entries"][0]["entry_id"],
                                        entry_id=fresh["entries"][0]["entry_id"], recorded_at=LATER)]
    prof2 = dict(fresh, events=retracted, entries=envelope.materialize_entries(retracted))
    before = translate.to_wrapper_v3(prof2, base_wrapper(), Q, "10-Q", as_of=NOW)
    after = translate.to_wrapper_v3(prof2, base_wrapper(), Q, "10-Q", as_of=LATER)
    assert before["wrapper"]["entity_name"] == "OLD"
    assert after["wrapper"]["entity_name"] == "Stellus Private Credit BDC"


def test_mixed_partition_is_not_expressible_never_flattened():
    part = dict(kind="segment_count", delimiter=" | ", count=4)
    prof = make_profile((entry("identifier_format.delimiter", " | "),
                         entry("identifier_format.delimiter", ", ", applies_to=part)))
    out = translate.to_wrapper_v3(prof, base_wrapper(), Q, "10-Q")
    [item] = out["sidecar"]["not_expressible"]
    assert item["reasons"] == ["mixed_partition"]
    assert sorted(item["entry_ids"]) == sorted(e["entry_id"] for e in prof["entries"])
    assert item["partitions"] == [None, part] or item["partitions"] == [part, None]
    # neither the null-partition value nor the partition value is written: the base stays
    assert out["wrapper"]["identifier_format"]["delimiter"] == ", "
    assert item["base_retained"]["pointer"] == "/identifier_format/delimiter"
    overlay = {f["pointer"] for f in out["sidecar"]["inherited_overlay"]["fields"]}
    assert "/identifier_format/delimiter" in overlay
    assert out["sidecar"]["translated"] == []


def test_form_specific_entry_is_not_expressible_even_for_the_matching_form():
    prof = make_profile((entry("fund_level_concepts.entity_registrant_name", "TEN K NAME", form_type="10-K"),))
    for form in ("10-K", "10-Q"):
        out = translate.to_wrapper_v3(prof, base_wrapper(), Q, form)
        [item] = out["sidecar"]["not_expressible"]
        assert item["reasons"] == ["form_specific"] and item["form_types"] == ["10-K"]
        assert out["wrapper"]["entity_name"] == "Stellus Private Credit BDC"


def test_presentation_view_declaration_is_not_expressible():
    prof = make_profile((entry("presentation_views.same_identifier_contexts", {"distinct_balances": 2}),))
    out = translate.to_wrapper_v3(prof, base_wrapper(), Q, "10-Q")
    [item] = out["sidecar"]["not_expressible"]
    assert item["reasons"] == ["presentation_view_declaration"] and item["wrapper_pointer"] is None
    assert out["sidecar"]["no_wrapper_field"] == []


def test_translatable_key_without_entry_lists_its_stubs():
    stub = dict(stub_id="s1", section="identifier_format", cause="candidate",
                bears_on=["identifier_format.delimiter"])
    out = translate.to_wrapper_v3(make_profile(stubs=[stub]), base_wrapper(), Q, "10-Q")
    item = next(i for i in out["sidecar"]["no_entry"] if i["profile_key"] == "identifier_format.delimiter")
    assert item["stub_ids"] == ["s1"] and item["base_present"] is True


# ---------------------------------------------------------------- inherited overlay, coverage, parity

def test_inherited_overlay_lists_every_retained_field_with_its_hash():
    base = base_wrapper()
    base["identifier_format"].pop("delimiter")  # the parent object exists; only the leaf is filled
    prof = make_profile(BASIC)
    out = translate.to_wrapper_v3(prof, base, Q, "10-Q")
    assert out["sidecar"]["fields_added"] == ["/identifier_format/delimiter"]
    assert out["sidecar"]["created_objects"] == []
    generated = leaves(out["wrapper"])
    driven = {"/cik", "/entity_name", "/identifier_format/delimiter"}
    overlay = {f["pointer"]: f["sha256"] for f in out["sidecar"]["inherited_overlay"]["fields"]}
    assert set(overlay) == set(generated) - driven
    assert all(overlay[p] == vhash(generated[p]) for p in overlay)
    assert out["sidecar"]["inherited_overlay"]["field_count"] == len(generated) - 3
    cov = out["sidecar"]["coverage"]
    assert (cov["fields_total"], cov["profile_driven"], cov["inherited"]) == (len(generated), 3, len(generated) - 3)
    assert cov["ratio"] == round(3 / len(generated), 6)
    added = next(t for t in out["sidecar"]["translated"] if t["wrapper_pointer"] == "/identifier_format/delimiter")
    assert added["base_present"] is False and added["equal_to_base"] is False
    same = next(t for t in out["sidecar"]["translated"] if t["wrapper_pointer"] == "/cik")
    assert same["equal_to_base"] is True  # equal to base still counts as profile-driven, not inherited
    parity = out["sidecar"]["parity"]
    assert parity["profile_driven_equal_to_base"] == 1 and parity["profile_driven_total"] == 3
    assert parity["fields_equal_to_base"] == len(generated) - 2


FV_ENTRY = entry("fund_level_concepts.investments_at_fair_value_concept", "us-gaap:InvestmentOwnedAtFairValue")


@pytest.mark.parametrize("strip", ["invariants", "fv_reconciliation"])
def test_creating_an_invariant_parent_is_not_expressible(strip):
    base = base_wrapper()
    if strip == "invariants":
        base.pop("invariants")
    else:
        base["invariants"] = {"rate_sanity": {"min_pct": 0.0, "max_pct": 30.0}}
    out = translate.to_wrapper_v3(make_profile((FV_ENTRY,)), base, Q, "10-Q")
    [item] = out["sidecar"]["not_expressible"]
    assert item["reasons"] == ["would_create_invariant"]
    assert item["would_create"] == (["/invariants", "/invariants/fv_reconciliation"] if strip == "invariants"
                                    else ["/invariants/fv_reconciliation"])
    assert out["wrapper"] == base  # no key created, production check not switched on
    assert out["sidecar"]["translated"] == [] and out["sidecar"]["fields_added"] == []
    assert out["sidecar"]["created_objects"] == []


def test_filling_a_leaf_of_an_existing_invariant_is_translated():
    base = base_wrapper()
    base["invariants"]["fv_reconciliation"].pop("source_field")
    out = translate.to_wrapper_v3(make_profile((FV_ENTRY,)), base, Q, "10-Q")
    [item] = out["sidecar"]["translated"]
    assert item["wrapper_pointer"] == "/invariants/fv_reconciliation/source_field" and item["base_present"] is False
    assert out["wrapper"]["invariants"]["fv_reconciliation"]["source_field"] == "investments_at_fair_value"
    assert out["sidecar"]["fields_added"] == ["/invariants/fv_reconciliation/source_field"]
    assert out["sidecar"]["created_objects"] == [] and out["sidecar"]["not_expressible"] == []


def test_creating_any_other_parent_object_is_not_expressible():
    base = base_wrapper()
    base.pop("identifier_format")
    out = translate.to_wrapper_v3(make_profile(BASIC), base, Q, "10-Q")
    [item] = out["sidecar"]["not_expressible"]
    assert item["reasons"] == ["would_create_object"] and item["would_create"] == ["/identifier_format"]
    assert "identifier_format" not in out["wrapper"] and out["sidecar"]["fields_added"] == []


def test_consumer_parity_needs_spec_parity_and_no_created_objects():
    assert translate.consumer_parity(dict(equal=True), []) == dict(verdict=True, spec_parity=True,
                                                                     created_objects=[])
    assert translate.consumer_parity(dict(equal=True), ["/invariants"])["verdict"] is False
    assert translate.consumer_parity(dict(equal=False), [])["verdict"] is False
    assert translate.consumer_parity(None, [])["verdict"] is False


def test_stale_entries_are_rejected_with_and_without_as_of():
    prof = make_profile(BASIC)
    stale = dict(prof, entries=prof["entries"][:-1])
    for as_of in (None, NOW, LATER):
        with pytest.raises(translate.TranslateError, match="materialized view"):
            translate.to_wrapper_v3(stale, base_wrapper(), Q, "10-Q", as_of=as_of)
    edited = copy.deepcopy(prof)
    edited["entries"][0]["value"] = "0000000001"
    with pytest.raises(translate.TranslateError, match="materialized view"):
        translate.to_wrapper_v3(edited, base_wrapper(), Q, "10-Q", as_of=LATER)


def test_coverage_splits_header_structural_and_via_inherited():
    # Finding I5: header (cik, entity_name) and via-inherited fields never count as structural.
    out = translate.to_wrapper_v3(make_profile(BASIC + (FV_ENTRY,)), base_wrapper(), Q, "10-Q")
    cov = out["sidecar"]["coverage"]
    assert (cov["profile_driven"], cov["profile_driven_header"], cov["profile_driven_structural"],
            cov["profile_driven_via_inherited"]) == (4, 2, 1, 1)
    assert cov["structural_ratio"] == round(1 / cov["fields_total"], 6)
    assert cov["ratio"] == round(4 / cov["fields_total"], 6)
    classes = {t["wrapper_pointer"]: t["coverage_class"] for t in out["sidecar"]["translated"]}
    assert classes == {"/cik": "header", "/entity_name": "header", "/identifier_format/delimiter": "structural",
                       "/invariants/fv_reconciliation/source_field": "via_inherited"}
    only_header = translate.to_wrapper_v3(make_profile(BASIC[:2]), base_wrapper(), Q, "10-Q")["sidecar"]["coverage"]
    assert only_header["profile_driven"] == 2 and only_header["profile_driven_structural"] == 0
    assert only_header["structural_ratio"] == 0.0


def test_a_mostly_copied_wrapper_reports_low_coverage_beside_high_parity():
    out = translate.to_wrapper_v3(make_profile(BASIC[:1]), base_wrapper(), Q, "10-Q")
    cov, parity = out["sidecar"]["coverage"], out["sidecar"]["parity"]
    assert parity["fields_equal_to_base"] == parity["fields_total"]
    assert cov["profile_driven"] == 1 and cov["ratio"] < 0.2


# ---------------------------------------------------------------- unknown keys, schema

def test_unknown_base_keys_are_refused_and_metadata_stays_in_the_sidecar():
    with pytest.raises(translate.UnknownWrapperKeyError):
        translate.to_wrapper_v3(make_profile(BASIC), base_wrapper(pilot_note="x"), Q, "10-Q")
    bad = base_wrapper()
    bad["dispatch"]["pilot_meta"] = {"a": 1}
    with pytest.raises(translate.UnknownWrapperKeyError):
        translate.to_wrapper_v3(make_profile(BASIC), bad, Q, "10-Q")
    out = translate.to_wrapper_v3(make_profile(BASIC), base_wrapper(), Q, "10-Q")
    assert set(out["wrapper"]) <= set(SCHEMA["properties"])
    assert out["sidecar"]["schema_validation"] == dict(verdict="pass", errors=[])


def test_other_schema_failures_are_recorded_not_hidden():
    bad = base_wrapper()
    bad["version"] = 0
    out = translate.to_wrapper_v3(make_profile(BASIC), bad, Q, "10-Q")
    assert out["sidecar"]["schema_validation"]["verdict"] == "fail"
    assert out["sidecar"]["schema_validation"]["errors"]


# ---------------------------------------------------------------- writing and loader admission

def test_write_overlay_confines_files_preserves_order_and_is_write_once(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-translate-test")
    out = translate.to_wrapper_v3(make_profile(BASIC), base_wrapper(), Q, "10-Q")
    records = translate.write_overlay(paths, CIK, "q1", out)
    wrapper_file = paths.run_root / "translate" / "wrappers_q1" / (CIK + ".json")
    sidecar_file = paths.run_root / "translate" / CIK / "q1.sidecar.json"
    assert Path(records["wrapper"]["path"]) == wrapper_file and Path(records["sidecar"]["path"]) == sidecar_file
    text = wrapper_file.read_text(encoding="ascii")
    loaded = json.loads(text)
    assert list(loaded["dispatch"]["prefix_rules"]) == ["Second Lien", "First Lien", "Equity"]
    assert loaded == out["wrapper"]
    sidecar = json.loads(sidecar_file.read_text(encoding="ascii"))
    assert sidecar["generated_wrapper"]["sha256"] == hashlib.sha256(wrapper_file.read_bytes()).hexdigest()
    with pytest.raises(translate.PathError):
        translate.write_overlay(paths, CIK, "q1", out)
    with pytest.raises(ValueError):
        translate.write_overlay(paths, CIK, "q3", out)


def test_production_loader_admits_a_generated_wrapper_and_reports_spec_parity(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-translate-test")
    real = json.loads((CODE_ROOT / "data" / "overrides" / "bdc_xbrl_wrappers" / (CIK + ".json")).read_text("utf-8"))
    out = translate.to_wrapper_v3(make_profile(BASIC[:2]), real, Q, "10-Q")
    translate.write_overlay(paths, CIK, "q1", out)
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    (base_dir / (CIK + ".json")).write_text(json.dumps(real), encoding="utf-8")
    verdicts = translate.admit_directory(paths.run_root / "translate" / "wrappers_q1", [CIK], base_dir=base_dir)
    v = verdicts["ciks"][CIK]
    assert v["admitted"] is True and v["error"] is None
    assert v["spec_parity"]["equal"] is True
    assert verdicts["directory_error"] is None


def test_loader_rejection_records_the_error_text_and_restores_state(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-translate-test")
    bad = base_wrapper()
    bad["dispatch"].pop("rule_prefix")  # schema-valid, but the production loader needs it
    out = translate.to_wrapper_v3(make_profile(BASIC), bad, Q, "10-Q")
    assert out["sidecar"]["schema_validation"]["verdict"] == "pass"
    translate.write_overlay(paths, CIK, "q1", out)
    specs_before = bdc_xbrl_wrapper.WRAPPER_SPECS
    handlers_before = list(logging.getLogger(bdc_xbrl_wrapper.__name__).handlers)
    verdicts = translate.admit_directory(paths.run_root / "translate" / "wrappers_q1", [CIK])
    v = verdicts["ciks"][CIK]
    assert v["admitted"] is False and "rule_prefix" in v["error"]
    assert "rule_prefix" in verdicts["directory_error"]
    assert bdc_xbrl_wrapper.WRAPPER_SPECS is specs_before
    assert logging.getLogger(bdc_xbrl_wrapper.__name__).handlers == handlers_before


def test_silent_loader_skip_is_a_rejection_with_a_reason(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-translate-test")
    bad = base_wrapper()
    bad.pop("dispatch")
    out = translate.to_wrapper_v3(make_profile(BASIC), bad, Q, "10-Q")
    translate.write_overlay(paths, CIK, "q1", out)
    v = translate.admit_directory(paths.run_root / "translate" / "wrappers_q1", [CIK])["ciks"][CIK]
    assert v["admitted"] is False and "dispatch" in v["error"]


def _consumer_bindings():
    from pipeline import staging_bdc, wrapper_content_signatures
    return dict(loader=(bdc_xbrl_wrapper, "_WRAPPER_DEFINITIONS_DIR"),
                staging=(staging_bdc, "_WRAPPER_DEFINITIONS_DIR"),
                signatures=(wrapper_content_signatures, "WRAPPER_DEFINITIONS_DIR"))


def test_restored_wrapper_context_restores_all_three_consumers_even_on_failure(tmp_path):
    # Finding I2: loader, staging_bdc and wrapper_content_signatures each bind their own directory.
    module = bdc_xbrl_wrapper
    bindings = _consumer_bindings()
    originals = {name: getattr(mod, attr) for name, (mod, attr) in bindings.items()}
    specs, specs_items = module.WRAPPER_SPECS, dict(module.WRAPPER_SPECS)
    logger = logging.getLogger(module.__name__)
    level, handlers, propagate = logger.level, list(logger.handlers), logger.propagate
    redirect = tmp_path / "generated"
    with pytest.raises(RuntimeError, match="boom"):
        with translate.restored_wrapper_context(redirect) as ctx:
            for name, (mod, attr) in bindings.items():
                assert getattr(mod, attr) == redirect, name  # redirected for the duration
                setattr(mod, attr, tmp_path / ("rebound_" + name))
            module.WRAPPER_SPECS = {}
            logger.setLevel(logging.CRITICAL)
            logger.propagate = False
            raise RuntimeError("boom")
    for name, (mod, attr) in bindings.items():
        assert getattr(mod, attr) is originals[name], name
    assert module.WRAPPER_SPECS is specs
    assert (logger.level, logger.handlers, logger.propagate) == (level, handlers, propagate)
    assert sorted(ctx.mutations) == sorted(["pipeline.bdc_xbrl_wrapper._WRAPPER_DEFINITIONS_DIR",
                                            "pipeline.bdc_xbrl_wrapper.WRAPPER_SPECS",
                                            "pipeline.staging_bdc._WRAPPER_DEFINITIONS_DIR",
                                            "pipeline.wrapper_content_signatures.WRAPPER_DEFINITIONS_DIR"])
    # In-place mutation of the loader's spec map is detected AND undone.
    with translate.restored_wrapper_context() as ctx:
        module.WRAPPER_SPECS["0000000000"] = object()
    assert module.WRAPPER_SPECS is specs and dict(module.WRAPPER_SPECS) == specs_items
    assert ctx.mutations == ["pipeline.bdc_xbrl_wrapper.WRAPPER_SPECS"]
    # A clean context reports no mutation and restores the redirect.
    with translate.restored_wrapper_context(redirect) as ctx:
        pass
    assert ctx.mutations == []
    assert all(getattr(mod, attr) is originals[name] for name, (mod, attr) in bindings.items())


def test_admission_records_the_directory_each_consumer_read(tmp_path):
    paths = fake_paths(tmp_path, run_id="stageb-translate-test")
    real = json.loads((CODE_ROOT / "data" / "overrides" / "bdc_xbrl_wrappers" / (CIK + ".json")).read_text("utf-8"))
    translate.write_overlay(paths, CIK, "q1", translate.to_wrapper_v3(make_profile(BASIC[:2]), real, Q, "10-Q"))
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    (base_dir / (CIK + ".json")).write_text(json.dumps(real), encoding="utf-8")
    generated = paths.run_root / "translate" / "wrappers_q1"
    report = translate.admit_directory(generated, [CIK], base_dir=base_dir)["wrapper_consumers"]
    consumers = report["consumers"]
    assert report["redirected_to"] == str(generated)
    assert consumers["loader"]["reads"] == [str(generated), str(base_dir)]
    assert consumers["loader"]["invoked"] is True
    for name in ("staging", "signatures"):
        assert consumers[name]["bound"] == str(generated)
        assert consumers[name]["reads"] == [] and consumers[name]["invoked"] is False
        assert "Stage C" in consumers[name]["note"]
    production = str(CODE_ROOT / "data" / "overrides" / "bdc_xbrl_wrappers")
    assert {consumers[n]["original"] for n in consumers} == {production}
    for name, (mod, attr) in _consumer_bindings().items():
        assert str(getattr(mod, attr)) == production, name


def test_nothing_is_written_under_data_overrides(tmp_path):
    # Minor B: data/overrides is a read-only root of the preservation inventory; the translate
    # stage (loader redirection included) runs inside it and the receipt must PASS.
    from tests.test_profile_pilot_profile import NOW as PNOW, build_census_root, sibling
    from scripts.profile_pilot import profile_run, protection
    overrides = (CODE_ROOT / "data" / "overrides").resolve()
    census_paths = build_census_root(tmp_path)
    profile_run.run_stage(sibling(census_paths, run_id="stageb-profile-test"), census_run_id=census_paths.run_id,
                          ciks=[CIK], recorded_at=PNOW)
    paths = sibling(census_paths, run_id="stageb-translate-test")
    assert overrides in paths.read_only_roots
    assert str(overrides) in {str(s.path) for s in protection.root_specs(paths)}
    before = protection.inventory(protection.root_specs(paths))
    assert any(p.startswith(str(overrides)) for p in before["files"])
    code = translate_run.main(["run", "--main-root", str(paths.main_repo_root), "--data-root", str(paths.data_root),
                               "--run-id", paths.run_id, "--profile-run-id", "stageb-profile-test", "--cik", CIK])
    assert code == 0
    after = protection.inventory(protection.root_specs(paths))
    assert protection.compare(before, after)["ok"]
    [receipt] = (paths.run_root / "verification").glob("*_translate_preservation.json")
    body = json.loads(receipt.read_text(encoding="ascii"))
    assert body["verdict"] == "PASS" and str(overrides) in body["read_only_roots"]
    assert str(overrides) in {s["path"] for s in body["before"]["specs"]}


# ---------------------------------------------------------------- stage (fake roots)

def test_stage_writes_wrappers_sidecars_and_summary_under_the_run_root(tmp_path):
    from tests.test_profile_pilot_profile import NOW as PNOW, build_census_root, sibling
    from scripts.profile_pilot import profile_run
    census_paths = build_census_root(tmp_path)
    prof_paths = sibling(census_paths, run_id="stageb-profile-test")
    profile_run.run_stage(prof_paths, census_run_id=census_paths.run_id, ciks=[CIK], recorded_at=PNOW)
    paths = sibling(census_paths, run_id="stageb-translate-test")
    summary = translate_run.run_stage(paths, profile_run_id="stageb-profile-test", ciks=[CIK], as_of=PNOW)
    root = paths.run_root
    bases = dict(q1=CODE_ROOT / "data" / "overrides" / "bdc_xbrl_wrappers" / (CIK + ".json"),
                 same_era=prof_paths.run_root / "inputs" / "verified_era_wrappers" / (CIK + ".json"))
    for era in ("q1", "same_era"):
        # The fixture census yields entity_cik and a " | " delimiter entry; the Stellus wrapper has
        # identifier_format (delimiter ", ") and invariants, so both translate and nothing is created.
        base = json.loads(bases[era].read_text(encoding="utf-8"))
        n = len(leaves(base))
        generated = json.loads((root / "translate" / ("wrappers_" + era) / (CIK + ".json")).read_text("ascii"))
        assert generated["identifier_format"]["delimiter"] == " | " and generated["cik"] == CIK
        sidecar = json.loads((root / "translate" / CIK / (era + ".sidecar.json")).read_text(encoding="ascii"))
        row = summary["ciks"][CIK][era]
        assert [(t["wrapper_pointer"], t["equal_to_base"]) for t in row["translated"]] == [
            ("/cik", True), ("/identifier_format/delimiter", False)]
        assert row["not_expressible"] == [] and row["entries_used"] == 2
        assert row["schema_validation"] == dict(verdict="pass", errors=[])
        assert row["loader_admission"]["admitted"] is True and row["loader_admission"]["error"] is None
        assert row["coverage"] == dict(fields_total=n, profile_driven=2, profile_driven_header=1,
                                       profile_driven_structural=1, profile_driven_via_inherited=0,
                                       inherited=n - 2, ratio=round(2 / n, 6), structural_ratio=round(1 / n, 6))
        assert [t["coverage_class"] for t in row["translated"]] == ["header", "structural"]
        assert summary["admission"][era]["wrapper_consumers"]["consumers"]["staging"]["invoked"] is False
        assert row["inherited_overlay"]["field_count"] == n - 2
        assert row["fields_added"] == [] and row["created_objects"] == []
        assert row["consumer_parity"] == dict(verdict=True, spec_parity=True, created_objects=[])
        assert sidecar["consumer_parity"] == row["consumer_parity"]
        assert sidecar["fields_added"] == [] and sidecar["inherited_overlay"]["field_count"] == n - 2
        totals = summary["totals"][era]
        assert (totals["admitted"], totals["schema_pass"], totals["not_expressible"]) == (1, 1, 0)
        assert totals["not_expressible_by_reason"] == {}
        assert (totals["fields_added"], totals["consumer_parity_true"]) == (0, 1)
        assert (totals["profile_driven_fields"], totals["profile_driven_header"], totals["profile_driven_structural"],
                totals["profile_driven_via_inherited"]) == (2, 1, 1, 0)
        assert totals["loader_state_mutations"] == []
        assert summary["admission"][era]["wrapper_consumers"]["consumers"]["loader"]["reads"][0].endswith(
            "wrappers_" + era)
    manifest_body = json.loads((root / "manifest.json").read_text(encoding="ascii"))
    labels = {r["label"] for r in manifest_body["inputs"]}
    assert "code/schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json" in labels
    assert "code/pipeline/bdc_xbrl_wrapper.py" in labels
    assert "profile_root/profiles/" + CIK + "/q1.json" in labels
    assert "base_wrapper/q1/" + CIK in labels and "base_wrapper/same_era/" + CIK in labels
    assert (root / "results" / "translate_summary.json").is_file()
    assert manifest_body["census_root"]["run_id"] == census_paths.run_id
    assert manifest_body["census_root"]["lineage"]["ok"] is True
    assert "census_root/results/authoritative.json" in labels
    with pytest.raises(translate.PathError):
        translate_run.run_stage(paths, profile_run_id="stageb-profile-test", ciks=[CIK], as_of=PNOW)


def test_translate_refuses_a_profile_root_whose_census_lineage_does_not_hold(tmp_path):
    # Finding I1, transitively: profile root -> the census root it names -> the census bytes listed there.
    from tests.test_profile_pilot_profile import NOW as PNOW, build_census_root, sibling
    from scripts.profile_pilot import profile_run
    from scripts.profile_pilot.manifest import StageInvalidated
    census_paths = build_census_root(tmp_path)
    profile_run.run_stage(sibling(census_paths, run_id="stageb-profile-test"), census_run_id=census_paths.run_id,
                          ciks=[CIK], recorded_at=PNOW)
    listing = census_paths.run_root / "results" / "authoritative.json"
    original = listing.read_text(encoding="ascii")
    body = json.loads(original)
    for row in body["fund_quarters"]:
        if row["role"] == "verified_era":
            row["census_sha256"] = "f" * 64
    listing.write_text(json.dumps(body), encoding="ascii")
    paths = sibling(census_paths, run_id="stageb-translate-test")
    with pytest.raises(StageInvalidated, match="same_era was derived from census"):
        translate_run.run_stage(paths, profile_run_id="stageb-profile-test", ciks=[CIK], as_of=PNOW)
    assert not (paths.run_root / "translate").exists()
    code = translate_run.main(["run", "--main-root", str(paths.main_repo_root), "--data-root", str(paths.data_root),
                               "--run-id", "stageb-translate-test2", "--profile-run-id", "stageb-profile-test",
                               "--cik", CIK])
    assert code == translate_run.EXIT_INVALIDATED
    # A non-pass verdict in the named census root is refused as well (one shared reader).
    body = json.loads(original)
    body["fund_quarters"][0].pop("validation_verdict")
    listing.write_text(json.dumps(body), encoding="ascii")
    with pytest.raises(StageInvalidated, match="validation_verdict"):
        translate_run.run_stage(sibling(census_paths, run_id="stageb-translate-test3"),
                                profile_run_id="stageb-profile-test", ciks=[CIK], as_of=PNOW)
    listing.write_text(original, encoding="ascii")
    translate_run.run_stage(sibling(census_paths, run_id="stageb-translate-test4"),
                            profile_run_id="stageb-profile-test", ciks=[CIK], as_of=PNOW)


# ---------------------------------------------------------------- cached profile (launcher only)

@pytest.mark.needs_cache
def test_real_stepstone_q1_profile_translates_and_is_admitted(tmp_path):
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    if not data_root:
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    cik = "0001950803"
    root = Path(data_root) / "pilot" / "filer_profile" / PROFILE_RUN_ID
    path = root / "profiles" / cik / "q1.json"
    if not path.is_file():
        pytest.skip("Task 6 profile root missing")
    summary = json.loads((root / "results" / "profile_summary.json").read_text(encoding="ascii"))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == summary["profiles"][cik + "/q1"]["sha256"]
    doc = json.loads(path.read_text(encoding="ascii"))["result"]
    base = json.loads((CODE_ROOT / "data" / "overrides" / "bdc_xbrl_wrappers" / (cik + ".json")).read_text("utf-8"))
    out = translate.to_wrapper_v3(doc, copy.deepcopy(base), doc["report_date"], doc["form_type"])
    assert out["wrapper"]["identifier_format"]["delimiter"] == " | "
    assert out["sidecar"]["schema_validation"]["verdict"] == "pass"
    assert out["sidecar"]["coverage"]["profile_driven"] >= 3
    folder = tmp_path / "gen"
    folder.mkdir()
    (folder / (cik + ".json")).write_text(json.dumps(out["wrapper"]), encoding="ascii")
    v = translate.admit_directory(folder, [cik])["ciks"][cik]
    assert v["admitted"] is True
