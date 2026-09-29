"""Filer-profile pilot Task 6: profile derivation (no wrapper access) and faithful M1 scoring.

Synthetic census documents come from synthetic XML through the real census code
(tests.test_profile_pilot_census helpers) or, for detector-outcome edge cases, from a
minimal hand-built census dict. The one `needs_cache` test reads a real census file
of the authoritative Stage B census root through PROFILE_PILOT_DATA_ROOT (set by the
pilot launcher) and writes nothing.
"""
from __future__ import annotations

import ast
import builtins
import copy
import json
import os
from pathlib import Path

import pytest

from scripts.profile_pilot import census, envelope, m1, manifest, profile, profile_run
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import PathError, resolve_paths
from tests.test_profile_pilot_census import assemble, ctx, document, fact, position, write
from tests.test_profile_pilot_paths import CODE_ROOT, fake_paths

CIK = "0001901037"
Q = "2023-03-31"
NOW = "2026-09-29T12:00:00Z"
IDENT = "us-gaap:InvestmentIdentifierAxis"
SOURCE = dict(cik=CIK, report_date=Q, role="q1", census_relative="census/" + CIK + "/" + Q + ".json",
              census_sha256="0" * 64, fingerprint="f" * 64, accession_number="0000000000-23-000001",
              form_type="10-Q")
CENSUS_ROOT_ID = "stageb-fake-census"
AUTH_ROOT_ID = "stageb-20260929t004819z"


# ---------------------------------------------------------------- builders

def dei_facts(cik=CIK, name="Stellus Private Credit BDC"):
    return [fact("dei:EntityCentralIndexKey", "dei_ctx", cik),
            fact("dei:EntityRegistrantName", "dei_ctx", name)]


def xml_census(tmp_path, *, delimiter=" | ", rows=12, total=True, name="Stellus Private Credit BDC"):
    parts = [position("p%d" % i, "Borrower %d LLC%sFirst Lien Term Loan" % (i, delimiter), "100")
             for i in range(rows)]
    contexts, facts = assemble(*parts)
    if total:
        contexts.append(ctx("fund_total", Q))
        facts.append(fact("us-gaap:InvestmentOwnedAtFairValue", "fund_total", str(100 * rows),
                          unit="usd", decimals="0"))
    facts += dei_facts(name=name)
    path = write(tmp_path, document(contexts, facts))
    meta = dict(cik=CIK, report_date=Q, accession_number="0000000000-23-000001",
                form_type="10-Q", role="q1")
    return census.build_census(path, meta)


def outcome(detector, finding, state="resolved", subject=None, evidence=None, provenance="derived",
            inherited_from=None):
    return dict(detector=detector, subject=subject or {}, outcome=state, finding=finding,
                evidence=evidence or {}, provenance=provenance, inherited_from=inherited_from,
                depends_on_channels=["contexts"])


def detector(outcomes):
    counts = {k: sum(o["outcome"] == k for o in outcomes)
              for k in ("candidate", "resolved", "insufficient_evidence")}
    return dict(outcomes=outcomes, counts=counts, channel_states={}, depends_on_channels=[])


def mini_doc(*, partition=(), subtotal=(), alternate=(), non_disclosure=(), footnotes="complete",
             identifiers=None, report_date=Q):
    """A minimal census document: only what derive_profile reads."""
    identifiers = identifiers if identifiers is not None else [
        "Borrower %d LLC | Term Loan" % i for i in range(12)]
    contexts, positions = [], []
    for i, ident in enumerate(identifiers):
        cid = "p%d" % i
        typed = [dict(axis=IDENT, value=ident)]
        contexts.append(dict(id=cid, period=dict(kind="instant", instant=report_date), dimensions=[],
                             typed_dimensions=typed, entity=dict(identifier=CIK), role="confirmed_position"))
        positions.append(dict(observation_id="obs:" + cid, context_id=cid,
                              period=dict(kind="instant", instant=report_date),
                              identity=dict(typed_identifier=ident, dimensions=[], typed_dimensions=typed),
                              dimension_fields={},
                              fields={"fair_value": dict(status="reported", value="100",
                                                         concepts=["us-gaap:InvestmentOwnedAtFairValue"],
                                                         provenance="inherited",
                                                         inherited_from="pipeline/bdc_filings.py:CONCEPT_MAP")},
                              provenance="inherited",
                              inherited_from="pipeline/context_inventory.py:classify_context"))
    channels = {name: dict(state="complete") for name in
                ("contexts", "identifiers", "numeric_facts", "text_facts", "units")}
    channels["footnotes"] = dict(state=footnotes)
    return dict(
        document=dict(cik=CIK, report_date=report_date, accession_number="0000000000-23-000001",
                      form_type="10-Q", role="q1"),
        document_metadata=dict(document_period_end_dates=[report_date]),
        channels=channels, contexts=contexts, positions=positions, periods=[],
        facts=[dict(i=0, qname="dei:EntityCentralIndexKey", field="entity_cik", context_id="dei",
                    status="reported", value=CIK, provenance="derived", inherited_from=None)],
        fund_income=[], fund_balance=[], dependencies=[dict(name="concept_map")],
        detectors=dict(partition=detector(list(partition)), subtotal=detector(list(subtotal)),
                       alternate_view=detector(list(alternate)),
                       non_disclosure=detector(list(non_disclosure))))


