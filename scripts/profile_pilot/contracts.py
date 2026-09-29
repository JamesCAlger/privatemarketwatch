"""Task 8: partitioned contracts learned from Q1, frozen, then evaluated on Q2 (spec 6.3, 9: M2).

Order (spec 6.3 / s8): (1) the tolerance table is frozen (`freeze_tolerances`, write-once,
Task 1 mechanism) before anything is learned; (2) `learn_contracts` reads ONLY the Q1
census, the Q1 profile, the authored grammar and the Q1 yield evidence, and learns every
contract inside the partitions evidenced in Q1; (3) `freeze_contracts` writes the full
fixed denominator (one contract per cik x field x partition x kind, with its learned
expectation and its band) before any Q2 census is parsed; (4) `evaluate_contracts` takes
the FROZEN inventory block and the FROZEN tolerance content (never SPEC_BANDS, which is
used only to write the tolerance file) and the Q2 observations; a missing frozen field
raises ContractError (fail closed); (5) `summarise_m2`.

Minimal suite, exactly: source_concept_set, fill_rate, scale, format_grammar, value_range,
fund_income_yield. Deferred and unchecked: non-accrual count, footnote-location,
position-identity. Every contract ends in exactly one of holds, holds_with_form_type,
breach, insufficient_evidence. holds_with_form_type is unreachable by construction here
(ruling R29): a form qualifier cannot be evidenced from one learning quarter, and a
10-Q/10-K change grants no tolerance relief; results are split by Q2 form type instead.

Partitions: predicates come from Q1 `evidenced_partition` detector outcomes (and any Q1
profile entry with a non-null applies_to); rows are routed with envelope.resolve_for_row
(partition-specific before the null partition; equally specific matches are ambiguous and
never picked). With no evidenced partition every contract is whole-filing (applies_to
null). An unresolved mixed identifier format (partition candidate / insufficient with a
real signature) blocks the identifier format contract: it is insufficient_evidence, not a
default whole-filing grammar contract.

Scale is the declared unit plus a deterministic conversion to percent (pure x100,
percent x1, bps /100). Namespace never identifies scale; magnitude is used ONLY to abstain
(mixed magnitudes under one declared unit, or a changed magnitude regime), never to assign
a scale. Stage B note (R28): Q2 "interpreted rows" are the Q2 census positions; Stage C
re-measures on interpreted rows. A `holds` records agreement with Q1; it proves nothing
about correctness.
"""
from __future__ import annotations

import copy

from scripts.profile_pilot import envelope
from scripts.profile_pilot.census import POSITION_FIELDS, POSITION_RATE, field_channel
from scripts.profile_pilot.contracts_observe import (  # noqa: F401  (current_positions, grammar_info re-exported)
    IDENTIFIER_FIELD, RATIO_CLASSES, SCALE_CONVENTIONS, UNIT_NOT_OBSERVABLE, WHOLE_FILING, as_grammars, canonical, channel_gaps,
    current_positions, grammar_for, grammar_info, grammar_observation, learn_partitions, observe_composition,
    observe_field, observe_text, quantile, route, routing_rows, widened)

CONTRACTS_VERSION = "contracts.v0.2"
CONTRACTS_VERSION_V3 = "contracts.v0.3"
TOLERANCES_VERSION = "contract-tolerances.v3"
TOLERANCES_VERSION_V2 = "contract-tolerances.v2"
V1_RUN_ID = "stageb-contracts-20260929t032414z"
V2_RUN_ID = "stageb-contracts-20260929t053506z"
IDENTIFIER_FORMAT_INTERPRETATION = (
    "as-evaluated: an unresolved mixed identifier format in Q1 (partition candidate / insufficient_evidence "
    "with a real signature) blocks only the identifier format contract; concept, fill, scale and range stay "
    "whole-filing (controller-directed reading of spec 6.3). strict 6.3 ('apply those predicates to Q2 rows "
    "before computing every expectation'; 'a mixed format without an evidenced discriminator is unresolved, "
    "not a default whole-filing contract'): every row-level contract of such a CIK is insufficient_evidence/"
    "identifier_format_unresolved; the fund-level yield contract is not row-partitioned and is unaffected. "
    "M2 is published both ways; each result carries identifier_format_unresolved.")
KINDS = ("source_concept_set", "fill_rate", "scale", "value_range", "format_grammar", "fund_income_yield")
STATUSES = ("holds", "holds_with_form_type", "breach", "insufficient_evidence")
CONCEPT_FIELDS = POSITION_FIELDS
SCALE_FIELDS = POSITION_RATE + ("pct_of_net_assets",)
RANGE_FIELDS = POSITION_RATE
YIELD_FIELD = "interest_rate"
LOW_HISTORY_BELOW = 50
SPEC_TABLE = [
    dict(expectation="source concept set", standard="identical set", low_history="identical set"),
    dict(expectation="fill rate", standard="+/- 10 percentage points", low_history="+/- 25 percentage points"),
    dict(expectation="scale", standard="identical", low_history="identical"),
    dict(expectation="value range (rates, spreads)", standard="Q2 p5-p95 inside Q1 min-max widened by 25%",
         low_history="same, widened by 50%"),
    dict(expectation="format grammar", standard="every Q2 identifier parses", low_history=">= 90% parse")]
SPEC_BANDS = {
    "standard": dict(source_concept_set="identical", fill_rate_pp=10, scale="identical", value_range_widen=0.25,
                     value_range_quantiles=[0.05, 0.95], format_grammar_min_parse_share=1.0),
    "low_history": dict(source_concept_set="identical", fill_rate_pp=25, scale="identical", value_range_widen=0.5,
                        value_range_quantiles=[0.05, 0.95], format_grammar_min_parse_share=0.9)}
KIND_BAND_KEYS = {"source_concept_set": ("source_concept_set",), "fill_rate": ("fill_rate_pp",),
                  "scale": ("scale",), "value_range": ("value_range_widen", "value_range_quantiles"),
                  "format_grammar": ("format_grammar_min_parse_share",), "fund_income_yield": (),
                  "rate_composition": ("share_pp", "iqr_widen", "min_rows"),
                  "text_agreement": ("text_share_pp", "min_rows", "min_parse_share")}
# ---- Task B2-3 (tolerances v3): two semantic kinds, learned per partition after the v2 suite.
SEMANTIC_KINDS = ("rate_composition", "text_agreement")
ALL_KINDS = KINDS + SEMANTIC_KINDS
COMPOSITION_FIELD = "interest_rate-basis_spread"
TEXT_FIELD = "investment_identifier-rate_text"
SEMANTIC_BAND_KEYS = ("share_pp", "iqr_widen", "text_share_pp", "min_rows", "min_parse_share")
SEMANTIC_CONSTANTS = dict(
    max_unresolved_pair_share=0.5, text_match_tolerance_pct=0.011,
    rule="fixed operational constants (not swept): a composition abstains when unresolved pair rows exceed "
         "max_unresolved_pair_share of the pair rows (addendum 1); text and numeric agree within "
         "text_match_tolerance_pct percentage points (the owner-session census tolerance)")
# The v3 bands. IN-SAMPLE: chosen after the Stage B Q2 censuses, the seeded drift of B2-1 and the
# recorded history of B2-2b were read; see CALIBRATION.
SEMANTIC_BANDS = {"standard": dict(share_pp=15, iqr_widen=3.0, text_share_pp=5, min_rows=10, min_parse_share=0.5),
                  "low_history": dict(share_pp=15, iqr_widen=3.0, text_share_pp=5, min_rows=10, min_parse_share=0.5)}


def _joint(rows) -> list:
    return [dict(value="s%s_i%s" % (s, i), seeded_detection_fraction=d, negatives_breach_rate=r, negatives_n=96,
                 negatives_breach_rate_per_criterion=dict(share=sh, iqr=iq, fixed=fx))
            for s, i, d, r, sh, iq, fx in rows]


def _curve(rows, n) -> list:
    return [dict(value=v, seeded_detection_fraction=d, negatives_breach_rate=r, negatives_n=n) for v, d, r in rows]


