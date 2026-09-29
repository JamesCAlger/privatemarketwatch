"""Task B2-2b: back-test M2 against recorded history (rolling and anchored fund-quarter pairs).

    python -m scripts.profile_pilot.m2_backtest run --data-root D
        --census-run-id stageb2-census-20260929t094408z --contracts-run-id stageb-contracts-20260929t053506z
        [--cik C ...] [--run-id stageb2-backtest-<stamp>] [--main-root M] [--scratch-dir S]

Method. For every pilot CIK the authoritative fund-quarters of the all-quarter census root
are sorted by report date. Two modes: `rolling` (primary: learn quarter t-1, evaluate t)
and `anchored` (secondary: learn the Stage B q1, evaluate every later quarter). Learning is
in memory: the profile is derived from the learning quarter's census with
profile.derive_profile (wrapper-free, exactly the Stage B derivation; anchors are not
copied, they do not create entries), then contracts.learn_contracts reads that census, that
profile, the authored grammar and the learning quarter's yield evidence. Evaluation is
contracts.evaluate_contracts against the FROZEN tolerances v2 file (content_sha256
asserted); both the as-evaluated and the strict spec-6.3 readings are kept. Nothing here
changes a contract kind, a band or a tolerance.

Yield: with INCOME_MIN_QUARTERS (frozen) = 2, the income evidence window of quarter d is
[prev, d] when the previous authoritative quarter is consecutive and ungapped, else [d]
(which cannot vote). The same evidence serves as the learning side of pair (d, next) and
the evaluation side of pair (prev, d), so rolling windows overlap by one quarter (stated
in every output). The S2 adapter is contracts_income.income_evidence over the contracts
root's pinned parquet slices; no formula is added.

Quarter classes (ruling R37; keyed on counts, never on validation_verdict):
  populated          summary.position_observations_current > 0
  recogniser_format  0 recognised positions and >= 100 position-like facts (a fact mapped to
                     a census position field whose context carries any explicit or typed
                     dimension): a POSITIVE for fill_rate and source_concept_set on every
                     position field at the pairs on both sides; learning from it yields the
                     full denominator as insufficient_evidence (an abstention)
  pre_tagging        0 recognised positions, < 100 position-like facts and < 100 facts in
                     all (cover-only): its pairs are NOT scored
  unverified_tagging 0 recognised positions, < 100 position-like facts, >= 100 facts:
                     scored, labelled, no positive

Positives: TYPED_POSITIVES (data, one `source` per row, each re-checked against its source
at run time) + computed rows (rate-tag fingerprint changes between consecutive selected
accessions, findings-ledger rows) + recogniser_format quarters. Negatives are every scored
contract result at a pair that no positive targets: "nothing recorded", not "verified
unchanged" (NEGATIVES_CAVEAT).
Per quarter the work is one cached light stage (one census JSON loaded; no XBRL parse; the
workload estimate is m2_seed's). Exit codes: 0 ok, 2 stage invalidated, 3 contract error,
4 refused, 5 measured limit exceeded.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date as _date, datetime, timezone
import io
import json
from pathlib import Path
import sys
import time

from scripts.profile_pilot import cohort, contracts, contracts_income, contracts_run, lineage, m2_seed, manifest, \
    protection
from scripts.profile_pilot.census import POSITION_FIELDS, POSITION_RATE, POSITION_VALUE
from scripts.profile_pilot.contracts_observe import IDENTIFIER_FIELD, WHOLE_FILING, current_positions
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import (PathError, confined, discover_main_root, pilot_cwd, pilot_duckdb,
                                         resolve_paths, write_once_json)

CODE_ROOT = Path(__file__).resolve().parents[2]
BACKTEST_VERSION = "m2-backtest.v1"
RUN_PREFIX = "stageb2-backtest-"
EXIT_INVALIDATED, EXIT_CONTRACT, EXIT_REFUSED, EXIT_LIMIT = 2, 3, 4, 5
TOLERANCES_V2_SHA256 = m2_seed.TOLERANCES_V2_SHA256
LIMIT_SECONDS, LIMIT_BYTES = m2_seed.LIMIT_SECONDS, m2_seed.LIMIT_BYTES
MODES = ("rolling", "anchored")
READINGS = ("as_evaluated", "strict")
POSITIVE_SETS = {"all": (), "without_recogniser_format": ("recogniser_format",)}
POSITION_LIKE_MIN = 100
COVER_ONLY_MAX_FACTS = 100
ZERO_LEARN_CAUSE = "zero_recognised_positions_in_learning_quarter"
QUARTER_CLASS_RULE = (
    "ruling R37: populated = position_observations_current > 0; otherwise position_like = facts whose field is a "
    "census position field (census.POSITION_FIELDS, via CONCEPT_MAP) and whose context carries any explicit or "
    "typed dimension; recogniser_format = position_like >= 100 (positive for fill_rate and source_concept_set on "
    "every position field, pairs on both sides scored); pre_tagging = position_like < 100 and facts < 100 "
    "(cover-only, pairs not scored); unverified_tagging = position_like < 100 and facts >= 100 (scored, labelled). "
    "Never keyed on validation_verdict.")
NEGATIVES_CAVEAT = (
    "Negatives are 'nothing recorded', not 'verified unchanged': a breach on a negative is listed as unadjudicated "
    "with its violating keys for the owner to judge, and the breach rate on negatives is an UPPER bound on the "
    "false-positive rate.")
D07_NOTE = ("D07 (oracle median-rate shift > 300 bps): a legitimate portfolio shift and a semantic change are "
            "indistinguishable from the D07 row alone")
YIELD_WINDOW_NOTE = ("yield evidence window = [previous authoritative quarter, quarter] when consecutive and "
                     "ungapped (frozen INCOME_MIN_QUARTERS = 2), else the quarter alone (cannot vote); rolling "
                     "learning and evaluation windows overlap by one quarter")
PROFILE_MODE = "derived_in_memory"
PROFILE_NOTE = ("learning profile derived in memory per learning quarter with profile.derive_profile (no wrapper, "
                "anchors not copied: they create no entries); a derivation error leaves the profile None and is "
                "recorded (every filled field then abstains)")
SUITE = {"source_concept_set": tuple(contracts.CONCEPT_FIELDS), "fill_rate": tuple(contracts.CONCEPT_FIELDS),
         "scale": tuple(contracts.SCALE_FIELDS), "value_range": tuple(contracts.RANGE_FIELDS),
         "format_grammar": (IDENTIFIER_FIELD,), "fund_income_yield": (contracts.YIELD_FIELD,),
         "rate_composition": (contracts.COMPOSITION_FIELD,), "text_agreement": (contracts.TEXT_FIELD,)}
KNOWN_KINDS = tuple(SUITE) + ("position_identity",)
FIELD_GROUPS = (tuple(POSITION_RATE) + ("pct_of_net_assets",), tuple(POSITION_VALUE), (IDENTIFIER_FIELD,))
CHECK_TYPES = ("d07", "json_scope", "csv_row", "doc_line")
FINGERPRINT_CSV = "output/linkbase_analysis/rate_tag_fingerprint_by_accession.csv"
ORACLE_CSV = "output/oracle/check_results.csv"
LEDGER_CSV = "output/quarter_pass/q1p3_20260831/findings_ledger_post.csv"
SEMANTIC_CSV = "scratch/2026-09-29_filer_profile_example/semantic_census_by_fund_quarter.csv"
FINGERPRINT_CLASSES = (("bare", "n_bare", ("interest_rate",)), ("cash", "n_cash", ("interest_rate",)),
                       ("pik", "n_pik", ("pik_rate",)), ("floor", "n_floor", ("interest_rate_floor",)),
                       ("ext", "n_ext_rate_facts", None))
EXT_REASON = ("extension-namespace rate facts are not position concepts (review I2a: Stepstone's are SOFR benchmark "
              "levels on VariableRateAxis contexts that never enter a position concept set): recorded, never scored")
AGENTA_REASON = ("no v2 contract kind tests identifier text against the XBRL value (review I2b); the v3 "
                 "text_agreement kind (B2-3) covers it")
COMPARATIVE_REASON = ("owner-session semantic census counted comparative facts; M2 reads current positions by design "
                      "(review I1: the 488 values >= 1 sit on the FY2022 10-K's 2021-12-31 comparative contexts; all "
                      "current-period spreads are < 1 under pure)")
LEDGER_STATES = ("real_error_unremediated", "remediated_promoted", "remediation_staged")
LEDGER_NEGATIVE_STATE = "adjudicated_false_alarm"
LEDGER_RULES = {
    "fmt_basis_spread": {"format_grammar": [IDENTIFIER_FIELD], "value_range": ["basis_spread"]},
    "fmt_interest_rate": {"format_grammar": [IDENTIFIER_FIELD], "value_range": ["interest_rate"]},
    "fmt_pik_rate": {"format_grammar": [IDENTIFIER_FIELD], "value_range": ["pik_rate"]},
    "dl_rate_fill": {"fill_rate": ["interest_rate"]},
    # identifier-text spread vs XBRL spread: the v2 targets are kept for the record and scored not_covered
    # (AGENTA_REASON); the v3 text_agreement kind is the covered target (Task B2-3)
    "agentA_spread_vs_xbrl": {"format_grammar": [IDENTIFIER_FIELD], "value_range": ["basis_spread"],
                              "text_agreement": [contracts.TEXT_FIELD]}}
LEDGER_NOT_COVERED_KINDS = {"agentA_spread_vs_xbrl": {"format_grammar": AGENTA_REASON, "value_range": AGENTA_REASON}}
CODE_FILES = ("scripts/profile_pilot/m2_backtest.py", "scripts/profile_pilot/m2_seed.py",
              "scripts/profile_pilot/contracts.py", "scripts/profile_pilot/contracts_observe.py",
              "scripts/profile_pilot/contracts_income.py", "scripts/profile_pilot/contracts_run.py",
              "scripts/profile_pilot/profile.py", "scripts/profile_pilot/envelope.py",
              "scripts/profile_pilot/census.py", "scripts/profile_pilot/census_detect.py",
              "scripts/profile_pilot/lineage.py", "scripts/profile_pilot/manifest.py",
              "scripts/profile_pilot/schemas/filer_profile_v0.schema.json",
              "scripts/profile_pilot/schemas/filer_profile_document_v0.schema.json",
              "pipeline/rate_convention.py", "pipeline/identifier_rate.py", "pipeline/identifier_signature.py")


def _typed(pid, cik, day, targets, category, source, check, note, expect="covered", not_covered_reason=None):
    out = dict(positive_id=pid, cik=cik, date=day, targets=targets, category=category, polarity="positive",
               attach="eval", source=source, check=check, note=note, expect=expect)
    if not_covered_reason:
        out["not_covered_reason"] = not_covered_reason
    return out


_D07 = (("0001588272", "2024-03-31", 325), ("0001588272", "2024-06-30", 1040), ("0001588272", "2024-09-30", 1040),
        ("0001950803", "2024-12-31", 518), ("0001950803", "2025-12-31", 359))
# The recorded history, as data. `check` is re-verified against the source at run time.
TYPED_POSITIVES = [
    _typed("d07:" + cik + ":" + day, cik, day, {"value_range": ["interest_rate"]}, "oracle_D07",
           "data/" + ORACLE_CSV + " check_id=D07 cik=" + cik + " report_date=" + day + " (median rate shift "
           + str(bps) + " bps > 300)", dict(type="d07"), D07_NOTE)
    for cik, day, bps in _D07] + [
    _typed("override:0001950803:column_remap", "0001950803", "2025-12-31",
           {"source_concept_set": ["interest_rate", "pik_rate"], "fill_rate": ["interest_rate", "pik_rate"]},
           "override", "data/overrides/agent_b2_corrections/0001950803/column_remap.json (fix_class column_remap "
           "pik_rate -> interest_rate, scope.quarters 2025-12-31)",
           dict(type="json_scope", path="data/overrides/agent_b2_corrections/0001950803/column_remap.json",
                expect={"template.from_field": "pik_rate", "template.to_field": "interest_rate"}),
           "pik_rate -> interest_rate column remap"),
    _typed("override:0001920453:unit_rescale", "0001920453", "2025-12-31", {"scale": ["principal_amount"]},
           "override", "data/overrides/agent_b2_corrections/0001920453/unit_rescale.json (principal_amount x1000, "
           "one row, scope.quarters 2025-12-31)",
           dict(type="json_scope", path="data/overrides/agent_b2_corrections/0001920453/unit_rescale.json",
                expect={"template.field": "principal_amount", "template.factor": 1000}),
           "single-row principal x1000; no scale contract exists for principal_amount", expect="not_covered"),
    _typed("override:0001715933:twin_star_fv_scale", "0001715933", "2025-06-30", {"scale": ["fair_value"]},
           "override", "data/overrides/agent_investigate_rules/1715933/1715933_twin_star_2025q2_fv_scale.json "
           "(fair_value x0.001, two rows, scope.quarters 2025-06-30)",
           dict(type="json_scope",
                path="data/overrides/agent_investigate_rules/1715933/1715933_twin_star_2025q2_fv_scale.json",
                expect={"field": "fair_value", "factor": 0.001}),
           "two-row fair_value x0.001; no scale contract exists for fair_value", expect="not_covered"),
    _typed("semantic:0001803498:basis_spread_scale", "0001803498", "2022-12-31", {"scale": ["basis_spread"]},
           "comparative_period_coverage_gap", "<main>/" + SEMANTIC_CSV + " row cik=0001803498 report_date=2022-12-31 "
           "spread_repr=mixed(frac=1299,pct=488,big=0) (~27% percent-scaled basis_spread rows)",
           dict(type="csv_row", path=SEMANTIC_CSV, key={"cik": "0001803498", "report_date": "2022-12-31"},
                expect={"spread_repr": "mixed(frac=1299,pct=488,big=0)"}),
           "owner-session semantic census finding; the 488 percent-scaled values are 2021-12-31 comparatives",
           expect="not_covered", not_covered_reason=COMPARATIVE_REASON),
    _typed("changelog:0001950803:monetary_1000x", "0001950803", "2025-12-31",
           {"scale": ["fair_value", "cost", "principal_amount"]}, "changelog",
           "docs/agent_changelog.md:3361 (2026-06-07 Stepstone 2025-12-31 1000x monetary understatement)",
           dict(type="doc_line", path="docs/agent_changelog.md", line=3361, contains="1000x monetary understatement"),
           "no scale contract exists for monetary fields", expect="not_covered"),
    _typed("changelog:0001588272:fixed_plus_1600", "0001588272", "2025-12-31", {"format_grammar": [IDENTIFIER_FIELD]},
           "changelog", "docs/agent_changelog.md:9491 (2026-08-21 NexPoint 'Fixed + 1600' identifier text)",
           dict(type="doc_line", path="docs/agent_changelog.md", line=9491, contains="Fixed + 1600"),
           "2025-12-31 is excluded (amendment scan): visible only through the gapped pair"),
    _typed("changelog:0001588272:explicit_member_identity", "0001588272", "2023-03-31",
           {"position_identity": [IDENTIFIER_FIELD]}, "changelog",
           "docs/agent_changelog.md:11930 (2026-09-12 NexPoint explicit members on dei:LegalEntityAxis, Q1-2023)",
           dict(type="doc_line", path="docs/agent_changelog.md", line=11930,
                contains="explicit members on `dei:LegalEntityAxis`"),
           "identity format; position_identity is deferred (unchecked)", expect="not_covered"),
    _typed("changelog:0001860424:explicit_member_identity", "0001860424", "2023-03-31",
           {"position_identity": [IDENTIFIER_FIELD]}, "changelog",
           "docs/agent_changelog.md:12397 (2026-09-15 Onex explicit-member rule, period 2023-03-31)",
           dict(type="doc_line", path="docs/agent_changelog.md", line=12397,
                contains="onex_explicit_investee_and_debt_type"),
           "identity format; position_identity is deferred (unchecked); 2023-03-31 failed validation",
           expect="not_covered")]
INCEPTION_ONLY = [dict(
    cik="0001588272", field="interest_rate", finding="interest_rate carries the spread for floating loans",
    source="<main>/" + SEMANTIC_CSV + " rows cik=0001588272 (text_vs_rate rate_equals_text_spread 13-14 per quarter)",
    reason="persistent from inception: no pair differs, so no pair test can detect it")]


class LimitExceeded(RuntimeError):
    """A pair's in-memory learn + evaluate exceeded the measured 60 s / 2 GiB bound."""