def single_dialect(delim="|", prevalence=1.0, rows=12):
    profile_ = {d: dict(rows=0, prevalence=0, segment_counts={}) for d in ("|", ";", ",", " - ", " / ")}
    profile_[delim] = dict(rows=rows, prevalence=prevalence, segment_counts={"2": rows})
    return outcome("partition", "single_dialect", subject=dict(signature=dict(kind="none"), rows=rows),
                   evidence=dict(delimiter_profile=profile_))


def wrapper_doc(**sections):
    base = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": CIK, "entity_name": "Stellus Private Credit BDC",
            "version": 4, "source": "bdc_xbrl",
            "dispatch": {"rule_prefix": "STELLUS", "prefix_rules": {},
                         "aggregate_markers": ["total investments", "subtotal"]},
            "identifier_format": {"delimiter": " | ", "field_order": ["issuer_name", "instrument"]},
            "invariants": {"fv_reconciliation": {"source_field": "investments_at_fair_value",
                                                 "tolerance_pct": 0.05, "tolerance_abs": 5000000}}}
    base.update(sections)
    return base


def inventory_for(tmp_path, wrapper, cik=CIK):
    folder = tmp_path / "wrappers"
    folder.mkdir(exist_ok=True)
    (folder / (cik + ".json")).write_text(json.dumps(wrapper), encoding="utf-8")
    return manifest.wrapper_key_inventory(CODE_ROOT, wrapper_dir=folder, ciks=[cik])


def synthetic_profile(entries=(), stubs=(), report_date=Q):
    """entries: (key, value, provenance, inherited_from, applies_to) tuples."""
    events = []
    for key, value, prov, inh, applies in entries:
        events = envelope.make_assertion(
            events, cik=CIK, key=key, value=value, valid_from=report_date, recorded_at=NOW,
            support=dict(kind="prevalence", numerator=1, denominator=1),
            evidence=[dict(kind="test")], applies_to=applies, provenance=prov, inherited_from=inh)
    return dict(cik=CIK, era="q1", report_date=report_date, form_type="10-Q",
                entries=envelope.materialize_entries(events), packet_stubs=list(stubs))


def score(tmp_path, wrapper, prof):
    inventory = inventory_for(tmp_path, wrapper)
    semantics = m1.build_semantics(inventory)
    keys = inventory["ciks"][CIK]["keys"]
    return m1.compare_to_wrapper(prof, wrapper, cik=CIK, inventory_keys=keys, semantics=semantics)


def cls(result, key):
    return next(r for r in result["keys"] if r["key"] == key)


# ---------------------------------------------------------------- derivation: wrapper isolation

def test_derivation_module_cannot_see_the_wrapper():
    source = (Path(profile.__file__)).read_text(encoding="ascii")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {(node.module or "") + "." + a.name for a in node.names}
    assert not any("m1" in name or "manifest" in name or "bdc_xbrl_wrapper" in name
                   or "profile_run" in name for name in imported), sorted(imported)
    for forbidden in ("bdc_xbrl_wrappers", "verified_era_wrappers", "historical_wrapper",
                      "wrapper_key_inventory", "WRAPPER_DIR"):
        assert forbidden not in source


def test_derive_profile_opens_only_schema_files(tmp_path, monkeypatch):
    """Derivation reads nothing but JSON Schemas (the pilot envelope schema, jsonschema's metaschemas)."""
    doc = xml_census(tmp_path)
    opened = []
    real_open, real_read_text, real_read_bytes = builtins.open, Path.read_text, Path.read_bytes
    schema_dir = Path(profile.__file__).resolve().parent / "schemas"

    def allowed(target) -> bool:
        path = Path(str(target)).resolve()
        opened.append(str(path))
        return schema_dir in path.parents or "jsonschema" in str(path).lower()

    def guard_open(file, *args, **kwargs):
        if not allowed(file):
            raise AssertionError("derive_profile opened " + str(file))
        return real_open(file, *args, **kwargs)

    def guard_text(self, *args, **kwargs):
        if not allowed(self):
            raise AssertionError("derive_profile read " + str(self))
        return real_read_text(self, *args, **kwargs)

    def guard_bytes(self, *args, **kwargs):
        if not allowed(self):
            raise AssertionError("derive_profile read " + str(self))
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guard_open)
    monkeypatch.setattr(Path, "read_text", guard_text)
    monkeypatch.setattr(Path, "read_bytes", guard_bytes)
    prof = profile.derive_profile(doc, source=SOURCE, era="q1", recorded_at=NOW, anchors=None)
    assert prof["cik"] == CIK and prof["era"] == "q1"
    assert not [p for p in opened if "bdc_xbrl_wrappers" in p or "verified_era_wrappers" in p]