_CAL_OK = "smallest candidate meeting both criteria"
CALIBRATION = dict(
    label="in-sample (bands chosen after Q2 and the history were read)",
    rule=("per CONTRACT (fix round 1, review I1): rate_composition is chosen on the joint share_pp x iqr_widen grid as "
          "the smallest point (ordered by share_pp, then iqr_widen) whose COMPOSITION-CONTRACT breach rate on negatives "
          "(upper bound, rolling / as-evaluated) is <= 10% and whose seeded detection fraction for spread_for_coupon is "
          "<= 0.30; text_agreement on text_share_pp by the same rule (target text_numeric_divergence). One tier basis "
          "for every band: pooled (all CIKs and tiers; both tiers take the chosen value). None = uncalibrated; no v2 "
          "band is widened. Per-criterion rates (share, iqr, fixed) are recorded, never used to choose"),
    tier_basis="pooled",
    seed_run_id="stageb2-seed-v3-20260929t141107z", backtest_run_id="stageb2-backtest-v3-20260929t141328z",
    code_head="6a2aeb5",
    bands={
        "rate_composition": dict(
            target="spread_for_coupon", status="calibrated", chosen=dict(share_pp=15, iqr_widen=3.0), reason=_CAL_OK,
            curve=_joint((
                (5, 1.5, 0.05, 0.1667, 0.0208, 0.1354, 0.0208), (5, 2.0, 0.05, 0.1458, 0.0208, 0.1146, 0.0208),
                (5, 3.0, 0.05, 0.1146, 0.0208, 0.0833, 0.0208), (10, 1.5, 0.1, 0.1667, 0.0208, 0.1354, 0.0208),
                (10, 2.0, 0.1, 0.1458, 0.0208, 0.1146, 0.0208), (10, 3.0, 0.1, 0.1146, 0.0208, 0.0833, 0.0208),
                (15, 1.5, 0.2, 0.1458, 0.0208, 0.1354, 0.0), (15, 2.0, 0.2, 0.125, 0.0208, 0.1146, 0.0),
                (15, 3.0, 0.2, 0.0938, 0.0208, 0.0833, 0.0), (20, 1.5, 0.2, 0.1354, 0.0104, 0.1354, 0.0),
                (20, 2.0, 0.2, 0.1146, 0.0104, 0.1146, 0.0), (20, 3.0, 0.2, 0.0833, 0.0104, 0.0833, 0.0),
                (25, 1.5, 0.3, 0.1354, 0.0104, 0.1354, 0.0), (25, 2.0, 0.3, 0.1146, 0.0104, 0.1146, 0.0),
                (25, 3.0, 0.3, 0.0833, 0.0104, 0.0833, 0.0)))),
        "text_share_pp": dict(target="text_numeric_divergence", status="calibrated", chosen=5, reason=_CAL_OK,
                              curve=_curve(((5, 0.05, 0.0753), (10, 0.1, 0.0645), (15, 0.2, 0.0645), (20, 0.2, 0.0538),
                                            (25, 0.3, 0.043)), 93))},
    fixed_not_swept=dict(min_rows=10, min_parse_share=0.5, note="floors, not calibrated"),
    consequence=("at share_pp 15 the fixed_coupon_in_spread criterion does not fire on the BCRED 2022-09-30 -> "
                 "2022-12-31 fixed-bond sleeve (a ~10 pp move); it fires at share_pp 5 and 10 only"),
    median_shift_experiment=dict(adopted=False, note="calibration-only (addendum 3); curves in the back-test root"))

SUPERSEDED_V3 = dict(run_id="stageb2-contracts-v3-20260929t124944z",
                     content_sha256="9ebef3466953375884cbd3603d20fa6aeb1d6e106337e55ecc29314cf4a505e9",
                     reason="calibration rule applied per contract; R38 fixed/floating split")

V3_REASON = ("adds rate_composition and text_agreement (owner ask 2026-09-29, M2 assessment); bands calibrated "
             "in-sample on B2-1 seeds and B2-2b negatives")
NEWLY_ABSTAINED_RULE = (
    "a reporting flag inside the existing status model, not a fifth status: newly_abstained is true when a "
    "contract that was decided on the learning side (learned, i.e. it held on the learning quarter) or holds/"
    "breach in the prior pair (rolling mode) evaluates to insufficient_evidence; the four statuses are unchanged")
DEFERRED = [dict(kind="non_accrual_count", status="unchecked", reason="deferred by the minimal-suite ruling"),
            dict(kind="footnote_location", status="unchecked", reason="deferred; footnote channel unsupported"),
            dict(kind="position_identity", status="unchecked", reason="deferred by the minimal-suite ruling")]
STAGE_B_NOTE = ("Stage B (ruling R28): Q2 interpreted rows are the Q2 census positions (canonical field values, "
                "raw values, units, decimals) plus identifier strings; the yield contract uses the pinned "
                "production slices through S2 (inherited evidence). Stage C re-measures on interpreted rows.")
HOLDS_WITH_FORM_TYPE_REASON = ("unreachable by construction (ruling R29): one learning quarter cannot evidence a "
                               "form-type qualifier; a 10-Q/10-K change grants no tolerance relief. Results are "
                               "split by Q2 form type instead.")
CLAIM = "A holds records agreement with the frozen Q1 expectation; it is not a correctness claim."


class ContractError(RuntimeError):
    """A frozen artifact is missing a field or disagrees with itself: fail closed."""


def _req(mapping, key, where: str):
    if not isinstance(mapping, dict) or key not in mapping:
        raise ContractError("frozen " + where + " is missing " + repr(key))
    return mapping[key]


# ---------------------------------------------------------------- tolerances (frozen first)

def tolerance_content() -> dict:
    """The current tolerance file: v3 = the v2 content verbatim + the two semantic kinds' bands."""
    return semantic_tolerances(tolerance_content_v2(), bands=SEMANTIC_BANDS, calibration=CALIBRATION)


def semantic_tolerances(v2: dict, *, bands: dict | None = None, share_pp=None, iqr_widen=None, text_share_pp=None,
                        min_rows=10, min_parse_share=0.5, calibration: dict | None = None) -> dict:
    """v3 content from a v2 content (the frozen file's, or tolerance_content_v2()): every v2 band and
    section verbatim, plus the semantic bands. Calibration passes one candidate per call (both tiers
    take the candidate unless a per-tier dict is given); the frozen v3 file uses SEMANTIC_BANDS."""
    from scripts.profile_pilot import manifest
    if v2.get("version") != TOLERANCES_VERSION_V2:
        raise ContractError("semantic tolerances extend only the v2 content, got " + repr(v2.get("version")))
    if bands is None:
        tier_value = lambda value, tier: value[tier] if isinstance(value, dict) else value
        bands = {tier: dict(share_pp=tier_value(share_pp, tier), iqr_widen=tier_value(iqr_widen, tier),
                            text_share_pp=tier_value(text_share_pp, tier), min_rows=min_rows,
                            min_parse_share=min_parse_share) for tier in ("standard", "low_history")}
    out = copy.deepcopy(v2)
    for tier in ("standard", "low_history"):
        extra = {k: _req(bands[tier], k, "semantic bands." + tier) for k in SEMANTIC_BAND_KEYS}
        if set(extra) & set(out["bands"][tier]):
            raise ContractError("a semantic band would overwrite a v2 band")
        out["bands"][tier].update(extra)
    out["version"] = TOLERANCES_VERSION
    out["operationalisation"].update(
        rate_composition=(
            "field pair interest_rate / basis_spread on rows carrying both (a 0 rate is an undrawn placeholder, "
            "counted apart); implied base = canonical(rate) - canonical(spread) in percent, magnitude resolved PER "
            "ROW (same magnitude class, or declared ratio units that differ, compute; otherwise unresolved_pair); "
            "NOT gated on the scale contract. Learn share_rate_le_spread (implied base <= 0), p25/p50/p75, n. "
            "Breach when |share - learned| * 100 > share_pp, or when the IQR exceeds learned IQR x iqr_widen. The "
            "level of the implied base is never a criterion (p50_shift is evidence). Abstain when n < min_rows or "
            "unresolved pair rows exceed max_unresolved_pair_share in either quarter. Violating keys: rows with "
            "implied base <= 0 (share) and rows farther than iqr_widen x learned IQR from the Q2 median (dispersion)"),
        text_agreement=(
            "identifier text parsed with the filer's authored grammar (inherited, hash pinned) where one applies to "
            "the partition, else the generic patterns (contracts_observe RE_BASE_PLUS_PCT / RE_BASE_PLUS_BPS / "
            "RE_PCT). Numeric values are canonical percent under the declared unit. Denominator of the parse share = "
            "non-label identifier rows carrying a filled numeric interest_rate or basis_spread. Shares per row "
            "category: spread_text_matches_numeric, rate_equals_text_spread (0 rates on undrawn/unfunded rows "
            "excluded and counted), rate_equals_text_pct. Breach when a share assessed on both sides moves by more "
            "than text_share_pp; a share with n < min_rows on either side is not assessed; abstain when no share is "
            "assessable or the parse share < min_parse_share. Violating keys: rows on the side the share moved to"),
        newly_abstained=NEWLY_ABSTAINED_RULE,
        inception=("both semantic kinds record an inception block on the LEARNING quarter (share_rate_le_spread, "
                   "rate_equals_text_spread share, implied base p50): evidence, not a contract status"))
    out["semantic_constants"] = copy.deepcopy(SEMANTIC_CONSTANTS)
    out["v2_verbatim"] = copy.deepcopy(v2)
    out["v2_content_sha256"] = manifest.digest(v2)
    out["supersedes"] = dict(version=TOLERANCES_VERSION_V2, run_id=V2_RUN_ID, reason=V3_REASON,
                             v2_results="unchanged: v2 contract ids, expectations and results are byte-for-byte "
                                        "the v2 run's; only the newly_abstained flag and its summary line are added")
    out["supersedes"]["superseded_v3"] = copy.deepcopy(SUPERSEDED_V3)
    out["calibration"] = copy.deepcopy(calibration if calibration is not None else CALIBRATION)
    return out