# ---------------------------------------------------------------- pairs

def _months(a: str, b: str) -> int:
    da, db = _date.fromisoformat(a), _date.fromisoformat(b)
    return (db.year - da.year) * 12 + db.month - da.month


def _pair(cik, mode, learn, ev, excluded, classes) -> dict:
    reasons = []
    if mode == "rolling":
        reasons = ["excluded:" + d + ":" + excluded[d] for d in sorted(excluded) if learn < d < ev]
        if not reasons and _months(learn, ev) > 3:
            reasons.append("calendar_gap:" + str(_months(learn, ev)) + "_months")
    pre = [side for side, d in (("learn", learn), ("eval", ev)) if classes.get(d) == "pre_tagging"]
    labels = [side + ":" + classes[d] for side, d in (("learn", learn), ("eval", ev))
              if classes.get(d) not in (None, "populated")]
    return dict(pair_id=mode + ":" + cik + ":" + learn + ":" + ev, cik=cik, mode=mode, learn_date=learn,
                eval_date=ev, gapped=bool(reasons) if mode == "rolling" else False, gap_reasons=reasons,
                status="pre_tagging" if pre else "evaluated", labels=labels)


def build_pairs(cik: str, dates, *, q1_date: str, excluded: dict, classes: dict) -> list:
    """Rolling (t-1, t) over consecutive authoritative quarters and anchored (q1, t) for t > q1."""
    dates = sorted(dates)
    out = [_pair(cik, "rolling", a, b, excluded, classes) for a, b in zip(dates, dates[1:])]
    out += [_pair(cik, "anchored", q1_date, d, excluded, classes) for d in dates if d > q1_date]
    return out


def classify_quarter(doc: dict) -> dict:
    """R37 quarter class from counts (recognised positions, position-like facts, facts)."""
    positions = int(doc["summary"]["position_observations_current"])
    dimensioned = {c["id"] for c in doc.get("contexts") or [] if c.get("dimensions") or c.get("typed_dimensions")}
    fields = set(POSITION_FIELDS)
    position_like = sum(1 for f in doc["facts"] if f.get("field") in fields and f.get("context_id") in dimensioned)
    facts = len(doc["facts"])
    if positions > 0:
        cls = "populated"
    elif position_like >= POSITION_LIKE_MIN:
        cls = "recogniser_format"
    elif facts < COVER_ONLY_MAX_FACTS:
        cls = "pre_tagging"
    else:
        cls = "unverified_tagging"
    return {"class": cls, "positions": positions, "position_like_facts": position_like, "facts": facts,
            "rule": "R37"}


# ---------------------------------------------------------------- positives

def fingerprint_positives(rows, selected) -> dict:
    """Positives where the rate-concept fingerprint of a selected accession differs from the previous one.

    rows: fingerprint CSV rows (cik without padding, accession without dashes); selected: (cik10, quarter,
    accession) of every SELECTED fund-quarter of the census inventory. Class presence (count > 0) is compared;
    bare/cash -> interest_rate, pik -> pik_rate, floor -> interest_rate_floor; an ext change is recorded with
    polarity not_a_position_event (EXT_REASON) and never scored."""
    by_acc = {(str(int(r["cik"])), str(r["accession"]).replace("-", "")): r for r in rows}
    positives, unmapped, seq = [], [], {}
    for cik, quarter, acc in sorted(selected):
        row = by_acc.get((str(int(cik)), str(acc).replace("-", "")))
        if row is None:
            unmapped.append((cik, quarter, acc))
            continue
        seq.setdefault(cik, []).append((quarter, acc, {n for n, col, _ in FINGERPRINT_CLASSES if int(row[col] or 0) > 0}))
    for cik, items in seq.items():
        for (_, pacc, before), (quarter, acc, after) in zip(items, items[1:]):
            changed = sorted(before ^ after)
            groups: dict = {}
            for name, _, fields in FINGERPRINT_CLASSES:
                if name in changed:
                    groups.setdefault(fields, []).append(name)
            for fields, names in sorted(groups.items(), key=lambda kv: (kv[0] is None, kv[0] or ())):
                ext = fields is None
                positives.append(dict(
                    positive_id="fingerprint:" + cik + ":" + quarter + ":" + "+".join(names), cik=cik, date=quarter,
                    targets={} if ext else {"source_concept_set": list(fields)}, category="rate_tag_fingerprint",
                    polarity="not_a_position_event" if ext else "positive", attach="eval",
                    **({"reason": EXT_REASON} if ext else {}),
                    source="data/" + FINGERPRINT_CSV + " accessions " + pacc + " -> " + acc,
                    note="classes " + ",".join(sorted(before)) + " -> " + ",".join(sorted(after)) + " (changed: "
                         + ",".join(names) + ")", expect="covered"))
    return dict(positives=positives, unmapped_selected=unmapped)


def ledger_positives(rows) -> list:
    out = []
    for r in rows:
        targets = LEDGER_RULES.get(r["rule_name"])
        if targets is None or r["state"] not in LEDGER_STATES + (LEDGER_NEGATIVE_STATE,):
            continue
        negative = r["state"] == LEDGER_NEGATIVE_STATE
        out.append(dict(positive_id="ledger:" + r["review_id"], cik=str(r["cik"]).zfill(10),
                        date=str(r["report_date"])[:10], targets={k: list(v) for k, v in targets.items()},
                        category="findings_ledger", polarity="recorded_negative" if negative else "positive",
                        attach="eval", source="data/" + LEDGER_CSV + " review_id=" + r["review_id"] + " state="
                        + r["state"] + " rule=" + r["rule_name"], note=r["rule_name"],
                        expect="covered",
                        **({"not_covered_kinds": dict(LEDGER_NOT_COVERED_KINDS[r["rule_name"]])}
                           if r["rule_name"] in LEDGER_NOT_COVERED_KINDS else {})))
    return out


def _not_covered(p: dict, kind: str):
    """Why a positive row claims no result for this kind (whole row or per kind), or None."""
    return p.get("not_covered_reason") or (p.get("not_covered_kinds") or {}).get(kind)


def recogniser_positives(classes: dict) -> list:
    out = []
    for (cik, day), info in sorted(classes.items()):
        if info["class"] != "recogniser_format":
            continue
        for field in sorted(POSITION_FIELDS):  # one positive per field: "on every field" (R37)
            out.append(dict(positive_id="recogniser:" + cik + ":" + day + ":" + field, cik=cik, date=day,
                            targets={"fill_rate": [field], "source_concept_set": [field]},
                            category="recogniser_format", polarity="positive", attach="eval_and_learn",
                            source="B2-2a review I1 (ruling R37): 0 recognised positions, "
                                   + str(info.get("position_like_facts")) + " position-like facts",
                            note="recogniser-format event; scored on the pairs on both sides", expect="covered"))
    return out


def _dotted(body, key):
    for part in key.split("."):
        body = (body or {}).get(part)
    return body


def verify_typed(paths, rows, *, d07_computed: set) -> list:
    """Re-check every typed row against its source; returns one record per row (never raises)."""
    out = []
    for row in rows:
        check = row["check"]
        ok, detail = False, None
        try:
            if check["type"] == "d07":
                ok = (row["cik"], row["date"]) in d07_computed
            elif check["type"] == "json_scope":
                body = json.loads((paths.code_root / check["path"]).read_text(encoding="utf-8"))
                got = {k: _dotted(body, k) for k in check["expect"]}
                ok = got == check["expect"] and row["date"] in ((body.get("scope") or {}).get("quarters") or [])
                detail = got
            elif check["type"] == "csv_row":
                path = paths.main_repo_root / check["path"]
                with open(path, encoding="utf-8", newline="") as stream:
                    hits = [r for r in csv.DictReader(stream) if all(r.get(k) == v for k, v in check["key"].items())]
                ok = len(hits) == 1 and all(hits[0].get(k) == v for k, v in check["expect"].items())
                detail = {k: hits[0].get(k) for k in check["expect"]} if hits else "row not found"
            elif check["type"] == "doc_line":
                lines = (paths.code_root / check["path"]).read_text(encoding="utf-8").splitlines()
                text = lines[check["line"] - 1] if len(lines) >= check["line"] else ""
                ok = check["contains"] in text
                detail = text[:160].encode("ascii", "backslashreplace").decode("ascii")
        except (OSError, ValueError, KeyError) as exc:
            detail = type(exc).__name__ + ": " + str(exc)[:160]
        out.append(dict(positive_id=row["positive_id"], check=check["type"], verified=bool(ok), detail=detail))
    return out


# ---------------------------------------------------------------- learning (in memory)