def test_wrapper_marker_evidence_value_is_never_copied_into_a_derived_value():
    marker = dict(marker="secret wrapper marker", provenance="inherited",
                  inherited_from="data/overrides/bdc_xbrl_wrappers/x.json", sha256="a" * 64)
    doc = mini_doc(partition=[single_dialect()], subtotal=[outcome(
        "subtotal", "wrapper_marker_only", state="candidate",
        subject=dict(context_id="t1", label="Total Investments"),
        evidence=dict(heading="total_label", wrapper_marker=marker, matched_sets=[]),
        provenance="inherited", inherited_from=marker["inherited_from"])])
    prof = profile.derive_profile(doc, source=SOURCE, era="q1", recorded_at=NOW, anchors=None)
    assert "secret wrapper marker" not in json.dumps(prof["entries"])
    assert not [e for e in prof["entries"] if e["key"] == "subtotals_and_headings.aggregate_labels"]


# ---------------------------------------------------------------- derivation: entries and stubs

def test_entries_carry_the_envelope_contract(tmp_path):
    prof = profile.derive_profile(xml_census(tmp_path), source=SOURCE, era="q1", recorded_at=NOW,
                                  anchors=None)
    profile.validate_document(prof)
    assert prof["entries"]
    for entry in prof["entries"]:
        assert entry["author"] == "census" and entry["status"] == "derived"
        assert entry["regression_pin"] is None and entry["valid_to"] is None
        assert entry["valid_from"] == Q and entry["recorded_at"] == NOW
        assert entry["provenance"] in ("derived", "inherited")
        assert (entry["provenance"] == "inherited") == bool(entry["inherited_from"])
        assert entry["support"]["kind"] in ("prevalence", "context_count")
        kinds = {item["kind"] for item in entry["evidence"]}
        assert {"census_source", "dependencies"} <= kinds
        source = next(i for i in entry["evidence"] if i["kind"] == "census_source")
        assert source["census_sha256"] == SOURCE["census_sha256"] and source["form_type"] == "10-Q"
    envelope.validate_profile(prof["events"], sample_rows={})


def test_delimiter_entry_from_resolved_single_dialect_with_measured_padding(tmp_path):
    prof = profile.derive_profile(xml_census(tmp_path, delimiter=" | "), source=SOURCE, era="q1",
                                  recorded_at=NOW, anchors=None)
    entry = next(e for e in prof["entries"] if e["key"] == "identifier_format.delimiter")
    assert entry["value"] == " | "
    assert entry["support"] == dict(kind="prevalence", numerator=12, denominator=12)
    assert entry["applies_to"] is None and entry["form_type"] is None


def test_candidate_and_insufficient_partitions_become_packet_stubs_not_entries():
    doc = mini_doc(partition=[
        single_dialect(),
        outcome("partition", "optional_trailing_segments", state="candidate",
                subject=dict(signature=dict(kind="segment_counts", delimiter="|", counts=[3, 6]))),
        outcome("partition", "no_structural_discriminator", state="insufficient_evidence",
                subject=dict(signature=dict(kind="segment_counts", delimiter="|", counts=[2, 3])),
                evidence=dict(packet_stub=dict(question="one grammar or two?")))])
    prof = profile.derive_profile(doc, source=SOURCE, era="q1", recorded_at=NOW, anchors=None)
    assert not [e for e in prof["entries"] if e["key"].startswith("identifier_format.")]
    stubs = [s for s in prof["packet_stubs"] if s["section"] == "identifier_format"]
    assert sorted(s["cause"] for s in stubs) == ["candidate", "insufficient_evidence"]
    assert all("identifier_format.delimiter" in s["bears_on"] for s in stubs)
    assert prof["sections"]["identifier_format"]["status"] == "unresolved"


def test_unsupported_footnote_channel_blocks_footnote_conventions(tmp_path):
    doc = xml_census(tmp_path)  # synthetic instance has no footnoteLink: channel unsupported
    assert doc["channels"]["footnotes"]["state"] == "unsupported"
    prof = profile.derive_profile(doc, source=SOURCE, era="q1", recorded_at=NOW, anchors=None)
    section = prof["sections"]["footnote_conventions"]
    assert section["status"] == "insufficient_evidence" and section["entry_ids"] == []
    assert any(s["section"] == "footnote_conventions" and s["cause"] == "insufficient_evidence"
               for s in prof["packet_stubs"])
    assert not [e for e in prof["entries"] if e["key"].startswith("footnote_conventions.")]
    nd = [e for e in prof["entries"] if e["key"].startswith("non_disclosure.")]
    assert all(e["value"] != "not_observed_in_complete_instance" for e in nd)