def has_semantic_bands(tolerances: dict) -> bool:
    return "share_pp" in (((tolerances or {}).get("bands") or {}).get("standard") or {})


def semantic_constants(tolerances: dict) -> dict:
    section = _req(tolerances, "semantic_constants", "tolerances")
    return {k: _req(section, k, "tolerances.semantic_constants") for k in
            ("max_unresolved_pair_share", "text_match_tolerance_pct")}


def rebanded_block(block: dict, tolerances: dict) -> dict:
    """Calibration only: the same learned block with the semantic contracts' bands taken from a
    candidate tolerance content (expectations are band-free; the v2 contracts are untouched)."""
    out = dict(block, contracts=[dict(c, band=band_for(tolerances, c["tier"], c["kind"]))
                                 if c["kind"] in SEMANTIC_KINDS else c for c in block["contracts"]])
    return out


def tolerance_content_v2() -> dict:
    """The frozen v2 content, reproduced exactly (its digest is the frozen bf15c296...)."""
    from scripts.profile_pilot.contracts_income import S2_FUNCTION, s2_constants
    return dict(
        version=TOLERANCES_VERSION_V2, source="docs/superpowers/specs/2026-09-28-filer-profile-pilot-design.md s6.3",
        spec_table_verbatim=copy.deepcopy(SPEC_TABLE), bands=copy.deepcopy(SPEC_BANDS),
        low_history_below_positions=LOW_HISTORY_BELOW,
        operationalisation=dict(
            position_count="current-period (document_period_end) recognised positions in the Q1 census",
            fill_rate="filled (reported or consistent_duplicate) / positions; nil, absent and conflict are not "
                      "filled; a reported zero is filled; |Q2 - Q1| * 100 <= fill_rate_pp holds",
            source_concept_set="set of concepts carrying the filled values; identical set holds",
            scale="declared unit class (pure/percent/bps) + conversion; a changed class is a breach; mixed or "
                  "changed magnitude regime under one declared unit is insufficient_evidence",
            value_range="canonical percent values; widened = [min - w*(max-min), max + w*(max-min)] "
                        "(w*|value| each side when max == min); Q2 p5 and p95 (linear interpolation) inside "
                        "the widened Q1 range holds",
            format_grammar="authored grammar (inherited), rows whose keyword signature is in the grammar's "
                           "declared signatures; parse = every required field extracted; parse share >= band; "
                           "learned only if Q1 itself meets the band inside a non-empty scope; an unresolved mixed "
                           "identifier format in Q1 leaves it insufficient_evidence; an empty Q2 scope is a breach",
            label_rows="identifier rows matching ^(sub)?total are set aside for the format contract"),
        scale_conventions=copy.deepcopy(SCALE_CONVENTIONS),
        fund_income_yield=dict(s2_function=S2_FUNCTION, constants=s2_constants(),
                               expectation="the Q1 S2 vote (cash_leg or all_in) persists in Q2",
                               vote_rule="S2 per-quarter votes (tagged / estimated thresholds) aggregated over the "
                                         "evidence window; a side votes only with >= INCOME_MIN_QUARTERS votes and "
                                         "2x dominance (classify_cik); a one-quarter window cannot vote"),
        form_type_qualifiers=dict(evidenced=[], rule=HOLDS_WITH_FORM_TYPE_REASON),
        supersedes=dict(version="contract-tolerances.v1", run_id=V1_RUN_ID,
                        reason="evidence-limit correction, not a relaxation: v1 let one quarter's S2 vote stand as "
                               "a vote, bypassing S2's INCOME_MIN_QUARTERS limit; v2 applies the limit (frozen "
                               "constant). v1 results stay untouched as the prior result."),
        identifier_format_interpretation=IDENTIFIER_FORMAT_INTERPRETATION,
        reporting="reporting bands, not pass/fail bars; the pilot records")


def frozen_scale_conventions(tolerances: dict) -> dict:
    conventions = _req(tolerances, "scale_conventions", "tolerances")
    for cls in RATIO_CLASSES:
        entry = _req(conventions, cls, "tolerances.scale_conventions")
        _req(entry, "factor", "tolerances.scale_conventions." + cls)
        _req(entry, "canonical_unit", "tolerances.scale_conventions." + cls)
    return conventions


def frozen_min_quarters(tolerances: dict) -> int:
    section = _req(tolerances, "fund_income_yield", "tolerances")
    constants = _req(section, "constants", "tolerances.fund_income_yield")
    return int(_req(constants, "INCOME_MIN_QUARTERS", "tolerances.fund_income_yield.constants"))


def band_for(tolerances: dict, tier: str, kind: str) -> dict:
    if kind == "fund_income_yield":
        section = _req(tolerances, "fund_income_yield", "tolerances")
        return dict(s2_constants=_req(section, "constants", "tolerances.fund_income_yield"))
    bands = _req(_req(tolerances, "bands", "tolerances"), tier, "tolerances.bands")
    return {key: _req(bands, key, "tolerances.bands." + tier) for key in KIND_BAND_KEYS[kind]}


def tier_for(tolerances: dict, positions: int) -> str:
    return "low_history" if positions < _req(tolerances, "low_history_below_positions", "tolerances") else "standard"


def freeze_tolerances(paths) -> dict:
    from scripts.profile_pilot import manifest
    return manifest.freeze_inventory(paths, "contract_tolerances", tolerance_content())


# ---------------------------------------------------------------- learning (Q1 only)

def _profile_entry(entries: list, rows: list, field: str, report_date: str, form_type) -> dict | None:
    key = "column_contract." + field
    if not rows:
        return None
    hits = set()
    found = None
    sample = rows if any(e["key"] == key and e["applies_to"] is not None for e in entries) else rows[:1]
    for row in sample:
        res = envelope.resolve_for_row(entries, row, key, report_date, form_type, None)
        hits.add(res.entry["entry_id"] if res.found else None)
        found = res.entry if res.found else found
    return dict(split=True) if len(hits) > 1 else found


def _profile_disagrees(entry, obs: dict, partitioned: bool) -> str | None:
    if partitioned:
        return None
    if obs["filled"] == 0:
        return "profile has a column_contract entry for a field with no filled Q1 value" if entry else None
    if not entry or entry.get("split"):
        return "no single profile column_contract entry for a filled Q1 field"
    support = entry.get("support") or {}
    if (entry["value"] or {}).get("concepts") != obs["concepts"] or support.get("numerator") != obs["filled"] \
            or support.get("denominator") != obs["rows"]:
        return "profile concepts/support differ from the census"
    return None


def _contract(cik, kind, field, partition, tier, band, *, expectation=None, cause=None, evidence=None) -> dict:
    return dict(contract_id=":".join((cik, kind, field, partition["partition_id"])), cik=cik, kind=kind,
                field=field, partition_id=partition["partition_id"], applies_to=partition["applies_to"], tier=tier,
                band=band, learn_status="learned" if cause is None else "insufficient_evidence",
                learn_cause=cause, expectation=expectation, evidence=evidence or {})


def _learn_scale(obs: dict, gaps: list, conventions: dict) -> tuple[dict | None, str | None]:
    if gaps or obs["unobservable_keys"]:
        return None, "q1_channel_incomplete"
    if not obs["filled"]:
        return None, "no_q1_observations"
    if any(c["reason"] == "unit_differs" for c in obs["conflicts"]):
        return None, "conflicting_units_on_one_field"
    classes = list(obs["classes"])
    if UNIT_NOT_OBSERVABLE in classes:
        return None, "unit_not_observable_no_fact_index"
    if len(classes) > 1:
        return None, "mixed_declared_units_unresolved"
    if classes[0] not in RATIO_CLASSES:
        return None, "no_declared_ratio_unit"
    if len(obs["values"]) != obs["filled"]:
        return None, "unparseable_numeric_values"
    if obs["regime"] == "mixed":
        return None, "magnitude_mixed_under_one_declared_unit"
    if classes[0] == "pure" and obs["regime"] == "ge1":
        return None, "pure_values_inconsistent_with_decimal_convention"
    return dict(scale_class=classes[0], conversion=conventions[classes[0]],
                magnitude_regime=obs["regime"]), None