def learn_block(cik: str, doc: dict, *, tolerances: dict, grammar, yield_ev: dict, recorded_at: str, derive) -> dict:
    """contracts.learn_contracts on one quarter; a zero-position quarter keeps the full denominator
    (every (kind, field) of the suite, whole filing) as insufficient_evidence."""
    positions = current_positions(doc)
    profile = derive(doc) if positions else None
    block = contracts.learn_contracts(cik=cik, q1_doc=doc, q1_profile=profile, grammar=grammar, yield_q1=yield_ev,
                                      tolerances=tolerances, recorded_at=recorded_at,
                                      q2_listing=dict(status="backtest", note="evaluation quarter set per pair"))
    if positions:
        return block
    whole = dict(partition_id=WHOLE_FILING, applies_to=None)
    have = {(c["kind"], c["field"], c["partition_id"]) for c in block["contracts"]}
    tier = block["tier"]
    added = []
    kinds = contracts.ALL_KINDS if contracts.has_semantic_bands(tolerances) else contracts.KINDS
    for kind in kinds:
        for field in SUITE[kind]:
            if (kind, field, WHOLE_FILING) in have:
                continue
            added.append(contracts._contract(cik, kind, field, whole, tier, contracts.band_for(tolerances, tier, kind),
                                             cause=ZERO_LEARN_CAUSE,
                                             evidence=dict(note="0 recognised current positions in the learning "
                                                                "quarter (R37): every contract abstains")))
    order = {k: i for i, k in enumerate(contracts.ALL_KINDS)}
    block["contracts"] = sorted(added + block["contracts"], key=lambda c: order[c["kind"]])
    block["zero_position_learning"] = True
    return block


def slim_view(doc: dict) -> dict:
    """Only what the S2 adapter reads from a census (currency / meaning / income facts)."""
    positions = []
    for p in current_positions(doc):
        fields = p.get("fields") or {}
        positions.append(dict(context_id=p["context_id"], period=dict(instant=p["period"].get("instant")),
                              fields=dict(principal_amount=dict(currency=(fields.get("principal_amount") or {})
                                                                .get("currency")),
                                          interest_rate=dict(concepts=(fields.get("interest_rate") or {})
                                                             .get("concepts")))))
    income = [dict(field=i.get("field"), period=i.get("period"), currency=i.get("currency"))
              for i in doc.get("fund_income") or [] if i.get("field") in contracts_income.INCOME_FIELDS]
    return dict(document_metadata=dict(document_period_end_dates=list(
        doc["document_metadata"]["document_period_end_dates"])), positions=positions, fund_income=income)


def income_window(day: str, *, prev, gapped: bool, min_quarters: int) -> list:
    if min_quarters >= 2 and prev and not gapped:
        return [prev, day]
    return [day]


def yield_evidence(paths, *, cik, day, window, slims, holdings_path, income_path, min_quarters) -> dict:
    import pandas as pd
    frames, inc = [], None
    for d in window:
        h, i = contracts_income.read_quarter_frames(paths, holdings_path=holdings_path, income_path=income_path,
                                                    cik=cik, report_date=d)
        frames.append(h)
        inc = i
    holdings = pd.concat(frames, ignore_index=True)
    ev = contracts_income.income_evidence(holdings, inc, cik=cik, report_date=day, census_doc=slims[day],
                                          window=window, window_docs={d: slims[d] for d in window},
                                          cwd=lambda: pilot_cwd(paths), min_quarters=min_quarters)
    return contracts_income._json_safe(ev)


def pair_timing(learn_timing: dict, eval_timing: dict, *, peak: int) -> dict:
    learn = round(float(learn_timing.get("learn_seconds") or 0.0), 3)
    ev = round(float(eval_timing.get("evaluate_seconds") or 0.0), 3)
    measured = round(learn + ev, 3)
    return dict(learn_seconds=learn, evaluate_seconds=ev, measured_seconds=measured, peak_bytes=int(peak),
                within_bound=measured <= LIMIT_SECONDS and peak <= LIMIT_BYTES,
                rule="R35: learn (profile + learn_contracts + learning-quarter yield) + evaluate (evaluate_contracts "
                     "+ evaluation-quarter yield); census load timed apart; peak is process-wide")


def _trim(r: dict) -> dict:
    keys = list(r["violating_keys"])
    return dict(contract_id=r["contract_id"], kind=r["kind"], field=r["field"], partition_id=r["partition_id"],
                status=r["status"], cause=r["cause"], n_violating=len(keys),
                violating_keys=keys if r["status"] == "breach" else [],
                expected=contracts._brief(r["expected"]), observed=contracts._brief(r["observed"]),
                identifier_format_unresolved=r["identifier_format_unresolved"], q2_form_type=r["q2"].get("form_type"),
                newly_abstained=bool(r.get("newly_abstained")))


def strict(results: list) -> list:
    return [dict(r, violating_keys=r["violating_keys"] if s["status"] == "breach" else [], status=s["status"],
                 cause=s["cause"]) for r, s in zip(results, contracts.strict_results(results))]


# ---------------------------------------------------------------- scoring

def _group(field: str) -> tuple:
    return next((g for g in FIELD_GROUPS if field in g), (field,))


def _attached(pair: dict, positives: list) -> tuple:
    hits, carried = [], []
    for p in positives:
        if p["cik"] != pair["cik"]:
            continue
        on_learn = p.get("attach") == "eval_and_learn" and p["date"] == pair["learn_date"]
        if pair["mode"] == "rolling":
            if pair["learn_date"] < p["date"] <= pair["eval_date"] or on_learn:
                hits.append(p)
        elif p["date"] == pair["eval_date"] or on_learn:
            hits.append(p)
        elif pair["learn_date"] < p["date"] < pair["eval_date"]:
            carried.append(p)
    return hits, carried


def _targets(items: list) -> set:
    """(kind, field) targets the rows claim a result for (a not-covered row or kind claims none)."""
    return {(kind, field) for p in items for kind, fields in p["targets"].items() if not _not_covered(p, kind)
            for field in fields}


def _blank_pos() -> dict:
    return dict(units=0, not_covered=0, no_contract=0, detected=0, abstained=0, missed=0, field_mismatch=0,
                abstained_newly=0, abstained_carried=0)


def _blank_neg() -> dict:
    return dict(n=0, holds=0, breach=0, insufficient_evidence=0, holds_with_form_type=0, recorded_negative=0,
                recorded_negative_breach=0, insufficient_newly=0)


def _finish(block: dict) -> dict:
    pos, neg = block["positives"], block["negatives"]
    covered = pos["detected"] + pos["abstained"] + pos["missed"]
    pos["covered"] = covered
    pos["recall"] = round(pos["detected"] / covered, 4) if covered else None
    pos["abstention_rate"] = round(pos["abstained"] / covered, 4) if covered else None
    decided = neg["holds"] + neg["breach"]
    neg["breach_rate_upper_bound"] = round(neg["breach"] / neg["n"], 4) if neg["n"] else None
    neg["breach_rate_of_decided"] = round(neg["breach"] / decided, 4) if decided else None
    neg["abstention_rate"] = round(neg["insufficient_evidence"] / neg["n"], 4) if neg["n"] else None
    return block


def score(pairs: list, results: dict, positives: list, *, mode: str, exclude_categories=()) -> dict:
    """Score one mode x one reading (results = pair_id -> contract results under that reading)."""
    use = [p for p in positives if p["category"] not in exclude_categories]
    pos_rows = [p for p in use if p["polarity"] == "positive"]
    neg_rows = [p for p in use if p["polarity"] == "recorded_negative"]
    by_kind, by_kind_cik, units, unadjudicated, adjudicated = {}, {}, [], [], []
    slot = lambda kind, cik: (by_kind.setdefault(kind, dict(positives=_blank_pos(), negatives=_blank_neg(), carried=0)),
                              by_kind_cik.setdefault(kind + ":" + cik, dict(positives=_blank_pos(),
                                                                            negatives=_blank_neg(), carried=0)))
    mine = [p for p in pairs if p["mode"] == mode]
    for pair in mine:
        if pair["status"] != "evaluated":
            continue
        res = results.get(pair["pair_id"]) or []
        hits, carried = _attached(pair, pos_rows)
        negs, _ = _attached(pair, neg_rows)
        for p in hits:
            others = _targets([q for q in hits if q is not p])
            for kind, fields in sorted(p["targets"].items()):
                covered = [] if _not_covered(p, kind) else [f for f in fields if f in SUITE.get(kind, ())]
                unit = dict(positive_id=p["positive_id"], category=p["category"], pair_id=pair["pair_id"],
                            cik=pair["cik"], learn_date=pair["learn_date"], eval_date=pair["eval_date"],
                            gapped=pair["gapped"], kind=kind, fields=list(fields), field_mismatch=[])
                matched = [r for r in res if r["kind"] == kind and r["field"] in covered]
                if not covered:
                    unit["outcome"] = "not_covered"
                    unit["not_covered_reason"] = _not_covered(p, kind) or "no contract kind covers the field"
                elif not matched:
                    unit["outcome"] = "no_contract"
                elif any(r["status"] == "breach" for r in matched):
                    unit["outcome"] = "detected"
                elif any(r["status"] == "insufficient_evidence" for r in matched):
                    unit["outcome"] = "abstained"
                    unit["abstained"] = "newly" if any(r.get("newly_abstained") for r in matched
                                                       if r["status"] == "insufficient_evidence") else "carried"
                else:
                    unit["outcome"] = "missed"
                unit["statuses"] = [[r["field"], r["status"], r["cause"]] for r in matched]
                if unit["outcome"] != "detected":
                    near = {g for f in fields for g in _group(f)}
                    unit["field_mismatch"] = [dict(kind=r["kind"], field=r["field"]) for r in res
                                              if r["status"] == "breach" and r["field"] in near
                                              and not (r["kind"] == kind and r["field"] in covered)
                                              and (r["kind"], r["field"]) not in others]
                units.append(unit)
                for block in slot(kind, pair["cik"]):
                    b = block["positives"]
                    b["units"] += 1
                    b[unit["outcome"]] += 1
                    if unit["outcome"] == "abstained":
                        b["abstained_" + unit["abstained"]] += 1
                    b["field_mismatch"] += bool(unit["field_mismatch"])
        # a not_covered row claims no result: its target results stay negatives
        targeted = _targets(hits)
        carried_targets = _targets(carried)
        neg_targets = {}
        for p in negs:
            for kind, fields in p["targets"].items():
                for field in fields:
                    neg_targets.setdefault((kind, field), []).append(p["positive_id"])
        for r in res:
            key = (r["kind"], r["field"])
            if key in targeted:
                continue
            blocks = slot(r["kind"], pair["cik"])
            if key in carried_targets:
                for block in blocks:
                    block["carried"] += 1
                continue
            recorded = neg_targets.get(key, [])
            for block in blocks:
                n = block["negatives"]
                n["n"] += 1
                n[r["status"]] += 1
                n["insufficient_newly"] += r["status"] == "insufficient_evidence" and bool(r.get("newly_abstained"))
                n["recorded_negative"] += bool(recorded)
                n["recorded_negative_breach"] += bool(recorded) and r["status"] == "breach"
            if r["status"] == "breach":
                item = dict(pair_id=pair["pair_id"], mode=mode, cik=pair["cik"], learn_date=pair["learn_date"],
                            eval_date=pair["eval_date"], gapped=pair["gapped"], kind=r["kind"], field=r["field"],
                            partition_id=r["partition_id"], cause=r["cause"], n_violating=r["n_violating"],
                            violating_keys=list(r["violating_keys"]), recorded_false_alarm=recorded)
                (adjudicated if recorded else unadjudicated).append(item)
    covered_dates = {}
    for pair in mine:
        for p in pos_rows:
            if p in _attached(pair, [p])[0]:
                covered_dates.setdefault(p["positive_id"], set()).add(pair["status"])
    unscorable = []
    for p in pos_rows:
        seen = covered_dates.get(p["positive_id"], set())
        if "evaluated" in seen:
            continue
        reason = "only_pre_tagging_pairs_cover_the_date" if seen else "no_evaluated_pair_covers_the_date"
        unscorable.append(dict(positive_id=p["positive_id"], cik=p["cik"], date=p["date"], category=p["category"],
                               reason=reason))
    unadjudicated.sort(key=lambda u: (-u["n_violating"], u["pair_id"], u["kind"], u["field"]))
    return dict(mode=mode, exclude_categories=list(exclude_categories),
                by_kind={k: _finish(v) for k, v in sorted(by_kind.items())},
                by_kind_cik={k: _finish(v) for k, v in sorted(by_kind_cik.items())},
                positive_units=units, unadjudicated=unadjudicated, adjudicated_false_alarm_breaches=adjudicated,
                unscorable=unscorable)


