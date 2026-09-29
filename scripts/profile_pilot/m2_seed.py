"""Task B2-1: seeded-drift harness for M2 (which frozen contract kinds see which injected drift).

    python -m scripts.profile_pilot.m2_seed run --data-root D
        --census-run-id stageb-20260929t004819z --profile-run-id stageb-profile-20260929t053308z
        --contracts-run-id stageb-contracts-20260929t053506z [--cik C ...] [--run-id stageb2-seed-<stamp>]
        [--main-root M] [--scratch-dir S]

Method. For each pilot CIK the REAL authoritative Q1 census is loaded (re-hashed against the
listing), one drift class is injected into a copy of it on a seeded subset of the current
positions, and the copy is evaluated as a synthetic Q2 against the FROZEN v2 contracts that
were learned from the unperturbed Q1 (`learning/{cik}.json` of the contracts root, reused as
is: the block is self-contained and is checked equal to the frozen contract_inventory). The
synthetic Q2 keeps Q1's report_date and form_type (it IS Q1 plus the drift), so no form or
date effect enters. Fraction 0 is the null control: any breach there is a harness bug or a
self-inconsistency. Nothing here changes a contract, a band or a tolerance; the frozen
tolerances v2 file is read and its content digest asserted.

Drift classes (target field interest_rate unless stated):
  scale_flip              value x100 (declared pure) or /100 (declared percent/bps), unit kept
  scale_flip_declared     unit_ref re-pointed to a unit of the other ratio class, value converted
                          so the canonical number is unchanged (the census records unit_ref per
                          fact and units[unit_ref].measures, so the declared unit is observable)
  concept_move_namespace  fact QName moved to the filer extension namespace, same local name
  concept_move_local      fact QName moved to another local name the collector maps to the
                          same field (the mapping is recomputed with census._concept_mapping)
  spread_for_coupon       interest_rate value := basis_spread value (same declared class)
  fill_drop               field set absent and its facts removed (counts kept consistent)
  range_shift_<d>         value x (1 + d), d in 0.15 / 0.3 / 0.6
  identifier_format       typed identifier: '%' -> ' pct' and m/d/yyyy -> m-d-yyyy

Detection = the target contract goes holds -> breach; holds -> insufficient_evidence is
ABSTENTION and is reported separately; a contract that does not hold in the null control is
not applicable (it cannot flip). Every other contract whose status changes is collateral.
Everything is in memory (no XBRL parse); each CIK is one light cached stage.
Exit codes: 0 ok, 2 stage invalidated, 3 contract error, 4 refused, 5 measured limit exceeded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import io
import json
import math
from pathlib import Path
import random
import re
import statistics
import sys
import time

from scripts.profile_pilot import cohort, contracts, lineage, manifest, protection
from scripts.profile_pilot.contracts_observe import FILLED, IDENTIFIER_FIELD, RATIO_CLASSES, scale_class
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import PathError, confined, discover_main_root, resolve_paths, write_once_json

CODE_ROOT = Path(__file__).resolve().parents[2]
SEED_VERSION = "m2-seed.v1"
RUN_PREFIX = "stageb2-seed-"
EXIT_INVALIDATED, EXIT_CONTRACT, EXIT_REFUSED, EXIT_LIMIT = 2, 3, 4, 5
TOLERANCES_V2_SHA256 = "bf15c296caf581617436b50c932d59c87164767eb77e79902c2a34584bb934ec"
FIELD = "interest_rate"
FRACTIONS = (0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 1.0)
SEEDS = (1, 2, 3)
RANGE_DELTAS = (0.15, 0.3, 0.6)
PERTURB_KINDS = ("scale_flip", "scale_flip_declared", "concept_move_namespace", "concept_move_local",
                 "spread_for_coupon", "fill_drop", "range_shift", "identifier_format", "text_numeric_divergence",
                 "bps_spread_scale")
VARIANTS = (("scale_flip", "scale_flip", None), ("scale_flip_declared", "scale_flip_declared", None),
            ("concept_move_namespace", "concept_move_namespace", None),
            ("concept_move_local", "concept_move_local", None), ("spread_for_coupon", "spread_for_coupon", None),
            ("fill_drop", "fill_drop", None)) + tuple(
    ("range_shift_" + str(d), "range_shift", d) for d in RANGE_DELTAS) + (
    ("identifier_format", "identifier_format", None),)
VARIANT_NAMES = tuple(v[0] for v in VARIANTS)
CONTRACT_KINDS = ("source_concept_set", "fill_rate", "scale", "value_range", "format_grammar")
EXPECTED_DETECTOR = {"scale_flip": "scale", "scale_flip_declared": "scale",
                     "concept_move_namespace": "source_concept_set", "concept_move_local": "source_concept_set",
                     "spread_for_coupon": "value_range", "fill_drop": "fill_rate",
                     "range_shift_0.15": "value_range", "range_shift_0.3": "value_range",
                     "range_shift_0.6": "value_range", "identifier_format": "format_grammar"}
# ---- Task B2-3 (semantic mode): the drift classes the two new kinds target, plus the range shifts
# for the median_shift calibration-only experiment (addendum 3; never adopted into v3).
SEMANTIC_VARIANTS = (("spread_for_coupon", "spread_for_coupon", None),
                     ("text_numeric_divergence", "text_numeric_divergence", None),
                     ("bps_spread_scale", "bps_spread_scale", None)) + tuple(
    ("range_shift_" + str(d), "range_shift", d) for d in RANGE_DELTAS)
SEMANTIC_TARGETS = {"share_pp": "spread_for_coupon", "iqr_widen": "spread_for_coupon",
                    "text_share_pp": "text_numeric_divergence"}
CANDIDATES = dict(share_pp=(5, 10, 15, 20, 25), iqr_widen=(1.5, 2.0, 3.0), text_share_pp=(5, 10, 15, 20, 25))
REFERENCE = dict(share_pp=10, iqr_widen=2.0, text_share_pp=10)
MEDIAN_SHIFT = dict(x=(0.10, 0.15, 0.25), y=(0.05, 0.10))
IN_SAMPLE = "in-sample (bands chosen after Q2 and the history were read)"
DIVERGENCE_PP = Decimal(1)
DIVERGENCE_STEP = {"pure": Decimal("0.01"), "percent": Decimal(1), "bps": Decimal(100)}
# Other local names pipeline.bdc_filings.CONCEPT_MAP maps to the same field (checked per move).
ALT_LOCAL = {"interest_rate": ("InvestmentInterestRate", "InvestmentInterestRatePaidInCash"),
             "basis_spread": ("InvestmentBasisSpreadVariableRate", "InvestmentSpreadRate"),
             "pik_rate": ("InvestmentInterestRatePaidInKind", "InvestmentPikRate")}
STANDARD_PREFIXES = frozenset({"us-gaap", "us-gaap-supplement", "srt", "dei", "cef", "xbrli", "iso4217", "country",
                               "currency", "ecd", "exch", "naics", "sic", "stpr", "invest"})
FALLBACK_EXTENSION = ("m2seed", "http://example.invalid/m2seed")
SEED_UNITS = {"percent": ("m2seed_percent", ["m2seed:percent"], "unresolved"),
              "pure": ("m2seed_pure", ["xbrli:pure"], "pure")}
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
FULL_VALIDATION_MAX_BYTES = 5_000_000
LIMIT_SECONDS = 60
LIMIT_BYTES = 2 * 2 ** 30
LIMIT_RULE = ("ruling R35: the 60 s / 2 GiB bound applies to the measured work (perturbation + contract "
              "evaluation, timed per step and per CIK); the realism self-check runs on seed 1 only per class x "
              "fraction and is timed separately (validate_seconds)")
CODE_FILES = ("scripts/profile_pilot/m2_seed.py", "scripts/profile_pilot/contracts.py",
              "scripts/profile_pilot/contracts_observe.py", "scripts/profile_pilot/contracts_run.py",
              "scripts/profile_pilot/envelope.py", "scripts/profile_pilot/census.py",
              "scripts/profile_pilot/census_detect.py", "scripts/profile_pilot/lineage.py",
              "scripts/profile_pilot/manifest.py", "scripts/profile_pilot/schemas/census_v0.schema.json",
              "pipeline/identifier_rate.py", "pipeline/identifier_signature.py", "pipeline/bdc_filings.py")
SYNTHETIC_Q2_NOTE = ("synthetic Q2 = the perturbed Q1 census: report_date and form_type are Q1's; the learned "
                     "block is the frozen one from the unperturbed Q1")


class PerturbError(ValueError):
    """A perturbation precondition failed (never silently skipped)."""


class LimitExceeded(RuntimeError):
    """A CIK's in-memory evaluation exceeded the measured 60 s / 2 GiB bound."""


# ---------------------------------------------------------------- copy-on-write editor

class _Editor:
    """Copies every container on the path to an edited value; untouched leaves are shared.

    With perturb(deep=True) the source is itself a fresh deep copy, so the result shares
    nothing with the caller's document either way; deep=False is the harness path (the
    caller's document is never mutated; the harness asserts it by digest)."""

    def __init__(self, doc: dict):
        self.src = doc
        self.out = dict(doc)
        self._pos: set = set()
        self._facts_copied = False
        self._fact_at = None
        self._fact_done: set = set()
        self._sections: set = set()
        self._contexts = None

    def position(self, index: int) -> dict:
        if "positions" not in self._sections:
            self.out["positions"] = list(self.src["positions"])
            self._sections.add("positions")
        if index not in self._pos:
            self.out["positions"][index] = copy.deepcopy(self.src["positions"][index])
            self._pos.add(index)
        return self.out["positions"][index]

    def _fact_index(self) -> dict:
        if self._fact_at is None:
            self._fact_at = {f["i"]: n for n, f in enumerate(self.out["facts"])}
        return self._fact_at

    def fact(self, i: int) -> dict:
        if not self._facts_copied:
            self.out["facts"] = list(self.src["facts"])
            self._facts_copied = True
        n = self._fact_index()[i]
        if i not in self._fact_done:
            self.out["facts"][n] = dict(self.out["facts"][n])
            self._fact_done.add(i)
        return self.out["facts"][n]

    def source_fact(self, i: int) -> dict:
        return self.src["facts"][self._fact_index()[i]]

    def remove_facts(self, indices) -> list:
        drop = set(indices)
        removed = [f for f in self.out["facts"] if f["i"] in drop]
        self.out["facts"] = [f for f in self.out["facts"] if f["i"] not in drop]
        self._facts_copied, self._fact_at = True, None
        return removed

    def section(self, name: str):
        if name not in self._sections and name in self.src:
            self.out[name] = copy.deepcopy(self.src[name])
            self._sections.add(name)
        return self.out.get(name)

    def context(self, context_id: str):
        if self._contexts is None:
            if "contexts" not in self.src:
                return None
            self.out["contexts"] = list(self.src["contexts"])
            self._contexts = {c["id"]: n for n, c in enumerate(self.out["contexts"])}
            self._ctx_done = set()
        n = self._contexts.get(context_id)
        if n is None:
            return None
        if n not in self._ctx_done:
            self.out["contexts"][n] = copy.deepcopy(self.out["contexts"][n])
            self._ctx_done.add(n)
        return self.out["contexts"][n]