def _scale_evidence(obs: dict) -> dict:
    return dict(classes=obs["classes"], magnitude_regime=obs["regime"], decimals=obs["decimals"],
                filled=obs["filled"], unit_conflicts=[c for c in obs["conflicts"] if c["reason"] == "unit_differs"],
                rule="declared unit class + conversion; magnitude only ever triggers abstention")


def learn_contracts(*, cik: str, q1_doc: dict, q1_profile: dict | None, grammar: dict | None, yield_q1: dict,
                    tolerances: dict, q2_listing: dict, recorded_at: str) -> dict:
    """Every contract for one CIK from Q1 evidence only (no Q2 input exists in this signature)."""
    positions = current_positions(q1_doc)
    tier = tier_for(tolerances, len(positions))
    conventions = frozen_scale_conventions(tolerances)
    grammars = as_grammars(grammar)
    q1_date, q1_form = q1_doc["document"]["report_date"], q1_doc["document"].get("form_type")
    entries = list((q1_profile or {}).get("entries") or [])
    learned = learn_partitions(q1_doc, entries)
    partitions = learned["partitions"]
    rows = routing_rows(q1_doc, positions, grammars)
    routing = route(partitions, rows, q1_date, q1_form, recorded_at)
    by_ctx = {p["context_id"]: p for p in positions}
    rows_by_ctx = {r["context_id"]: r for r in rows}
    blocked = {pid for a in routing["ambiguous"] for pid in a["partitions"]}
    if routing["unroutable"]:
        blocked |= {p["partition_id"] for p in partitions}
    facts_by_i = {f["i"]: f for f in q1_doc["facts"]}
    contracts, partition_records, semantic = [], [], []
    semantic_on = has_semantic_bands(tolerances)
    for partition in partitions:
        pid = partition["partition_id"]
        keys = routing["routed"][pid]
        partition_records.append(dict(partition, q1_rows=len(keys)))
        if not keys and pid not in blocked:
            continue
        members = [by_ctx[k] for k in keys]
        member_rows = [rows_by_ctx[k] for k in keys]
        block_cause = "ambiguous_partition_overlap" if pid in blocked else None
        for field in CONCEPT_FIELDS:
            gaps = channel_gaps(q1_doc, ("contexts", field_channel(field)))
            obs = observe_field(q1_doc, members, field, facts_by_i)
            base = block_cause or ("q1_channel_incomplete" if gaps or obs["unobservable_keys"] else None)
            entry = _profile_entry(entries, member_rows, field, q1_date, q1_form)
            disagree = _profile_disagrees(entry, obs, learned["evidenced"])
            cause = base or ("q1_profile_disagrees_with_census" if disagree else None)
            profile_ref = dict(entry_id=(entry or {}).get("entry_id"), disagreement=disagree,
                               note="whole-filing profile entry" if not learned["evidenced"]
                               else "profile entries are whole-filing; not compared per partition")
            contracts.append(_contract(
                cik, "source_concept_set", field, partition, tier, band_for(tolerances, tier, "source_concept_set"),
                expectation=None if cause else dict(concepts=obs["concepts"]), cause=cause,
                evidence=dict(profile=profile_ref, filled=obs["filled"], rows=obs["rows"], channel_gaps=gaps)))
            contracts.append(_contract(
                cik, "fill_rate", field, partition, tier, band_for(tolerances, tier, "fill_rate"),
                expectation=None if cause else dict(fill_share=obs["fill_share"], filled=obs["filled"],
                                                    rows=obs["rows"]),
                cause=cause, evidence=dict(profile=profile_ref, absent=len(obs["absent_keys"]),
                                           nil=len(obs["nil_keys"]), conflicts=len(obs["conflicts"]),
                                           zero_values=obs["zero_values"], channel_gaps=gaps)))
            if field in SCALE_FIELDS:
                expectation, scale_cause = _learn_scale(obs, gaps, conventions)
                scale_cause = block_cause or scale_cause
                contracts.append(_contract(cik, "scale", field, partition, tier, band_for(tolerances, tier, "scale"),
                                           expectation=None if scale_cause else expectation, cause=scale_cause,
                                           evidence=_scale_evidence(obs)))
                if field in RANGE_FIELDS:
                    band = band_for(tolerances, tier, "value_range")
                    range_exp, range_cause = None, block_cause or (
                        ("scale_not_established_in_q1" if scale_cause else None))
                    if not range_cause:
                        values = sorted(v for _, v in canonical(obs["values"], expectation["scale_class"],
                                                                conventions))
                        range_exp = dict(canonical_unit="percent", scale_class=expectation["scale_class"],
                                         min=values[0], max=values[-1], n_values=len(values),
                                         widened=widened(values[0], values[-1], band["value_range_widen"]))
                    contracts.append(_contract(cik, "value_range", field, partition, tier, band,
                                               expectation=range_exp, cause=range_cause,
                                               evidence=dict(scale_learn_cause=scale_cause)))
        contracts.append(_learn_format(cik, partition, tier, tolerances, q1_doc, member_rows, grammars,
                                       learned["identifier_format"], block_cause))
        if semantic_on:
            semantic += _learn_semantic(cik, partition, tier, tolerances, q1_doc, members, grammars, facts_by_i,
                                        conventions, block_cause, q1_date)
    whole = next(p for p in partitions if p["partition_id"] == WHOLE_FILING)
    vote_ok = yield_q1.get("status") == "vote" and yield_q1.get("vote") in ("cash_leg", "all_in")
    contracts.append(_contract(
        cik, "fund_income_yield", YIELD_FIELD, whole, tier, band_for(tolerances, tier, "fund_income_yield"),
        expectation=dict(vote=yield_q1["vote"], r=(yield_q1.get("s2") or {}).get("r"),
                         src=(yield_q1.get("s2") or {}).get("src"), quarter=q1_date) if vote_ok else None,
        cause=None if vote_ok else str(yield_q1.get("cause") or "q1_yield_without_vote"),
        evidence=dict(q1_yield=yield_q1)))
    contracts += semantic
    return dict(cik=cik, version=CONTRACTS_VERSION_V3 if semantic_on else CONTRACTS_VERSION, tier=tier,
                q1=dict(report_date=q1_date, form_type=q1_form, positions=len(positions),
                        accession_number=q1_doc["document"].get("accession_number")),
                q2_listing=q2_listing, partitions=partition_records, partitions_evidenced=learned["evidenced"],
                identifier_format=learned["identifier_format"],
                routing=dict(ambiguous=routing["ambiguous"], unroutable=routing["unroutable"]),
                partition_statement=partition_statement(learned["evidenced"]),
                grammar=[dict(path=g["path"], sha256=g["sha256"], dialect=g["dialect"], signatures=g["signatures"])
                         for g in grammars] or None,
                contracts=contracts, recorded_at=recorded_at, stage_b_note=STAGE_B_NOTE)


def partition_statement(evidenced: bool) -> str:
    if evidenced:
        return "partitions evidenced in Q1; contracts are per partition (applies_to = frozen Q1 predicate)"
    return ("no evidenced partition in Q1: every contract is whole-filing (applies_to null); unresolved mixed "
            "identifier formats leave the format contract insufficient_evidence")


def _learn_format(cik, partition, tier, tolerances, q1_doc, rows, grammars, identifier_format, block_cause) -> dict:
    band = band_for(tolerances, tier, "format_grammar")
    gaps = channel_gaps(q1_doc, ("contexts", "identifiers"))
    grammar, missing = grammar_for(partition["applies_to"], grammars)
    obs = grammar_observation(rows, grammar) if grammar and not gaps else None
    if block_cause:
        cause = block_cause
    elif not grammar:
        cause = missing
    elif gaps:
        cause = "q1_channel_incomplete"
    elif identifier_format["status"] == "unresolved_mixed":
        cause = "unresolved_mixed_identifier_format"
    elif not obs["scope_rows"]:
        cause = "grammar_scope_empty_in_q1"
    elif obs["parse_share"] < band["format_grammar_min_parse_share"]:
        cause = "grammar_does_not_hold_on_q1"
    else:
        cause = None
    expectation = None if cause else dict(
        field=IDENTIFIER_FIELD, dialect=obs["dialect"], signatures=obs["signatures"],
        required_fields=obs["required_fields"], grammar_sha256=obs["grammar_sha256"],
        q1_scope_rows=obs["scope_rows"], q1_parse_share=obs["parse_share"])
    evidence = dict(obs or {}, identifier_format=identifier_format, channel_gaps=gaps)
    if not grammar:
        evidence["note"] = "delimiter structure (profile identifier_format) is not a rate grammar"
    return _contract(cik, "format_grammar", IDENTIFIER_FIELD, partition, tier, band, expectation=expectation,
                     cause=cause, evidence=evidence)


# ---------------------------------------------------------------- semantic kinds (Task B2-3, v3)