def _neg_cell() -> dict:
    return dict(n=0, breach=0, insufficient_evidence=0)


def _neg_finish(cell: dict) -> dict:
    cell["breach_rate_upper_bound"] = round(cell["breach"] / cell["n"], 4) if cell["n"] else None
    return cell


def _pos_cell() -> dict:
    return dict(units=0, detected=0, abstained=0, missed=0)


def semantic_negatives(pairs: list, grid_results: dict, positives: list, *, grid: list, tiers: dict,
                       mode: str = "rolling") -> dict:
    """Per candidate band (m2_seed._semantic_families): negatives n / breach / abstain (the named
    criterion for share_pp and iqr_widen, the status otherwise), split by the learning block's tier,
    the unadjudicated breaches with their keys, and the positive units the new kinds cover.

    grid_results: pair_id -> grid point name -> [[contract_id, kind, status, cause, criteria, keys]]."""
    pos_rows = [p for p in positives if p["polarity"] == "positive"]
    out: dict = {}
    for family, key, point, kind, criterion in m2_seed._semantic_families(grid):
        field = SUITE[kind][0]
        cell = dict(point=point, criterion=criterion or "status", all=_neg_cell(), standard=_neg_cell(),
                    low_history=_neg_cell(), unadjudicated=[], positives=_pos_cell(), positive_units=[])
        for pair in pairs:
            if pair["mode"] != mode or pair["status"] != "evaluated":
                continue
            hits, _ = _attached(pair, pos_rows)
            covered = _targets(hits)
            for cid, k, status, cause, criteria, keys in (grid_results.get(pair["pair_id"]) or {}).get(point, []):
                if k != kind:
                    continue
                hit = (criteria or {}).get(criterion) == "breach" if criterion else status == "breach"
                if (kind, field) in covered:
                    outcome = "detected" if hit else ("abstained" if status == "insufficient_evidence" else "missed")
                    cell["positives"]["units"] += 1
                    cell["positives"][outcome] += 1
                    cell["positive_units"].append(dict(pair_id=pair["pair_id"], contract_id=cid, outcome=outcome,
                                                       positives=[p["positive_id"] for p in hits]))
                    continue
                for tier in ("all", tiers.get(pair["pair_id"])):
                    if tier in cell:
                        c = cell[tier]
                        c["n"] += 1
                        c["breach"] += hit
                        c["insufficient_evidence"] += status == "insufficient_evidence"
                if hit:
                    cell["unadjudicated"].append(dict(pair_id=pair["pair_id"], cik=pair["cik"],
                                                      learn_date=pair["learn_date"], eval_date=pair["eval_date"],
                                                      gapped=pair["gapped"], contract_id=cid, cause=cause,
                                                      criteria=criteria, n_violating=len(keys),
                                                      violating_keys=list(keys)))
        for tier in ("all", "standard", "low_history"):
            _neg_finish(cell[tier])
        if not cell["positive_units"]:
            del cell["positive_units"]
        out.setdefault(family, {})[key] = cell
    return out


def median_shift_scores(pairs: list, ms: dict, positives: list, *, fields: dict, mode: str = "rolling") -> dict:
    """The median_shift experiment (calibration only, never in v3) on the value_range contracts:
    negatives and positive units per (x, y) candidate; ms: pair_id -> contract_id -> name -> verdict."""
    pos_rows = [p for p in positives if p["polarity"] == "positive"]
    names = sorted({n for per in ms.values() for verdicts in per.values() for n in verdicts})
    out = {n: dict(negatives=_neg_cell(), positives=_pos_cell()) for n in names}
    for pair in pairs:
        if pair["mode"] != mode or pair["status"] != "evaluated":
            continue
        hits, _ = _attached(pair, pos_rows)
        covered = _targets(hits)
        for cid, verdicts in sorted((ms.get(pair["pair_id"]) or {}).items()):
            targeted = ("value_range", fields[cid]) in covered
            for name in names:
                verdict = verdicts.get(name, "insufficient_evidence")
                if targeted:
                    p = out[name]["positives"]
                    p["units"] += 1
                    p[{"breach": "detected", "insufficient_evidence": "abstained"}.get(verdict, "missed")] += 1
                else:
                    n = out[name]["negatives"]
                    n["n"] += 1
                    n["breach"] += verdict == "breach"
                    n["insufficient_evidence"] += verdict == "insufficient_evidence"
    for name in names:
        _neg_finish(out[name]["negatives"])
    return out


TIER_BASIS = "pooled"
CALIBRATION_RULE = (
    "per CONTRACT (fix round 1, review I1): rate_composition is chosen on the joint share_pp x iqr_widen grid as the "
    "smallest point (ordered by share_pp, then iqr_widen) whose COMPOSITION-CONTRACT breach rate on negatives (upper "
    "bound, rolling / as-evaluated) is <= 10% and whose seeded detection fraction for spread_for_coupon (median over "
    "applicable CIKs of the smallest fraction >= 2 of 3 seeds breach the contract) is <= 0.30; text_agreement is "
    "chosen on text_share_pp by the same rule (target text_numeric_divergence). One tier basis for every band: "
    "pooled (all CIKs and tiers; both tiers take the chosen value). None = uncalibrated (curve reported); no v2 band "
    "is widened. Per-criterion rates (share, iqr, fixed) are recorded for the record, never used to choose")


def choose_band(curve: list, *, max_neg: float = 0.10, max_detection: float = 0.30, key=None) -> dict:
    key = key or (lambda r: r["value"])
    ok = [row for row in sorted(curve, key=key)
          if row["neg_rate"] is not None and row["neg_rate"] <= max_neg + 1e-12
          and row["detection"] is not None and row["detection"] <= max_detection + 1e-12]
    chosen = ok[0]["value"] if ok else None
    return dict(label=m2_seed.IN_SAMPLE, rule=CALIBRATION_RULE, curve=curve, chosen=chosen,
                status="calibrated" if ok else "uncalibrated",
                reason=("smallest candidate meeting both criteria" if ok else
                        "no candidate meets both criteria: uncalibrated, curve reported"))


X100_CAUSES = ("magnitude_regime_changed_under_same_declared_unit", "magnitude_mixed_under_one_declared_unit")


def newly_abstained_summary(pairs: list, results: dict, scoring: dict) -> dict:
    """Addendum 2: abstentions split newly / carried (rolling, as-evaluated), by kind, and for the
    recogniser-format positives and the x100 magnitude causes."""
    by_kind: dict = {}
    x100 = dict(newly=0, carried=0)
    for pair in pairs:
        if pair["mode"] != "rolling" or pair["status"] != "evaluated":
            continue
        for r in results.get(pair["pair_id"], []):
            if r["status"] != "insufficient_evidence":
                continue
            which = "newly" if r.get("newly_abstained") else "carried"
            by_kind.setdefault(r["kind"], dict(newly=0, carried=0))[which] += 1
            if r["cause"] in X100_CAUSES:
                x100[which] += 1
    units = scoring["rolling"]["as_evaluated"]["all"]["positive_units"]
    rf = dict(newly=0, carried=0)
    for u in units:
        if u["category"] == "recogniser_format" and u["outcome"] == "abstained":
            rf[u.get("abstained", "carried")] += 1
    totals = dict(newly=sum(v["newly"] for v in by_kind.values()), carried=sum(v["carried"] for v in by_kind.values()))
    return dict(by_kind=dict(sorted(by_kind.items())), recogniser_format_units=rf, x100_magnitude_causes=x100,
                totals=totals, rule=contracts.NEWLY_ABSTAINED_RULE)


def _curve(seed_curves: dict, negatives: dict, family: str, variant: str, det_tier: str, neg_tier: str,
           others=()) -> dict:
    rows = []
    for value in m2_seed.CANDIDATES["share_pp" if family == "fixed_share" else family]:
        key = str(value)
        cell = seed_curves[family][key][variant]
        neg = negatives[family][key][neg_tier]
        rows.append(dict(value=value, detection=cell["median"][det_tier], detected=cell["detected"][det_tier],
                         applicable=cell["applicable"][det_tier], neg_rate=neg["breach_rate_upper_bound"],
                         neg_n=neg["n"], neg_breach=neg["breach"],
                         other_classes={o: seed_curves[family][key][o]["median"][det_tier] for o in others
                                        if o in seed_curves[family][key]}))
    out = choose_band(rows)
    out.update(family=family, target=variant, detection_tier=det_tier, negatives_tier=neg_tier)
    return out


def _joint_curve(seed_curves: dict, negatives: dict, tier: str) -> dict:
    """rate_composition on the joint grid: the CONTRACT status decides; per-criterion rates recorded."""
    rows = []
    for s in m2_seed.CANDIDATES["share_pp"]:
        for i in m2_seed.CANDIDATES["iqr_widen"]:
            point = "c:s%s_i%s" % (s, i)
            cell = seed_curves["composition_status"][point]["spread_for_coupon"]
            neg = negatives["composition_status"][point][tier]
            per = dict(share=negatives["share_pp"][str(s)][tier]["breach_rate_upper_bound"],
                       iqr=negatives["iqr_widen"][str(i)][tier]["breach_rate_upper_bound"],
                       fixed=negatives["fixed_share"][str(s)][tier]["breach_rate_upper_bound"])
            rows.append(dict(value="s%s_i%s" % (s, i), share_pp=s, iqr_widen=i, detection=cell["median"][tier],
                             detected=cell["detected"][tier], applicable=cell["applicable"][tier],
                             neg_rate=neg["breach_rate_upper_bound"], neg_n=neg["n"], neg_breach=neg["breach"],
                             per_criterion=per))
    out = choose_band(rows, key=lambda r: (r["share_pp"], r["iqr_widen"]))
    if out["chosen"] is not None:
        row = next(r for r in rows if r["value"] == out["chosen"])
        out["chosen"] = dict(share_pp=row["share_pp"], iqr_widen=row["iqr_widen"])
    out.update(family="composition_status", target="spread_for_coupon", detection_tier=tier, negatives_tier=tier)
    return out


def assemble_calibration(seed_body: dict, negatives: dict, median_shift: dict, scoring: dict, *,
                         seed_run_id: str) -> dict:
    """The in-sample calibration per CONTRACT: seeded detection (seed root) x negatives breach rate (this root),
    on one tier basis (TIER_BASIS) for every band."""
    curves, tier = seed_body["curves"], {"pooled": "all"}[TIER_BASIS]
    bands = {"rate_composition": _joint_curve(curves, negatives, tier),
             "text_share_pp": _curve(curves, negatives, "text_share_pp", "text_numeric_divergence", tier, tier,
                                     others=("bps_spread_scale", "spread_for_coupon"))}
    criteria = {"share_pp": _curve(curves, negatives, "share_pp", "spread_for_coupon", tier, tier,
                                   others=("bps_spread_scale", "text_numeric_divergence")),
                "iqr_widen": _curve(curves, negatives, "iqr_widen", "spread_for_coupon", tier, tier,
                                    others=("bps_spread_scale",)),
                "fixed_share": _curve(curves, negatives, "fixed_share", "spread_for_coupon", tier, tier)}
    for c in criteria.values():
        c.update(status="record_only", chosen=None, reason="per-criterion curve, recorded; the contract decides")
    v2_range = scoring["rolling"]["as_evaluated"]["all"]["by_kind"].get("value_range", {}).get("negatives", {})
    ms = dict(label=m2_seed.IN_SAMPLE, adopted=False, note="calibration-only experiment (addendum 3): never in v3",
              v2_band=dict(seeded={v: seed_body["median_shift"][v]["v2_band"]["median"]["all"]
                                   for v in seed_body["median_shift"]},
                           negatives_rate=v2_range.get("breach_rate_upper_bound")),
              candidates={name: dict(seeded={v: seed_body["median_shift"][v][name]["median"]["all"]
                                             for v in seed_body["median_shift"] if name in seed_body["median_shift"][v]},
                                     negatives=cell["negatives"], positives=cell["positives"])
                          for name, cell in median_shift.items()})

    def slim(b):
        return [dict(value=r["value"], seeded_detection_fraction=r["detection"], negatives_breach_rate=r["neg_rate"],
                     negatives_n=r["neg_n"], **({"negatives_breach_rate_per_criterion": r["per_criterion"]}
                                                if "per_criterion" in r else {}))
                for r in b["curve"]]
    block = dict(label=m2_seed.IN_SAMPLE, rule=CALIBRATION_RULE, tier_basis=TIER_BASIS, seed_run_id=seed_run_id,
                 bands={name: dict(target=b["target"], status=b["status"], chosen=b["chosen"], reason=b["reason"],
                                   curve=slim(b)) for name, b in bands.items()},
                 criteria_record_only={name: dict(target=b["target"], curve=slim(b)) for name, b in criteria.items()},
                 median_shift_experiment=dict(adopted=False, candidates=list(ms["candidates"])))
    return dict(label=m2_seed.IN_SAMPLE, rule=CALIBRATION_RULE, tier_basis=TIER_BASIS, seed_run_id=seed_run_id,
                bands=bands, criteria=criteria, median_shift=ms, tolerances_block=block)