def test_stub_sections_and_anchor_copy_are_explicit():
    anchors = dict(status="copied", provenance="inherited",
                   inherited_from="data/overrides/agent_anchor/1901037/2023-03-31.json",
                   files=[dict(path="data/overrides/agent_anchor/1901037/2023-03-31.json",
                               sha256="b" * 64, report_date=Q, content={"grand_total": 1})])
    prof = profile.derive_profile(mini_doc(partition=[single_dialect()]), source=SOURCE, era="q1",
                                  recorded_at=NOW, anchors=anchors)
    assert prof["sections"]["accounting_scope"]["status"] == "stub"
    assert prof["sections"]["lifecycle"]["status"] == "stub"
    assert prof["sections"]["anchors"]["status"] == "copied"
    assert prof["anchors"]["files"][0]["sha256"] == "b" * 64
    missing = profile.derive_profile(mini_doc(partition=[single_dialect()]), source=SOURCE,
                                     era="q1", recorded_at=NOW, anchors=None)
    assert missing["sections"]["anchors"]["status"] == "stub"


def test_document_schema_rejects_a_bad_entry(tmp_path):
    prof = profile.derive_profile(xml_census(tmp_path), source=SOURCE, era="q1", recorded_at=NOW,
                                  anchors=None)
    bad = copy.deepcopy(prof)
    bad["entries"][0]["regression_pin"] = "tests/x.py::t"
    with pytest.raises(profile.ProfileError):
        profile.validate_document(bad)
    bad = copy.deepcopy(prof)
    del bad["sections"]["lifecycle"]
    with pytest.raises(profile.ProfileError):
        profile.validate_document(bad)


# ---------------------------------------------------------------- M1: comparison semantics

def test_identical_prefix_sets_with_different_mappings_are_not_exact(tmp_path):
    wrapper = wrapper_doc()
    wrapper["dispatch"]["prefix_rules"] = {"Debt Securities": "debt", "Equity Securities": "equity"}
    prof = synthetic_profile([("subtotals_and_headings.prefix_rules",
                               [["Debt Securities", "equity"], ["Equity Securities", "debt"]],
                               "derived", None, None)])
    result = score(tmp_path, wrapper, prof)
    # overlapping prefixes with zero matching (prefix, family) pairs is a miss, not partial
    assert cls(result, "dispatch.prefix_rules")["class"] == "miss"
    assert cls(result, "dispatch.prefix_rules.Debt Securities")["class"] == "miss"
    assert cls(result, "dispatch.prefix_rules.Equity Securities")["class"] == "miss"
    one_right = synthetic_profile([("subtotals_and_headings.prefix_rules",
                                    [["Debt Securities", "debt"], ["Equity Securities", "debt"]],
                                    "derived", None, None)])
    assert cls(score(tmp_path, wrapper, one_right), "dispatch.prefix_rules")["class"] == "partial"


def test_prefix_presence_without_family_mapping_is_not_exact(tmp_path):
    wrapper = wrapper_doc()
    wrapper["dispatch"]["prefix_rules"] = {"Debt Securities": "debt"}
    prof = synthetic_profile([("subtotals_and_headings.prefix_rules", [["Debt Securities", None]],
                               "derived", None, None)])
    result = score(tmp_path, wrapper, prof)
    assert cls(result, "dispatch.prefix_rules")["class"] == "miss"
    assert cls(result, "dispatch.prefix_rules.Debt Securities")["class"] == "miss"
    exact = [r["key"] for r in result["keys"] if r["class"] == "exact"]
    assert not [k for k in exact if k.startswith("dispatch.prefix_rules")]


def test_prefix_rule_order_is_significant(tmp_path):
    wrapper = wrapper_doc()
    wrapper["dispatch"]["prefix_rules"] = {"A": "debt", "B": "equity"}
    same = synthetic_profile([("subtotals_and_headings.prefix_rules", [["A", "debt"], ["B", "equity"]],
                               "derived", None, None)])
    swapped = synthetic_profile([("subtotals_and_headings.prefix_rules",
                                  [["B", "equity"], ["A", "debt"]], "derived", None, None)])
    assert cls(score(tmp_path, wrapper, same), "dispatch.prefix_rules")["class"] == "exact"
    assert cls(score(tmp_path, wrapper, swapped), "dispatch.prefix_rules")["class"] == "partial"


def test_wrong_tolerance_with_the_right_anchor_field(tmp_path):
    prof = synthetic_profile([
        ("fund_level_concepts.investments_at_fair_value_concept", "us-gaap:InvestmentOwnedAtFairValue",
         "derived", None, None),
        ("fund_level_concepts.invariants.fv_reconciliation.tolerance_pct", 0.10, "derived", None, None)])
    result = score(tmp_path, wrapper_doc(), prof)
    source = cls(result, "invariants.fv_reconciliation.source_field")
    # the concept -> field translation is the imported companyfacts table: inherited, never exact
    assert source["class"] == "inherited" and source["provenance"] == "inherited"
    assert source["inherited_from"].startswith("pipeline/extract_companyfacts.py@")
    assert cls(result, "invariants.fv_reconciliation.tolerance_pct")["class"] == "miss"
    tol_abs = cls(result, "invariants.fv_reconciliation.tolerance_abs")
    assert (tol_abs["class"], tol_abs["reason"]) == ("unresolved", "not_implemented")
    for key in ("invariants.fv_reconciliation", "invariants"):
        record = cls(result, key)
        assert (record["class"], record["reason"]) == ("unresolved", "not_implemented")
    wrong = synthetic_profile([("fund_level_concepts.investments_at_fair_value_concept",
                                "us-gaap:Assets", "derived", None, None)])
    assert cls(score(tmp_path, wrapper_doc(), wrong),
               "invariants.fv_reconciliation.source_field")["class"] == "miss"