INCEPTION_NOTE = ("evidence, not a contract status: a meaning wrong from inception (e.g. spread carried as the "
                  "coupon) is visible here although no pair test can flag it")
SEMANTIC_CHANNELS = ("contexts", field_channel("interest_rate"), field_channel("basis_spread"))


def _channels(*names) -> tuple:
    return tuple(dict.fromkeys(names))


def _text_parser(applies_to, grammars) -> tuple[dict | None, str | None]:
    grammar, missing = grammar_for(applies_to, grammars)
    return grammar, (None if grammar else missing)


def _inception(q1_date: str, comp: dict, text: dict) -> dict:
    brief = lambda slot: dict(share=slot["share"], n=slot["n"])
    return dict(report_date=q1_date, share_rate_le_spread=comp["share_rate_le_spread"], implied_base_p50=comp["p50"],
                composition_n=comp["n"], floating_n=comp["floating_n"], fixed_n=comp["fixed_n"],
                unresolved_n=comp["unresolved_n"], fixed_coupon_in_spread=comp["fixed_coupon_in_spread"],
                rate_equals_text_spread=brief(text["shares"]["rate_equals_text_spread"]),
                rate_equals_text_spread_magnitude_normalised=text["rate_equals_text_spread_magnitude_normalised"],
                rate_equals_text_pct=brief(text["shares"]["rate_equals_text_pct"]), note=INCEPTION_NOTE)


FLOATING_STATS = ("share_rate_le_spread", "p25", "p50", "p75", "iqr")


def _composition_brief(obs: dict, min_rows: int | None = None) -> dict:
    """R38: counts per rate type always; the floating statistics only when floating_n >= min_rows."""
    out = dict(n=obs["n"], pair_rows=obs["pair_rows"], floating_n=obs["floating_n"], fixed_n=obs["fixed_n"],
               unresolved_n=obs["unresolved_n"], magnitude_unresolved_n=len(obs["magnitude_unresolved_keys"]),
               type_basis=dict(obs["type_basis"]), fixed_coupon_in_spread=obs["fixed_coupon_in_spread"],
               basis=sorted(obs["basis"]), unresolved_share=obs["unresolved_share"],
               **{k: obs[k] for k in FLOATING_STATS})
    if min_rows is not None and obs["floating_n"] < min_rows:
        out.update({k: None for k in FLOATING_STATS}, floating_stats="not_assessed_below_min_rows")
    return out


def _composition_gate(obs: dict, gaps: list, band: dict, constants: dict, suffix: str) -> str | None:
    if gaps or obs["unobservable_keys"]:
        return "q" + ("2" if suffix else "1") + "_channel_incomplete"
    if not obs["pair_rows"]:
        return "no_rows_with_both_fields" + suffix
    if obs["unresolved_share"] > constants["max_unresolved_pair_share"]:
        return "unresolved_pair_majority" + suffix
    if obs["n"] < band["min_rows"]:
        return "fewer_than_min_rows_with_both_fields" + suffix
    return None


def _text_gate(obs: dict, gaps: list, band: dict, suffix: str) -> str | None:
    if gaps or obs["unobservable_keys"]:
        return "q" + ("2" if suffix else "1") + "_channel_incomplete"
    if not obs["debt_rows"]:
        return "no_identifier_rows_with_rate_fields" + suffix
    if obs["parse_share"] < band["min_parse_share"]:
        return "identifier_rate_text_parse_share_below_min" + suffix
    if not any(s["n"] >= band["min_rows"] for s in obs["shares"].values()):
        return "fewer_than_min_rows_parseable" + suffix
    return None


def _text_brief(obs: dict) -> dict:
    return dict(parse_share=obs["parse_share"], debt_rows=obs["debt_rows"], parsed_rows=obs["parsed_rows"],
                categories=dict(sorted(obs["categories"].items())), numeric_unit_unresolved=obs["numeric_unit_unresolved"],
                undrawn_zero_rate_rows=len(obs["undrawn_zero_rate_keys"]),
                shares={k: dict(share=v["share"], n=v["n"]) for k, v in obs["shares"].items()})


def _learn_semantic(cik, partition, tier, tolerances, q1_doc, members, grammars, facts_by_i, conventions,
                    block_cause, q1_date) -> list:
    constants = semantic_constants(tolerances)
    comp_band, text_band = band_for(tolerances, tier, "rate_composition"), band_for(tolerances, tier, "text_agreement")
    comp_gaps = channel_gaps(q1_doc, SEMANTIC_CHANNELS)
    text_gaps = channel_gaps(q1_doc, _channels("contexts", "identifiers", *SEMANTIC_CHANNELS[1:]))
    grammar, grammar_cause = _text_parser(partition["applies_to"], grammars)
    comp = observe_composition(q1_doc, members, facts_by_i, conventions, grammar)
    text = observe_text(q1_doc, members, facts_by_i, conventions, grammar,
                        tol_pct=constants["text_match_tolerance_pct"])
    inception = _inception(q1_date, comp, text)
    cause = block_cause or _composition_gate(comp, comp_gaps, comp_band, constants, "")
    marker_parser = text["parser"]
    out = [_contract(cik, "rate_composition", COMPOSITION_FIELD, partition, tier, comp_band,
                     expectation=None if cause else dict(_composition_brief(comp, comp_band["min_rows"]),
                                                         marker_parser=marker_parser),
                     cause=cause,
                     evidence=dict(inception=inception, observed=_composition_brief(comp), channel_gaps=comp_gaps,
                                   zero_rate_rows=len(comp["zero_rate_keys"]),
                                   unresolved_pair_rows=len(comp["unresolved_keys"]), basis_counts=comp["basis"],
                                   marker_parser=marker_parser, rate_type_rule=comp["rule"],
                                   rule="magnitude resolved per row; never gated on the scale contract; share and "
                                        "IQR on floating rows only (R38)"))]
    cause = block_cause or _text_gate(text, text_gaps, text_band, "")
    assessed = {k: dict(share=v["share"], n=v["n"]) for k, v in text["shares"].items() if v["n"] >= text_band["min_rows"]}
    out.append(_contract(
        cik, "text_agreement", TEXT_FIELD, partition, tier, text_band,
        expectation=None if cause else dict(parser=text["parser"], parse_share=text["parse_share"], shares=assessed,
                                            unassessed={k: v["n"] for k, v in text["shares"].items()
                                                        if k not in assessed}),
        cause=cause, evidence=dict(inception=inception, parse_share=text["parse_share"], parser=text["parser"],
                                   grammar_cause=grammar_cause, observed=_text_brief(text), channel_gaps=text_gaps,
                                   undrawn_zero_rate_rows=len(text["undrawn_zero_rate_keys"]))))
    return out


def freeze_contracts(paths, blocks: dict, *, tolerances_state: dict) -> dict:
    """Write-once contract_inventory: the full fixed M2 denominator with expectations and bands."""
    from scripts.profile_pilot import manifest
    by_cik, by_kind = {}, {}
    for cik, block in blocks.items():
        for c in block["contracts"]:
            by_cik[cik] = by_cik.get(cik, 0) + 1
            by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    content = dict(version=CONTRACTS_VERSION, tolerances=dict(content_sha256=tolerances_state["content_sha256"],
                                                             path=tolerances_state["path"]),
                   learning="Q1 census + Q1 profile + authored grammar (inherited) + Q1 S2 evidence; no Q2 read",
                   ciks=blocks, denominator=dict(total=sum(by_cik.values()), by_cik=by_cik, by_kind=by_kind),
                   kinds=[k for k in ALL_KINDS if k in by_kind], deferred_unchecked=DEFERRED, stage_b_note=STAGE_B_NOTE, claim=CLAIM)
    return manifest.freeze_inventory(paths, "contract_inventory", content)


# ---------------------------------------------------------------- evaluation (frozen inputs only)

def _result(c: dict, status: str, q2: dict, *, cause=None, expected=None, observed=None, keys=()) -> dict:
    return dict(contract_id=c["contract_id"], cik=c["cik"], kind=c["kind"], field=c["field"],
                partition_id=c["partition_id"], applies_to=c["applies_to"], tier=c["tier"], status=status,
                cause=cause, expected=expected, observed=observed, violating_keys=sorted(keys), q2=q2,
                band=c["band"])


def _check_frozen(c: dict, tolerances: dict) -> None:
    for key in ("contract_id", "cik", "kind", "field", "partition_id", "applies_to", "tier", "band",
                "learn_status", "learn_cause", "expectation"):
        _req(c, key, "contract " + str(c.get("contract_id")))
    if c["band"] != band_for(tolerances, c["tier"], c["kind"]):
        raise ContractError("frozen contract band disagrees with the frozen tolerance file: " + c["contract_id"])
    if c["learn_status"] == "learned" and c["expectation"] is None:
        raise ContractError("learned contract without an expectation: " + c["contract_id"])