def render_semantic(sem: dict, calibration: dict | None) -> str:
    fmt = lambda v: "-" if v is None else ("%g" % v if isinstance(v, (int, float)) else str(v))
    lines = ["# M2 back-test: semantic kinds, newly-abstained events and the median_shift experiment ("
             + sem["run_id"] + ")", "", "Label: " + m2_seed.IN_SAMPLE + ".", "", "Caveat: " + NEGATIVES_CAVEAT, ""]
    neg = sem["negatives"]["rolling"]
    for family in ("share_pp", "fixed_share", "iqr_widen", "text_share_pp", "composition_status"):
        lines += ["## Negatives per candidate: " + family + " (rolling / as-evaluated)", "",
                  "| band | n | breach | abstain | breach rate UB | std n/breach | low n/breach | positives d/a/m |",
                  "|---|---|---|---|---|---|---|---|"]
        for key, cell in (neg.get(family) or {}).items():
            a, s, lo, p = cell["all"], cell["standard"], cell["low_history"], cell["positives"]
            lines.append("| " + " | ".join(fmt(x) for x in (
                key, a["n"], a["breach"], a["insufficient_evidence"], a["breach_rate_upper_bound"],
                "%d/%d" % (s["n"], s["breach"]), "%d/%d" % (lo["n"], lo["breach"]),
                "%d/%d/%d" % (p["detected"], p["abstained"], p["missed"]))) + " |")
        lines.append("")
    if calibration:
        lines += ["## Calibration (" + m2_seed.IN_SAMPLE + ")", "", CALIBRATION_RULE, ""]
        lines += ["Tier basis: " + calibration["tier_basis"], ""]
        for name, band in list(calibration["bands"].items()) + [("criterion:" + k, v) for k, v in
                                                               calibration["criteria"].items()]:
            lines += ["### " + name + " (target " + band["target"] + "): " + band["status"] + ", chosen "
                      + fmt(band["chosen"]), "", "| value | seeded detection | d/n | negatives breach rate | neg n | "
                      "per-criterion rates or other classes |", "|---|---|---|---|---|---|"]
            for r in band["curve"]:
                lines.append("| " + " | ".join(fmt(x) for x in (
                    r["value"], r["detection"], "%s/%s" % (r["detected"], r["applicable"]), r["neg_rate"], r["neg_n"],
                    json.dumps(r.get("per_criterion") or r.get("other_classes"), sort_keys=True))) + " |")
            lines.append("")
        ms = calibration["median_shift"]
        lines += ["## median_shift experiment (NOT adopted; beside the v2 value_range band)", "",
                  "v2 band: seeded " + json.dumps(ms["v2_band"]["seeded"], sort_keys=True) + "; negatives breach rate "
                  + fmt(ms["v2_band"]["negatives_rate"]), "", "| candidate | seeded (by class) | neg n | neg breach | "
                  "rate UB | positives d/a/m |", "|---|---|---|---|---|---|"]
        for name, c in ms["candidates"].items():
            p = c["positives"]
            lines.append("| " + " | ".join(fmt(x) for x in (
                name, json.dumps(c["seeded"], sort_keys=True), c["negatives"]["n"], c["negatives"]["breach"],
                c["negatives"]["breach_rate_upper_bound"], "%d/%d/%d" % (p["detected"], p["abstained"],
                                                                        p["missed"]))) + " |")
        lines.append("")
    newly = sem["newly_abstained"]
    lines += ["## Newly abstained vs carried (rolling / as-evaluated)", "", contracts.NEWLY_ABSTAINED_RULE, "",
              "- totals: " + json.dumps(newly["totals"], sort_keys=True),
              "- recogniser_format positive units: " + json.dumps(newly["recogniser_format_units"], sort_keys=True),
              "- x100 magnitude causes: " + json.dumps(newly["x100_magnitude_causes"], sort_keys=True),
              "- by kind: " + json.dumps(newly["by_kind"], sort_keys=True), "",
              "## Inception blocks (first learned quarter per CIK; evidence, not a status)", ""]
    for cik, by_day in sorted(sem["inception"].items()):
        days = [d for d in sorted(by_day) if any(i.get("inception") for i in by_day[d])]
        if not days:
            continue
        day = days[0]
        for item in by_day[day]:
            inc = item.get("inception") or {}
            lines.append("- " + cik + " " + day + " " + item["kind"] + ": share_rate_le_spread "
                         + fmt(inc.get("share_rate_le_spread")) + ", rate_equals_text_spread "
                         + json.dumps(inc.get("rate_equals_text_spread"), sort_keys=True) + ", magnitude-normalised "
                         + json.dumps((inc.get("rate_equals_text_spread_magnitude_normalised") or {}).get("share"))
                         + ", implied base p50 " + fmt(inc.get("implied_base_p50")))
    text = "\n".join(lines) + "\n"
    text.encode("ascii")
    return text


def score_all(pairs: list, results_by_reading: dict, positives: list, *, modes=MODES) -> dict:
    return {mode: {reading: {name: score(pairs, results_by_reading[reading], positives, mode=mode,
                                         exclude_categories=excl)
                             for name, excl in POSITIVE_SETS.items()}
                   for reading in READINGS} for mode in modes}


# ---------------------------------------------------------------- rendering

def _pct(v) -> str:
    return "-" if v is None else "%.1f%%" % (100 * v)


def _kind_table(block: dict) -> list:
    lines = ["| kind | pos units | not covered | detected | abstained | missed | field mismatch | recall | "
             "neg n | neg breach | neg abstain | breach rate (upper bound) | breach rate of decided | carried |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for kind in KNOWN_KINDS:
        v = block["by_kind"].get(kind)
        if not v:
            continue
        p, n = v["positives"], v["negatives"]
        lines.append("| " + " | ".join(str(x) for x in (
            kind, p["units"], p["not_covered"] + p["no_contract"], p["detected"], p["abstained"], p["missed"],
            p["field_mismatch"], _pct(p["recall"]), n["n"], n["breach"], n["insufficient_evidence"],
            _pct(n["breach_rate_upper_bound"]), _pct(n["breach_rate_of_decided"]), v["carried"])) + " |")
    return lines


def render_recall(*, run_id: str, scoring: dict, context: dict) -> str:
    lines = ["# M2 back-test against recorded history (" + run_id + ")", "",
             "Frozen tolerances v2 (content_sha256 " + TOLERANCES_V2_SHA256[:12] + "...). Learning profile: "
             + str(context.get("profile_mode")) + ". " + PROFILE_NOTE + ".", "",
             "Caveat: " + NEGATIVES_CAVEAT, "",
             "Yield: " + YIELD_WINDOW_NOTE + ".", "",
             "Quarter classes: " + QUARTER_CLASS_RULE, "",
             "Recall = detected / (detected + abstained + missed); abstention is not detection. Rolling (learn t-1, "
             "evaluate t) is the primary reading; anchored (learn the Stage B q1) is secondary. A rolling pair "
             "collects every positive dated in (t-1, t] (gapped pairs included, flagged); an anchored pair collects "
             "positives dated t, and results whose (kind, field) had a positive strictly between q1 and t are "
             "'carried' (neither positive nor negative). Field mismatch = not detected on the target, but a breach "
             "by another kind or on a neighbouring field at the same pair.", ""]
    for mode in scoring:
        for reading in READINGS:
            for name in POSITIVE_SETS:
                title = mode + " / " + reading + " / " + ("all positives" if name == "all"
                                                         else "without recogniser_format positives")
                lines += ["## " + title, ""] + _kind_table(scoring[mode][reading][name]) + [""]
    main = scoring.get("rolling", {}).get("as_evaluated", {}).get("all")
    if main:
        lines += ["## Per CIK x kind (rolling / as_evaluated / all positives)", "",
                  "| cik:kind | pos units | detected | abstained | missed | not covered | neg n | neg breach | "
                  "neg abstain |", "|---|---|---|---|---|---|---|---|---|"]
        for key, v in main["by_kind_cik"].items():
            p, n = v["positives"], v["negatives"]
            lines.append("| " + " | ".join(str(x) for x in (
                key, p["units"], p["detected"], p["abstained"], p["missed"], p["not_covered"] + p["no_contract"],
                n["n"], n["breach"], n["insufficient_evidence"])) + " |")
        lines += ["", "## Unadjudicated breaches on negatives, top 30 by violating keys (rolling / as_evaluated)", "",
                  "| cik | learn -> eval | gapped | kind | field | cause | violating keys | sample keys |",
                  "|---|---|---|---|---|---|---|---|"]
        for u in main["unadjudicated"][:30]:
            lines.append("| " + " | ".join(str(x) for x in (
                u["cik"], u["learn_date"] + " -> " + u["eval_date"], u["gapped"], u["kind"], u["field"], u["cause"],
                u["n_violating"], ", ".join(u["violating_keys"][:3]))) + " |")
        lines += ["", "Total unadjudicated (rolling / as_evaluated): " + str(len(main["unadjudicated"]))
                  + "; breaches on recorded false alarms: " + str(len(main["adjudicated_false_alarm_breaches"])), "",
                  "## Positive units by outcome (rolling / as_evaluated / all positives)", "",
                  "| positive | category | pair | kind | outcome | field mismatch |", "|---|---|---|---|---|---|"]
        for u in main["positive_units"]:
            if u["category"] == "recogniser_format":
                continue
            lines.append("| " + " | ".join(str(x) for x in (
                u["positive_id"], u["category"], u["learn_date"] + " -> " + u["eval_date"]
                + (" (gapped)" if u["gapped"] else ""), u["kind"], u["outcome"],
                ";".join(m["kind"] + "/" + m["field"] for m in u["field_mismatch"]) or "-")) + " |")
        rf = [u for u in main["positive_units"] if u["category"] == "recogniser_format"]
        counts: dict = {}
        for u in rf:
            counts[(u["pair_id"], u["outcome"])] = counts.get((u["pair_id"], u["outcome"]), 0) + 1
        lines += ["", "recogniser_format units (" + str(len(rf)) + "): "
                  + ("; ".join(k[0] + " " + k[1] + " x" + str(v) for k, v in sorted(counts.items())) or "none"), ""]
        lines += ["## Coverage gaps (positives no contract kind covers)", ""]
        gaps = sorted({(u["positive_id"], u["kind"]) for mode_block in scoring.values()
                       for u in mode_block["as_evaluated"]["all"]["positive_units"] if u["outcome"] == "not_covered"})
        gaps_rows = [p for p in context.get("positives", []) if p.get("polarity") == "positive" and (
            p.get("not_covered_reason") or any(k not in SUITE or not set(f) & set(SUITE[k])
                                              for k, f in p["targets"].items()))]
        for p in gaps_rows:
            lines.append("- " + p["positive_id"] + " (" + p["date"] + ", " + p["category"] + "): "
                         + json.dumps(p["targets"], sort_keys=True) + " -- " + p["source"]
                         + (" -- " + p["not_covered_reason"] if p.get("not_covered_reason") else ""))
        excluded_rows = [p for p in context.get("positives", []) if p.get("polarity") == "not_a_position_event"]
        lines += ["", "Recorded but not scored (not a position event):"]
        lines += ["- " + p["positive_id"] + ": " + p["reason"] for p in excluded_rows] or ["- none"]
        lines += ["- scored not_covered units: " + str(len(gaps)), "", "## Unscorable positives (rolling)", ""]
        for u in main["unscorable"]:
            lines.append("- " + u["positive_id"] + " " + u["date"] + ": " + u["reason"])
        if not main["unscorable"]:
            lines.append("- none")
    lines += ["", "## Inception-only semantics (undetectable by any pair test)", ""]
    for item in context.get("inception_only", []):
        lines.append("- " + item["cik"] + " " + item["field"] + ": " + item["finding"] + " (" + item["source"] + ")")
    lines += ["", "## Quarter classes other than populated", ""]
    for key, info in sorted((context.get("classes") or {}).items()):
        if info["class"] != "populated":
            lines.append("- " + key + ": " + info["class"] + " (positions " + str(info["positions"])
                         + ", position-like " + str(info["position_like_facts"]) + ", facts " + str(info["facts"]) + ")")
    lines += ["", "## Yield contract (fund_income_yield) per CIK", ""]
    for cik, y in sorted((context.get("yields") or {}).items()):
        lines.append("- " + cik + ": " + json.dumps(y, sort_keys=True))
    lines += ["", "## Learning reproduction at the Stage B q1 (vs the frozen contract_inventory block)", ""]
    for cik, r in sorted((context.get("reproduction") or {}).items()):
        lines.append("- " + cik + ": equal=" + str(r.get("equal")) + " differences=" + str(len(r.get("differences", []))))
    lines += ["", "## Timing extremes (R35: learn + evaluate per pair)", ""]
    for key, value in sorted((context.get("timing") or {}).items()):
        lines.append("- " + key + ": " + json.dumps(value, sort_keys=True))
    text = "\n".join(lines) + "\n"
    text.encode("ascii")
    return text


def render_csv(header, rows) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


# ---------------------------------------------------------------- the stage

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_run_id(now: datetime | None = None) -> str:
    return RUN_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")


def _query(paths, sql: str, params) -> list:
    con = pilot_duckdb(paths)
    try:
        cur = con.execute(sql, params)
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]
    finally:
        con.close()


