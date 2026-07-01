"""Agent A2 deterministic SELF-SCREEN -- the required "validate before finishing" step.

The worker MUST run this on its own proposal before it exits. It is a deterministic SCREEN
(fast, on the BUNDLE's sample rows only -- no-haystack), NOT acceptance: the parent's A3
held-out gate still runs independently on the full population and remains authoritative.
Passing this is NECESSARY, not SUFFICIENT. It exists to fail-fast on obvious-garbage proposals
(bad JSON, non-compiling regex, the over-require trap, low sample completeness) so the agent
iterates immediately instead of burning a full parent gate run.

Exit 0 = screen passed; exit 1 = fix and re-run. Reads ONLY the proposal files + the bundle.

Usage:
  python -m scripts.agent_a.validate_proposal --cik <CIK> --bundle <bundle.json>
"""

from __future__ import annotations

import json
import re
import sys

from pipeline import config
from pipeline.identifier_rate import apply_grammar, evaluate_invariants
from pipeline.identifier_signature import keyword_signature

# the over-require trap (bit us twice): these are optional fields and must NOT be required
_OPTIONAL_FIELDS = {"pik_rate", "interest_rate_floor", "interest_rate_cash_leg"}
_SCREEN_MIN_COMPLETENESS = 90.0   # on the dominant variant's sample rows
_SCREEN_MIN_INVARIANT = 80.0      # lenient screen threshold (gate is 85 on full pop)
# keyword_signature() returns this when NO anchor matches an identifier. If it is the MODAL
# signature across the sampled identifiers, the proposed anchors do not describe the filer's
# format at all -- so any completeness % is measured on a self-selected sliver and is vacuous.
# Empirically (2025-12-31 batch, 55 staged proposals) this is the only sample-only signal that
# separates a real overfit from a gate-PASS with zero false positives; a support floor or
# per-quarter completeness on the bounded sample does NOT separate (the breaking identifiers
# live in the population tail the sample omits -- those are the parent A3 gate's job).
_NONE_SIGNATURE = "(none)"

# #1 schema conformance: the engine's apply_grammar (agentA-rate-grammar.v1) ONLY honors
# these extractor keys. Anything else (e.g. a hallucinated `source: source_table`, or `unit`
# instead of `type`) is silently ignored -> the extractor no-ops. Reject it at the screen.
_ALLOWED_EXTRACTOR_KEYS = {"field", "regex", "group", "type", "map"}
_VALID_TYPES = {"pct", "bps", "date_mdy", "ref_code", "text"}
_NUMERIC_DATE_TYPES = {"pct", "bps", "date_mdy", "ref_code"}
# #2 anti-degeneracy: a rate grammar must REQUIRE at least one substantive rate field --
# requiring only a non-rate field (e.g. investment_type) makes "completeness" vacuous.
_SUBSTANTIVE_FIELDS = {"basis_spread", "interest_rate", "interest_rate_all_in",
                       "interest_rate_total", "reference_rate_type", "maturity_date"}
# the keys each invariant kind MUST carry, or evaluate_invariants can't score it (and,
# pre-guard, KeyError'd over the whole population). Mirrors pipeline.identifier_rate.
_INVARIANT_REQUIRED_KEYS = {
    "pct_agree": ["parsed", "twin"],
    "date_agree": ["parsed", "twin"],
    "implication": ["if_present", "then_present"],
    "sum_identity": ["total", "parts"],
}
_NOT_APPLICABLE_STATUS = "NOT_APPLICABLE_RATE_GRAMMAR"
_IDENTIFIER_RATE_RE = re.compile(
    r"[0-9]+\.?[0-9]*\s*%|\b(?:SOFR|LIBOR|PRIME|EURIBOR|BBSW|SF|P)\b|"
    r"\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}\b",
    re.I,
)


def _find(cik, kind):
    """Locate the proposal: proposals/<CIK>.<kind>.json (staging) else overrides/<CIK>.json."""
    prop = config.OUTPUT_DIR / "agent_a" / "proposals" / f"{cik}.{kind}.json"
    if prop.exists():
        return prop
    sub = "identifier_anchors" if kind == "anchors" else "identifier_rate_grammars"
    return config.DATA_DIR / "overrides" / sub / f"{cik}.json"


def _load_anchors(path):
    spec = json.loads(path.read_text(encoding="utf-8"))
    return [(a["label"], re.compile(a["regex"], re.I)) for a in spec["anchors"]]


def _identifier_rate_evidence_pct(bundle: dict) -> float:
    rows = []
    for v in bundle.get("top_variants", []):
        rows.extend(s.get("identifier", "") for s in v.get("samples", []))
    if not rows:
        return 0.0
    n_hit = sum(1 for ident in rows if _IDENTIFIER_RATE_RE.search(ident or ""))
    return round(100.0 * n_hit / len(rows), 1)