# ---------------------------------------------------------------- helpers

def _decimal(value):
    try:
        out = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return out if out.is_finite() else None


def _fmt(value: Decimal) -> str:
    out = format(value.normalize(), "f")
    return "0" if out in ("-0", "") else out


def _local(qname: str) -> str:
    return qname.rsplit(":", 1)[-1]


def _prefix(qname: str) -> str:
    return qname.rsplit(":", 1)[0] if ":" in qname else ""


def _current_indices(doc: dict) -> list:
    dped = set(doc["document_metadata"]["document_period_end_dates"])
    return [n for n, p in enumerate(doc["positions"]) if p["period"].get("instant") in dped]


def _filled(position: dict, field: str) -> dict | None:
    value = position["fields"].get(field) or {}
    return value if value.get("status") in FILLED and value.get("fact_indices") else None


def _select(eligible: dict, fraction: float, seed: int) -> list:
    """Seeded subset of exactly ceil(fraction x n) context ids (RNG over the sorted ids)."""
    ids = sorted(eligible)
    k = math.ceil(round(fraction * len(ids), 9))
    return sorted(random.Random(seed).sample(ids, k)) if k else []


def _check_args(kind: str, fraction: float, delta) -> None:
    if kind not in PERTURB_KINDS:
        raise ValueError("unknown drift class: " + repr(kind))
    if not isinstance(fraction, (int, float)) or isinstance(fraction, bool) or not 0 <= fraction <= 1:
        raise ValueError("fraction must be in [0, 1], got " + repr(fraction))
    if kind == "range_shift" and delta not in RANGE_DELTAS:
        raise ValueError("range_shift needs delta in " + repr(RANGE_DELTAS) + ", got " + repr(delta))
    if kind != "range_shift" and delta is not None:
        raise ValueError("delta applies only to range_shift")


def _filled_rows(doc: dict, field: str) -> int:
    """Denominator for eligibility: current positions carrying the target field (or a non-label identifier)."""
    if field == IDENTIFIER_FIELD:
        from scripts.profile_pilot.census_detect import LABEL_RE
        texts = [doc["positions"][n]["identity"].get("typed_identifier") for n in _current_indices(doc)]
        return sum(1 for t in texts if t and not LABEL_RE.match(t))
    return sum(1 for n in _current_indices(doc)
               if any(_filled(doc["positions"][n], f) for f in field.split("+")))


def finish_timing(raw: dict) -> dict:
    """Round each part once; measured_seconds is the rounded sum of the RECORDED parts (R35 bound)."""
    out = {k: round(v, 3) for k, v in sorted(raw.items())}
    out["measured_seconds"] = round(out.get("perturb_seconds", 0.0) + out.get("evaluate_seconds", 0.0), 3)
    return out


def _set_value(ed: _Editor, index: int, field: str, new: str) -> list:
    position = ed.position(index)
    value = position["fields"][field]
    value["value"] = new
    value["raw"] = [new for _ in (value.get("raw") or [None])]
    for i in value["fact_indices"]:
        fact = ed.fact(i)
        fact["value"], fact["raw"] = new, new
    return list(value["fact_indices"])


def _ratio_rows(doc: dict, field: str) -> dict:
    """Current positions whose `field` is filled with a parseable number under a ratio unit."""
    facts = {f["i"]: f for f in doc["facts"]}
    units = doc.get("units") or {}
    rows = {}
    for n in _current_indices(doc):
        p = doc["positions"][n]
        value = _filled(p, field)
        if not value:
            continue
        cls = scale_class(facts.get(value["fact_indices"][0]), units)
        number = _decimal(value.get("value"))
        if cls in RATIO_CLASSES and number is not None:
            rows[p["context_id"]] = (n, cls, number)
    return rows


def _extension(doc: dict) -> tuple:
    from scripts.profile_pilot.census import _STANDARD_NS
    counts: Counter = Counter()
    namespace = {}
    for f in doc["facts"]:
        prefix = _prefix(f["qname"])
        ns = f.get("namespace")
        if not prefix or prefix in STANDARD_PREFIXES or (ns and _STANDARD_NS.match(ns)):
            continue
        counts[prefix] += 1
        namespace.setdefault(prefix, ns)
    if not counts:
        return FALLBACK_EXTENSION
    prefix = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return prefix, namespace[prefix] or FALLBACK_EXTENSION[1]


def _mapping(qname: str) -> dict:
    from pipeline import context_inventory as ci
    from pipeline.bdc_filings import CONCEPT_MAP
    from scripts.profile_pilot.census import _concept_mapping
    return _concept_mapping(qname, CONCEPT_MAP, ci.FUND_BASIS_CONCEPTS)


def _prune_mappings(ed: _Editor, candidates) -> list:
    mappings = ed.src.get("concept_mappings")
    if mappings is None:
        return []
    used = {f["qname"] for f in ed.out["facts"]}
    gone = [q for q in sorted(set(candidates)) if q not in used and q in mappings]
    if gone:
        section = ed.section("concept_mappings")
        for q in gone:
            section.pop(q, None)
    return gone


def _count_adjust(ed: _Editor, removed: list) -> None:
    """Decrement every recorded facts count that equalled the facts list before the removal."""
    if not removed:
        return
    total = len(ed.src["facts"])
    numeric = sum(f.get("value_kind") == "numeric" for f in removed)
    if (ed.src.get("summary") or {}).get("facts") == total:
        ed.section("summary")["facts"] -= len(removed)
    if any(m.get("name") == "facts" and m.get("value") == total for m in ed.src.get("metrics") or []):
        for metric in ed.section("metrics"):
            if metric.get("name") == "facts":
                metric["value"] -= len(removed)
    count = lambda name: (ed.src["channels"].get(name) or {}).get("count")
    if isinstance(count("numeric_facts"), int) and isinstance(count("text_facts"), int) \
            and count("numeric_facts") + count("text_facts") == total:
        channels = ed.section("channels")
        channels["numeric_facts"]["count"] -= numeric
        channels["text_facts"]["count"] -= len(removed) - numeric


# ---------------------------------------------------------------- perturbations

def perturb(doc: dict, kind: str, fraction: float, *, seed: int, field: str = FIELD, delta=None,
            deep: bool = True) -> tuple[dict, dict]:
    """A copy of the census result `doc` with one drift class on a seeded subset + its receipt."""
    _check_args(kind, fraction, delta)
    ed = _Editor(copy.deepcopy(doc) if deep else doc)
    receipt = dict(kind=kind, field=IDENTIFIER_FIELD if kind == "identifier_format" else field,
                   fraction=fraction, seed=seed, delta=delta, rule=None, eligible=0, touched=0, rows=[],
                   removed_fact_indices=[], added_units=[], added_concepts=[], removed_concepts=[])
    handler = {"scale_flip": _scale_flip, "scale_flip_declared": _scale_flip_declared,
               "concept_move_namespace": _concept_move, "concept_move_local": _concept_move,
               "spread_for_coupon": _spread_for_coupon, "fill_drop": _fill_drop, "range_shift": _range_shift,
               "identifier_format": _identifier_format, "text_numeric_divergence": _text_numeric_divergence,
               "bps_spread_scale": _bps_spread_scale}[kind]
    handler(ed, receipt, field, fraction, seed, delta)
    receipt["touched"] = len(receipt["rows"])
    receipt["filled"] = _filled_rows(ed.src, receipt["field"])
    return ed.out, receipt


def _scale_flip(ed, receipt, field, fraction, seed, _delta):
    rows = _ratio_rows(ed.src, field)
    receipt.update(eligible=len(rows), rule="raw value x100 when the declared unit class is pure, /100 when it is "
                                         "percent or bps; unit_ref, unit_kind and decimals unchanged")
    for ctx in _select(rows, fraction, seed):
        n, cls, number = rows[ctx]
        new = _fmt(number * (Decimal(100) if cls == "pure" else Decimal("0.01")))
        facts = _set_value(ed, n, field, new)
        receipt["rows"].append(dict(context_id=ctx, before=ed.src["positions"][n]["fields"][field]["value"],
                                    after=new, declared_class=cls, fact_indices=facts))


def _scale_flip_declared(ed, receipt, field, fraction, seed, _delta):
    rows = _ratio_rows(ed.src, field)
    receipt.update(eligible=len(rows), rule="unit_ref re-pointed to a seeded unit of the other ratio class "
                                         "(pure -> percent measure, value x100; percent -> pure, value /100; "
                                         "bps -> pure, value /10000): the canonical number is unchanged, only "
                                         "the declared unit class differs")
    factors = {"pure": ("percent", Decimal(100)), "percent": ("pure", Decimal("0.01")),
               "bps": ("pure", Decimal("0.0001"))}
    for ctx in _select(rows, fraction, seed):
        n, cls, number = rows[ctx]
        target, factor = factors[cls]
        unit_id, measures, unit_kind = SEED_UNITS[target]
        units = ed.section("units")
        if unit_id not in units:
            units[unit_id] = dict(unit_kind=unit_kind, currency=None, measures=list(measures),
                                  provenance="derived", inherited_from=None)
            receipt["added_units"].append(unit_id)
            channels = ed.section("channels")
            if isinstance((channels.get("units") or {}).get("count"), int):
                channels["units"]["count"] += 1
        new = _fmt(number * factor)
        facts = _set_value(ed, n, field, new)
        for i in facts:
            fact = ed.fact(i)
            fact["unit_ref"], fact["unit_kind"], fact["currency"] = unit_id, unit_kind, None
        ed.position(n)["fields"][field]["unit_kind"] = unit_kind
        receipt["rows"].append(dict(context_id=ctx, before=ed.src["positions"][n]["fields"][field]["value"],
                                    after=new, declared_class=cls, declared_class_after=target, unit_after=unit_id,
                                    fact_indices=facts))