def load_sources(paths, ciks, census_paths) -> dict:
    """Source files for the positives (read only; each recorded with its sha256)."""
    plain = [str(int(c)) for c in ciks]
    records = [m2_seed._record(paths.data_root / rel, "data/" + rel) for rel in (FINGERPRINT_CSV, ORACLE_CSV, LEDGER_CSV)]
    records.append(m2_seed._record(paths.main_repo_root / SEMANTIC_CSV, "main/" + SEMANTIC_CSV))
    for row in TYPED_POSITIVES:
        if row["check"]["type"] in ("json_scope", "doc_line"):
            rel = row["check"]["path"]
            if not any(r["label"] == "code/" + rel for r in records):
                records.append(m2_seed._record(paths.code_root / rel, "code/" + rel))
    fp_rows = _query(paths, "SELECT * FROM read_csv(?, all_varchar=true, header=true) WHERE cik IN (SELECT unnest(?))",
                     [str(paths.data_root / FINGERPRINT_CSV), plain])
    d07 = _query(paths, "SELECT cik, substr(report_date, 1, 10) AS report_date, metric_value FROM read_csv(?, "
                        "all_varchar=true, header=true) WHERE check_id = 'D07' AND status = 'fail' AND "
                        "CAST(metric_value AS DOUBLE) > 300 AND lpad(cik, 10, '0') IN (SELECT unnest(?))",
                 [str(paths.data_root / ORACLE_CSV), list(ciks)])
    ledger = _query(paths, "SELECT review_id, state, lpad(cik, 10, '0') AS cik, rule_name, substr(report_date, 1, 10) "
                           "AS report_date FROM read_csv(?, all_varchar=true, header=true) WHERE lpad(cik, 10, '0') "
                           "IN (SELECT unnest(?)) AND state IN (SELECT unnest(?)) AND rule_name IN (SELECT unnest(?)) "
                           "ORDER BY review_id",
                    [str(paths.data_root / LEDGER_CSV), list(ciks), list(LEDGER_STATES + (LEDGER_NEGATIVE_STATE,)),
                     list(LEDGER_RULES)])
    inventory = manifest.load_inventory(census_paths, "primary_quarter_inventory")
    selected = [(r["cik"], r["quarter"], r["accession_number"]) for r in inventory["fund_quarters"]
                if r.get("status") == "selected" and r["cik"] in ciks and r.get("accession_number")]
    return dict(records=records, fingerprint_rows=fp_rows, d07={(str(r["cik"]).zfill(10), r["report_date"])
                                                                for r in d07}, ledger=ledger, selected=selected)


def _stage_timing(timing: dict) -> dict:
    out = {k: round(v, 3) for k, v in sorted(timing.items())}
    out["learn_seconds"] = round(out.get("profile_seconds", 0.0) + out.get("learn_contracts_seconds", 0.0)
                                 + out.get("yield_seconds", 0.0), 3)
    return out