def test_a_visible_fund_total_does_not_reproduce_an_invariant(tmp_path):
    prof = profile.derive_profile(xml_census(tmp_path, total=True), source=SOURCE, era="q1",
                                  recorded_at=NOW, anchors=None)
    concept = [e for e in prof["entries"] if e["key"] == "fund_level_concepts.investments_at_fair_value_concept"]
    assert concept and concept[0]["value"] == "us-gaap:InvestmentOwnedAtFairValue"
    result = score(tmp_path, wrapper_doc(), prof)
    for key in ("invariants.fv_reconciliation.tolerance_pct", "invariants.fv_reconciliation.tolerance_abs"):
        record = cls(result, key)
        assert (record["class"], record["reason"]) == ("unresolved", "not_implemented")
    assert cls(result, "invariants.fv_reconciliation.source_field")["class"] == "inherited"
    assert cls(result, "invariants.fv_reconciliation")["class"] == "unresolved"


def test_extra_aggregate_markers_are_partial_not_exact(tmp_path):
    """Derived values are full observed labels; wrapper values are any() substring markers.
    Observed labels cannot reproduce a marker set, so the best class is partial."""
    wrapper = wrapper_doc()
    extra = synthetic_profile([("subtotals_and_headings.aggregate_labels",
                                ["total investments (153.8%)", "subtotal", "total cash"], "derived", None, None)])
    record = cls(score(tmp_path, wrapper, extra), "dispatch.aggregate_markers")
    assert record["class"] == "partial" and record["extra"] == ["total cash"] and record["missing"] == []
    fewer = synthetic_profile([("subtotals_and_headings.aggregate_labels", ["Total  Investments"],
                                "derived", None, None)])
    record = cls(score(tmp_path, wrapper, fewer), "dispatch.aggregate_markers")
    assert record["class"] == "partial" and record["missing"] == ["subtotal"]
    same = synthetic_profile([("subtotals_and_headings.aggregate_labels", ["Subtotal", "total investments"],
                               "derived", None, None)])
    assert cls(score(tmp_path, wrapper, same), "dispatch.aggregate_markers")["class"] == "partial"
    disjoint = synthetic_profile([("subtotals_and_headings.aggregate_labels", ["grand sum"],
                                   "derived", None, None)])
    assert cls(score(tmp_path, wrapper, disjoint), "dispatch.aggregate_markers")["class"] == "miss"


def test_inherited_equality_is_inherited_never_exact(tmp_path):
    source = "data/overrides/bdc_xbrl_wrappers/0001901037.json (corroboration)"
    prof = synthetic_profile([("identifier_format.delimiter", " | ", "inherited", source, None)])
    result = score(tmp_path, wrapper_doc(), prof)
    assert cls(result, "identifier_format.delimiter")["class"] == "inherited"
    assert result["counts"]["exact"] == sum(r["class"] == "exact" for r in result["keys"])
    assert "identifier_format.delimiter" not in [r["key"] for r in result["keys"] if r["class"] == "exact"]


def test_subtotal_resting_on_wrapper_marker_yields_an_inherited_entry():
    marker = dict(marker="total investments", provenance="inherited",
                  inherited_from="data/overrides/bdc_xbrl_wrappers/0001901037.json", sha256="a" * 64)
    doc = mini_doc(partition=[single_dialect()], subtotal=[outcome(
        "subtotal", "structural_subtotal", subject=dict(context_id="t1", label="Total Investments"),
        evidence=dict(heading="category_only_dimensions", wrapper_marker=marker,
                      matched_sets=[dict(set="leaf_positions", children=["p1"], sum="1")]))])
    prof = profile.derive_profile(doc, source=SOURCE, era="q1", recorded_at=NOW, anchors=None)
    entry = next(e for e in prof["entries"] if e["key"] == "subtotals_and_headings.aggregate_labels")
    assert entry["value"] == ["total investments"]
    assert entry["provenance"] == "inherited" and "bdc_xbrl_wrappers" in entry["inherited_from"]


def test_unsupported_key_comparison_is_unresolved_not_implemented(tmp_path):
    wrapper = wrapper_doc(staging={"strategy": "hierarchy_extract"})
    prof = synthetic_profile([("fund_level_concepts.staging_strategy", "hierarchy_extract",
                               "derived", None, None)])
    result = score(tmp_path, wrapper, prof)
    record = cls(result, "staging.strategy")
    assert (record["class"], record["reason"]) == ("unresolved", "not_implemented")
    assert cls(result, "staging")["class"] == "unresolved"
    header = cls(result, "schema_version")
    assert header["class"] == "not_derivable"


def test_every_inventory_key_needs_a_frozen_family(tmp_path):
    wrapper = wrapper_doc(brand_new_section={"x": 1})
    inventory = inventory_for(tmp_path, wrapper)
    with pytest.raises(m1.SemanticsError):
        m1.build_semantics(inventory)