def _check_s2_constants(tolerances: dict) -> None:
    from scripts.profile_pilot.contracts_income import s2_constants
    frozen = _req(_req(tolerances, "fund_income_yield", "tolerances"), "constants", "tolerances.fund_income_yield")
    if frozen != s2_constants():
        raise ContractError("pipeline.rate_convention constants changed after the freeze")


def evaluate_contracts(block: dict, tolerances: dict, *, q2_doc: dict | None, q2_listing: dict,
                       grammar, yield_q2: dict | None) -> list:
    """Evaluate the frozen contracts of one CIK on Q2; every contract yields exactly one result.

    Each result carries `identifier_format_unresolved` (the frozen Q1 identifier-format status)
    so M2 can be reported under both readings of spec 6.3 (see IDENTIFIER_FORMAT_INTERPRETATION).
    """
    results = _evaluate(block, tolerances, q2_doc=q2_doc, q2_listing=q2_listing, grammar=grammar,
                        yield_q2=yield_q2)
    status = _req(_req(block, "identifier_format", "inventory block"), "status", "inventory block.identifier_format")
    learned = {c["contract_id"] for c in block["contracts"] if c["learn_status"] == "learned"}
    for r in results:
        r["identifier_format_unresolved"] = status == "unresolved_mixed"
        # a reporting flag, not a fifth status (NEWLY_ABSTAINED_RULE); rolling mode adds the prior pair
        r["newly_abstained"] = r["contract_id"] in learned and r["status"] == "insufficient_evidence"
    return results


def mark_prior_abstentions(results: list, prior: list | None) -> list:
    """Rolling mode: an abstention whose contract was holds/breach in the prior pair is newly abstained."""
    before = {r["contract_id"]: r["status"] for r in prior or []}
    return [dict(r, newly_abstained=True) if r["status"] == "insufficient_evidence" and not r["newly_abstained"]
            and before.get(r["contract_id"]) in ("holds", "breach") else r for r in results]


def _q2_frame(block: dict, q2_doc: dict, q2_listing: dict, grammars: list) -> dict:
    q2 = dict(report_date=q2_doc["document"]["report_date"], form_type=q2_doc["document"].get("form_type"),
              status="available", census_relative=q2_listing.get("census_relative"))
    positions = current_positions(q2_doc)
    partitions = [dict(partition_id=p["partition_id"], applies_to=p["applies_to"])
                  for p in _req(block, "partitions", "inventory block")]
    rows = routing_rows(q2_doc, positions, grammars)
    routing = route(partitions, rows, q2["report_date"], q2["form_type"], _req(block, "recorded_at", "block"))
    ambiguous = {}
    for item in routing["ambiguous"]:
        for pid in item["partitions"]:
            ambiguous.setdefault(pid, []).append(item["context_id"])
    return dict(q2=q2, routing=routing, by_ctx={p["context_id"]: p for p in positions},
                rows_by_ctx={r["context_id"]: r for r in rows}, facts_by_i={f["i"]: f for f in q2_doc["facts"]},
                ambiguous=ambiguous, unroutable=[u["context_id"] for u in routing["unroutable"]])


def _evaluate(block: dict, tolerances: dict, *, q2_doc, q2_listing, grammar, yield_q2) -> list:
    contracts = _req(block, "contracts", "inventory block")
    for c in contracts:
        _check_frozen(c, tolerances)
    _check_s2_constants(tolerances)
    conventions = frozen_scale_conventions(tolerances)
    grammars = as_grammars(grammar)
    if q2_doc is None:
        q2 = dict(report_date=q2_listing.get("report_date"), form_type=None, status=q2_listing.get("status"),
                  detail=q2_listing.get("detail"))
        return [_result(c, "insufficient_evidence", q2, cause="q2_census_unavailable",
                        observed=dict(detail=q2_listing.get("detail"))) for c in contracts]
    frame = _q2_frame(block, q2_doc, q2_listing, grammars)
    q2, routing, by_ctx, rows_by_ctx, facts_by_i = (frame[k] for k in ("q2", "routing", "by_ctx", "rows_by_ctx",
                                                                       "facts_by_i"))
    ambiguous, unroutable = frame["ambiguous"], frame["unroutable"]
    cache, scale_status, results = {}, {}, []
    for c in sorted(contracts, key=lambda c: ALL_KINDS.index(c["kind"])):
        pid = c["partition_id"]
        if c["learn_status"] != "learned":
            results.append(_result(c, "insufficient_evidence", q2, cause="not_learned_in_q1: " + str(c["learn_cause"])))
            continue
        if c["kind"] == "fund_income_yield":
            results.append(_evaluate_yield(c, q2, yield_q2))
            continue
        if pid in ambiguous or unroutable:
            keys = ambiguous.get(pid, []) + unroutable
            results.append(_result(c, "insufficient_evidence", q2, keys=keys, cause="ambiguous_partition_overlap"
                                   if pid in ambiguous else "rows_not_routable"))
            continue
        members = [by_ctx[k] for k in routing["routed"].get(pid, [])]
        if c["kind"] in SEMANTIC_KINDS:
            obs = observe_semantic(c, q2_doc, members, grammars, facts_by_i, conventions, tolerances)
            results.append(semantic_verdict(c, q2, obs, tolerances))
            continue
        if c["kind"] == "format_grammar":
            results.append(_evaluate_format(c, q2, q2_doc, [rows_by_ctx[k] for k in routing["routed"].get(pid, [])],
                                            grammars))
            continue
        gaps = channel_gaps(q2_doc, ("contexts", field_channel(c["field"])))
        if (pid, c["field"]) not in cache:
            cache[(pid, c["field"])] = observe_field(q2_doc, members, c["field"], facts_by_i)
        obs = cache[(pid, c["field"])]
        if gaps or obs["unobservable_keys"]:
            results.append(_result(c, "insufficient_evidence", q2, cause="q2_channel_incomplete",
                                   observed=dict(channel_gaps=gaps, unobservable=len(obs["unobservable_keys"])),
                                   keys=obs["unobservable_keys"]))
            continue
        if not obs["rows"]:
            results.append(_result(c, "insufficient_evidence", q2, cause="no_q2_positions_in_partition"))
            continue
        if c["kind"] == "value_range":
            verdict = _evaluate_range(c, q2, obs, scale_status, conventions)
        else:
            verdict = {"source_concept_set": _evaluate_concepts, "fill_rate": _evaluate_fill,
                       "scale": _evaluate_scale}[c["kind"]](c, q2, obs)
        if c["kind"] == "scale":
            scale_status[(pid, c["field"])] = verdict["status"]
        results.append(verdict)
    order = {c["contract_id"]: i for i, c in enumerate(contracts)}
    return sorted(results, key=lambda r: order[r["contract_id"]])


def _evaluate_concepts(c, q2, obs) -> dict:
    expected = _req(c["expectation"], "concepts", c["contract_id"])
    got = obs["concepts"]
    if got == expected:
        return _result(c, "holds", q2, expected=expected, observed=dict(concepts=got))
    added = sorted(set(got) - set(expected))
    removed = sorted(set(expected) - set(got))
    # Attribution without cross-quarter row identity: an addition (incl. a namespace move,
    # added AND removed) names the rows carrying the added concept; a pure removal names the
    # rows where the field is unfilled (absent, nil, conflict). Never rows still filled under
    # an expected concept, never rows outside those sets.
    if added:
        keys = {k for concept in added for k in obs["concept_keys"][concept]}
    else:
        keys = set(obs["absent_keys"] + obs["nil_keys"] + [x["context_id"] for x in obs["conflicts"]])
    return _result(c, "breach", q2, expected=expected,
                   observed=dict(concepts=got, added=added, removed=removed,
                                 rows_not_carrying_removed=len(obs["row_keys"]) if removed else 0),
                   keys=keys, cause="concept_set_changed")


def _evaluate_fill(c, q2, obs) -> dict:
    exp = _req(c["expectation"], "fill_share", c["contract_id"])
    pp = _req(c["band"], "fill_rate_pp", c["contract_id"])
    observed = dict(fill_share=obs["fill_share"], filled=obs["filled"], rows=obs["rows"],
                    absent=len(obs["absent_keys"]), nil=len(obs["nil_keys"]), conflicts=len(obs["conflicts"]),
                    zero_values=obs["zero_values"], delta_pp=round((obs["fill_share"] - exp) * 100, 4))
    if abs(obs["fill_share"] - exp) * 100 <= pp + 1e-9:
        return _result(c, "holds", q2, expected=dict(fill_share=exp, band_pp=pp), observed=observed)
    keys = obs["filled_keys"] if obs["fill_share"] > exp else (obs["absent_keys"] + obs["nil_keys"]
                                                                + [x["context_id"] for x in obs["conflicts"]])
    return _result(c, "breach", q2, expected=dict(fill_share=exp, band_pp=pp), observed=observed, keys=keys,
                   cause="fill_rate_outside_band")