def _concept_move(ed, receipt, field, fraction, seed, _delta):
    namespace_move = receipt["kind"] == "concept_move_namespace"
    rows = {}
    for n in _current_indices(ed.src):
        p = ed.src["positions"][n]
        if _filled(p, field):
            rows[p["context_id"]] = n
    extension = _extension(ed.src) if namespace_move else None
    receipt.update(eligible=len(rows), extension=extension, rule=(
        "every fact carrying the field moves to the filer extension prefix with the same local name "
        "(namespace move); the field mapping is recomputed with census._concept_mapping" if namespace_move else
        "every fact carrying the field moves to another local name that pipeline.bdc_filings.CONCEPT_MAP maps "
        "to the same field (prefix and namespace kept); the mapping is recomputed with census._concept_mapping"))
    old_names, new_names = set(), set()
    for ctx in _select(rows, fraction, seed):
        n = rows[ctx]
        value = ed.position(n)["fields"][field]
        before = list(value.get("concepts") or [])
        moved = []
        for i in value["fact_indices"]:
            old = ed.source_fact(i)["qname"]
            if namespace_move:
                new, ns = extension[0] + ":" + _local(old), extension[1]
            else:
                alts = [a for a in ALT_LOCAL.get(field, ()) if a.lower() != _local(old).lower()]
                if not alts:
                    raise PerturbError("no alternative local name maps to " + field + " (from " + old + ")")
                new, ns = _prefix(old) + ":" + alts[0], ed.source_fact(i).get("namespace")
            mapping = _mapping(new)
            if mapping["field"] != field:
                raise PerturbError(new + " would map to " + str(mapping["field"]) + ", not " + field)
            fact = ed.fact(i)
            fact.update(qname=new, field=mapping["field"], group=mapping["group"],
                        provenance=mapping["provenance"], inherited_from=mapping["inherited_from"])
            if "namespace" in fact or ns is not None:
                fact["namespace"] = ns
            mappings = ed.src.get("concept_mappings")
            if mappings is not None and new not in mappings:
                ed.section("concept_mappings")[new] = {k: mapping[k] for k in
                                                       ("field", "group", "provenance", "inherited_from", "rule")}
                receipt["added_concepts"].append(new)
            old_names.add(old)
            new_names.add(new)
            moved.append(new)
        value["concepts"] = sorted(set(moved))
        receipt["rows"].append(dict(context_id=ctx, before=before[0] if len(before) == 1 else before,
                                    after=value["concepts"][0] if len(value["concepts"]) == 1 else value["concepts"],
                                    fact_indices=list(value["fact_indices"])))
    receipt["added_concepts"] = sorted(set(receipt["added_concepts"]))
    receipt["removed_concepts"] = _prune_mappings(ed, old_names - new_names)


def _spread_for_coupon(ed, receipt, field, fraction, seed, _delta):
    rates, spreads = _ratio_rows(ed.src, field), _ratio_rows(ed.src, "basis_spread")
    rows = {ctx: (rates[ctx], spreads[ctx]) for ctx in rates if ctx in spreads and rates[ctx][1] == spreads[ctx][1]}
    receipt.update(eligible=len(rows), rule="interest_rate value := basis_spread value on positions carrying both "
                                         "under the same declared ratio class (units and concepts unchanged)",
                   not_same_class=sum(1 for c in rates if c in spreads and rates[c][1] != spreads[c][1]))
    for ctx in _select(rows, fraction, seed):
        (n, cls, _), (_, _, spread) = rows[ctx]
        new = ed.src["positions"][n]["fields"]["basis_spread"]["value"]
        facts = _set_value(ed, n, field, str(new))
        receipt["rows"].append(dict(context_id=ctx, before=ed.src["positions"][n]["fields"][field]["value"],
                                    after=str(new), declared_class=cls, fact_indices=facts))


def _fill_drop(ed, receipt, field, fraction, seed, _delta):
    rows = {}
    for n in _current_indices(ed.src):
        p = ed.src["positions"][n]
        if _filled(p, field):
            rows[p["context_id"]] = n
    receipt.update(eligible=len(rows), rule="field set to status absent and every fact behind it removed from "
                                         "facts; summary.facts, the facts metric and the numeric/text channel "
                                         "counts are decremented; unused concept mappings are pruned")
    drop = []
    for ctx in _select(rows, fraction, seed):
        n = rows[ctx]
        position = ed.position(n)
        before = position["fields"][field]
        drop += before["fact_indices"]
        position["fields"][field] = dict(status="absent", provenance="derived", inherited_from=None)
        receipt["rows"].append(dict(context_id=ctx, before=before.get("value"), after=None,
                                    fact_indices=list(before["fact_indices"])))
    if drop:
        removed = ed.remove_facts(drop)
        receipt["removed_fact_indices"] = sorted(f["i"] for f in removed)
        _count_adjust(ed, removed)
        receipt["removed_concepts"] = _prune_mappings(ed, {f["qname"] for f in removed})


def _range_shift(ed, receipt, field, fraction, seed, delta):
    rows = _ratio_rows(ed.src, field)
    factor = Decimal(1) + Decimal(str(delta))
    receipt.update(eligible=len(rows), rule="raw value x (1 + " + str(delta) + "); unit and concept unchanged")
    for ctx in _select(rows, fraction, seed):
        n, cls, number = rows[ctx]
        new = _fmt(number * factor)
        facts = _set_value(ed, n, field, new)
        receipt["rows"].append(dict(context_id=ctx, before=ed.src["positions"][n]["fields"][field]["value"],
                                    after=new, declared_class=cls, fact_indices=facts))


def _text_numeric_divergence(ed, receipt, _field, fraction, seed, _delta):
    rates, spreads = _ratio_rows(ed.src, "interest_rate"), _ratio_rows(ed.src, "basis_spread")
    rows = sorted(set(rates) | set(spreads))
    receipt.update(eligible=len(rows), field="interest_rate+basis_spread",
                   rule="interest_rate and basis_spread each + 1.00 percentage point in their declared ratio class "
                        "(pure +0.01, percent +1, bps +100); identifier text, units and concepts unchanged")
    for ctx in _select({c: None for c in rows}, fraction, seed):
        before, after, facts = {}, {}, []
        for field, table in (("interest_rate", rates), ("basis_spread", spreads)):
            if ctx not in table:
                continue
            n, cls, number = table[ctx]
            new = _fmt(number + DIVERGENCE_STEP[cls])
            before[field] = ed.src["positions"][n]["fields"][field]["value"]
            after[field] = new
            facts += _set_value(ed, n, field, new)
        receipt["rows"].append(dict(context_id=ctx, before=before, after=after, delta_pp=float(DIVERGENCE_PP),
                                    fact_indices=facts))


def _bps_spread_scale(ed, receipt, _field, fraction, seed, _delta):
    rows = _ratio_rows(ed.src, "basis_spread")
    receipt.update(eligible=len(rows), field="basis_spread",
                   rule="basis_spread raw value x100 with the declared unit kept (pure 0.055 -> 5.5: a percent-point "
                        "number under a decimal unit; percent 5.5 -> 550: a bps number under a percent unit)")
    for ctx in _select(rows, fraction, seed):
        n, cls, number = rows[ctx]
        new = _fmt(number * 100)
        facts = _set_value(ed, n, "basis_spread", new)
        receipt["rows"].append(dict(context_id=ctx, before=ed.src["positions"][n]["fields"]["basis_spread"]["value"],
                                    after=new, declared_class=cls, fact_indices=facts))


def rewrite_identifier(text: str) -> str:
    return DATE_RE.sub(r"\1-\2-\3", text).replace("%", " pct")


def _identifier_format(ed, receipt, _field, fraction, seed, _delta):
    from scripts.profile_pilot.census_detect import LABEL_RE
    rows = {}
    for n in _current_indices(ed.src):
        text = ed.src["positions"][n]["identity"].get("typed_identifier")
        if text and not LABEL_RE.match(text) and rewrite_identifier(text) != text:
            rows[ed.src["positions"][n]["context_id"]] = n
    receipt.update(eligible=len(rows), rule="typed identifier rewritten: every '%' -> ' pct' and every m/d/yyyy "
                                         "date -> m-d-yyyy (position identity, its typed dimension and the "
                                         "context's typed dimension); eligible = rows the rewrite changes")
    for ctx in _select(rows, fraction, seed):
        n = rows[ctx]
        identity = ed.position(n)["identity"]
        old = identity["typed_identifier"]
        new = rewrite_identifier(old)
        identity["typed_identifier"] = new
        for dim in identity.get("typed_dimensions") or []:
            if dim.get("value") == old:
                dim["value"] = new
        context = ed.context(ctx)
        if context is not None:
            for dim in context.get("typed_dimensions") or []:
                if dim.get("value") == old:
                    dim["value"] = new
        receipt["rows"].append(dict(context_id=ctx, before=old, after=new))


# ---------------------------------------------------------------- realism guard

@lru_cache(maxsize=1)
def _validators() -> dict:
    import jsonschema
    from scripts.profile_pilot.census import SCHEMA_PATH
    schema = json.loads(SCHEMA_PATH.read_text(encoding="ascii"))
    defs, props = schema["$defs"], schema["properties"]

    def make(sub):
        return jsonschema.Draft202012Validator(dict(sub, **{"$defs": defs}))
    return dict(field_value=make({"$ref": "#/$defs/field_value"}),
                identity=make(props["positions"]["items"]["properties"]["identity"]), fact=make(props["facts"]["items"]),
                context=make(props["contexts"]["items"]), unit=make(props["units"]["additionalProperties"]),
                mapping=make(props["concept_mappings"]["additionalProperties"]), channels=make(props["channels"]))


def _errs(kind: str, obj) -> set:
    if obj is None:
        return set()
    return {kind + ":" + "/".join(map(str, e.absolute_path)) + ": " + e.message[:160]
            for e in _validators()[kind].iter_errors(obj)}