def run_stage(paths, *, census_run_id: str, contracts_run_id: str, ciks=None, scratch_dir: Path | None = None,
              semantic: bool = False, seed_run_id: str | None = None) -> dict:
    ciks = list(ciks or cohort.PILOT_CIKS)
    started = time.perf_counter()
    clock = dict(started_utc=_now())
    recorded_at = clock["started_utc"]
    probe = lineage.load_authoritative_census(paths, census_run_id, roles=(), ciks=ciks, hash_files=False,
                                              require_excluded=True)
    roles = sorted({r["role"] for r in probe["listing"]["fund_quarters"] if r["cik"] in ciks})
    census = lineage.load_authoritative_census(paths, census_run_id, roles=roles, ciks=ciks,
                                               label_prefix="census_root/", require_excluded=True)
    excluded_body = json.loads(Path(census["excluded"]["path"]).read_text(encoding="ascii"))
    excluded = {c: {r["report_date"]: r["reason"] + ("/" + r["detail"] if r.get("detail") else "")
                    for r in excluded_body["fund_quarters"] if r["cik"] == c} for c in ciks}
    rows_by_cik = {c: sorted((r for (cc, _), r in census["rows"].items() if cc == c), key=lambda r: r["report_date"])
                   for c in ciks}
    q1 = {}
    for c in ciks:
        if (c, "q1") not in census["rows"]:
            raise StageInvalidated("no authoritative Stage B q1 census for " + c)
        q1[c] = census["rows"][(c, "q1")]["report_date"]
        dates = [r["report_date"] for r in rows_by_cik[c]]
        if len(set(dates)) != len(dates):
            raise StageInvalidated("two authoritative censuses for one quarter: " + c)
    cpaths = lineage.sibling_root(paths, contracts_run_id)
    croot = cpaths.run_root
    cman_rec = m2_seed._record(croot / "manifest.json", "contracts_root/manifest.json")
    cman = json.loads(Path(cman_rec["path"]).read_text(encoding="ascii"))
    tolerances, tol_rec = m2_seed.pin_tolerances(croot / "inventories" / "contract_tolerances.json")
    inv_rec = m2_seed._record(croot / "inventories" / "contract_inventory.json",
                              "contracts_root/inventories/contract_inventory.json")
    inventory = manifest.load_inventory(cpaths, "contract_inventory")
    if inventory["tolerances"]["content_sha256"] != TOLERANCES_V2_SHA256:
        raise StageInvalidated("contract_inventory was frozen against other tolerances")
    slices = {}
    for name in ("private_markets_holdings_pilot8.parquet", "bdc_fund_income_pilot8.parquet"):
        rec = m2_seed._record(croot / "inputs" / name, "contracts_root/inputs/" + name)
        pinned = next((s for s in cman["slices"] if s["label"].endswith(name)), None)
        if pinned is None or pinned["sha256"] != rec["sha256"]:
            raise StageInvalidated("contracts root slice differs from its manifest: " + name)
        slices[name] = rec
    grammars, grammar_recs = {}, {}
    for c in ciks:
        grammars[c], grammar_recs[c] = contracts_run.pin_grammar(paths, c)
        want = [(g["sha256"], g["dialect"]) for g in inventory["ciks"][c]["grammar"] or []]
        got = [(grammars[c]["sha256"], grammars[c]["dialect"])] if grammars[c] else []
        if want != got:
            raise StageInvalidated("authored grammar differs from the one pinned in the frozen block: " + c)
    min_quarters = contracts.frozen_min_quarters(tolerances)
    sources = load_sources(paths, ciks, census["paths"])
    fingerprint = fingerprint_positives(sources["fingerprint_rows"], sources["selected"])
    ledger = ledger_positives(sources["ledger"])
    typed = [r for r in TYPED_POSITIVES if r["cik"] in ciks]
    checks = verify_typed(paths, typed, d07_computed=sources["d07"])
    d07_typed = {(r["cik"], r["date"]) for r in typed if r["category"] == "oracle_D07"}
    pre_rows = typed + fingerprint["positives"] + ledger
    code = [m2_seed._record(paths.code_root / rel, "code/" + rel, code_root=paths.code_root, blob_of=rel)
            for rel in CODE_FILES]
    config = dict(modes=list(MODES), readings=list(READINGS), positive_sets={k: list(v) for k, v in
                                                                            POSITIVE_SETS.items()},
                  profile_mode=PROFILE_MODE, profile_note=PROFILE_NOTE, yield_window=YIELD_WINDOW_NOTE,
                  min_quarters=min_quarters, recorded_at=recorded_at, quarter_class_rule=QUARTER_CLASS_RULE,
                  position_like_min=POSITION_LIKE_MIN, cover_only_max_facts=COVER_ONLY_MAX_FACTS,
                  limits=dict(seconds=LIMIT_SECONDS, bytes=LIMIT_BYTES), negatives_caveat=NEGATIVES_CAVEAT,
                  suite={k: list(v) for k, v in SUITE.items()}, ledger_rules=LEDGER_RULES)
    grid = learn_tol = sem_arg = None
    learn_tol = tolerances
    if semantic:
        grid = m2_seed.semantic_grid(tolerances)
        learn_tol = contracts.semantic_tolerances(tolerances, bands=contracts.SEMANTIC_BANDS, calibration=dict(
            label=m2_seed.IN_SAMPLE, status="learning reference only"))
        sem_arg = dict(grid=grid)
        config.update(semantic=True, label=m2_seed.IN_SAMPLE, learning_reference=manifest.digest(learn_tol),
                      grid=[dict(name=g["name"], family=g["family"], share_pp=g["share_pp"], iqr_widen=g["iqr_widen"],
                                 text_share_pp=g["text_share_pp"], content_sha256=manifest.digest(g["tolerances"]))
                            for g in grid],
                      median_shift=dict(m2_seed.MEDIAN_SHIFT, note="calibration-only experiment; not in v3"),
                      calibration_rule=CALIBRATION_RULE, seed_run_id=seed_run_id)
    seed_rec = seed_body = None
    if seed_run_id:
        if not semantic:
            raise StageInvalidated("--seed-run-id needs --semantic (calibration assembles the semantic curves)")
        sroot = lineage.sibling_root(paths, seed_run_id).run_root
        seed_rec = m2_seed._record(sroot / "results" / "semantic_curves.json", "seed_root/results/semantic_curves.json")
        seed_body = json.loads(Path(seed_rec["path"]).read_text(encoding="ascii"))
        if seed_body.get("label") != m2_seed.IN_SAMPLE or seed_body.get("candidates") != {
                k: list(v) for k, v in m2_seed.CANDIDATES.items()}:
            raise StageInvalidated("seed root semantic curves were not swept over the same candidates")
    keep = ("label", "path", "status", "sha256", "bytes")
    inputs = ([census["authoritative"], census["excluded"]] + census["files"] + [cman_rec, tol_rec, inv_rec]
              + list(slices.values()) + [r for recs in grammar_recs.values() for r in recs] + sources["records"] + code
              + ([seed_rec] if seed_rec else []))
    built = dict(
        run_id=paths.run_id, stage="m2_backtest", version=BACKTEST_VERSION, created_utc=_now(),
        git=dict(head=manifest.git_head(paths.code_root),
                 dirty_source_digest=manifest.dirty_source_digest(paths.code_root)["sha256"]),
        roots=dict(main_repo_root=str(paths.main_repo_root), code_root=str(paths.code_root),
                   data_root=str(paths.data_root), run_root=str(paths.run_root)),
        census_source=dict(run_id=census_run_id, roles=roles,
                           files={r["census_relative"]: r["census_sha256"] for rows in rows_by_cik.values() for r in rows},
                           excluded=excluded, stage_b_q1=q1),
        contracts_source=dict(run_id=contracts_run_id, manifest_sha256=cman_rec["sha256"],
                              inventory_sha256=inv_rec["sha256"], slices={k: v["sha256"] for k, v in slices.items()}),
        tolerances=dict(content_sha256=tol_rec["content_sha256"], version=tol_rec["version"], run_id=tol_rec["run_id"],
                        file_sha256=tol_rec["sha256"], rule="read from the frozen file; never rebuilt"),
        grammars={c: (None if g is None else dict(path=g["path"], sha256=g["sha256"], dialect=g["dialect"],
                                                  provenance="inherited")) for c, g in grammars.items()},
        positives=dict(rows=pre_rows, typed_checks=checks, fingerprint_unmapped_selected=fingerprint["unmapped_selected"],
                       d07_typed_vs_computed=dict(equal=d07_typed == {k for k in sources["d07"] if k[0] in ciks},
                                                  typed_only=sorted(d07_typed - sources["d07"]),
                                                  computed_only=sorted(sources["d07"] - d07_typed)),
                       derived_at_run=dict(category="recogniser_format", rule=QUARTER_CLASS_RULE,
                                           published="results/positives.json"),
                       inception_only=INCEPTION_ONLY),
        code=code, config=config, inputs=[{k: r[k] for k in keep if k in r} for r in inputs])
    write_once_json(paths, "manifest.json", built)
    clock["manifest_written_utc"] = _now()

    slice_deps = {k: dict(label=v["label"], sha256=v["sha256"], bytes=v["bytes"]) for k, v in slices.items()}
    holdings_path = slices["private_markets_holdings_pilot8.parquet"]["path"]
    income_path = slices["bdc_fund_income_pilot8.parquet"]["path"]
    all_pairs, results_json, classes, yields_by, repro, timing_rows = [], {}, {}, {}, {}, []
    semantic_by, inception_by = dict(semantic_grid={}, median_shift={}, tier={}), {}
    for cik in ciks:
        rows = rows_by_cik[cik]
        dates = [r["report_date"] for r in rows]
        prev_out, prev_rec, q1_out, q1_rec = None, None, None, None
        cik_pairs = {}
        for idx, row in enumerate(rows):
            day = row["report_date"]
            prev = dates[idx - 1] if idx else None
            gapped = bool(prev) and (any(prev < d < day for d in excluded[cik]) or _months(prev, day) > 3)
            deps = dict(cik=cik, day=day, census=row["record"], census_fingerprint=row["fingerprint"], prev=prev_rec,
                        q1=q1_rec if day > q1[cik] else None, tolerances=tol_rec, grammar=grammar_recs[cik],
                        slices=slice_deps, code=code, config=config)
            identity = manifest.cache_identity("m2_backtest_quarter", deps, collector_version=BACKTEST_VERSION)

            def compute(row=row, day=day, prev=prev, gapped=gapped, prev_out=prev_out, q1_out=q1_out, cik=cik):
                return _quarter(paths, cik=cik, row=row, day=day, prev=prev, gapped=gapped, prev_out=prev_out,
                                q1_out=q1_out, q1_date=q1[cik], tolerances=learn_tol, grammar=grammars[cik],
                                holdings_path=holdings_path, income_path=income_path, min_quarters=min_quarters,
                                recorded_at=recorded_at, frozen_block=inventory["ciks"][cik], semantic=sem_arg)

            rel = "stages/" + cik + "/" + day + ".json"
            out = manifest.run_cached_stage(paths, rel, identity, compute,
                                            workload=m2_seed._workload(cik, row["record"]["bytes"]))
            result = out["result"]
            rec = manifest.file_record(confined(paths, rel), "run/" + rel)
            classes[cik + "/" + day] = result["quarter_class"]
            yields_by.setdefault(cik, []).append(dict(day=day, window=result["yield"].get("window"),
                                                      status=result["yield"].get("status"),
                                                      vote=result["yield"].get("vote"), cause=result["yield"].get("cause")))
            if result.get("reproduction") is not None:
                repro[cik] = result["reproduction"]
            for mode, ev in result["evaluations"].items():
                learn_out = prev_out if mode == "rolling" else q1_out
                t = pair_timing(learn_out["timing"], ev["timing"], peak=result["timing"]["peak_bytes"])
                cik_pairs[(mode, ev["learn_date"], day)] = dict(timing=t, results=ev["results"], **{
                    k: ev[k] for k in ("semantic_grid", "median_shift", "tier") if k in ev})
                timing_rows.append(dict(cik=cik, mode=mode, learn_date=ev["learn_date"], eval_date=day, **t))
                if not t["within_bound"]:
                    write_once_json(paths, "results/limit_exceeded.json", dict(cik=cik, mode=mode, day=day, timing=t))
                    raise LimitExceeded(cik + " " + mode + " " + day + " exceeded the measured bound: " + json.dumps(t))
            print("  " + cik + " " + day + ": " + result["quarter_class"]["class"] + ", positions "
                  + str(result["quarter_class"]["positions"]) + ", load " + str(result["timing"].get("load_seconds"))
                  + " s, learn " + str(result["timing"].get("learn_seconds")) + " s, evaluations "
                  + str(len(result["evaluations"])) + " (" + out["cache"] + ")")
            if result.get("inception"):
                inception_by.setdefault(cik, {})[day] = result["inception"]
            prev_out, prev_rec = result, rec
            if day == q1[cik]:
                q1_out, q1_rec = result, rec
        cls = {d: classes[cik + "/" + d]["class"] for d in dates}
        for pair in build_pairs(cik, dates, q1_date=q1[cik], excluded=excluded[cik], classes=cls):
            got = cik_pairs.get((pair["mode"], pair["learn_date"], pair["eval_date"]))
            if pair["status"] == "evaluated" and got is None:
                raise StageInvalidated("evaluated pair without results: " + pair["pair_id"])
            if got is not None:
                pair["timing"] = got["timing"]
                results_json[pair["pair_id"]] = got["results"]
                for name in ("semantic_grid", "median_shift", "tier"):
                    if name in got:
                        semantic_by[name][pair["pair_id"]] = got[name]
            all_pairs.append(pair)
    clock["evaluation_done_utc"] = _now()

    class_items = {(k.split("/")[0], k.split("/")[1]): v for k, v in classes.items()}
    positives = pre_rows + recogniser_positives(class_items)
    by_reading = dict(as_evaluated=results_json, strict={k: strict(v) for k, v in results_json.items()})
    scoring = score_all(all_pairs, by_reading, positives)
    yield_summary = {}
    for cik, items in yields_by.items():
        votes = [i for i in items if i["status"] == "vote"]
        learned = [p for p in all_pairs if p["cik"] == cik and p["status"] == "evaluated"]
        statuses = {}
        for p in learned:
            for r in results_json.get(p["pair_id"], []):
                if r["kind"] == "fund_income_yield":
                    statuses[p["mode"] + ":" + r["status"]] = statuses.get(p["mode"] + ":" + r["status"], 0) + 1
        causes = {}
        for i in items:
            if i["status"] != "vote":
                causes[str(i["cause"])] = causes.get(str(i["cause"]), 0) + 1
        yield_summary[cik] = dict(quarters=len(items), two_quarter_windows=sum(len(i["window"] or []) == 2 for i in items),
                                  votes={i["day"]: i["vote"] for i in votes}, learnable=bool(votes),
                                  contract_statuses=statuses, causes=causes)
    evaluated = [p for p in all_pairs if p["status"] == "evaluated"]
    extremes = {}
    if evaluated:
        worst = max(evaluated, key=lambda p: p["timing"]["measured_seconds"])
        extremes = dict(max_measured=dict(pair=worst["pair_id"], **worst["timing"]),
                        min_measured=dict(pair=min(evaluated, key=lambda p: p["timing"]["measured_seconds"])["pair_id"],
                                          seconds=min(p["timing"]["measured_seconds"] for p in evaluated)),
                        max_peak_bytes=max(p["timing"]["peak_bytes"] for p in evaluated))
    context = dict(profile_mode=PROFILE_MODE, pairs=all_pairs, yields=yield_summary, timing=extremes,
                   positives=positives, inception_only=INCEPTION_ONLY, reproduction=repro, classes=classes)
    recall = render_recall(run_id=paths.run_id, scoring=scoring, context=context)
    write_once_json(paths, "results/positives.json", dict(rows=positives, typed_checks=checks,
                                                          inception_only=INCEPTION_ONLY))
    write_once_json(paths, "results/pairs.json", dict(pairs=all_pairs, quarter_classes=classes,
                                                      rule=QUARTER_CLASS_RULE, yield_window=YIELD_WINDOW_NOTE))
    write_once_json(paths, "results/backtest_results.json", dict(
        note="as-evaluated results per pair; the strict reading is contracts.strict_results of these",
        results=results_json, yields=yields_by))
    slim_scoring = {m: {r: {n: {k: v for k, v in s.items() if k != "positive_units"}
                            for n, s in by_set.items()} for r, by_set in by_r.items()} for m, by_r in scoring.items()}
    write_once_json(paths, "results/scoring.json", dict(
        scoring=slim_scoring, positive_units={m: {r: by_r[r]["all"]["positive_units"] for r in READINGS}
                                              for m, by_r in scoring.items()},
        yield_contract=yield_summary, reproduction=repro, timing_extremes=extremes, negatives_caveat=NEGATIVES_CAVEAT))
    csv_results = render_csv(
        ("pair_id", "mode", "cik", "learn_date", "eval_date", "gapped", "labels", "kind", "field", "partition_id",
         "status", "strict_status", "cause", "n_violating"),
        [(p["pair_id"], p["mode"], p["cik"], p["learn_date"], p["eval_date"], p["gapped"], ";".join(p["labels"]),
          r["kind"], r["field"], r["partition_id"], r["status"], s["status"], r["cause"] or "", r["n_violating"])
         for p in all_pairs for r, s in zip(by_reading["as_evaluated"].get(p["pair_id"], []),
                                            by_reading["strict"].get(p["pair_id"], []))])
    csv_scoring = render_csv(
        ("mode", "reading", "positive_set", "scope", "pos_units", "not_covered", "detected", "abstained", "missed",
         "field_mismatch", "recall", "neg_n", "neg_holds", "neg_breach", "neg_insufficient", "breach_rate_upper_bound",
         "carried"),
        [(m, r, n, scope, v["positives"]["units"], v["positives"]["not_covered"] + v["positives"]["no_contract"],
          v["positives"]["detected"], v["positives"]["abstained"], v["positives"]["missed"],
          v["positives"]["field_mismatch"], v["positives"]["recall"], v["negatives"]["n"], v["negatives"]["holds"],
          v["negatives"]["breach"], v["negatives"]["insufficient_evidence"], v["negatives"]["breach_rate_upper_bound"],
          v["carried"])
         for m, by_r in scoring.items() for r, by_set in by_r.items() for n, s in by_set.items()
         for scope, v in list(s["by_kind"].items()) + list(s["by_kind_cik"].items())])
    csv_unadj = render_csv(
        ("mode", "reading", "cik", "learn_date", "eval_date", "gapped", "kind", "field", "cause", "n_violating",
         "violating_keys"),
        [(m, r, u["cik"], u["learn_date"], u["eval_date"], u["gapped"], u["kind"], u["field"], u["cause"],
          u["n_violating"], " ".join(u["violating_keys"])) for m, by_r in scoring.items() for r in READINGS
         for u in by_r[r]["all"]["unadjudicated"]])
    for rel, text in (("results/recall.md", recall), ("results/backtest_results.csv", csv_results),
                      ("results/scoring.csv", csv_scoring), ("results/unadjudicated.csv", csv_unadj)):
        m2_seed._write_text_once(confined(paths, rel), text)
    scratch = Path(scratch_dir) if scratch_dir else paths.code_root / "scratch" / "2026-09-29_m2_assessment"
    copies = [str(m2_seed._write_text_once(scratch / (name + "_" + paths.run_id + ext), text)) for name, ext, text in (
        ("backtest_recall", ".md", recall), ("backtest_results", ".csv", csv_results),
        ("backtest_scoring", ".csv", csv_scoring), ("backtest_unadjudicated", ".csv", csv_unadj))]
    after = manifest.verify_inputs(dict(inputs=[{k: r[k] for k in keep if k in r} for r in inputs]))
    if not after["ok"]:
        raise StageInvalidated("pinned inputs changed during the stage: " + json.dumps(after)[:400])
    semantic_out = None
    if semantic:
        sem_neg = {mode: semantic_negatives(all_pairs, semantic_by["semantic_grid"], positives, grid=grid,
                                            tiers=semantic_by["tier"], mode=mode) for mode in MODES}
        fields = {r["contract_id"]: r["field"] for res in results_json.values() for r in res
                  if r["kind"] == "value_range"}
        ms_scores = {mode: median_shift_scores(all_pairs, semantic_by["median_shift"], positives, fields=fields,
                                               mode=mode) for mode in MODES}
        newly = newly_abstained_summary(all_pairs, results_json, scoring)
        calibration = assemble_calibration(seed_body, sem_neg["rolling"], ms_scores["rolling"], scoring,
                                           seed_run_id=seed_run_id) if seed_body else None
        semantic_out = dict(run_id=paths.run_id, label=m2_seed.IN_SAMPLE, negatives=sem_neg,
                            median_shift=ms_scores, newly_abstained=newly, inception=inception_by,
                            grid=[{k: v for k, v in g.items() if k != "tolerances"} for g in grid],
                            negatives_caveat=NEGATIVES_CAVEAT)
        write_once_json(paths, "results/semantic.json", semantic_out)
        texts = [("backtest_semantic", render_semantic(semantic_out, calibration))]
        if calibration:
            write_once_json(paths, "results/calibration.json", calibration)
        for name, text in texts:
            m2_seed._write_text_once(confined(paths, "results/" + name + ".md"), text)
            copies.append(str(m2_seed._write_text_once(scratch / (name + "_" + paths.run_id + ".md"), text)))
    main_s = scoring["rolling"]["as_evaluated"]["all"]
    headline = {k: dict(pos=v["positives"]["covered"], detected=v["positives"]["detected"],
                        abstained=v["positives"]["abstained"], missed=v["positives"]["missed"],
                        not_covered=v["positives"]["not_covered"] + v["positives"]["no_contract"],
                        neg=v["negatives"]["n"], neg_breach=v["negatives"]["breach"],
                        rate=v["negatives"]["breach_rate_upper_bound"]) for k, v in main_s["by_kind"].items()}
    summary = dict(run_id=paths.run_id, git_head=built["git"]["head"], clock=clock,
                   seconds=round(time.perf_counter() - started, 1), pairs=len(all_pairs),
                   evaluated_pairs=len(evaluated), headline_rolling_as_evaluated=headline,
                   unadjudicated_rolling_as_evaluated=len(main_s["unadjudicated"]), timing_extremes=extremes,
                   yield_learnable={c: y["learnable"] for c, y in yield_summary.items()},
                   scratch_copies=copies, input_verification_after=after,
                   **({} if not semantic_out else dict(newly_abstained=semantic_out["newly_abstained"]["totals"])))
    write_once_json(paths, "results/run_summary.json", summary)
    return summary