def _evaluate_scale(c, q2, obs) -> dict:
    exp = c["expectation"]
    expected_class = _req(exp, "scale_class", c["contract_id"])
    regime = _req(exp, "magnitude_regime", c["contract_id"])
    observed = _scale_evidence(obs)
    if not obs["filled"]:
        return _result(c, "insufficient_evidence", q2, cause="no_q2_values_to_assess", expected=exp,
                       observed=observed)
    # A filled field with no fact index cannot show its unit: inability to observe is
    # insufficient_evidence, never a declared-unit breach. A differing unit that WAS
    # observed on other rows is still a breach.
    other = {k: v for k, v in obs["class_keys"].items() if k not in (expected_class, UNIT_NOT_OBSERVABLE)}
    unobservable = obs["class_keys"].get(UNIT_NOT_OBSERVABLE, [])
    unit_conflicts = [x["context_id"] for x in obs["conflicts"] if x["reason"] == "unit_differs"]
    if other:
        return _result(c, "breach", q2, cause="declared_unit_class_changed", expected=exp, observed=observed,
                       keys={k for v in other.values() for k in v})
    if unobservable:
        return _result(c, "insufficient_evidence", q2, cause="unit_not_observable_no_fact_index", expected=exp,
                       observed=observed, keys=unobservable)
    if unit_conflicts:
        return _result(c, "insufficient_evidence", q2, cause="conflicting_units_on_one_field", expected=exp,
                       observed=observed, keys=unit_conflicts)
    if obs["regime"] == "mixed":
        return _result(c, "insufficient_evidence", q2, cause="magnitude_mixed_under_one_declared_unit",
                       expected=exp, observed=observed, keys=[k for k, _, _ in obs["values"]])
    if obs["regime"] != regime and "zero_only" not in (obs["regime"], regime):
        return _result(c, "insufficient_evidence", q2, cause="magnitude_regime_changed_under_same_declared_unit",
                       expected=exp, observed=observed, keys=[k for k, _, _ in obs["values"]])
    return _result(c, "holds", q2, expected=exp, observed=observed)


def _evaluate_range(c, q2, obs, scale_status, conventions) -> dict:
    exp = c["expectation"]
    lo, hi = _req(exp, "widened", c["contract_id"])
    q_lo, q_hi = _req(c["band"], "value_range_quantiles", c["contract_id"])
    status = scale_status.get((c["partition_id"], c["field"]))
    if status != "holds":
        return _result(c, "insufficient_evidence", q2, cause="scale_contract_not_holds",
                       observed=dict(scale_status=status), expected=exp)
    values = canonical(obs["values"], _req(exp, "scale_class", c["contract_id"]), conventions)
    if not values:
        return _result(c, "insufficient_evidence", q2, cause="no_q2_values_to_assess", expected=exp)
    ordered = sorted(v for _, v in values)
    p_lo, p_hi = round(quantile(ordered, q_lo), 10), round(quantile(ordered, q_hi), 10)
    observed = dict(p5=p_lo, p95=p_hi, min=ordered[0], max=ordered[-1], n_values=len(ordered))
    outside = [k for k, v in values if v < lo or v > hi]
    if lo <= p_lo and p_hi <= hi:
        return _result(c, "holds", q2, expected=exp, observed=dict(observed, rows_outside=len(outside)))
    return _result(c, "breach", q2, cause="quantiles_outside_widened_q1_range", expected=exp, observed=observed,
                   keys=outside)


def _evaluate_format(c, q2, q2_doc, rows, grammars) -> dict:
    exp = c["expectation"]
    minimum = _req(c["band"], "format_grammar_min_parse_share", c["contract_id"])
    pinned = [g for g in grammars if g["sha256"] == _req(exp, "grammar_sha256", c["contract_id"])
              and g["dialect"] == _req(exp, "dialect", c["contract_id"])]
    if len(pinned) != 1:
        raise ContractError("format contract evaluated without its pinned grammar: " + c["contract_id"])
    grammar = pinned[0]
    gaps = channel_gaps(q2_doc, ("contexts", "identifiers"))
    if gaps:
        return _result(c, "insufficient_evidence", q2, cause="q2_channel_incomplete", expected=exp,
                       observed=dict(channel_gaps=gaps))
    obs = grammar_observation(rows, grammar)
    if not obs["scope_rows"]:
        keys = [r["context_id"] for r in rows if r.get("investment_identifier")]
        return _result(c, "breach", q2, cause="dialect_scope_empty_in_q2", expected=exp, observed=obs, keys=keys)
    if obs["parse_share"] >= minimum:
        return _result(c, "holds", q2, expected=exp, observed=obs)
    return _result(c, "breach", q2, cause="identifiers_do_not_parse_under_dialect", expected=exp, observed=obs,
                   keys=[v["context_id"] for v in obs["violating"]])


def _evaluate_yield(c, q2, yield_q2) -> dict:
    exp = c["expectation"]
    expected = _req(exp, "vote", c["contract_id"])
    ev = yield_q2 or dict(status="insufficient_evidence", cause="q2_yield_evidence_missing")
    observed = dict(q2_yield=ev)
    if ev.get("status") != "vote":
        return _result(c, "insufficient_evidence", q2, cause=str(ev.get("cause")), expected=exp, observed=observed)
    if ev.get("vote") == expected:
        return _result(c, "holds", q2, expected=exp, observed=observed)
    keys = ["income:" + str(ev.get("cik")) + ":" + str(ev.get("report_date"))]
    return _result(c, "breach", q2, cause="s2_convention_vote_changed", expected=exp, observed=observed, keys=keys)


# ---------------------------------------------------------------- semantic kinds: observe once, verdict per band

def observe_semantic(c, q2_doc, members, grammars, facts_by_i, conventions, tolerances) -> dict:
    """The band-free Q2 observation of one learned semantic contract (shared across candidate bands)."""
    constants = semantic_constants(tolerances)
    key = "marker_parser" if c["kind"] == "rate_composition" else "parser"
    parser = _req(c["expectation"], key, c["contract_id"])
    grammar = None
    if parser["kind"] == "grammar":
        pinned = [g for g in grammars if g["sha256"] == parser["grammar_sha256"] and g["dialect"] == parser["dialect"]]
        if len(pinned) != 1:
            raise ContractError(c["kind"] + " contract evaluated without its pinned grammar: " + c["contract_id"])
        grammar = pinned[0]
    if c["kind"] == "rate_composition":
        return dict(members=len(members), gaps=channel_gaps(q2_doc, SEMANTIC_CHANNELS),
                    obs=observe_composition(q2_doc, members, facts_by_i, conventions, grammar))
    return dict(members=len(members),
                gaps=channel_gaps(q2_doc, _channels("contexts", "identifiers", *SEMANTIC_CHANNELS[1:])),
                obs=observe_text(q2_doc, members, facts_by_i, conventions, grammar,
                                 tol_pct=constants["text_match_tolerance_pct"]))