def realism_errors(before: dict, after: dict, receipt: dict, *, full: bool = False) -> list:
    """New schema errors on every touched object (vs the same object before) + count consistency.

    Untouched objects are the census's own (validated at census time, verdict pass). With
    full=True the whole document also goes through census.validate_census."""
    errors = []
    if len(after["positions"]) != len(before["positions"]) or [p["context_id"] for p in after["positions"]] != [
            p["context_id"] for p in before["positions"]]:
        errors.append("positions: count or order changed")
    removed = len(receipt.get("removed_fact_indices") or [])
    if len(after["facts"]) != len(before["facts"]) - removed:
        errors.append("facts: count differs from before minus removed")
    for key in ("summary",):
        b, a = (before.get(key) or {}).get("facts"), (after.get(key) or {}).get("facts")
        if b == len(before["facts"]) and a != len(after["facts"]):
            errors.append("summary.facts no longer equals the facts count")
    metric = lambda doc: next((m.get("value") for m in doc.get("metrics") or [] if m.get("name") == "facts"), None)
    if metric(before) == len(before["facts"]) and metric(after) != len(after["facts"]):
        errors.append("metrics.facts no longer equals the facts count")
    count = lambda doc, name: (doc["channels"].get(name) or {}).get("count")
    if (count(before, "numeric_facts") or 0) + (count(before, "text_facts") or 0) == len(before["facts"]) and \
            (count(after, "numeric_facts") or 0) + (count(after, "text_facts") or 0) != len(after["facts"]):
        errors.append("channels numeric_facts + text_facts no longer equal the facts count")
    if len(after.get("units") or {}) != len(before.get("units") or {}) + len(receipt.get("added_units") or []):
        errors.append("units: count differs from before plus added")
    present = {f["i"] for f in after["facts"]}
    old_pos = {p["context_id"]: p for p in before["positions"]}
    old_fact = {f["i"]: f for f in before["facts"]}
    old_ctx = {c["id"]: c for c in before.get("contexts") or []}
    touched = {r["context_id"] for r in receipt["rows"]}
    for p in after["positions"]:
        if p["context_id"] not in touched:
            continue
        old = old_pos.get(p["context_id"])
        if old is None or sorted(p) != sorted(old) or sorted(p["fields"]) != sorted(old["fields"]):
            errors.append("position " + p["context_id"] + ": keys or field names changed")
            continue
        for name, value in p["fields"].items():
            if value != old["fields"][name]:
                errors += sorted(_errs("field_value", value) - _errs("field_value", old["fields"][name]))
        if p["identity"] != old["identity"]:
            errors += sorted(_errs("identity", p["identity"]) - _errs("identity", old["identity"]))
        for value in p["fields"].values():
            missing = [i for i in value.get("fact_indices") or [] if i not in present]
            if missing:
                errors.append("position " + p["context_id"] + " references removed facts " + repr(missing[:5]))
    fact_ids = {i for r in receipt["rows"] for i in r.get("fact_indices") or []} - set(
        receipt.get("removed_fact_indices") or [])
    for f in after["facts"]:
        if f["i"] in fact_ids:
            errors += sorted(_errs("fact", f) - _errs("fact", old_fact.get(f["i"])))
    for c in after.get("contexts") or []:
        if c["id"] in touched and c is not old_ctx.get(c["id"]):
            errors += sorted(_errs("context", c) - _errs("context", old_ctx.get(c["id"])))
    for unit in receipt.get("added_units") or []:
        errors += sorted(_errs("unit", (after.get("units") or {}).get(unit)))
    for concept in receipt.get("added_concepts") or []:
        if "concept_mappings" in after:
            errors += sorted(_errs("mapping", after["concept_mappings"].get(concept)))
    errors += sorted(_errs("channels", after["channels"]) - _errs("channels", before["channels"]))
    if full:
        from scripts.profile_pilot.census import validate_census
        errors += ["full: " + e for e in validate_census(after)["errors"]]
    return errors


# ---------------------------------------------------------------- the matrix for one CIK

def outcome(baseline: str, status: str, *, fraction: float | None = None) -> str:
    """Target outcome. Fraction 0 is the null control: 'null_control' when unchanged (never 'missed'),
    'null_control_changed' otherwise (a harness bug or self-inconsistency)."""
    if baseline != "holds":
        return "not_applicable"
    if fraction == 0:
        return "null_control" if status == baseline else "null_control_changed"
    return {"breach": "detected", "insufficient_evidence": "abstained"}.get(status, "missed")


def _target_ids(results: list) -> dict:
    targets = {}
    for kind in CONTRACT_KINDS:
        field = IDENTIFIER_FIELD if kind == "format_grammar" else FIELD
        hits = [r for r in results if r["kind"] == kind and r["field"] == field]
        for r in hits:
            key = kind if len(hits) == 1 else kind + ":" + r["partition_id"]
            targets[key] = r["contract_id"]
    return targets


def evaluate_matrix(*, cik: str, block: dict, tolerances: dict, q1_doc: dict, grammar, yield_q2,
                    variants=VARIANTS, fractions=FRACTIONS, seeds=SEEDS, full_validation: bool = False,
                    semantic: dict | None = None) -> dict:
    """Null control + every variant x fraction x seed, evaluated against the frozen block.

    semantic (Task B2-3): dict(block=<v3 block learned from the unperturbed Q1>, grid=semantic_grid(...),
    range_stats=bool). Each evaluation then also carries the semantic contracts' status at every
    candidate band (`semantic`) and, with range_stats, the median_shift experiment verdicts."""
    variants = list(variants)
    before_digest = manifest.digest(q1_doc)
    listing = dict(status="available", report_date=q1_doc["document"]["report_date"],
                   census_relative="synthetic:perturbed-q1", note=SYNTHETIC_Q2_NOTE)

    def ev(doc):
        return contracts.evaluate_contracts(block, tolerances, q2_doc=doc, q2_listing=listing, grammar=grammar,
                                            yield_q2=yield_q2)

    sem_eval = ms_eval = None
    learn_stats = {}
    if semantic:
        sem_block, grid = semantic["block"], semantic["grid"]
        tols = [g["tolerances"] for g in grid]

        def sem_eval(doc):
            out = contracts.evaluate_semantic_grid(sem_block, tols, q2_doc=doc, q2_listing=listing, grammar=grammar)
            return {g["name"]: {r["contract_id"]: [r["status"], r["cause"], (r.get("observed") or {}).get("criteria"),
                                                   len(r["violating_keys"])] for r in res}
                    for g, res in zip(grid, out)}
        if semantic.get("range_stats"):
            learn_stats = range_stats(range_samples(block, q1_doc, grammar=grammar, tolerances=tolerances))
            meta = {c["contract_id"]: c for c in block["contracts"]}

            def ms_eval(doc, results):
                samples = range_samples(block, doc, grammar=grammar, tolerances=tolerances)
                scale = {(r["partition_id"], r["field"]): r["status"] for r in results if r["kind"] == "scale"}
                out = {}
                for cid, stats in learn_stats.items():
                    gate = scale.get((meta[cid]["partition_id"], meta[cid]["field"])) == "holds"
                    out[cid] = {ms_name(x, y): median_shift_verdict(stats, samples.get(cid, []), x=x, y=y)
                                if gate else "insufficient_evidence"
                                for x in MEDIAN_SHIFT["x"] for y in MEDIAN_SHIFT["y"]}
                return out

    timing = Counter()
    t0 = time.perf_counter()
    null = ev(q1_doc)
    sem_null = sem_eval(q1_doc) if sem_eval else None
    ms_null = ms_eval(q1_doc, null) if ms_eval else None
    timing["evaluate_seconds"] += time.perf_counter() - t0
    ids = [r["contract_id"] for r in null]
    base = {r["contract_id"]: r for r in null}
    targets = _target_ids(null)
    target_set = set(targets.values())
    evaluations, receipts = [], []
    for name, kind, delta in variants:
        for fraction in fractions:
            for s_i, seed in enumerate(seeds):
                t = time.perf_counter()
                doc, receipt = perturb(q1_doc, kind, fraction, seed=seed, delta=delta, deep=False)
                timing["perturb_seconds"] += time.perf_counter() - t
                t = time.perf_counter()
                checked = s_i == 0  # ruling R35: the realism self-check runs on the first seed only
                full = full_validation and fraction == max(fractions) and checked
                problems = realism_errors(q1_doc, doc, receipt, full=full) if checked else []
                timing["validate_seconds"] += time.perf_counter() - t
                t = time.perf_counter()
                results = ev(doc)
                sem_out = sem_eval(doc) if sem_eval else None
                ms_out = ms_eval(doc, results) if ms_eval else None
                timing["evaluate_seconds"] += time.perf_counter() - t
                if [r["contract_id"] for r in results] != ids:
                    raise contracts.ContractError("contract order/denominator changed under perturbation: " + cik)
                changed = [r for r in results if r["status"] != base[r["contract_id"]]["status"]]
                tgt = {}
                for key, cid in targets.items():
                    r = next(x for x in results if x["contract_id"] == cid)
                    tgt[key] = dict(contract_id=cid, status=r["status"], cause=r["cause"],
                                    baseline_status=base[cid]["status"], baseline_cause=base[cid]["cause"],
                                    outcome=outcome(base[cid]["status"], r["status"], fraction=fraction),
                                    violating=len(r["violating_keys"]), expected=contracts._brief(r["expected"]),
                                    observed=contracts._brief(r["observed"]))
                receipt_sha = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode("ascii")).hexdigest()
                evaluations.append(dict(
                    cik=cik, variant=name, kind=kind, delta=delta, fraction=fraction, seed=seed,
                    eligible=receipt["eligible"], filled=receipt["filled"], touched=receipt["touched"],
                    receipt_sha256=receipt_sha,
                    statuses=[[r["status"], r["cause"]] for r in results],
                    changed=[r["contract_id"] for r in changed], targets=tgt,
                    collateral=[dict(contract_id=r["contract_id"], kind=r["kind"], field=r["field"],
                                     before=base[r["contract_id"]]["status"], after=r["status"], cause=r["cause"])
                                for r in changed if r["contract_id"] not in target_set],
                    realism_errors=problems, realism_checked=checked, full_validation=full,
                    **({"semantic": sem_out} if sem_eval else {}),
                    **({"median_shift": ms_out} if ms_eval else {})))
                receipts.append(dict(variant=name, fraction=fraction, seed=seed, receipt_sha256=receipt_sha,
                                     receipt=receipt))
                del doc
    unchanged = manifest.digest(q1_doc) == before_digest
    counts = Counter(r["status"] for r in null)
    extra = {}
    if semantic:
        extra["semantic"] = dict(
            tier=semantic["block"]["tier"], null_control=sem_null, median_shift_null=ms_null, range_stats=learn_stats,
            grid=[{k: v for k, v in g.items() if k != "tolerances"} for g in semantic["grid"]],
            contracts=[dict(contract_id=c["contract_id"], kind=c["kind"], partition_id=c["partition_id"],
                            tier=c["tier"], learn_status=c["learn_status"], learn_cause=c["learn_cause"],
                            expectation=c["expectation"], inception=(c.get("evidence") or {}).get("inception"))
                       for c in semantic["block"]["contracts"] if c["kind"] in contracts.SEMANTIC_KINDS])
    return dict(extra,
        cik=cik, contract_ids=ids,
        contract_meta=[dict(contract_id=r["contract_id"], kind=r["kind"], field=r["field"],
                            partition_id=r["partition_id"]) for r in null],
        targets=targets, synthetic_q2=SYNTHETIC_Q2_NOTE,
        null_control=dict(counts=dict(sorted(counts.items())),
                          breaches=[dict(contract_id=r["contract_id"], cause=r["cause"]) for r in null
                                    if r["status"] == "breach"],
                          statuses=[[r["status"], r["cause"]] for r in null]),
        evaluations=evaluations, receipts=receipts, original_unchanged=unchanged,
        timing=finish_timing(timing))


# ---------------------------------------------------------------- Task B2-3: candidate bands and experiments

def semantic_grid(v2: dict) -> list:
    """Every candidate band as a v3 tolerance over the (frozen) v2 content: 15 composition points
    (share_pp x iqr_widen) and 5 text points; the other family's bands sit at REFERENCE."""
    point = lambda **kw: contracts.semantic_tolerances(v2, calibration=dict(label=IN_SAMPLE, status="candidate grid "
                                                                           "point (calibration only)"), **kw)
    grid = [dict(name="c:s%s_i%s" % (s, i), family="composition", share_pp=s, iqr_widen=i,
                 text_share_pp=REFERENCE["text_share_pp"],
                 tolerances=point(share_pp=s, iqr_widen=i, text_share_pp=REFERENCE["text_share_pp"]))
            for s in CANDIDATES["share_pp"] for i in CANDIDATES["iqr_widen"]]
    grid += [dict(name="t:%s" % t, family="text", share_pp=REFERENCE["share_pp"], iqr_widen=REFERENCE["iqr_widen"],
                  text_share_pp=t, tolerances=point(share_pp=REFERENCE["share_pp"], iqr_widen=REFERENCE["iqr_widen"],
                                                    text_share_pp=t))
             for t in CANDIDATES["text_share_pp"]]
    return grid