def test_delimiter_vocabulary_and_padding_rules(tmp_path):
    padded = synthetic_profile([("identifier_format.delimiter", "|", "derived", None, None)])
    record = cls(score(tmp_path, wrapper_doc(), padded), "identifier_format.delimiter")
    assert record["class"] == "partial"
    space = wrapper_doc(identifier_format={"delimiter": " ", "field_order": ["a"]})
    record = cls(score(tmp_path, space, padded), "identifier_format.delimiter")
    assert (record["class"], record["reason"]) == ("unresolved", "not_implemented")
    exact = synthetic_profile([("identifier_format.delimiter", " | ", "derived", None, None)])
    assert cls(score(tmp_path, wrapper_doc(), exact), "identifier_format.delimiter")["class"] == "exact"


def test_unresolved_selectors_follow_the_detector_reason(tmp_path):
    candidate = synthetic_profile(stubs=[dict(stub_id="identifier_format:1", section="identifier_format",
                                              cause="candidate", bears_on=["identifier_format.delimiter"])])
    record = cls(score(tmp_path, wrapper_doc(), candidate), "identifier_format.delimiter")
    assert (record["class"], record["reason"]) == ("unresolved", "candidate")
    insufficient = synthetic_profile(stubs=[dict(stub_id="identifier_format:1", section="identifier_format",
                                                 cause="insufficient_evidence",
                                                 bears_on=["identifier_format.delimiter"])])
    record = cls(score(tmp_path, wrapper_doc(), insufficient), "identifier_format.delimiter")
    assert (record["class"], record["reason"]) == ("unresolved", "insufficient_evidence")
    nothing = synthetic_profile()
    record = cls(score(tmp_path, wrapper_doc(), nothing), "identifier_format.delimiter")
    assert (record["class"], record["reason"]) == ("unresolved", "no_observation")
    record = cls(score(tmp_path, wrapper_doc(), nothing), "dispatch.aggregate_markers")
    assert (record["class"], record["reason"]) == ("unresolved", "no_observation")
    # resolved evidence that contradicts the wrapper (no dominant delimiter) is a miss
    contradicts = synthetic_profile(stubs=[dict(stub_id="identifier_format:1", section="identifier_format",
                                                cause="no_value", bears_on=["identifier_format.delimiter"])])
    assert cls(score(tmp_path, wrapper_doc(), contradicts), "identifier_format.delimiter")["class"] == "miss"


def test_partition_specific_entries_do_not_resolve_a_flat_wrapper_key(tmp_path):
    a = dict(kind="segment_count", delimiter="|", count=3)
    b = dict(kind="segment_count", delimiter="|", count=6)
    prof = synthetic_profile([("identifier_format.delimiter", " | ", "derived", None, a),
                              ("identifier_format.delimiter", "|", "derived", None, b)])
    record = cls(score(tmp_path, wrapper_doc(), prof), "identifier_format.delimiter")
    assert (record["class"], record["reason"]) == ("unresolved", "not_implemented")


def test_counts_use_the_fixed_denominator_and_partial_is_not_exact(tmp_path):
    wrapper = wrapper_doc()
    prof = synthetic_profile([("identifier_format.delimiter", "|", "derived", None, None)])
    result = score(tmp_path, wrapper, prof)
    keys = inventory_for(tmp_path, wrapper)["ciks"][CIK]["keys"]
    assert result["denominator"] == len(keys) == len(result["keys"])
    assert sum(result["counts"].values()) == len(keys)
    assert set(result["counts"]) == set(m1.CLASSES)
    assert result["counts"]["partial"] >= 1
    assert result["counts"]["exact"] == sum(r["class"] == "exact" for r in result["keys"])
    assert "verified" not in json.dumps(result).lower().replace("verified_era", "")


# ---------------------------------------------------------------- frozen semantics, stage wiring