def _grid_slim(block: dict, grid: list, doc: dict, listing: dict, grammar) -> dict:
    """The semantic contracts at every candidate band: point -> [[cid, kind, status, cause, criteria, keys]]."""
    out = contracts.evaluate_semantic_grid(block, [g["tolerances"] for g in grid], q2_doc=doc, q2_listing=listing,
                                           grammar=grammar)
    return {g["name"]: [[r["contract_id"], r["kind"], r["status"], r["cause"],
                         (r.get("observed") or {}).get("criteria"),
                         list(r["violating_keys"]) if r["status"] == "breach" else []] for r in res]
            for g, res in zip(grid, out)}


def _median_shift(learn_out: dict, doc: dict, results: list, *, grammar, tolerances) -> dict:
    stats = learn_out.get("range_stats") or {}
    if not stats:
        return {}
    samples = m2_seed.range_samples(learn_out["block"], doc, grammar=grammar, tolerances=tolerances)
    scale = {(r["partition_id"], r["field"]): r["status"] for r in results if r["kind"] == "scale"}
    meta = {c["contract_id"]: c for c in learn_out["block"]["contracts"]}
    return {cid: {m2_seed.ms_name(x, y): (m2_seed.median_shift_verdict(st, samples.get(cid, []), x=x, y=y)
                                          if scale.get((meta[cid]["partition_id"], meta[cid]["field"])) == "holds"
                                          else "insufficient_evidence")
                  for x in m2_seed.MEDIAN_SHIFT["x"] for y in m2_seed.MEDIAN_SHIFT["y"]}
            for cid, st in sorted(stats.items())}


def _inception(block: dict | None) -> list:
    return [dict(kind=c["kind"], learn_status=c["learn_status"], learn_cause=c["learn_cause"],
                 inception=(c.get("evidence") or {}).get("inception"))
            for c in (block or {}).get("contracts", []) if c["kind"] in contracts.SEMANTIC_KINDS]


def _quarter(paths, *, cik, row, day, prev, gapped, prev_out, q1_out, q1_date, tolerances, grammar, holdings_path,
             income_path, min_quarters, recorded_at, frozen_block, semantic=None) -> dict:
    """One quarter: classify, slim view, yield evidence, learn, evaluate the rolling and anchored pairs ending here.

    semantic (Task B2-3): dict(grid=m2_seed.semantic_grid(v2)); `tolerances` is then the v3 learning
    reference. Each pair also carries the semantic contracts at every candidate band, the median_shift
    experiment and (rolling) the prior-pair newly_abstained marks."""
    from scripts.profile_pilot import profile
    timing: dict = {}
    t = time.perf_counter()
    doc = contracts_run.load_census(row)
    timing["load_seconds"] = time.perf_counter() - t
    qclass = classify_quarter(doc)
    slim = slim_view(doc)
    window = income_window(day, prev=prev, gapped=gapped, min_quarters=min_quarters)
    slims = {day: slim}
    if len(window) == 2:
        slims[prev] = prev_out["slim"]
    t = time.perf_counter()
    ev_yield = yield_evidence(paths, cik=cik, day=day, window=window, slims=slims, holdings_path=holdings_path,
                              income_path=income_path, min_quarters=min_quarters)
    timing["yield_seconds"] = time.perf_counter() - t
    source = dict(cik=cik, report_date=day, role=row["role"], census_relative=row["census_relative"],
                  census_sha256=row["census_sha256"], fingerprint=row["fingerprint"],
                  accession_number=doc["document"].get("accession_number"), form_type=doc["document"].get("form_type"))
    profile_state = dict(mode=PROFILE_MODE, status=None, entries=None)

    def derive(d, at=recorded_at):
        t0 = time.perf_counter()
        try:
            out = profile.derive_profile(d, source=source, era="q1", recorded_at=at)
            profile_state.update(status="derived", entries=len(out["entries"]))
            return out
        except profile.ProfileError as exc:
            profile_state.update(status="failed: " + str(exc)[:200])
            return None
        finally:
            timing["profile_seconds"] = timing.get("profile_seconds", 0.0) + time.perf_counter() - t0

    block = None
    if qclass["class"] != "pre_tagging":
        t = time.perf_counter()
        block = learn_block(cik, doc, tolerances=tolerances, grammar=grammar, yield_ev=ev_yield,
                            recorded_at=recorded_at, derive=derive)
        timing["learn_contracts_seconds"] = time.perf_counter() - t - timing.get("profile_seconds", 0.0)
    listing = dict(status="available", report_date=day, census_relative=row["census_relative"])
    evaluations = {}
    prev_ok = prev_out is not None and prev_out["block"] is not None and qclass["class"] != "pre_tagging"
    for mode, learn_out in (("rolling", prev_out if prev_ok else None),
                            ("anchored", q1_out if day > q1_date and qclass["class"] != "pre_tagging" else None)):
        if learn_out is None or learn_out["block"] is None:
            continue
        t = time.perf_counter()
        res = contracts.evaluate_contracts(learn_out["block"], tolerances, q2_doc=doc, q2_listing=listing,
                                           grammar=grammar, yield_q2=ev_yield)
        extra = {}
        if mode == "rolling":
            prior = ((prev_out.get("evaluations") or {}).get("rolling") or {}).get("results")
            res = contracts.mark_prior_abstentions(res, prior)
        if semantic:
            extra = dict(semantic_grid=_grid_slim(learn_out["block"], semantic["grid"], doc, listing, grammar),
                         median_shift=_median_shift(learn_out, doc, res, grammar=grammar, tolerances=tolerances),
                         tier=learn_out["block"]["tier"])
        spent = time.perf_counter() - t + timing["yield_seconds"]
        evaluations[mode] = dict(learn_date=learn_out["day"], results=[_trim(r) for r in res],
                                 timing=dict(evaluate_seconds=round(spent, 3)), **extra)
    reproduction = None
    if day == q1_date and block is not None:
        single = yield_evidence(paths, cik=cik, day=day, window=[day], slims={day: slim}, holdings_path=holdings_path,
                                income_path=income_path, min_quarters=min_quarters)
        saved = dict(timing)
        again = learn_block(cik, doc, tolerances=tolerances, grammar=grammar, yield_ev=single,
                            recorded_at=frozen_block["recorded_at"],
                            derive=lambda d: derive(d, at=frozen_block["recorded_at"]))
        timing.clear()
        timing.update(saved)
        key = lambda c: (c["contract_id"], c["learn_status"], c["learn_cause"], c["expectation"])
        # the frozen block is v2: compare the v2 subset (a v3 learn adds only the semantic contracts)
        mine = [key(c) for c in again["contracts"] if c["kind"] in contracts.KINDS]
        frozen = [key(c) for c in frozen_block["contracts"]]
        diffs = [dict(contract_id=a[0], backtest=list(a[1:3]), frozen=list(b[1:3]), expectation_equal=a[3] == b[3])
                 for a, b in zip(mine, frozen) if a != b]
        reproduction = dict(equal=mine == frozen, contracts=[len(mine), len(frozen)], differences=diffs[:60],
                            note="learned again at q1 with the frozen recorded_at and a one-quarter yield window "
                                 "(the Stage B learning inputs) and compared per contract with contract_inventory")
    extra = {}
    if semantic and block is not None:
        t = time.perf_counter()
        extra = dict(range_stats=m2_seed.range_stats(m2_seed.range_samples(block, doc, grammar=grammar,
                                                                           tolerances=tolerances)),
                     inception=_inception(block))
        timing["learn_contracts_seconds"] = timing.get("learn_contracts_seconds", 0.0) + time.perf_counter() - t
    peak = m2_seed._peak_bytes()
    stage_timing = _stage_timing(timing)
    stage_timing["peak_bytes"] = peak
    return dict(cik=cik, day=day, form_type=doc["document"].get("form_type"),
                accession_number=doc["document"].get("accession_number"), quarter_class=qclass, slim=slim,
                **{"yield": ev_yield}, profile=profile_state,
                block=block, evaluations=evaluations, reproduction=reproduction, timing=stage_timing, **extra)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("run")
    cmd.add_argument("--main-root", type=Path, default=None)
    cmd.add_argument("--data-root", type=Path, required=True)
    cmd.add_argument("--code-root", type=Path, default=None)
    cmd.add_argument("--run-id", default=None)
    cmd.add_argument("--census-run-id", required=True)
    cmd.add_argument("--contracts-run-id", required=True)
    cmd.add_argument("--cik", action="append", default=None)
    cmd.add_argument("--scratch-dir", type=Path, default=None)
    cmd.add_argument("--semantic", action="store_true", help="Task B2-3: v3 semantic kinds at every candidate band")
    cmd.add_argument("--seed-run-id", default=None, help="Task B2-3: seed root whose semantic curves calibrate")
    args = parser.parse_args(argv)
    try:
        main_root = args.main_root or discover_main_root(CODE_ROOT)
        paths = resolve_paths(main_repo_root=main_root, data_root=args.data_root,
                              code_root=args.code_root or CODE_ROOT, run_id=args.run_id or default_run_id())
        receipt = ("verification/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                   + "_m2_backtest_preservation.json")
        with protection.protected_session(paths, receipt=receipt):
            summary = run_stage(paths, census_run_id=args.census_run_id, contracts_run_id=args.contracts_run_id,
                                ciks=args.cik, scratch_dir=args.scratch_dir, semantic=args.semantic,
                                seed_run_id=args.seed_run_id)
    except StageInvalidated as exc:
        print("STAGE INVALIDATED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_INVALIDATED
    except (contracts.ContractError, contracts_income.IncomeEvidenceError) as exc:
        print("CONTRACT ERROR: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_CONTRACT
    except (PathError, protection.LeaseRefused) as exc:
        print("REFUSED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_REFUSED
    except LimitExceeded as exc:
        print("LIMIT EXCEEDED (stopped, not widened): " + str(exc))
        return EXIT_LIMIT
    print("run: " + summary["run_id"] + " | git_head " + summary["git_head"] + " | " + str(summary["seconds"])
          + " s | pairs " + str(summary["pairs"]) + " (evaluated " + str(summary["evaluated_pairs"]) + ")")
    for kind, h in summary["headline_rolling_as_evaluated"].items():
        print("  rolling/as_evaluated " + kind + ": " + json.dumps(h, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