def ms_name(x: float, y: float) -> str:
    return "x%s_y%s" % (x, y)


def range_samples(block: dict, doc: dict, *, grammar, tolerances: dict) -> dict:
    """Canonical percent values per LEARNED value_range contract, routed by the block's frozen partitions."""
    from scripts.profile_pilot.contracts_observe import canonical, observe_field
    grammars = contracts.as_grammars(grammar)
    frame = contracts._q2_frame(block, doc, dict(census_relative="range_samples"), grammars)
    conventions = contracts.frozen_scale_conventions(tolerances)
    out = {}
    for c in block["contracts"]:
        if c["kind"] != "value_range" or c["learn_status"] != "learned":
            continue
        pid = c["partition_id"]
        if pid in frame["ambiguous"] or frame["unroutable"]:
            continue
        members = [frame["by_ctx"][k] for k in frame["routing"]["routed"].get(pid, [])]
        obs = observe_field(doc, members, c["field"], frame["facts_by_i"])
        out[c["contract_id"]] = sorted(v for _, v in canonical(obs["values"], c["expectation"]["scale_class"],
                                                               conventions))
    return out


def range_stats(samples: dict) -> dict:
    from scripts.profile_pilot.contracts_observe import quantile
    return {cid: dict(p50=round(quantile(v, 0.5), 10), min=v[0], max=v[-1], n=len(v)) for cid, v in samples.items() if v}


def median_shift_verdict(learned: dict, values: list, *, x: float, y: float) -> str:
    """Calibration-only alternative value_range band (addendum 3, never adopted into v3): breach when
    |Q2 p50 - Q1 p50| / |Q1 p50| > x AND the share of Q2 values outside the Q1 min-max exceeds y."""
    from scripts.profile_pilot.contracts_observe import quantile
    if not values or not learned.get("p50"):
        return "insufficient_evidence"
    ordered = sorted(values)
    shift = abs(quantile(ordered, 0.5) - learned["p50"]) / abs(learned["p50"])
    outside = sum(v < learned["min"] or v > learned["max"] for v in ordered) / len(ordered)
    return "breach" if shift > x + 1e-12 and outside > y + 1e-12 else "holds"


def _semantic_families(grid: list) -> list:
    """(family, value key, grid point, contract kind, criterion or None for the status) per curve cell."""
    out = []
    for g in grid:
        if g["family"] == "composition":
            if g["iqr_widen"] == REFERENCE["iqr_widen"]:
                out.append(("share_pp", str(g["share_pp"]), g["name"], "rate_composition", "share"))
                out.append(("fixed_share", str(g["share_pp"]), g["name"], "rate_composition", "fixed"))
            if g["share_pp"] == REFERENCE["share_pp"]:
                out.append(("iqr_widen", str(g["iqr_widen"]), g["name"], "rate_composition", "iqr"))
            out.append(("composition_status", g["name"], g["name"], "rate_composition", None))
        else:
            out.append(("text_share_pp", str(g["text_share_pp"]), g["name"], "text_agreement", None))
    return out


def _tier_medians(per_cik: dict, tiers: dict) -> tuple[dict, dict, dict]:
    median, applicable, detected = {}, {}, {}
    for tier in ("all", "standard", "low_history"):
        ciks = [c for c in per_cik if tier == "all" or tiers[c] == tier]
        median[tier] = _median_fraction([per_cik[c] for c in ciks])
        applicable[tier] = len(ciks)
        detected[tier] = sum(per_cik[c] is not None for c in ciks)
    return median, applicable, detected


def semantic_curves(evaluations: list, *, grid: list, meta: dict) -> dict:
    """Seeded detection per candidate band: per CIK the smallest fraction at which >= 2 of 3 seeds detect
    (criterion breach, or status breach for whole-contract cells), median over CIKs where the contract
    holds in the null control at that band (median_high, never ranked above 1.0), by tier."""
    grouped: dict = {}
    for e in evaluations:
        grouped.setdefault((e["variant"], e["cik"]), []).append(e)
    variants = sorted({e["variant"] for e in evaluations})
    curves: dict = {}
    for family, key, point, kind, criterion in _semantic_families(grid):
        for variant in variants:
            per_cik, abstained, tiers = {}, {}, {}
            for cik, info in sorted(meta.items()):
                cids = [cid for cid, k in info["contracts"].items() if k == kind
                        and (info["null"].get(point) or {}).get(cid) == "holds"]
                if not cids:
                    continue
                by_f: dict = {}
                for e in grouped.get((variant, cik), []):
                    if e["fraction"] <= 0:
                        continue
                    per = e["semantic"][point]
                    flags = []
                    for cid in cids:
                        status, _, crit = per[cid][0], per[cid][1], per[cid][2] or {}
                        hit = crit.get(criterion) == "breach" if criterion else status == "breach"
                        flags.append("detected" if hit else ("abstained" if status == "insufficient_evidence"
                                                            else "missed"))
                    outcome = "detected" if "detected" in flags else ("abstained" if "abstained" in flags else "missed")
                    by_f.setdefault(e["fraction"], []).append(outcome)
                first = lambda wanted: next((f for f in sorted(by_f) if _majority(by_f[f], wanted)), None)
                per_cik[cik], abstained[cik], tiers[cik] = first("detected"), first("abstained"), info["tier"]
            median, applicable, detected = _tier_medians(per_cik, tiers)
            curves.setdefault(family, {}).setdefault(key, {})[variant] = dict(
                point=point, criterion=criterion or "status", per_cik=per_cik, per_cik_abstained=abstained,
                median=median, applicable=applicable, detected=detected)
    return curves


def median_shift_curves(evaluations: list, *, meta: dict) -> dict:
    """The median_shift experiment beside the v2 band, on the interest_rate value_range contract."""
    grouped: dict = {}
    for e in evaluations:
        grouped.setdefault((e["variant"], e["cik"]), []).append(e)
    names = [ms_name(x, y) for x in MEDIAN_SHIFT["x"] for y in MEDIAN_SHIFT["y"]]
    out: dict = {}
    for variant in sorted({e["variant"] for e in evaluations}):
        for name in names + ["v2_band"]:
            per_cik, tiers = {}, {}
            for cik, info in sorted(meta.items()):
                cid = info.get("range_contract")
                if not cid:
                    continue
                if name != "v2_band" and (info["ms_null"].get(cid) or {}).get(name) != "holds":
                    continue
                if name == "v2_band" and info.get("v2_null") != "holds":
                    continue
                by_f: dict = {}
                for e in grouped.get((variant, cik), []):
                    if e["fraction"] <= 0:
                        continue
                    if name == "v2_band":
                        o = (e["targets"].get("value_range") or {}).get("outcome")
                    else:
                        o = {"breach": "detected", "insufficient_evidence": "abstained"}.get(
                            ((e.get("median_shift") or {}).get(cid) or {}).get(name), "missed")
                    by_f.setdefault(e["fraction"], []).append(o)
                per_cik[cik] = next((f for f in sorted(by_f) if _majority(by_f[f], "detected")), None)
                tiers[cik] = info["tier"]
            median, applicable, detected = _tier_medians(per_cik, tiers)
            out.setdefault(variant, {})[name] = dict(per_cik=per_cik, median=median, applicable=applicable,
                                                     detected=detected)
    return out


def compare_relearned(frozen: dict, relearned: dict) -> dict:
    """The block re-learned with the current code must equal the frozen block on every v2 contract and
    every block field except the version (a v3 block adds only the semantic contracts)."""
    diffs = ["block." + k for k in sorted(set(frozen) | set(relearned))
             if k not in ("version", "contracts") and frozen.get(k) != relearned.get(k)]
    v2 = [c for c in relearned["contracts"] if c["kind"] in contracts.KINDS]
    if len(v2) != len(frozen["contracts"]):
        diffs.append("v2 contract count %d != %d" % (len(v2), len(frozen["contracts"])))
    diffs += [a["contract_id"] for a, b in zip(frozen["contracts"], v2) if a != b]
    return dict(equal=not diffs, differences=diffs[:40], v2_contracts=len(v2),
                semantic_contracts=len(relearned["contracts"]) - len(v2))


# ---------------------------------------------------------------- aggregation

def _majority(outcomes: list, wanted: str) -> bool:
    return sum(o == wanted for o in outcomes) * 2 > len(outcomes)


def _median_fraction(values: list):
    if not values:
        return None
    ranked = [math.inf if v is None else v for v in values]
    med = statistics.median_high(ranked)
    return None if med == math.inf else med


def sensitivity(evaluations: list, *, variants=VARIANT_NAMES, kinds=CONTRACT_KINDS) -> dict:
    """Per variant x kind: per CIK the smallest fraction the seed majority detects (and abstains on);
    median over applicable CIKs with 'never' ranked above every fraction (median_high)."""
    grouped: dict = {}
    eligibility: dict = {}
    for e in evaluations:
        for kind, t in e["targets"].items():
            grouped.setdefault((e["variant"], kind, e["cik"], e["fraction"]), []).append(t["outcome"])
        if "eligible" in e:
            slot = eligibility.setdefault(e["variant"], {}).setdefault(
                e["cik"], dict(eligible=e["eligible"], filled=e.get("filled")))
            if (slot["eligible"], slot["filled"]) != (e["eligible"], e.get("filled")):
                raise ValueError("eligibility differs across evaluations: " + e["variant"] + " " + e["cik"])
    for variant, by_cik in eligibility.items():
        for slot in by_cik.values():
            slot["reason"] = None if slot["eligible"] else (
                "0 eligible rows (of " + str(slot["filled"]) + " filled): nothing was perturbed")
    cells = {}
    for variant in variants:
        cells[variant] = {}
        for kind in kinds:
            per_cik = {}
            ciks = sorted({c for (v, k, c, _) in grouped if v == variant and k == kind})
            for cik in ciks:
                by_f = {f: o for (v, k, c, f), o in grouped.items() if (v, k, c) == (variant, kind, cik)}
                applicable = any(o != "not_applicable" for os_ in by_f.values() for o in os_)
                elig = (eligibility.get(variant) or {}).get(cik)
                reason = None if applicable else "contract does not hold in the null control"
                if elig is not None and not elig["eligible"]:
                    applicable, reason = False, elig["reason"]
                pos = sorted(f for f in by_f if f > 0)
                first = lambda wanted, rule: next((f for f in pos if rule(by_f[f], wanted)), None)
                per_cik[cik] = dict(
                    applicable=applicable, reason=reason,
                    smallest_detected=first("detected", _majority) if applicable else None,
                    smallest_detected_any_seed=first("detected", lambda os_, w: w in os_) if applicable else None,
                    smallest_detected_all_seeds=first("detected", lambda os_, w: all(o == w for o in os_))
                    if applicable else None,
                    smallest_abstained=first("abstained", _majority) if applicable else None,
                    at_full=dict(Counter(by_f.get(1.0, []))),
                    by_fraction={str(f): dict(Counter(o)) for f, o in sorted(by_f.items())})
            applicable = [c for c in per_cik.values() if c["applicable"]]
            cells[variant][kind] = dict(
                per_cik=per_cik, applicable_ciks=len(applicable),
                detected_ciks=sum(c["smallest_detected"] is not None for c in applicable),
                abstained_ciks=sum(c["smallest_abstained"] is not None for c in applicable),
                median_smallest_detected=_median_fraction([c["smallest_detected"] for c in applicable]),
                median_smallest_abstained=_median_fraction([c["smallest_abstained"] for c in applicable]))
    return dict(cells=cells, rule="detected at a fraction = at least 2 of the 3 seeds flip holds -> breach; "
                                  "median over applicable CIKs uses median_high with 'never' ranked above 1.0; a "
                                  "CIK with 0 eligible rows for a class is not applicable for every kind of it",
                variants=list(variants), kinds=list(kinds), eligibility=eligibility)