def test_comparison_reads_the_frozen_semantics_file(tmp_path, monkeypatch):
    paths = fake_paths(tmp_path, run_id="stageb-profile-test")
    inventory = manifest.wrapper_key_inventory(CODE_ROOT)
    state = m1.freeze_semantics(paths, inventory)
    assert Path(state["path"]).name == "m1_comparison_semantics.json"
    frozen = m1.load_semantics(paths)
    with pytest.raises(PathError):
        m1.freeze_semantics(paths, inventory)
    wrapper = json.loads((CODE_ROOT / "data" / "overrides" / "bdc_xbrl_wrappers" / (CIK + ".json"))
                         .read_text(encoding="utf-8"))
    wrapper["entity_name"] = "Stellus Private Credit BDC LLC"
    prof = synthetic_profile(
        [("fund_level_concepts.entity_registrant_name", "STELLUS PRIVATE CREDIT BDC", "derived", None, None),
         ("fund_level_concepts.investments_at_fair_value_concept", "us-gaap:InvestmentOwnedAtFairValue",
          "derived", None, None)],
        stubs=[dict(stub_id="s:%d" % i, section="identifier_format", cause=c,
                    bears_on=["identifier_format.delimiter"])
               for i, c in enumerate(("insufficient_evidence", "candidate"))])
    keys = inventory["ciks"][CIK]["keys"]
    before = m1.compare_to_wrapper(prof, wrapper, cik=CIK, inventory_keys=keys, semantics=frozen)
    assert cls(before, "entity_name")["class"] == "partial"
    assert cls(before, "identifier_format.delimiter")["reason"] == "candidate"
    assert cls(before, "invariants.fv_reconciliation.source_field")["class"] == "inherited"
    for name, value in (("FAMILIES", []), ("LEGAL_FORM_TOKENS", ()), ("EQUIVALENCE", {}),
                        ("REASONS", ("not_implemented", "insufficient_evidence", "candidate")),
                        ("CLASSES", ("exact",)), ("ROLLUP", []), ("NO_ENTRY_RULE", [])):
        monkeypatch.setattr(m1, name, value)
    assert m1.load_semantics(paths) == frozen
    after = m1.compare_to_wrapper(prof, wrapper, cik=CIK, inventory_keys=keys, semantics=frozen)
    assert after == before
    for field in m1.REQUIRED_FIELDS:
        partial = {k: v for k, v in frozen.items() if k != field}
        with pytest.raises(m1.SemanticsError):
            m1.compare_to_wrapper(prof, wrapper, cik=CIK, inventory_keys=keys, semantics=partial)
    target = Path(state["path"])
    body = json.loads(target.read_text(encoding="ascii"))
    body["content"]["families"][0]["derivation"] = "implemented"
    target.write_text(json.dumps(body), encoding="ascii")
    with pytest.raises(StageInvalidated):
        m1.load_semantics(paths)
    missing = {k: v for k, v in frozen.items() if k != "legal_form_tokens"}
    target.write_text(json.dumps(dict(body, content=missing, content_sha256=manifest.digest(missing))),
                      encoding="ascii")
    with pytest.raises(m1.SemanticsError):
        m1.load_semantics(paths)


def build_census_root(tmp_path, *, ciks=(CIK,), inventory_override=None):
    """A fake authoritative census root built with the real Task 1 mechanism."""
    census_paths = fake_paths(tmp_path, run_id=CENSUS_ROOT_ID)
    inventory = inventory_override or manifest.wrapper_key_inventory(CODE_ROOT)
    manifest.freeze_inventory(census_paths, "wrapper_key_inventory", inventory)
    manifest.freeze_inventory(census_paths, "primary_quarter_inventory",
                              dict(fund_quarters=[], counts={}))
    rows = []
    for cik in ciks:
        for role, date in (("q1", Q), ("verified_era", "2026-03-31")):
            doc = mini_doc(partition=[single_dialect()], report_date=date)
            doc["document"]["cik"] = cik
            relative = "census/" + cik + "/" + date + ".json"
            target = census_paths.run_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            identity = dict(fingerprint=("%s%s" % (cik, date)).replace("-", "") .ljust(64, "0"))
            target.write_text(json.dumps(dict(identity=identity, complete=True, result=doc)),
                              encoding="ascii")
            rows.append(dict(cik=cik, role=role, report_date=date, census_relative=relative,
                             census_sha256=manifest.sha256_file(target),
                             fingerprint=identity["fingerprint"], validation_verdict="pass"))
    results = census_paths.run_root / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "authoritative.json").write_text(json.dumps(dict(run_id=CENSUS_ROOT_ID, fund_quarters=rows)),
                                                encoding="ascii")
    (results / "excluded.json").write_text(json.dumps(dict(fund_quarters=[])), encoding="ascii")
    return census_paths


def sibling(census_paths, run_id="stageb-profile-test"):
    return resolve_paths(main_repo_root=census_paths.main_repo_root, data_root=census_paths.data_root,
                         code_root=CODE_ROOT, run_id=run_id)


