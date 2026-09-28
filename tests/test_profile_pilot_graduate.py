"""Graduation [E] (spec 6.5): exact origin fidelity, witnesses, anchors, classes.

Synthetic frames run through the REAL production appliers
(agent_promoted.apply_raw_staging_exclusions / apply_promoted_plan); only the frame
source is synthetic. The cached-slice tests at the bottom are `needs_cache`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from scripts.profile_pilot import graduate as g

CIK = "0000000001"
ACC = "0000000001-25-000001"
Q1, Q2, Q3, Q4 = "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"
T0 = "2026-09-28T00:00:00Z"
AFF = "Controlled Affiliated Investments"


# ------------------------------------------------------------------ helpers

def raw(rows, rd=Q4, cik=CIK, acc=ACC):
    """bdc_holdings-shaped rows: (identifier, fair_value, period, context)."""
    out = []
    for ident, fv, period, ctx in rows:
        out.append(dict(cik=cik, report_date=rd, period=period, accession_number=acc,
                        src_context_id=ctx, investment_identifier=ident,
                        dimensions_raw="investmentidentifieraxis=" + ident,
                        fair_value=None if fv is None else str(fv), fair_value_unit="U_USD"))
    return g.with_rids(pd.DataFrame(out))


def staged(rows, rd=Q2, cik=CIK, acc=ACC, dims=None):
    """Unified-shaped rows: (identifier, fair_value, context[, cost])."""
    out = []
    for i, row in enumerate(rows):
        ident, fv, ctx = row[:3]
        cost = row[3] if len(row) > 3 else None
        out.append(dict(source="bdc", cik=cik, entity_name="Pilot Fund", accession_number=acc,
                        report_date=rd, src_context_id=ctx, bdc_investment_identifier=ident,
                        bdc_dimensions_raw=(dims[i] if dims else "investmentidentifieraxis=" + ident),
                        issuer_name=ident, fair_value=fv, cost=cost, principal_amount=None,
                        maturity_date=None, asset_category="LOAN", index_classification="LOAN",
                        is_subsidiary="0", fair_value_currency="USD"))
    return g.with_rids(pd.DataFrame(out))


def comparative_leaf(rd=Q4, cik=CIK):
    return dict(cik=cik, mechanism="comparative_leak", fix_class="comparative_period_filter",
                template=dict(report_date=rd), confidence=0.9, rationale="comparative leak")


def rule(predicate, quarters, rule_id="dup_rule", rationale="alternate-axis duplicate presentation"):
    return dict(cik=str(int(CIK)), rule_id=rule_id, rule_type="row_exclusion", action="exclude",
                scope=dict(quarters=quarters), predicate_sql=predicate,
                evidence=[dict(source="query", quote="q")], rationale=rationale, confidence=0.9)


def item_for(body):
    return g.inventory_item(body, path="synthetic/" + g.body_id(body) + ".json", sha256="0" * 64)


AFF_PRED = "bdc_dimensions_raw LIKE 'investmentidentifieraxis=" + AFF + "%'"


def anchor(q, total, basis="published_rows"):
    return dict(cik=str(int(CIK)), target_quarter=q, grand_total=total, method="total_row",
                components=[dict(label="Total Investments", value=total, source="synthetic")],
                evidence=[dict(source="filing", quote="Total Investments")], rationale="r",
                companyfacts_fv=total, basis=basis)


def dup_quarter(rd, *, fv=100.0, extra=()):
    """One detail position plus its affiliation-axis duplicate view (same FV)."""
    return staged([("Debt Securities Chemicals AGY Holdings Corp. Term Loan - 15.59% inc PIK", fv, "c1"),
                   (AFF + " AGY Holdings Corp. Term Loan - 15.59% inc PIK", fv, "c2"), *extra], rd=rd)


def published(frame, drop_prefix=AFF):
    keep = ~frame["bdc_investment_identifier"].astype(str).str.startswith(drop_prefix)
    return frame.loc[keep].drop(columns=[g.RID]).reset_index(drop=True)


# ------------------------------------------------------------------ translation

def test_comparative_leaf_translates_to_comparative_periods_declaration():
    cand = g.express_candidate(item_for(comparative_leaf()), comparative_leaf(), recorded_at=T0)
    assert cand["status"] == "expressible"
    assert cand["key"] == "comparative_periods" and cand["applies_to"] is None
    assert cand["temporal_scope"] == [Q4]
    assert cand["value"]["null_or_empty_period"] == "comparative"
    entry = cand["entry"]
    assert entry["author"] == "census" and entry["status"] == "derived"
    assert entry["valid_from"] is None and entry["valid_to"] is None  # scope kept apart


def test_embedded_date_selector_is_separated_by_the_parser_not_stripped():
    body = rule("report_date = '2025-06-30' AND (" + AFF_PRED + ")", [Q2])
    cand = g.express_candidate(item_for(body), body, recorded_at=T0)
    assert cand["status"] == "expressible"
    assert cand["temporal_scope"] == [Q2]
    assert cand["applies_to"] == {"kind": "prefix", "vocabulary": [AFF]}
    assert Q2 not in json.dumps(cand["entry"]["applies_to"]) + json.dumps(cand["entry"]["value"])


@pytest.mark.parametrize("predicate, reason", [
    ("report_date >= '2025-01-01' AND " + AFF_PRED, "unparsed_temporal_clause"),
    ("bdc_dimensions_raw LIKE '%2025-06-30%'", "substring_match_no_predicate_kind"),
    ("bdc_dimensions_raw ILIKE '%Affiliated Investment%'", "substring_match_no_predicate_kind"),
    ("report_date = '2025-06-30' AND row_id IN ('ROW-1', 'ROW-2')", "row_id_pinned"),
    ("asset_category = 'CASH'", "derived_classification_predicate"),
    ("bdc_dimensions_raw = 'investmentidentifieraxis=PRG'", "exact_typed_member_no_predicate_kind"),
])
def test_unrecognised_predicates_are_not_expressible_with_reason(predicate, reason):
    body = rule(predicate, [Q2])
    cand = g.express_candidate(item_for(body), body, recorded_at=T0)
    assert cand["status"] == "not_expressible"
    assert cand["reason"] == reason


def test_value_fixes_and_row_adds_are_not_expressible():
    add = dict(rule("x", [Q2]), rule_type="row_add", action="add", positions=[{}])
    add.pop("predicate_sql")
    pinned = dict(cik=CIK, fix_class="all_pik_normalization",
                  template=dict(row_selector=dict(row_id="ROW-1"), pik_rate=14.0))
    assert g.express_candidate(item_for(add), add, recorded_at=T0)["reason"] == "row_add_no_structural_counterpart"
    assert g.express_candidate(item_for(pinned), pinned, recorded_at=T0)["reason"] == "row_pinned_value_fix"


# ------------------------------------------------------------------ origin fidelity

def test_null_and_empty_periods_match_the_actual_raw_staging_applier():
    frame = raw([("A", 1, Q4, "c1"), ("B", 2, None, "c2"), ("C", 3, "", "c3"),
                 ("D", 4, "2024-12-31", "c4"), ("E", 0, "2024-12-31", "c5")])
    body = comparative_leaf()
    cand = g.express_candidate(item_for(body), body, recorded_at=T0)
    original = g.original_selection(item_for(body), body, frame)
    assert sorted(frame.loc[frame[g.RID].isin(original["rids"]), "src_context_id"]) == ["c2", "c3", "c4", "c5"]
    result = g.compare_effects(frame, original, g.candidate_selection(cand, frame, cik=CIK), stage="staging")
    assert result["fidelity"] is True
    assert result["original_keys"] == result["candidate_keys"]


def test_partial_origin_overlap_is_not_fidelity():
    dims = ["investmentidentifieraxis=" + AFF + " X", "otheraxis=Y|investmentidentifieraxis=" + AFF + " Z",
            "investmentidentifieraxis=Plain"]
    frame = staged([(AFF + " X", 10.0, "c1"), (AFF + " Z", 20.0, "c2"), ("Plain", 5.0, "c3")], dims=dims)
    body = rule(AFF_PRED, [Q2])
    cand = g.express_candidate(item_for(body), body, recorded_at=T0)
    original = g.original_selection(item_for(body), body, frame)
    result = g.compare_effects(frame, original, g.candidate_selection(cand, frame, cik=CIK), stage="unified")
    assert result["fidelity"] is False
    assert result["overlap"] == 1 and result["only_candidate"] == [[ACC, "c2"]]


def test_offsetting_errors_with_equal_aggregate_still_fail_fidelity():
    frame = staged([("A", 10.0, "c1"), ("B", 10.0, "c2"), ("C", 7.0, "c3")])
    rids = dict(zip(frame["src_context_id"], frame[g.RID]))
    original = dict(action="exclude", rids=[rids["c1"]], value_changes=0, additions=0)
    candidate = dict(action="exclude", rids=[rids["c2"]])
    result = g.compare_effects(frame, original, candidate, stage="unified")
    assert result["selected_fv_original"] == result["selected_fv_candidate"]
    assert result["fidelity"] is False


def test_zero_fv_wrong_deletion_is_detected_at_origin():
    frame = staged([(AFF + " X", 10.0, "c1"), (AFF + " Y", 0.0, "c2")],
                   dims=["investmentidentifieraxis=" + AFF + " X", "axis2=q|investmentidentifieraxis=" + AFF + " Y"])
    body = rule(AFF_PRED, [Q2])
    cand = g.express_candidate(item_for(body), body, recorded_at=T0)
    original = g.original_selection(item_for(body), body, frame)
    result = g.compare_effects(frame, original, g.candidate_selection(cand, frame, cik=CIK), stage="unified")
    assert result["selected_fv_original"] == result["selected_fv_candidate"]  # aggregate blind
    assert result["fidelity"] is False and result["only_candidate"] == [[ACC, "c2"]]


def test_already_deleted_origin_rows_make_the_frame_unrecoverable():
    body = rule(AFF_PRED, [Q2])
    corrected = published(dup_quarter(Q2))  # the correction already ran: nothing to select
    provider = g.StaticProvider({(CIK, Q2, "unified"): g.with_rids(corrected)})
    out = g.graduate_item(item_for(body), body, provider, anchors={}, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "insufficient_evidence"
    assert out["cause"] == "origin_rows_absent"


def test_candidate_keeps_the_per_cik_restriction():
    other = staged([(AFF + " X", 5.0, "c9")], cik="0000000002")
    frame = g.with_rids(pd.concat([dup_quarter(Q2).drop(columns=[g.RID]), other.drop(columns=[g.RID])],
                                  ignore_index=True))
    body = rule(AFF_PRED, [Q2])
    cand = g.express_candidate(item_for(body), body, recorded_at=T0)
    selected = g.candidate_selection(cand, frame, cik=CIK)
    assert frame.loc[frame[g.RID].isin(selected["rids"]), "cik"].tolist() == [CIK]
    original = g.original_selection(item_for(body), body, frame)
    assert g.compare_effects(frame, original, selected, stage="unified")["fidelity"] is True


# ------------------------------------------------------------------ witnesses

def test_equal_fv_distinct_tranches_are_not_merged_into_a_witness():
    frame = staged([("Debt Securities Aerospace Navistar Defense, LLC Super Senior Revolver", 100.0, "c1"),
                    (AFF + " AGY Holdings Corp. Term Loan - 16.08% inc PIK", 100.0, "c2")])
    cand = g.express_candidate(item_for(rule(AFF_PRED, [Q1])), rule(AFF_PRED, [Q1]), recorded_at=T0)
    sel = g.candidate_selection(cand, frame, cik=CIK)
    w = g.gather_witnesses(cand, frame, sel["rids"])
    assert w["missing"] == 1 and w["witnessed"] == 0


def test_duplicate_views_need_one_counterpart_each():
    frame = staged([("Debt Securities AGY Holdings Corp. Term Loan", 50.0, "c1"),
                    (AFF + " AGY Holdings Corp. Term Loan", 50.0, "c2"),
                    (AFF + " AGY Holdings Corp. Term Loan", 50.0, "c3")])
    cand = g.express_candidate(item_for(rule(AFF_PRED, [Q1])), rule(AFF_PRED, [Q1]), recorded_at=T0)
    w = g.gather_witnesses(cand, frame, g.candidate_selection(cand, frame, cik=CIK)["rids"])
    assert w["witnessed"] == 1 and w["missing"] == 1


# ------------------------------------------------------------------ classes

def _dup_provider(quarters, *, anchored, extra=None):
    frames, pubs = {}, {}
    for q in quarters:
        frame = dup_quarter(q, extra=(extra or {}).get(q, ()))
        frames[(CIK, q, "unified")] = frame
        pubs[(CIK, q)] = published(frame)
    anchors = {(CIK, q): anchor(q, float(pubs[(CIK, q)]["fair_value"].sum())) for q in anchored}
    return g.StaticProvider(frames, published=pubs), anchors


def test_positive_duplicate_view_case_generalises():
    provider, anchors = _dup_provider([Q1, Q2, Q3], anchored=[Q2, Q3])
    body = rule("report_date = '2025-03-31' AND (" + AFF_PRED + ")", [Q1])
    out = g.graduate_item(item_for(body), body, provider, anchors=anchors, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "generalises", out
    assert [h["status"] for h in out["holdouts"]] == ["supported", "supported"]


def test_two_supported_plus_one_unknown_quarter_is_insufficient():
    provider, anchors = _dup_provider([Q1, Q2, Q3, Q4], anchored=[Q2, Q3])
    body = rule(AFF_PRED, [Q1])
    out = g.graduate_item(item_for(body), body, provider, anchors=anchors, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "insufficient_evidence"
    assert "no_anchor" in out["causes"]


def test_zero_fv_selected_without_witness_blocks_generalisation():
    zero = ((AFF + " Orphan Holdco Class A Units", 0.0, "c7"),)
    provider, anchors = _dup_provider([Q1, Q2, Q3], anchored=[Q2, Q3], extra={Q3: zero})
    body = rule(AFF_PRED, [Q1])
    out = g.graduate_item(item_for(body), body, provider, anchors=anchors, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "insufficient_evidence" and "missing_witness" in out["causes"]
    q3 = [h for h in out["holdouts"] if h["quarter"] == Q3][0]
    assert q3["zero_fv_unwitnessed"] == 1


def test_currency_and_basis_mismatch_are_insufficient():
    provider, anchors = _dup_provider([Q1, Q2, Q3], anchored=[Q2, Q3])
    pub = provider.published[(CIK, Q3)]
    pub.loc[:, "fair_value_currency"] = "EUR"
    anchors[(CIK, Q2)] = dict(anchors[(CIK, Q2)], basis=None)
    body = rule(AFF_PRED, [Q1])
    out = g.graduate_item(item_for(body), body, provider, anchors=anchors, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "insufficient_evidence"
    assert {"anchor_basis_unresolved", "currency_not_comparable"} <= set(out["causes"])


def test_filer_total_contradicted_by_candidate_is_conflicts():
    provider, anchors = _dup_provider([Q1, Q2, Q3], anchored=[Q2, Q3])
    # Q3: production keeps the affiliated row (anchor = total WITH it), so deleting it breaks the total.
    frame = provider.frames[(CIK, Q3, "unified")]
    provider.published[(CIK, Q3)] = frame.drop(columns=[g.RID]).reset_index(drop=True)
    anchors[(CIK, Q3)] = anchor(Q3, float(frame["fair_value"].sum()))
    body = rule(AFF_PRED, [Q1])
    out = g.graduate_item(item_for(body), body, provider, anchors=anchors, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "conflicts"


def test_quarter_bound_needs_assessed_empty_holdouts():
    provider, anchors = _dup_provider([Q1], anchored=[])
    provider.frames[(CIK, Q2, "unified")] = staged([("Plain Co Term Loan", 1.0, "c1")], rd=Q2)
    provider.published[(CIK, Q2)] = published(provider.frames[(CIK, Q2, "unified")])
    body = rule(AFF_PRED, [Q1])
    out = g.graduate_item(item_for(body), body, provider, anchors=anchors, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "quarter_bound"


def test_all_quarters_rule_has_no_holdout():
    provider, anchors = _dup_provider([Q1, Q2], anchored=[Q2])
    body = rule(AFF_PRED, ["all"])
    out = g.graduate_item(item_for(body), body, provider, anchors=anchors, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "insufficient_evidence"
    assert out["cause"] == "no_holdout_all_quarters_rule"


def test_positive_comparative_case_generalises_with_date_witnesses():
    frames, pubs = {}, {}
    for q, prior in ((Q2, Q1), (Q3, Q2), (Q4, Q3)):
        frame = raw([("A", 10, q, "a" + q), ("A", 9, prior, "p" + q), ("B", 0, prior, "z" + q)], rd=q)
        frames[(CIK, q, "staging")] = frame
        pubs[(CIK, q)] = staged([("A", 10.0, "a" + q)], rd=q).drop(columns=[g.RID])
    anchors = {(CIK, q): anchor(q, 10.0) for q in (Q2, Q3)}
    provider = g.StaticProvider(frames, published=pubs)
    body = comparative_leaf(rd=Q4)
    out = g.graduate_item(item_for(body), body, provider, anchors=anchors, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "generalises", out
    assert all(h["witnessed"] == 2 for h in out["holdouts"])  # zero-FV prior row included


def test_comparative_null_period_in_holdout_has_no_witness():
    frames, pubs = {}, {}
    for q, period in ((Q2, Q1), (Q3, None), (Q4, Q3)):
        frames[(CIK, q, "staging")] = raw([("A", 10, q, "a" + q), ("A", 9, period, "p" + q)], rd=q)
        pubs[(CIK, q)] = staged([("A", 10.0, "a" + q)], rd=q).drop(columns=[g.RID])
    anchors = {(CIK, q): anchor(q, 10.0) for q in (Q2, Q3)}
    body = comparative_leaf(rd=Q4)
    out = g.graduate_item(item_for(body), body, g.StaticProvider(frames, published=pubs),
                          anchors=anchors, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "insufficient_evidence" and "missing_witness" in out["causes"]


def test_unified_transform_effect_difference_blocks_origin_fidelity():
    frame = dup_quarter(Q2)
    body = rule(AFF_PRED, [Q2])
    reference = published(frame)
    reference.loc[0, "fair_value"] = 99.0  # not explained by any live correction
    check = g.unified_transform_effect(frame, reference, cik=CIK, corrections=[], rules=[body])
    assert check["ok"] is False and check["attributed"]["fv_differences"] == 1
    assert check["literal"]["staged_only_keys"] == 1  # the literal (no replay) view differs too
    provider = g.StaticProvider({(CIK, Q2, "unified"): frame}, checks={(CIK, Q2): check})
    out = g.graduate_item(item_for(body), body, provider, anchors={}, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "insufficient_evidence" and out["cause"] == "unified_transform_effect"


def test_unified_transform_effect_attributes_live_corrections():
    frame = dup_quarter(Q2)
    body = rule(AFF_PRED, [Q2])
    check = g.unified_transform_effect(frame, published(frame), cik=CIK, corrections=[], rules=[body])
    assert check["ok"] is True
    assert check["literal"]["equal"] is False and check["attributed"]["equal"] is True


def test_unified_transform_effect_replays_only_what_production_applies_to_that_quarter():
    frame = dup_quarter(Q2)
    add = dict(rule("x", [Q3], rule_id="add_q3"), rule_type="row_add", action="add",
               positions=[dict(report_date=Q3, fair_value=5.0, bdc_dimensions_raw="investmentidentifieraxis=New",
                               bdc_investment_identifier="New", issuer_name="New", source_row_id="s1")])
    add.pop("predicate_sql")
    pinned = dict(cik=CIK, fix_class="all_pik_normalization", scope=dict(quarters=[Q3]),
                  template=dict(row_selector=dict(row_id="ROW-0000000000000000"), cash_rate=0.0,
                                pik_rate=14.0, set_interest_to_cash=True))
    check = g.unified_transform_effect(frame, published(frame), cik=CIK, corrections=[pinned],
                                       rules=[rule(AFF_PRED, [Q2]), add])
    assert check["ok"] is True, check
    assert check["replayed"] == dict(corrections=[], rules=["dup_rule"])


def test_heavy_reconstruction_is_insufficient_and_not_executed():
    calls = []

    def stager(frame, raw_exclusions, cache_dir):
        calls.append(len(frame))
        raise AssertionError("heavy staging must not run")

    big = pd.DataFrame(dict(cik=[CIK] * 9000, report_date=[Q2] * 9000, period=[Q2] * 9000,
                            accession_number=[ACC] * 9000, src_context_id=[str(i) for i in range(9000)],
                            fair_value=["1"] * 9000, fair_value_unit=["U_USD"] * 9000))
    provider = g.SliceProvider(raw_frames={(CIK, Q2): big}, reference={}, stager=stager,
                               corrections=[], rules_by_cik={}, cache_dir=None)
    got = provider.frame(CIK, Q2, "unified")
    assert got["status"] == "unavailable" and got["cause"] == "heavy_reconstruction_not_executed"
    assert got["lease"]["requires_lease"] is True and calls == []
    body = rule(AFF_PRED, [Q2])
    out = g.graduate_item(item_for(body), body, provider, anchors={}, band_pct=0.5, recorded_at=T0)
    assert out["class"] == "insufficient_evidence" and out["cause"] == "heavy_reconstruction_not_executed"


def test_yield_summary_counts_every_class_per_cik_and_fix_class():
    results = [dict(item_id="a", cik=CIK, fix_class="row_exclusion", **{"class": "generalises"}, cause=None),
               dict(item_id="b", cik=CIK, fix_class="row_add", **{"class": "not_expressible"},
                    reason="row_add_no_structural_counterpart", cause=None),
               dict(item_id="c", cik="0000000002", fix_class="row_exclusion",
                    **{"class": "insufficient_evidence"}, cause="no_anchor")]
    summary = g.yield_summary(results, denominator=3)
    assert summary["overall"] == dict(generalises=1, quarter_bound=0, conflicts=0,
                                      insufficient_evidence=1, not_expressible=1)
    assert summary["per_fix_class"]["row_exclusion"]["insufficient_evidence"] == 1
    assert summary["insufficient_evidence_causes"] == {"c": "no_anchor"}
    with pytest.raises(ValueError):
        g.yield_summary(results, denominator=4)


# ------------------------------------------------------------------ inventory (tracked overrides)

def test_correction_inventory_uses_the_loader_contract_and_excludes_retired():
    code_root = Path(__file__).resolve().parents[1]
    inv = g.correction_inventory(code_root)
    ids = [i["item_id"] for i in inv["items"]]
    assert len(ids) == len(set(ids)) == inv["denominator"]
    assert all("/_" not in i["path"] and ".proposed." not in i["path"] for i in inv["items"])
    assert any(e["reason"] == "proposed_or_retired" for e in inv["excluded"])
    for entry in inv["items"]:
        assert g.sha256_file(code_root / entry["path"]) == entry["sha256"]


# ------------------------------------------------------------------ cached slices

@pytest.mark.needs_cache
def test_real_tcw_quarter_stages_and_attributes_live_corrections():
    data_root = os.environ.get("PROFILE_PILOT_DATA_ROOT")
    if not data_root:
        pytest.skip("PROFILE_PILOT_DATA_ROOT not set (run through the pilot launcher)")
    code_root = Path(__file__).resolve().parents[1]
    tcw, quarter = "0001715933", "2025-06-30"
    inv = g.correction_inventory(code_root)
    corrections, rules = g.live_bodies(code_root, inv, cik=tcw)
    raw_q, ref_q = g.read_output_slice(Path(data_root) / "output", tcw, quarter)
    provider = g.SliceProvider(raw_frames={(tcw, quarter): raw_q}, reference={(tcw, quarter): ref_q},
                               stager=g.production_stager, corrections=corrections,
                               rules_by_cik={tcw: rules}, cache_dir=None)
    got = provider.frame(tcw, quarter, "unified")
    assert got["status"] == "ok" and got["lease"]["requires_lease"] is False
    literal, attributed = got["check"]["literal"], got["check"]["attributed"]
    assert literal["staged_only_keys"] > 0  # the live exclusions explain the literal gap ...
    assert (attributed["staged_only_keys"], attributed["reference_only_keys"],
            attributed["fv_differences"]) == (0, 0, 0)  # ... once replayed through production
    # Whatever remains (e.g. added rows whose identifiers differ from an older reference
    # build) is reported and gates the quarter; it is never hidden.
    assert got["check"]["ok"] is attributed["equal"]