def blind_spots(evaluations: list, sens: dict) -> list:
    """Every applicable (variant, kind, cik) not detected by the seed majority at fraction 1.0."""
    out = []
    for variant, row in sens["cells"].items():
        for kind, cell in row.items():
            for cik, c in cell["per_cik"].items():
                if not c["applicable"]:
                    continue
                full = [e["targets"][kind] for e in evaluations
                        if e["variant"] == variant and e["cik"] == cik and e["fraction"] == 1.0 and kind in e["targets"]]
                if full and not _majority([t["outcome"] for t in full], "detected"):
                    out.append(dict(variant=variant, kind=kind, cik=cik,
                                    expected_detector=EXPECTED_DETECTOR.get(variant) == kind,
                                    outcomes=[t["outcome"] for t in full], statuses=[t["status"] for t in full],
                                    causes=sorted({str(t["cause"]) for t in full})))
    return out


# ---------------------------------------------------------------- rendering

def _cell(value, n, d) -> str:
    return ("never" if value is None else ("%g" % value)) + " (" + str(d) + "/" + str(n) + ")" if n else "n/a"


def render_summary(*, run_id: str, sens: dict, spots: list, per_cik: dict, timing: dict) -> str:
    lines = ["# M2 seeded-drift sensitivity (" + run_id + ")", "",
             "Frozen contracts v2 (tolerances content_sha256 " + TOLERANCES_V2_SHA256[:12] + "...), learned from the "
             "unperturbed Q1; " + SYNTHETIC_Q2_NOTE + ".",
             "Cell = median over applicable CIKs of the smallest fraction at which >= 2 of 3 seeds BREACH "
             "(never = not detected even at 1.0); (d/n) = CIKs detecting / CIKs where the contract holds in the "
             "null control. Abstention (holds -> insufficient_evidence) is NOT detection; see the second table.", ""]
    kinds = sens["kinds"]
    for title, key, count in (("Detection (breach)", "median_smallest_detected", "detected_ciks"),
                              ("Abstention (insufficient_evidence)", "median_smallest_abstained", "abstained_ciks")):
        lines += ["## " + title, "", "| drift class | " + " | ".join(kinds) + " |",
                  "|---|" + "---|" * len(kinds)]
        for variant in sens["variants"]:
            row = sens["cells"][variant]
            lines.append("| " + variant + " | " + " | ".join(
                _cell(row[k][key], row[k]["applicable_ciks"], row[k][count]) for k in kinds) + " |")
        lines.append("")
    ciks = sorted({c for by_cik in sens.get("eligibility", {}).values() for c in by_cik})
    lines += ["## Eligibility (eligible rows / filled rows of the target field; 0 eligible = not applicable "
              "for every kind of that class)", "", "| drift class | " + " | ".join(ciks) + " |",
              "|---|" + "---|" * len(ciks)]
    for variant in sens["variants"]:
        by_cik = sens.get("eligibility", {}).get(variant, {})
        lines.append("| " + variant + " | " + " | ".join(
            (str(by_cik[c]["eligible"]) + "/" + str(by_cik[c]["filled"])) if c in by_cik else "-" for c in ciks)
            + " |")
    lines.append("")
    lines += ["## Null control (fraction 0, unperturbed Q1 as its own Q2)", "",
              "| cik | breaches | holds | insufficient_evidence |", "|---|---|---|---|"]
    for cik, info in per_cik.items():
        counts = info["null_control"]["counts"]
        lines.append("| " + cik + " | " + str(len(info["null_control"]["breaches"])) + " | "
                     + str(counts.get("holds", 0)) + " | " + str(counts.get("insufficient_evidence", 0)) + " |")
    lines += ["", "## Blind spots: expected detector did not breach at fraction 1.0", ""]
    expected = [s for s in spots if s["expected_detector"]]
    lines += ["- " + s["variant"] + " / " + s["kind"] + " / " + s["cik"] + ": " + ",".join(s["outcomes"])
              + " (" + "; ".join(s["causes"]) + ")" for s in expected] or ["- none"]
    lines += ["", "Other applicable (class, kind, CIK) not detected at 1.0: " + str(len(spots) - len(expected))
              + " (listed in sensitivity.json)", "", "## Timing per CIK", "",
              "| cik | measured s (perturb + evaluate; R35 bound) | evaluate s | perturb s | validate s (seed-1 self-check) | wall s | peak wset MiB |", "|---|---|---|---|---|---|---|"]
    for cik, t in timing.items():
        lines.append("| " + cik + " | " + str(t["measured_seconds"]) + " | " + str(t.get("evaluate_seconds")) + " | "
                     + str(t.get("perturb_seconds")) + " | " + str(t.get("validate_seconds")) + " | " + str(t["wall_seconds"]) + " | "
                     + str(t["peak_wset_bytes"] // 2 ** 20) + " |")
    text = "\n".join(lines) + "\n"
    text.encode("ascii")
    return text


def semantic_meta(per_cik: dict) -> tuple[dict, dict]:
    """Per CIK: tier, learned semantic contracts and their null-control status per band; and the
    median_shift inputs (interest_rate value_range contract, its null verdicts, the v2 null status)."""
    meta, ms = {}, {}
    for cik, info in per_cik.items():
        sem = info["semantic"]
        meta[cik] = dict(tier=sem["tier"],
                         contracts={c["contract_id"]: c["kind"] for c in sem["contracts"] if c["learn_status"] == "learned"},
                         null={name: {cid: v[0] for cid, v in per.items()} for name, per in sem["null_control"].items()})
        rc = info["targets"].get("value_range")
        null = dict(zip(info["contract_ids"], (s[0] for s in info["null_control"]["statuses"])))
        ms[cik] = dict(tier=sem["tier"], range_contract=rc, ms_null=sem.get("median_shift_null") or {},
                       v2_null=null.get(rc))
    return meta, ms


def _fmt_median(cell: dict) -> str:
    med = cell["median"]
    show = lambda v: "never" if v is None else "%g" % v
    return (show(med["all"]) + " (" + str(cell["detected"]["all"]) + "/" + str(cell["applicable"]["all"]) + ")"
            + "; std " + show(med["standard"]) + ", low " + (show(med["low_history"])
                                                              if cell["applicable"]["low_history"] else "n/a"))


def render_semantic_summary(*, run_id: str, curves: dict, ms_curves: dict, meta: dict, contracts_by_cik: dict) -> str:
    lines = ["# M2 semantic kinds: seeded sensitivity per candidate band (" + run_id + ")", "",
             "Label: " + IN_SAMPLE + ". Bands swept on the B2-1 seeds after the Stage B Q2 and the history were read.",
             "Cell = median over CIKs where the contract holds in the null control at that band of the smallest "
             "fraction at which >= 2 of 3 seeds detect (never = not at 1.0); (d/n) CIKs detecting / applicable; std/low "
             "= tier medians. share_pp and iqr_widen cells count their own criterion; text_share_pp and the "
             "composition grid count the contract status.", ""]
    for family in ("share_pp", "fixed_share", "iqr_widen", "text_share_pp", "composition_status"):
        table = curves.get(family) or {}
        if not table:
            continue
        variants = sorted({v for cells in table.values() for v in cells})
        lines += ["## " + family, "", "| band | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
        for key in table:
            lines.append("| " + key + " | " + " | ".join(_fmt_median(table[key][v]) if v in table[key] else "-"
                                                          for v in variants) + " |")
        lines.append("")
    lines += ["## median_shift experiment (calibration only, NOT in v3) beside the v2 value_range band", "",
              "interest_rate value_range; x = relative median move, y = share of rows outside the Q1 min-max.", ""]
    names = sorted({n for by in ms_curves.values() for n in by})
    lines += ["| variant | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for variant, by in sorted(ms_curves.items()):
        lines.append("| " + variant + " | " + " | ".join(_fmt_median(by[n]) if n in by else "-" for n in names) + " |")
    lines += ["", "## Semantic contracts learned from the unperturbed Q1 (with the inception block)", "",
              "| cik | tier | kind | learn | cause | inception share_rate_le_spread | rate_equals_text_spread | "
              "(magnitude-normalised) | implied base p50 |", "|---|---|---|---|---|---|---|---|---|"]
    for cik, items in sorted(contracts_by_cik.items()):
        for c in items:
            inc = c.get("inception") or {}
            lines.append("| " + " | ".join(str(x) for x in (
                cik, meta.get(cik, {}).get("tier"), c["kind"], c["learn_status"], c["learn_cause"],
                inc.get("share_rate_le_spread"), inc.get("rate_equals_text_spread"),
                (inc.get("rate_equals_text_spread_magnitude_normalised") or {}).get("share"),
                inc.get("implied_base_p50"))) + " |")
    text = "\n".join(lines) + "\n"
    text.encode("ascii")
    return text


CSV_FIELDS = ("cik", "variant", "fraction", "seed", "eligible", "touched", "contract_id", "kind", "field",
              "status", "cause", "null_status", "role", "outcome")


def render_csv(per_cik: dict) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    for cik, info in per_cik.items():
        meta = info["contract_meta"]
        null = info["null_control"]["statuses"]
        by_target = {cid: key for key, cid in info["targets"].items()}
        for e in info["evaluations"]:
            for m, (st, cause), (nst, _) in zip(meta, e["statuses"], null):
                key = by_target.get(m["contract_id"])
                role = "target" if key else ("collateral" if m["contract_id"] in e["changed"] else "other")
                writer.writerow((cik, e["variant"], e["fraction"], e["seed"], e["eligible"], e["touched"],
                                 m["contract_id"], m["kind"], m["field"], st, cause or "", nst, role,
                                 e["targets"][key]["outcome"] if key else ""))
    return buf.getvalue()


def _write_text_once(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="ascii", newline="\n") as stream:
        stream.write(text)
    return path


# ---------------------------------------------------------------- the stage

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_run_id(now: datetime | None = None) -> str:
    return RUN_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")


def _record(path, label: str, *, code_root=None, blob_of=None) -> dict:
    record = manifest.file_record(path, label)
    if record["status"] != "present":
        raise StageInvalidated("pinned input missing: " + label + " (" + str(path) + ")")
    if blob_of is not None:
        record["git_blob"] = cohort.git_blob(code_root, blob_of)
    return record


def _peak_bytes() -> int:
    import psutil
    info = psutil.Process().memory_info()
    return int(getattr(info, "peak_wset", 0) or info.rss)


def _workload(cik: str, size: int) -> dict:
    return dict(ciks=[cik], instance_count=0, full_cache_scan=False, pipeline_cik_count=1,
                est_seconds=round(5 + size / 1e6, 1), est_bytes=int(400e6 + 20 * size))


def pin_tolerances(tol_path: Path) -> tuple[dict, dict]:
    record = manifest.file_record(tol_path, "contracts_root/inventories/contract_tolerances.json")
    if record["status"] != "present":
        raise StageInvalidated("frozen tolerances missing: " + str(tol_path))
    body = json.loads(Path(tol_path).read_text(encoding="ascii"))
    if body.get("inventory") != "contract_tolerances" or body.get("content_sha256") != TOLERANCES_V2_SHA256:
        raise StageInvalidated("tolerances file is not the frozen v2 (content_sha256 " + str(body.get("content_sha256"))
                               + ")")
    if manifest.digest(body["content"]) != body["content_sha256"]:
        raise StageInvalidated("tolerances content does not match its content_sha256")
    if body["content"].get("version") != contracts.TOLERANCES_VERSION_V2:
        raise StageInvalidated("tolerances version is not " + contracts.TOLERANCES_VERSION_V2)
    return body["content"], dict(record, content_sha256=body["content_sha256"], run_id=body.get("run_id"),
                                 version=body["content"]["version"])


def pin_block(paths, croot: Path, cik: str, row: dict, inventory: dict) -> tuple[dict, dict]:
    """The frozen learned block, reused as is (self-contained); fails closed on any drift."""
    record = _record(croot / "learning" / (cik + ".json"), "contracts_root/learning/" + cik + ".json")
    outer = json.loads(Path(record["path"]).read_text(encoding="ascii"))
    if outer.get("complete") is not True:
        raise StageInvalidated("learning block incomplete: " + cik)
    deps = outer["identity"]["dependencies"]
    if deps["census"]["sha256"] != row["census_sha256"] or deps["census_fingerprint"] != row["fingerprint"]:
        raise StageInvalidated("learning block was not learned from the authoritative Q1 census: " + cik)
    block = outer["result"]
    if block != inventory["ciks"].get(cik):
        raise StageInvalidated("learning block differs from the frozen contract_inventory: " + cik)
    if len(block["contracts"]) != inventory["denominator"]["by_cik"][cik]:
        raise StageInvalidated("learning block denominator differs from the frozen inventory: " + cik)
    drift = []
    for rec in deps["code"]:
        rel = rec["label"][len("code/"):]
        now = manifest.file_record(paths.code_root / rel, rec["label"])
        if now.get("sha256") != rec["sha256"]:
            drift.append(rel)
    # Code drift (Task B2-3 changed contracts.py) no longer fails here: the stage re-learns the block
    # from the same Q1 inputs with the current code and requires equality (compare_relearned) before
    # any evaluation; the frozen block is still the one evaluated.
    return block, dict(record, learned_code_checked=len(deps["code"]), code_drift=drift,
                       block_source="reused_frozen_learning_block",
                       drift_rule="code drift -> re-learn with the current code and require equality with the frozen "
                                  "block (v2 subset for a v3 re-learn) before evaluating; mismatch invalidates")


def run_stage(paths, *, census_run_id: str, profile_run_id: str, contracts_run_id: str, ciks=None,
              scratch_dir: Path | None = None, fractions=FRACTIONS, seeds=SEEDS, semantic: bool = False) -> dict:
    """semantic=True (Task B2-3): the semantic drift classes + range shifts, the v3 semantic contracts at
    every candidate band (IN-SAMPLE calibration) and the median_shift experiment; the v2 block is still
    the frozen one and the re-learned block must equal it on the v2 subset."""
    from scripts.profile_pilot import contracts_run
    ciks = list(ciks or cohort.PILOT_CIKS)
    run_variants = SEMANTIC_VARIANTS if semantic else VARIANTS
    started = time.perf_counter()
    clock = dict(started_utc=_now())
    census = lineage.load_authoritative_census(paths, census_run_id, roles=("q1",), ciks=ciks,
                                               label_prefix="census_root/")
    for cik in ciks:
        if (cik, "q1") not in census["rows"]:
            raise StageInvalidated("no authoritative Q1 census for " + cik)
    proot = lineage.sibling_root(paths, profile_run_id).run_root
    summary_rec = _record(proot / lineage.PROFILE_SUMMARY_RELATIVE, "profile_root/" + lineage.PROFILE_SUMMARY_RELATIVE)
    summary_body = json.loads(Path(summary_rec["path"]).read_text(encoding="ascii"))
    profile_lineage = lineage.check_profile_lineage(summary_body, census_run_id=census_run_id,
                                                    census_rows=census["rows"], ciks=ciks, eras=("q1",))
    profile_recs = {}
    for cik in ciks:
        rec = _record(proot / "profiles" / cik / "q1.json", "profile_root/profiles/" + cik + "/q1.json")
        if rec["sha256"] != (summary_body["profiles"].get(cik + "/q1") or {}).get("sha256"):
            raise StageInvalidated("profile file differs from profile_summary: " + cik)
        profile_recs[cik] = rec
    cpaths = lineage.sibling_root(paths, contracts_run_id)
    croot = cpaths.run_root
    cman_rec = _record(croot / "manifest.json", "contracts_root/manifest.json")
    cman = json.loads(Path(cman_rec["path"]).read_text(encoding="ascii"))
    if cman["census_source"]["run_id"] != census_run_id or cman["profile_source"]["run_id"] != profile_run_id:
        raise StageInvalidated("contracts root was not built from the pinned census/profile roots")
    tolerances, tol_rec = pin_tolerances(croot / "inventories" / "contract_tolerances.json")
    inv_rec = _record(croot / "inventories" / "contract_inventory.json", "contracts_root/inventories/contract_inventory.json")
    inventory = manifest.load_inventory(cpaths, "contract_inventory")
    if inventory["tolerances"]["content_sha256"] != TOLERANCES_V2_SHA256:
        raise StageInvalidated("contract_inventory was frozen against other tolerances")
    blocks, block_recs, grammars, grammar_recs = {}, {}, {}, {}
    for cik in ciks:
        blocks[cik], block_recs[cik] = pin_block(paths, croot, cik, census["rows"][(cik, "q1")], inventory)
        grammars[cik], grammar_recs[cik] = contracts_run.pin_grammar(paths, cik)
        want = [(g["sha256"], g["dialect"]) for g in blocks[cik]["grammar"] or []]
        got = [(grammars[cik]["sha256"], grammars[cik]["dialect"])] if grammars[cik] else []
        if want != got:
            raise StageInvalidated("authored grammar differs from the one pinned in the learned block: " + cik)
    code = [_record(paths.code_root / rel, "code/" + rel, code_root=paths.code_root, blob_of=rel) for rel in CODE_FILES]
    config = dict(fractions=list(fractions), seeds=list(seeds), variants=[list(v) for v in run_variants], field=FIELD,
                  contract_kinds=list(CONTRACT_KINDS), expected_detector=EXPECTED_DETECTOR,
                  full_validation_max_bytes=FULL_VALIDATION_MAX_BYTES, limit_rule=LIMIT_RULE, limits=dict(seconds=LIMIT_SECONDS,
                                                                                   bytes=LIMIT_BYTES))
    grid = ref_tol = None
    if semantic:
        grid = semantic_grid(tolerances)
        ref_tol = contracts.semantic_tolerances(tolerances, bands=contracts.SEMANTIC_BANDS,
                                                calibration=dict(label=IN_SAMPLE, status="learning reference only"))
        config.update(semantic=True, label=IN_SAMPLE, candidates={k: list(v) for k, v in CANDIDATES.items()},
                      reference=REFERENCE, targets=SEMANTIC_TARGETS,
                      median_shift=dict(MEDIAN_SHIFT, note="calibration-only experiment (addendum 3); not in v3"),
                      grid=[dict(name=g["name"], family=g["family"], share_pp=g["share_pp"], iqr_widen=g["iqr_widen"],
                                 text_share_pp=g["text_share_pp"], content_sha256=manifest.digest(g["tolerances"]))
                            for g in grid],
                      learning_reference=dict(content_sha256=manifest.digest(ref_tol),
                                              rule="the semantic block is learned once from the unperturbed Q1 "
                                                   "(expectations are band-free); every grid point re-bands it"),
                      v2_subset_rule="the re-learned block equals the frozen v2 block on every v2 contract "
                                     "(compare_relearned); a mismatch invalidates the stage")
    inputs = ([census["authoritative"]] + census["files"] + [summary_rec] + list(profile_recs.values())
              + [cman_rec, tol_rec, inv_rec] + list(block_recs.values())
              + [r for recs in grammar_recs.values() for r in recs] + code)
    keep = ("label", "path", "status", "sha256", "bytes")
    built = dict(
        run_id=paths.run_id, stage="m2_seed", version=SEED_VERSION, created_utc=_now(),
        git=dict(head=manifest.git_head(paths.code_root),
                 dirty_source_digest=manifest.dirty_source_digest(paths.code_root)["sha256"]),
        roots=dict(main_repo_root=str(paths.main_repo_root), code_root=str(paths.code_root),
                   data_root=str(paths.data_root), run_root=str(paths.run_root)),
        census_source=dict(run_id=census_run_id, census_sha256={
            c: census["rows"][(c, "q1")]["census_sha256"] for c in ciks},
            census_relative={c: census["rows"][(c, "q1")]["census_relative"] for c in ciks}),
        profile_source=dict(run_id=profile_run_id, lineage=profile_lineage,
                            sha256={c: r["sha256"] for c, r in profile_recs.items()},
                            use="lineage and pinning only; the learned partitions are in the reused frozen blocks"),
        contracts_source=dict(run_id=contracts_run_id, manifest_sha256=cman_rec["sha256"],
                              git_head=cman.get("git", {}).get("head"),
                              inventory_content_sha256=inventory.get("tolerances"),
                              learning={c: dict(sha256=r["sha256"], block_source=r["block_source"]) for c, r in
                                        block_recs.items()}),
        tolerances=dict(content_sha256=tol_rec["content_sha256"], version=tol_rec["version"],
                        run_id=tol_rec["run_id"], file_sha256=tol_rec["sha256"],
                        rule="read from the frozen file; never rebuilt from tolerance_content()"),
        grammars={c: (None if g is None else dict(path=g["path"], sha256=g["sha256"], dialect=g["dialect"],
                                                  anchors_source=g.get("anchors_source"), provenance="inherited"))
                  for c, g in grammars.items()},
        code=code, config=config, synthetic_q2=SYNTHETIC_Q2_NOTE,
        inputs=[{k: r[k] for k in keep if k in r} for r in inputs])
    write_once_json(paths, "manifest.json", built)
    clock["manifest_written_utc"] = _now()

    per_cik, timing, receipts_rel = {}, {}, {}
    for cik in ciks:
        row = census["rows"][(cik, "q1")]
        block = blocks[cik]
        identity = manifest.cache_identity("m2_seed", dict(
            cik=cik, census=row["record"], census_fingerprint=row["fingerprint"], learning=block_recs[cik],
            tolerances=tol_rec, grammar=grammar_recs[cik], code=code, config=config), collector_version=SEED_VERSION)

        def compute(cik=cik, row=row, block=block):
            t0 = time.perf_counter()
            q1_doc = contracts_run.load_census(row)
            yield_q1 = next(c for c in block["contracts"] if c["kind"] == "fund_income_yield")["evidence"]["q1_yield"]
            check, relearned, learn_seconds = None, None, 0.0
            if semantic or block_recs[cik]["code_drift"]:
                t = time.perf_counter()
                profile = contracts_run.load_profile(
                    profile_recs[cik], census_sha256=summary_body["profiles"][cik + "/q1"]["census_sha256"])
                relearned = contracts.learn_contracts(
                    cik=cik, q1_doc=q1_doc, q1_profile=profile, grammar=grammars[cik], yield_q1=yield_q1,
                    tolerances=ref_tol if semantic else tolerances, q2_listing=block["q2_listing"],
                    recorded_at=block["recorded_at"])
                check = compare_relearned(block, relearned)
                learn_seconds = time.perf_counter() - t
                if not check["equal"]:
                    raise StageInvalidated("the current code does not re-learn the frozen v2 block for " + cik + ": "
                                           + ", ".join(check["differences"][:10]))
            matrix = evaluate_matrix(cik=cik, block=block, tolerances=tolerances, q1_doc=q1_doc,
                                     grammar=grammars[cik], yield_q2=yield_q1, fractions=fractions, seeds=seeds,
                                     full_validation=row["record"]["bytes"] <= FULL_VALIDATION_MAX_BYTES,
                                     variants=run_variants,
                                     semantic=dict(block=relearned, grid=grid, range_stats=True) if semantic else None)
            matrix["timing"].update(wall_seconds=round(time.perf_counter() - t0, 2), peak_wset_bytes=_peak_bytes(),
                                    census_bytes=row["record"]["bytes"], q1_positions=block["q1"]["positions"],
                                    learn_seconds=round(learn_seconds, 3))
            # R35 bound: the re-learn is measured work too (added to perturb + evaluate)
            matrix["timing"]["measured_seconds"] = round(matrix["timing"]["measured_seconds"] + learn_seconds, 3)
            matrix["relearn_check"] = check
            matrix["block_source"] = block_recs[cik]["block_source"]
            matrix["yield_q2"] = "the frozen Q1 yield evidence (the yield contract is not perturbed)"
            return matrix

        out = manifest.run_cached_stage(paths, "results/cik/" + cik + ".json", identity, compute,
                                        workload=_workload(cik, row["record"]["bytes"]))
        matrix = out["result"]
        receipts_rel[cik] = "results/cik/" + cik + ".json"
        timing[cik] = matrix["timing"]
        per_cik[cik] = {k: v for k, v in matrix.items() if k != "receipts"}
        print("  " + cik + ": " + str(len(matrix["evaluations"])) + " evaluations, " + str(
            matrix["timing"]["wall_seconds"]) + " s, peak " + str(matrix["timing"]["peak_wset_bytes"] // 2 ** 20)
              + " MiB, null breaches " + str(len(matrix["null_control"]["breaches"])) + " (" + out["cache"] + ")")
        if matrix["timing"]["measured_seconds"] > LIMIT_SECONDS or matrix["timing"]["peak_wset_bytes"] > LIMIT_BYTES:
            write_once_json(paths, "results/limit_exceeded.json", dict(cik=cik, timing=matrix["timing"],
                                                                       done=list(per_cik)))
            raise LimitExceeded(cik + " exceeded the measured bound: " + json.dumps(matrix["timing"]))
    clock["evaluation_done_utc"] = _now()
    evaluations = [e for info in per_cik.values() for e in info["evaluations"]]
    names = tuple(v[0] for v in run_variants)
    sens = sensitivity(evaluations, variants=names)
    spots = blind_spots(evaluations, sens)
    semantic_copies = []
    if semantic:
        meta, ms_meta = semantic_meta(per_cik)
        curves = semantic_curves(evaluations, grid=grid, meta=meta)
        ms_curves = median_shift_curves(evaluations, meta=ms_meta)
        body = dict(run_id=paths.run_id, label=IN_SAMPLE, candidates={k: list(v) for k, v in CANDIDATES.items()},
                    reference=REFERENCE, targets=SEMANTIC_TARGETS, curves=curves, median_shift=ms_curves,
                    tiers={c: m["tier"] for c, m in meta.items()},
                    contracts={c: info["semantic"]["contracts"] for c, info in per_cik.items()},
                    relearn_checks={c: info["relearn_check"] for c, info in per_cik.items()},
                    eligibility=sens.get("eligibility"),
                    rule="detected at a band = >= 2 of 3 seeds breach (the named criterion for share_pp / iqr_widen, "
                         "the contract status otherwise); applicable = the contract holds in the null control at that "
                         "band; median over applicable CIKs (median_high, never ranked above 1.0)")
        write_once_json(paths, "results/semantic_curves.json", body)
        semantic_md = render_semantic_summary(run_id=paths.run_id, curves=curves, ms_curves=ms_curves, meta=meta,
                                              contracts_by_cik=body["contracts"])
        _write_text_once(confined(paths, "results/semantic_summary.md"), semantic_md)
        semantic_copies.append(semantic_md)
    collateral = Counter()
    for e in evaluations:
        for c in e["collateral"]:
            collateral[(e["variant"], c["kind"], c["field"], c["before"], c["after"], str(c["cause"]))] += 1
    realism = sum(len(e["realism_errors"]) for e in evaluations)
    write_once_json(paths, "results/seed_matrix.json", dict(
        run_id=paths.run_id, fractions=list(fractions), seeds=list(seeds), variants=list(names),
        synthetic_q2=SYNTHETIC_Q2_NOTE, receipts=receipts_rel, ciks=per_cik))
    write_once_json(paths, "results/sensitivity.json", dict(
        sens, run_id=paths.run_id, blind_spots=spots, expected_detector=EXPECTED_DETECTOR,
        collateral=[dict(variant=k[0], kind=k[1], field=k[2], before=k[3], after=k[4], cause=k[5], evaluations=n)
                    for k, n in sorted(collateral.items())],
        null_control={c: info["null_control"]["breaches"] for c, info in per_cik.items()},
        realism_errors=realism, original_unchanged={c: info["original_unchanged"] for c, info in per_cik.items()}))
    summary_md = render_summary(run_id=paths.run_id, sens=sens, spots=spots, per_cik=per_cik, timing=timing)
    matrix_csv = render_csv(per_cik)
    _write_text_once(confined(paths, "results/summary.md"), summary_md)
    _write_text_once(confined(paths, "results/seed_matrix.csv"), matrix_csv)
    scratch = Path(scratch_dir) if scratch_dir else paths.code_root / "scratch" / "2026-09-29_m2_assessment"
    copies = [str(_write_text_once(scratch / ("seed_summary_" + paths.run_id + ".md"), summary_md)),
              str(_write_text_once(scratch / ("seed_matrix_" + paths.run_id + ".csv"), matrix_csv))]
    copies += [str(_write_text_once(scratch / ("seed_semantic_" + paths.run_id + ".md"), text))
               for text in semantic_copies]
    after = manifest.verify_inputs(dict(inputs=[{k: r[k] for k in keep if k in r} for r in inputs]))
    if not after["ok"]:
        raise StageInvalidated("pinned inputs changed during the stage: " + json.dumps(after)[:400])
    run_summary = dict(run_id=paths.run_id, git_head=built["git"]["head"], clock=clock,
                       seconds=round(time.perf_counter() - started, 1), evaluations=len(evaluations),
                       null_breaches=sum(len(i["null_control"]["breaches"]) for i in per_cik.values()),
                       realism_errors=realism, blind_spots_expected=sum(s["expected_detector"] for s in spots),
                       timing=timing, scratch_copies=copies, input_verification_after=after)
    write_once_json(paths, "results/run_summary.json", run_summary)
    return run_summary


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
    cmd.add_argument("--profile-run-id", required=True)
    cmd.add_argument("--contracts-run-id", required=True)
    cmd.add_argument("--cik", action="append", default=None)
    cmd.add_argument("--scratch-dir", type=Path, default=None)
    cmd.add_argument("--semantic", action="store_true",
                     help="Task B2-3: semantic drift classes, v3 semantic contracts at every candidate band")
    args = parser.parse_args(argv)
    try:
        main_root = args.main_root or discover_main_root(CODE_ROOT)
        paths = resolve_paths(main_repo_root=main_root, data_root=args.data_root,
                              code_root=args.code_root or CODE_ROOT, run_id=args.run_id or default_run_id())
        receipt = "verification/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_m2_seed_preservation.json"
        with protection.protected_session(paths, receipt=receipt):
            summary = run_stage(paths, census_run_id=args.census_run_id, profile_run_id=args.profile_run_id,
                                contracts_run_id=args.contracts_run_id, ciks=args.cik, scratch_dir=args.scratch_dir,
                                semantic=args.semantic)
    except StageInvalidated as exc:
        print("STAGE INVALIDATED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_INVALIDATED
    except (contracts.ContractError, PerturbError) as exc:
        print("CONTRACT ERROR: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_CONTRACT
    except (PathError, protection.LeaseRefused) as exc:
        print("REFUSED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_REFUSED
    except LimitExceeded as exc:
        print("LIMIT EXCEEDED (stopped, not widened): " + str(exc))
        return EXIT_LIMIT
    print("run: " + summary["run_id"] + " | git_head " + summary["git_head"] + " | " + str(summary["seconds"])
          + " s | evaluations " + str(summary["evaluations"]) + " | null breaches " + str(summary["null_breaches"])
          + " | realism errors " + str(summary["realism_errors"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