def test_same_era_and_q1_are_separately_keyed_and_never_overwrite(tmp_path):
    census_paths = build_census_root(tmp_path)
    paths = sibling(census_paths)
    summary = profile_run.run_stage(paths, census_run_id=CENSUS_ROOT_ID, ciks=[CIK], recorded_at=NOW)
    root = paths.run_root
    q1 = json.loads((root / "profiles" / CIK / "q1.json").read_text(encoding="ascii"))["result"]
    same = json.loads((root / "profiles" / CIK / "same_era.json").read_text(encoding="ascii"))["result"]
    assert (q1["era"], q1["report_date"]) == ("q1", Q)
    assert (same["era"], same["report_date"]) == ("same_era", "2026-03-31")
    r_q1 = json.loads((root / "results" / "m1_q1.json").read_text(encoding="ascii"))
    r_same = json.loads((root / "results" / "m1_same_era.json").read_text(encoding="ascii"))
    assert r_q1["era"] == "q1" and r_same["era"] == "same_era"
    assert r_q1["ciks"][CIK]["wrapper"]["commit"] == "HEAD"
    assert r_same["ciks"][CIK]["wrapper"]["commit"] == "eed082b"
    assert r_q1["ciks"][CIK]["profile"]["relative"] == "profiles/" + CIK + "/q1.json"
    assert r_same["ciks"][CIK]["profile"]["relative"] == "profiles/" + CIK + "/same_era.json"
    assert r_same["ciks"][CIK]["verified_era_label"]
    assert set(r_same["groups"]) >= {"reconciled", "verified_era_unreconciled"}
    assert summary["results"]["q1"] != summary["results"]["same_era"]
    manifest_body = json.loads((root / "manifest.json").read_text(encoding="ascii"))
    assert manifest_body["census_source"]["run_id"] == CENSUS_ROOT_ID
    assert manifest_body["census_source"]["authoritative"]["sha256"]
    assert {r["label"] for r in manifest_body["census_source"]["census_files"]} == {
        "census/" + CIK + "/" + Q + ".json", "census/" + CIK + "/2026-03-31.json"}
    sem = root / "inventories" / "m1_comparison_semantics.json"
    assert sem.stat().st_mtime <= (root / "profiles" / CIK / "q1.json").stat().st_mtime
    with pytest.raises((PathError, StageInvalidated)):
        profile_run.run_stage(paths, census_run_id=CENSUS_ROOT_ID, ciks=[CIK], recorded_at=NOW)
    assert json.loads((root / "results" / "m1_q1.json").read_text(encoding="ascii")) == r_q1


def test_inventory_hash_mismatch_invalidates_the_stage(tmp_path):
    other = manifest.wrapper_key_inventory(CODE_ROOT)
    other = copy.deepcopy(other)
    other["ciks"][CIK]["keys"] = other["ciks"][CIK]["keys"][:-1]
    paths = sibling(build_census_root(tmp_path, inventory_override=other))
    with pytest.raises(StageInvalidated):
        profile_run.run_stage(paths, census_run_id=CENSUS_ROOT_ID, ciks=[CIK], recorded_at=NOW)
    assert not (paths.run_root / "profiles").exists()
    code = profile_run.main(["run", "--main-root", str(paths.main_repo_root), "--data-root",
                             str(paths.data_root), "--run-id", "stageb-profile-test2",
                             "--census-run-id", CENSUS_ROOT_ID, "--cik", CIK])
    assert code != 0


def test_a_changed_census_file_invalidates_the_stage(tmp_path):
    census_paths = build_census_root(tmp_path)
    target = census_paths.run_root / "census" / CIK / (Q + ".json")
    target.write_text(target.read_text(encoding="ascii") + " ", encoding="ascii")
    paths = sibling(census_paths)
    with pytest.raises(StageInvalidated):
        profile_run.run_stage(paths, census_run_id=CENSUS_ROOT_ID, ciks=[CIK], recorded_at=NOW)


# ---------------------------------------------------------------- cached census (launcher only)

@pytest.mark.needs_cache
def test_real_stellus_q1_census_derives_without_the_wrapper():
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    if not data_root:
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    root = Path(data_root) / "pilot" / "filer_profile" / AUTH_ROOT_ID
    auth = root / "results" / "authoritative.json"
    if not auth.is_file():
        pytest.skip("authoritative census root missing")
    rows = json.loads(auth.read_text(encoding="ascii"))["fund_quarters"]
    row = next(r for r in rows if r["cik"] == CIK and r["role"] == "q1")
    path = root / row["census_relative"]
    assert manifest.sha256_file(path) == row["census_sha256"]
    doc = json.loads(path.read_text(encoding="ascii"))["result"]
    source = dict(cik=CIK, report_date=row["report_date"], role="q1", census_relative=row["census_relative"],
                  census_sha256=row["census_sha256"], fingerprint=row["fingerprint"],
                  accession_number=doc["document"]["accession_number"], form_type=doc["document"]["form_type"])
    prof = profile.derive_profile(doc, source=source, era="q1", recorded_at=NOW, anchors=None)
    profile.validate_document(prof)
    assert prof["sections"]["footnote_conventions"]["status"] == "insufficient_evidence"
    assert prof["sections"]["identifier_format"]["status"] == "unresolved"
    keys = {e["key"] for e in prof["entries"]}
    assert "fund_level_concepts.entity_cik" in keys
    assert "identifier_format.delimiter" not in keys
    wrapper = json.loads((CODE_ROOT / "data" / "overrides" / "bdc_xbrl_wrappers" / (CIK + ".json"))
                         .read_text(encoding="utf-8"))
    inventory = manifest.wrapper_key_inventory(CODE_ROOT, ciks=[CIK])
    result = m1.compare_to_wrapper(prof, wrapper, cik=CIK, inventory_keys=inventory["ciks"][CIK]["keys"],
                                   semantics=m1.build_semantics(inventory))
    assert cls(result, "cik")["class"] == "exact"
    delim = cls(result, "identifier_format.delimiter")
    assert (delim["class"], delim["reason"]) == ("unresolved", "insufficient_evidence")
    assert sum(result["counts"].values()) == len(inventory["ciks"][CIK]["keys"])