def screen(cik: str, bundle_path: str):
    fails, warns = [], []

    # --- 1. files load + schema-shape + regex compile ---
    apath, gpath = _find(cik, "anchors"), _find(cik, "grammar")
    try:
        anchors = _load_anchors(apath)
    except Exception as e:  # noqa: BLE001
        return ["anchors file invalid: %s (%s)" % (apath, e)], [], {}
    try:
        grammar = json.loads(gpath.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return ["grammar file invalid: %s (%s)" % (gpath, e)], [], {}

    bundle = json.loads(open(bundle_path, encoding="utf-8").read())
    status = grammar.get("status") or grammar.get("verdict")

    for key in ("extractors", "required_fields", "applies_to"):
        if key not in grammar:
            fails.append(f"grammar missing required key '{key}'")
    for ex in grammar.get("extractors", []):
        try:
            compiled = re.compile(ex["regex"])
        except Exception as e:  # noqa: BLE001
            fails.append(f"extractor '{ex.get('field')}' regex does not compile: {e}")
        else:
            # the group index must exist: a non-capturing '(?:...)' regex with "group": 1
            # extracts nothing and (pre-guard) crashed the engine with IndexError
            grp = ex.get("group", 1)
            if isinstance(grp, int) and grp > compiled.groups:
                fails.append(f"extractor '{ex.get('field')}' declares group {grp} but its regex "
                             f"has {compiled.groups} capture group(s) -- it would extract nothing; "
                             f"use a capturing group '(...)' (a '(?:...)' group does not count)")
        # #1 schema conformance -- catch hallucinated keys the engine silently ignores
        unknown = set(ex) - _ALLOWED_EXTRACTOR_KEYS - {k for k in ex if k.startswith("_")}
        if unknown:
            fails.append(f"extractor '{ex.get('field')}' has non-schema key(s) {sorted(unknown)} "
                         f"-- the engine ignores these (only {sorted(_ALLOWED_EXTRACTOR_KEYS)} "
                         f"are honored); e.g. 'source'/'unit' are no-ops -> extractor won't work")
        if ex.get("type") and ex["type"] not in _VALID_TYPES:
            fails.append(f"extractor '{ex.get('field')}' type '{ex['type']}' invalid "
                         f"(valid: {sorted(_VALID_TYPES)}); did you mean 'type' not 'unit'?")
        if "P<" in ex.get("regex", "") and "group" not in ex:
            warns.append(f"extractor '{ex.get('field')}' uses a named group but no 'group' index "
                         f"-- the engine reads by integer group, confirm group 1 is the value")
    for inv in grammar.get("invariants", []):
        iname, ikind = inv.get("name"), inv.get("kind")
        if not iname or not ikind:
            fails.append(f"invariant {inv!r} missing 'name' and/or 'kind'")
            continue
        req = _INVARIANT_REQUIRED_KEYS.get(ikind)
        if req is None:
            fails.append(f"invariant '{iname}' has unknown kind '{ikind}' "
                         f"(valid: {sorted(_INVARIANT_REQUIRED_KEYS)})")
        else:
            missing = [k for k in req if k not in inv]
            if missing:
                fails.append(f"invariant '{iname}' (kind '{ikind}') missing key(s) {missing} "
                             f"-- the engine would KeyError; required for this kind: {req}")
    if not grammar.get("applies_to", {}).get("regime"):
        warns.append("applies_to.regime missing -- era-aware gate needs it")

    # Supported non-applicable outcome: the worker may truthfully report that this CIK's
    # identifier strings do not carry rate/date datapoints. That is a routing result, not a
    # promotable rate grammar, and it must be backed by the actual bundle sample.
    if status == _NOT_APPLICABLE_STATUS:
        ident_rate_pct = _identifier_rate_evidence_pct(bundle)
        available = grammar.get("available_identifier_datapoints", [])
        unsupported = grammar.get("unsupported_identifier_datapoints", [])
        if not isinstance(available, list) or not available:
            fails.append("NOT_APPLICABLE proposal must list available_identifier_datapoints")
        if not isinstance(unsupported, list) or not unsupported:
            fails.append("NOT_APPLICABLE proposal must list unsupported_identifier_datapoints")
        if not grammar.get("not_applicable_reason"):
            fails.append("NOT_APPLICABLE proposal must include not_applicable_reason")
        if ident_rate_pct > 10.0:
            fails.append(f"NOT_APPLICABLE contradicted by identifier sample: {ident_rate_pct}% "
                         "of sampled identifiers contain rate/date evidence")

        none_ex = bundle.get("none_examples", [])
        none_recovered = sum(1 for e in none_ex if keyword_signature(e, anchors) != _NONE_SIGNATURE)
        metrics = {
            "status": _NOT_APPLICABLE_STATUS,
            "available_identifier_datapoints": available,
            "unsupported_identifier_datapoints": unsupported,
            "identifier_rate_evidence_pct": ident_rate_pct,
            "none_examples": len(none_ex),
            "none_recovered": none_recovered,
        }
        return fails, warns, metrics

    # --- 2. the over-require trap + anti-degeneracy ---
    req = set(grammar.get("required_fields", []))
    bad_req = _OPTIONAL_FIELDS & req
    if bad_req:
        fails.append(f"required_fields includes OPTIONAL field(s) {sorted(bad_req)} "
                     f"-- over-require collapses completeness and FAILS the parent gate")
    # #2 anti-degeneracy: must require >=1 substantive rate field (not just investment_type)
    if not (req & _SUBSTANTIVE_FIELDS):
        fails.append(f"DEGENERATE: required_fields {sorted(req)} has no substantive rate field "
                     f"({sorted(_SUBSTANTIVE_FIELDS)}) -- completeness is vacuous; if this filer's "
                     f"identifier carries no rate, it is not a rate-grammar target (see discover)")
    # #2 a grammar that extracts rates must validate them with >=1 invariant
    extracts_rates = any(ex.get("type") in _NUMERIC_DATE_TYPES for ex in grammar.get("extractors", []))
    if extracts_rates and not grammar.get("invariants"):
        fails.append("DEGENERATE: grammar extracts rate/date fields but has ZERO invariants "
                     "-- no cross-twin/identity validation; add >=1 invariant")
    if fails:
        return fails, warns, {}

    # --- 3. run the real deterministic logic on the BUNDLE's sample rows ---
    required = grammar.get("required_fields", [])
    gating = [inv["name"] for inv in grammar.get("invariants", [])
              if inv["kind"] in ("pct_agree", "date_agree", "sum_identity")]
    dom = (grammar.get("applies_to", {}).get("signature") or "")

    n_dom = n_complete = inv_pass = inv_dec = 0
    sig_counts: dict = {}
    for v in bundle.get("top_variants", []):
        for s in v.get("samples", []):
            ident = s["identifier"]
            sig = keyword_signature(ident, anchors)
            sig_counts[sig] = sig_counts.get(sig, 0) + 1
            if sig != dom:
                continue
            n_dom += 1
            parsed = apply_grammar(ident, grammar)
            if all(parsed.get(k) is not None for k in required):
                n_complete += 1
            verd = evaluate_invariants(parsed, s.get("twins", {}), grammar)
            for name in gating:
                if verd.get(name) in ("pass", "fail"):
                    inv_dec += 1
                    inv_pass += verd[name] == "pass"

    # none-coverage: do the bundle's (none) examples now gain a signature?
    none_ex = bundle.get("none_examples", [])
    none_recovered = sum(1 for e in none_ex if keyword_signature(e, anchors) != _NONE_SIGNATURE)

    metrics = {
        "dominant_signature": dom,
        "dominant_sample_rows": n_dom,
        "actual_top_sig_in_sample": max(sig_counts, key=sig_counts.get) if sig_counts else "",
        "sample_completeness_pct": round(100.0 * n_complete / n_dom, 1) if n_dom else None,
        "sample_invariant_pct": round(100.0 * inv_pass / inv_dec, 1) if inv_dec else None,
        "none_examples": len(none_ex),
        "none_recovered": none_recovered,
    }

    if metrics["actual_top_sig_in_sample"] == _NONE_SIGNATURE:
        fails.append(f"the proposed anchors label the PLURALITY of sampled identifiers as "
                     f"'{_NONE_SIGNATURE}' (no signature) -- the anchor set does not describe this "
                     f"filer's identifier format, so 'sample_completeness' is computed on a "
                     f"self-selected sliver and is not trustworthy. Re-author the anchors to "
                     f"cover the modal identifier shape before proposing a grammar.")
    if n_dom == 0:
        fails.append(f"applies_to.signature '{dom}' matches ZERO sample rows under the "
                     f"committed anchors (actual top sample sig: "
                     f"'{metrics['actual_top_sig_in_sample']}') -- the parent will resolve "
                     f"applies_to, but the grammar likely targets the wrong signature")
    else:
        if metrics["sample_completeness_pct"] < _SCREEN_MIN_COMPLETENESS:
            fails.append(f"sample completeness {metrics['sample_completeness_pct']}% < "
                         f"{_SCREEN_MIN_COMPLETENESS}% on the dominant variant -- required_fields "
                         f"not all extracting; fix extractors or required_fields")
        if metrics["sample_invariant_pct"] is not None \
                and metrics["sample_invariant_pct"] < _SCREEN_MIN_INVARIANT:
            warns.append(f"sample invariant {metrics['sample_invariant_pct']}% < "
                         f"{_SCREEN_MIN_INVARIANT}% -- many sample rows disagree with twins "
                         f"(could be real mis-bins to FLAG, or a parse bug)")
    return fails, warns, metrics


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cik", required=True)
    ap.add_argument("--bundle", required=True)
    args = ap.parse_args(argv)

    fails, warns, metrics = screen(args.cik, args.bundle)
    print("=== Agent A2 self-screen (deterministic; NOT acceptance -- parent A3 gate decides) ===")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    for w in warns:
        print(f"  WARN: {w}")
    if fails:
        for f in fails:
            print(f"  FAIL: {f}")
        print("SCREEN: FAIL -- fix the proposal and re-run before finishing.")
        return 1
    print("SCREEN: PASS (necessary, not sufficient -- the parent held-out gate is authoritative).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