def semantic_verdict(c: dict, q2: dict, sem: dict, tolerances: dict) -> dict:
    exp, band = c["expectation"], c["band"]
    if not sem["members"]:
        return _result(c, "insufficient_evidence", q2, cause="no_q2_positions_in_partition", expected=exp)
    obs = sem["obs"]
    if c["kind"] == "rate_composition":
        brief = dict(_composition_brief(obs, band["min_rows"]), zero_rate_rows=len(obs["zero_rate_keys"]))
        cause = _composition_gate(obs, sem["gaps"], band, semantic_constants(tolerances), "_in_q2")
        if cause is None and brief["basis"] != _req(exp, "basis", c["contract_id"]):
            cause = "composition_basis_changed"
        if cause:
            return _result(c, "insufficient_evidence", q2, cause=cause, expected=exp,
                           observed=dict(brief, channel_gaps=sem["gaps"]), keys=obs["unobservable_keys"])
        floating = exp["share_rate_le_spread"] is not None and brief["share_rate_le_spread"] is not None
        criteria, observed, keys = {}, dict(brief), set()
        if floating:
            delta = (obs["share_rate_le_spread"] - exp["share_rate_le_spread"]) * 100
            limit = exp["iqr"] * band["iqr_widen"]
            criteria.update(share="breach" if abs(delta) > band["share_pp"] + 1e-9 else "holds",
                            iqr="breach" if obs["iqr"] > limit + 1e-9 else "holds")
            observed.update(share_delta_pp=round(delta, 6),
                            iqr_ratio=round(obs["iqr"] / exp["iqr"], 6) if exp["iqr"] else None,
                            p50_shift=round(obs["p50"] - exp["p50"], 10),
                            p50_rule="evidence only: the reference rate moves every quarter; the level is never a "
                                     "criterion")
            if criteria["share"] == "breach":
                keys |= {k for k, v in obs["floating"] if v <= 0}
            if criteria["iqr"] == "breach":
                keys |= {k for k, v in obs["floating"] if abs(v - obs["p50"]) > limit + 1e-9}
        else:
            criteria.update(share="not_assessed", iqr="not_assessed")
        fixed_delta = (obs["fixed_coupon_in_spread"] - exp["fixed_coupon_in_spread"]) * 100
        criteria["fixed"] = "breach" if abs(fixed_delta) > band["share_pp"] + 1e-9 else "holds"
        observed.update(fixed_delta_pp=round(fixed_delta, 6), criteria=criteria)
        if criteria["fixed"] == "breach":
            keys |= set(obs["fixed_keys"])
        failed = [name for name, verdict in criteria.items() if verdict == "breach"]
        if not failed:
            return _result(c, "holds", q2, expected=exp, observed=observed)
        cause = "+".join({"share": "implied_base_share_moved", "iqr": "implied_base_dispersion_widened",
                          "fixed": "fixed_coupon_in_spread_share_changed"}[f] for f in failed)
        return _result(c, "breach", q2, cause=cause, expected=exp, observed=observed, keys=keys)
    brief = _text_brief(obs)
    cause = _text_gate(obs, sem["gaps"], band, "_in_q2")
    if cause:
        return _result(c, "insufficient_evidence", q2, cause=cause, expected=exp,
                       observed=dict(brief, channel_gaps=sem["gaps"]), keys=obs["unobservable_keys"])
    criteria, deltas, keys = {}, {}, set()
    for name, learned in sorted(_req(exp, "shares", c["contract_id"]).items()):
        now = obs["shares"][name]
        if now["n"] < band["min_rows"]:
            criteria[name] = "not_assessed"
            continue
        delta = (now["share"] - learned["share"]) * 100
        deltas[name] = round(delta, 6)
        criteria[name] = "breach" if abs(delta) > band["text_share_pp"] + 1e-9 else "holds"
        if criteria[name] == "breach":
            keys |= set(now["hit_keys"] if delta > 0 else now["miss_keys"])
    observed = dict(brief, criteria=criteria, delta_pp=deltas)
    if not any(v != "not_assessed" for v in criteria.values()):
        return _result(c, "insufficient_evidence", q2, cause="fewer_than_min_rows_parseable_in_q2", expected=exp,
                       observed=observed)
    if "breach" in criteria.values():
        return _result(c, "breach", q2, cause="text_share_moved", expected=exp, observed=observed, keys=keys)
    return _result(c, "holds", q2, expected=exp, observed=observed)


def evaluate_semantic_grid(block: dict, grid: list, *, q2_doc, q2_listing, grammar) -> list:
    """Calibration only: the semantic contracts of `block` at every candidate tolerance in `grid`.

    One routing and one observation per contract; each candidate's verdict uses that candidate's
    bands (rebanded_block). Returns one result list per grid entry, in grid order, with the same
    newly_abstained flag as evaluate_contracts."""
    grammars = as_grammars(grammar)
    semantic = [c for c in _req(block, "contracts", "inventory block") if c["kind"] in SEMANTIC_KINDS]
    per_grid = [[dict(c, band=band_for(tol, c["tier"], c["kind"])) for c in semantic] for tol in grid]
    for tol, contracts in zip(grid, per_grid):
        for c in contracts:
            _check_frozen(c, tol)
        if frozen_scale_conventions(tol) != frozen_scale_conventions(grid[0]) or \
                semantic_constants(tol) != semantic_constants(grid[0]):
            raise ContractError("candidate tolerances differ outside the semantic bands")
    out = [[] for _ in grid]
    if q2_doc is None:
        q2 = dict(report_date=q2_listing.get("report_date"), form_type=None, status=q2_listing.get("status"),
                  detail=q2_listing.get("detail"))
        for k, contracts in enumerate(per_grid):
            out[k] = [_result(c, "insufficient_evidence", q2, cause="q2_census_unavailable") for c in contracts]
    else:
        frame = _q2_frame(block, q2_doc, q2_listing, grammars)
        q2, routed = frame["q2"], frame["routing"]["routed"]
        for idx, c in enumerate(semantic):
            pid = c["partition_id"]
            if c["learn_status"] != "learned":
                for k in range(len(grid)):
                    out[k].append(_result(per_grid[k][idx], "insufficient_evidence", q2,
                                          cause="not_learned_in_q1: " + str(c["learn_cause"])))
                continue
            if pid in frame["ambiguous"] or frame["unroutable"]:
                keys = frame["ambiguous"].get(pid, []) + frame["unroutable"]
                for k in range(len(grid)):
                    out[k].append(_result(per_grid[k][idx], "insufficient_evidence", q2, keys=keys,
                                          cause="ambiguous_partition_overlap" if pid in frame["ambiguous"]
                                          else "rows_not_routable"))
                continue
            members = [frame["by_ctx"][k] for k in routed.get(pid, [])]
            sem = observe_semantic(c, q2_doc, members, grammars, frame["facts_by_i"],
                                   frozen_scale_conventions(grid[0]), grid[0])
            for k, tol in enumerate(grid):
                out[k].append(semantic_verdict(per_grid[k][idx], q2, sem, tol))
    status = _req(_req(block, "identifier_format", "inventory block"), "status", "inventory block.identifier_format")
    for results in out:
        for r, c in zip(results, semantic):
            r["identifier_format_unresolved"] = status == "unresolved_mixed"
            r["newly_abstained"] = c["learn_status"] == "learned" and r["status"] == "insufficient_evidence"
    return out


# ---------------------------------------------------------------- M2

def _counts(results) -> dict:
    out = {s: 0 for s in STATUSES}
    for r in results:
        out[r["status"]] += 1
    return out


def _tables(results: list) -> dict:
    by = lambda key: {k: _counts([r for r in results if key(r) == k]) for k in sorted({key(r) for r in results})}
    causes: dict = {}
    for r in results:
        if r["status"] == "insufficient_evidence":
            causes[r["cause"]] = causes.get(r["cause"], 0) + 1
    counts = _counts(results)
    newly = sum(bool(r.get("newly_abstained")) for r in results)
    return dict(denominator=len(results), counts=counts,
                holds_share=round(counts["holds"] / len(results), 6) if results else None,
                by_cik=by(lambda r: r["cik"]), by_kind=by(lambda r: r["kind"]),
                by_q2_form_type=by(lambda r: r["q2"]["form_type"] or "unavailable"),
                by_cik_and_kind=by(lambda r: r["cik"] + ":" + r["kind"]),
                by_q2_form_type_and_kind=by(lambda r: (r["q2"]["form_type"] or "unavailable") + ":" + r["kind"]),
                insufficient_causes=dict(sorted(causes.items())),
                newly_abstained=dict(count=newly, share=round(newly / len(results), 6) if results else None,
                                     rule=NEWLY_ABSTAINED_RULE))


def strict_results(results: list) -> list:
    """Strict spec 6.3 reading: every row-level contract of a CIK whose Q1 identifier format is an
    unresolved mixture is insufficient_evidence/identifier_format_unresolved (yield is fund-level)."""
    out = []
    for r in results:
        flagged = _req(r, "identifier_format_unresolved", "result " + str(r.get("contract_id")))
        if flagged and r["kind"] != "fund_income_yield" and r["status"] != "insufficient_evidence":
            r = dict(r, status="insufficient_evidence", cause="identifier_format_unresolved")
        out.append(r)
    return out


def summarise_m2(results: list, *, denominator: int) -> dict:
    if len(results) != denominator:
        raise ContractError("M2 results (%d) differ from the frozen denominator (%d)" % (len(results), denominator))
    strict = strict_results(results)
    return dict(_tables(results), reading="as_evaluated",
                breaches=[dict(contract_id=r["contract_id"], cause=r["cause"], expected=r["expected"],
                               observed=_brief(r["observed"]), violating_keys=r["violating_keys"],
                               q2_form_type=r["q2"]["form_type"],
                               identifier_format_unresolved=r["identifier_format_unresolved"])
                          for r in results if r["status"] == "breach"],
                identifier_format_unresolved_contracts=sum(r["identifier_format_unresolved"] for r in results),
                strict_6_3=dict(_tables(strict), interpretation=IDENTIFIER_FORMAT_INTERPRETATION),
                holds_with_form_type_reason=HOLDS_WITH_FORM_TYPE_REASON, deferred_unchecked=DEFERRED,
                stage_b_note=STAGE_B_NOTE, claim=CLAIM)


def _brief(observed):
    if not isinstance(observed, dict):
        return observed
    return {k: v for k, v in observed.items() if k not in ("violating", "q2_yield")}
