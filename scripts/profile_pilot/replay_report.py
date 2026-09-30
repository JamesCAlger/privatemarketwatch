"""Sub-project 1: score the single Q4-2025 -> Q1-2026 rolling pair per filer, evaluate the spec's
criterion 3 floors, and write the shadow drift queue in findings-ledger shape.

    python -m scripts.profile_pilot.replay_report run --data-root D
        --backtest-run-id B --seed-run-id S [--run-id sp1-replay-<stamp>] [--main-root M]

Inputs (read only, each pinned with its sha256 in this run's manifest): the back-test run root
(results/pairs.json, results/backtest_results.json, results/positives.json, results/scoring.json,
manifest.json), the seed run root (results/sensitivity.json, results/run_summary.json, manifest.json:
its contracts_source/census_source run ids must equal the back-test's), the census run root the back-test
read (the eval-quarter census documents only) and the q1p3 findings ledger.

Scoring is m2_backtest.score over ONLY the selected pairs (mode rolling, reading as_evaluated,
positive set all); the selected pairs' positive units are cross-checked against the back-test's
own scoring.json. Floors are pre-registered constants below and are never tuned. Every number
is IN-SAMPLE (SAMPLE_LABEL). Negatives are 'nothing recorded', not 'verified unchanged': the
false-alarm rate is an UPPER bound (unadjudicated breaches count against the kind).
Exit codes: 0 ok, 2 stage invalidated, 4 refused.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from scripts.profile_pilot import contracts_run, contracts_totals, lineage, m2_backtest, m2_seed, manifest, protection
from scripts.profile_pilot.manifest import StageInvalidated
from scripts.profile_pilot.paths import PathError, confined, discover_main_root, resolve_paths, write_once_json

CODE_ROOT = Path(__file__).resolve().parents[2]
REPLAY_VERSION = "sp1-replay.v1"
RUN_PREFIX = "sp1-replay-"
EXIT_INVALIDATED, EXIT_REFUSED = 2, 4

STRUCTURAL = ("source_concept_set", "fill_rate", "format_grammar", "scale")
NOT_CLAIMED = ("value_range", "rate_composition", "text_agreement", "fund_income_yield")
TOTALS_KIND = contracts_totals.KIND
STRUCTURAL_RECALL_FLOOR = 0.90
STRUCTURAL_FP_CEILING = 0.02
TOTALS_FRACTION_FLOOR = 0.20
TOTALS_VARIANT = "fair_value_scale_flip"
# Both totals seed variants are reported per filer; only TOTALS_VARIANT carries the floor.
TOTALS_VARIANT_FIELDS = {TOTALS_VARIANT: contracts_totals.TOTALS_FIELD, "pct_scale_flip": contracts_totals.PCT_FIELD}
TOTALS_SEED_NOTE = ("x0.01 is not seeded: the seed harness has only the x100 flip (fair_value_scale_flip, "
                    "pct_scale_flip)")
EVAL_DATE = "2026-03-31"
MODE, READING, POSITIVE_SET = "rolling", "as_evaluated", "all"
# The Interfaces block's wording (task-5 brief); step 3 carried a paraphrase (resolution in the task-5 report).
SAMPLE_LABEL = "IN-SAMPLE (q1p3 adjudicated 2026-08/09; first out-of-sample quarter 2026-06-30)"
PAIR_RULE = ("per CIK the rolling pair whose eval_date is " + EVAL_DATE + " (learn = the previous authoritative "
             "quarter, normally 2025-12-31); a pair with a gap between learn and eval is kept and flagged gapped")
LEDGER_HEADER = ("review_id", "state", "in_queue", "population_origin", "verdict_status", "verdict_detail",
                 "has_fix_route", "cik", "rule_name", "report_date", "lane", "engine", "fv_at_risk_m",
                 "fund_quarter_fv_m")
QUEUE_TRAILING = ("contract_id", "kind", "field", "cause", "n_violating", "violating_keys")
FV_FIELD = contracts_totals.TOTALS_FIELD
FLOOR_TEXT = {
    "structural": "recall >= %.2f AND false_alarm_rate <= %.2f (false_alarm_rate = (adjudicated_false_alarm_breaches "
                  "+ unadjudicated_breaches) / neg_n, the upper bound); pos_units == 0 -> NO_POSITIVES"
                  % (STRUCTURAL_RECALL_FLOOR, STRUCTURAL_FP_CEILING),
    "totals": "seed " + TOTALS_VARIANT + ": every ANCHORED CIK (seed run_summary financials_loaded) detected at "
              "fraction <= %.2f; denominator = anchored CIKs, not the seed's applicable set (controller ruling "
              "2026-10-01); 0 anchored -> NO_ANCHORS" % TOTALS_FRACTION_FLOOR,
    "not_claimed": "detection_not_claimed (spec criterion 3): measured numbers reported, no floor"}


# ---------------------------------------------------------------- pure parts

def select_pairs(pairs: list, *, eval_date: str = EVAL_DATE) -> dict:
    """cik -> the rolling pair evaluated at eval_date (at most one per CIK: rolling pairs are consecutive)."""
    chosen = {}
    for p in pairs:
        if p["mode"] != MODE or p["eval_date"] != eval_date:
            continue
        if p["cik"] in chosen:
            raise StageInvalidated("two rolling pairs evaluated at " + eval_date + " for " + p["cik"])
        chosen[p["cik"]] = p
    return dict(sorted(chosen.items()))


def _rate(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def _recall(m: dict):
    return _rate(m["detected"], m["pos_units"])


def _false_alarm_rate(m: dict):
    return _rate(m["adjudicated_false_alarm_breaches"] + m["unadjudicated_breaches"], m["neg_n"])


def floor_verdict(kind: str, m: dict) -> str:
    """PASS / FAIL / NO_POSITIVES for the structural kinds; NOT_CLAIMED for the value/semantic kinds."""
    if kind in NOT_CLAIMED:
        return "NOT_CLAIMED"
    if kind not in STRUCTURAL:
        raise ValueError("no structural floor for kind " + repr(kind))
    if not m["pos_units"]:
        return "NO_POSITIVES"
    fa = _false_alarm_rate(m)
    ok = _recall(m) >= STRUCTURAL_RECALL_FLOOR and fa is not None and fa <= STRUCTURAL_FP_CEILING
    return "PASS" if ok else "FAIL"


def totals_measured(seeded: dict) -> dict:
    """detected / anchored for TOTALS_VARIANT: a CIK counts as detected only when its seed smallest_detected
    fraction is <= TOTALS_FRACTION_FLOOR. The denominator is every anchored CIK (financials loaded in the
    seed run), so a CIK whose contract never held at baseline counts against the floor."""
    per_cik = seeded["variants"][TOTALS_VARIANT]["per_cik"]
    anchored = sorted(c for c, r in per_cik.items() if r["anchored"])
    detected = sorted(c for c in anchored if per_cik[c]["smallest_detected"] is not None
                      and per_cik[c]["smallest_detected"] <= TOTALS_FRACTION_FLOOR)
    return dict(detected=len(detected), anchored=len(anchored), detected_over_anchored=
                str(len(detected)) + "/" + str(len(anchored)), detected_ciks=detected,
                not_detected={c: per_cik[c]["reason"] for c in anchored if c not in detected})


def totals_verdict(seeded: dict) -> str:
    """independent_totals floor (controller ruling 2026-10-01): PASS only when EVERY anchored CIK is detected
    at fraction <= TOTALS_FRACTION_FLOOR under TOTALS_VARIANT; 0 anchored CIKs -> NO_ANCHORS (not measurable,
    never a PASS); otherwise FAIL."""
    m = totals_measured(seeded)
    if not m["anchored"]:
        return "NO_ANCHORS"
    return "PASS" if m["detected"] == m["anchored"] else "FAIL"


def _fmt_m(value: float) -> str:
    return format(value / 1e6, ".1f")


def review_id(contract_id: str, eval_date: str) -> str:
    return "DRIFT_" + hashlib.sha1((contract_id + eval_date).encode("ascii")).hexdigest()[:12]


def _num_or_none(value):
    return None if value is None else float(value)


def fv_at_risk(result: dict, *, keys: list, fv: dict) -> float:
    """Fair value at risk of one queued result (controller ruling, Task 5 fix round 1).

    independent_totals carries no violating keys, so its at-risk figure comes from the observed totals:
    fair_value -> |fv_sum - fv_anchor|; pct_of_net_assets -> fund FV x |pct_sum - pct_sum_q1| / 100;
    0 when an input is missing. Every other kind: the FV sum of the violating rows."""
    if result["kind"] == TOTALS_KIND:
        observed = result.get("observed") if isinstance(result.get("observed"), dict) else {}
        expected = result.get("expected") if isinstance(result.get("expected"), dict) else {}
        if result["field"] == contracts_totals.TOTALS_FIELD:
            fv_sum, anchor = _num_or_none(observed.get("fv_sum")), _num_or_none(observed.get("fv_anchor"))
            return abs(fv_sum - anchor) if fv_sum is not None and anchor is not None else 0.0
        if result["field"] == contracts_totals.PCT_FIELD:
            pct, pct_q1 = _num_or_none(observed.get("pct_sum")), _num_or_none(expected.get("pct_sum_q1"))
            return float(fv["total"]) * abs(pct - pct_q1) / 100 if pct is not None and pct_q1 is not None else 0.0
        return 0.0
    return sum(float(fv["by_key"].get(k) or 0.0) for k in keys)


def queue_rows(results: dict, *, pairs: dict, fv_by_quarter: dict) -> list:
    """One ledger-shaped row per breach or newly-abstained result on the selected pairs, ranked by FV at risk."""
    out = []
    for cik, pair in sorted(pairs.items()):
        fv = fv_by_quarter.get((cik, pair["eval_date"])) or dict(total=0.0, by_key={})
        for r in results.get(pair["pair_id"]) or []:
            if r["status"] != "breach" and not r.get("newly_abstained"):
                continue
            keys = list(r.get("violating_keys") or [])
            at_risk = fv_at_risk(r, keys=keys, fv=fv)
            out.append(dict(review_id=review_id(r["contract_id"], pair["eval_date"]), state="open", in_queue="shadow",
                            population_origin="live", verdict_status="MISSING", verdict_detail="",
                            has_fix_route="False", cik=cik, rule_name="drift:" + r["kind"],
                            report_date=pair["eval_date"], lane="drift", engine="profile_contracts",
                            fv_at_risk_m=_fmt_m(at_risk), fund_quarter_fv_m=_fmt_m(float(fv["total"])),
                            contract_id=r["contract_id"], kind=r["kind"], field=r["field"], cause=r.get("cause") or "",
                            n_violating=r.get("n_violating", len(keys)), violating_keys=" ".join(keys),
                            _at_risk=at_risk, _status=r["status"]))
    out.sort(key=lambda o: (-o["_at_risk"], o["cik"], o["contract_id"]))
    return out


def drift_queue_csv(results: dict, *, pairs: dict, fv_by_quarter: dict) -> str:
    header = LEDGER_HEADER + QUEUE_TRAILING
    return m2_backtest.render_csv(header, [[row[h] for h in header]
                                           for row in queue_rows(results, pairs=pairs, fv_by_quarter=fv_by_quarter)])


def fv_of_doc(doc: dict) -> dict:
    """Census FV total (contracts_totals.observe_totals) and per-position FV keyed by the position's context_id.

    The key is the census position's TOP-LEVEL `context_id` (census.py builds positions with
    context_id=context["id"]; `identity` carries no context id): the id contracts.py puts in
    violating_keys (contracts_observe row_keys / absent_keys / conflicts are p["context_id"])."""
    total = contracts_totals.observe_totals(doc, financials=None)["fv_sum"]
    by_key = {}
    for p in contracts_totals.current_positions(doc):
        value = contracts_totals.numeric_value((p["fields"].get(FV_FIELD) or {}).get("value"))
        if value is not None:
            by_key[p["context_id"]] = float(value)
    return dict(total=float(total), by_key=by_key)


def per_kind_scores(pairs: dict, results: dict, positives: list) -> dict:
    """kind -> the replay's measured numbers, from ONE m2_backtest.score call over the selected pairs only."""
    block = m2_backtest.score(list(pairs.values()), results, positives, mode=MODE,
                              exclude_categories=m2_backtest.POSITIVE_SETS[POSITIVE_SET])
    adjudicated, unadjudicated = {}, {}
    for item in block["adjudicated_false_alarm_breaches"]:
        adjudicated[item["kind"]] = adjudicated.get(item["kind"], 0) + 1
    for item in block["unadjudicated"]:
        unadjudicated[item["kind"]] = unadjudicated.get(item["kind"], 0) + 1
    abstentions = {}
    for cik, pair in pairs.items():
        if pair["status"] != "evaluated":
            continue
        for r in results.get(pair["pair_id"]) or []:
            if r["status"] == "insufficient_evidence":
                abstentions.setdefault(r["kind"], []).append([cik, r["field"], r["cause"]])
    kinds = sorted(set(block["by_kind"]) | set(STRUCTURAL) | set(NOT_CLAIMED) | {TOTALS_KIND})
    out = {}
    for kind in kinds:
        v = block["by_kind"].get(kind) or dict(positives=m2_backtest._blank_pos(), negatives=m2_backtest._blank_neg())
        pos, neg = v["positives"], v["negatives"]
        m = dict(pos_units=pos["detected"] + pos["abstained"] + pos["missed"], detected=pos["detected"],
                 abstained=pos["abstained"], missed=pos["missed"],
                 not_covered=pos["not_covered"] + pos["no_contract"], neg_n=neg["n"], neg_breach=neg["breach"],
                 adjudicated_false_alarm_breaches=adjudicated.get(kind, 0),
                 unadjudicated_breaches=unadjudicated.get(kind, 0))
        m["recall"] = _recall(m)
        m["false_alarm_rate"] = _false_alarm_rate(m)
        m["abstentions"] = sorted(abstentions.get(kind, []), key=lambda a: [str(x) for x in a])
        out[kind] = m
    return dict(per_kind=out, units=block["positive_units"], unadjudicated=block["unadjudicated"],
                adjudicated=block["adjudicated_false_alarm_breaches"], unscorable=block["unscorable"])


def floors(per_kind: dict, seeded: dict) -> dict:
    out = {}
    for kind, m in per_kind.items():
        measured = dict(recall=m["recall"], false_alarm_rate=m["false_alarm_rate"], pos_units=m["pos_units"],
                        neg_n=m["neg_n"])
        if kind in STRUCTURAL:
            out[kind] = dict(floor=FLOOR_TEXT["structural"], measured=measured, verdict=floor_verdict(kind, m),
                             basis="replay pair (eval " + EVAL_DATE + "); " + SAMPLE_LABEL)
        elif kind in NOT_CLAIMED:
            out[kind] = dict(floor=FLOOR_TEXT["not_claimed"], measured=measured, verdict="NOT_CLAIMED",
                             basis="spec criterion 3 detection_not_claimed; " + SAMPLE_LABEL)
        elif kind == TOTALS_KIND:
            entry = seeded.get(TOTALS_KIND)
            seed = totals_measured(entry) if entry else None
            out[kind] = dict(floor=FLOOR_TEXT["totals"], measured=dict(seed=seed, replay=measured),
                             verdict=totals_verdict(entry) if entry else "FAIL",
                             basis="seed run sensitivity (" + TOTALS_VARIANT + ")"
                                   + ("" if entry else ": cell missing") + "; " + TOTALS_SEED_NOTE + "; "
                                   + SAMPLE_LABEL)
    return out


def _baseline_cause(null_control: list, field: str):
    """The seed null control's breach cause for this CIK's independent_totals contract on `field`, or None."""
    for b in null_control or []:
        parts = str(b.get("contract_id", "")).split(":")
        if len(parts) >= 3 and parts[1] == TOTALS_KIND and parts[2] == field:
            return b.get("cause") or "unknown"
    return None


def totals_row(cell_cik: dict | None, *, anchored: bool, null_control: list, field: str) -> dict:
    """One filer's totals seed outcome: anchored (financials loaded), applicable (the contract held in the null
    control), smallest_detected, and why it was not measured/detected."""
    c = cell_cik or {}
    applicable, smallest = bool(c.get("applicable")), c.get("smallest_detected")
    if not anchored:
        reason = "no_anchor"
    elif applicable:
        reason = "measured" if smallest is not None else "not_detected_at_1.0"
    else:
        cause = _baseline_cause(null_control, field)
        reason = ("baseline_out_of_band:" + cause if cause
                  else "not_applicable:" + str(c.get("reason") or "absent from the seed cell"))
    return dict(anchored=anchored, applicable=applicable, smallest_detected=smallest, reason=reason)


def seeded_cells(sens: dict, *, financials_loaded: dict) -> dict:
    """Both totals seed variants, per filer. `financials_loaded` = the seed run_summary's cik -> bool."""
    cells = sens.get("cells") or {}
    if (cells.get(TOTALS_VARIANT) or {}).get(TOTALS_KIND) is None:
        return {}
    null_control = sens.get("null_control") or {}
    variants = {}
    for variant, field in TOTALS_VARIANT_FIELDS.items():
        cell = (cells.get(variant) or {}).get(TOTALS_KIND) or {}
        per = cell.get("per_cik") or {}
        ciks = sorted(set(per) | set(financials_loaded))
        variants[variant] = dict(field=field, median_smallest_detected=cell.get("median_smallest_detected"),
                                 detected_ciks=cell.get("detected_ciks"), applicable_ciks=cell.get("applicable_ciks"),
                                 per_cik={c: totals_row(per.get(c), anchored=financials_loaded.get(c) is True,
                                                        null_control=null_control.get(c), field=field)
                                          for c in ciks})
    return {TOTALS_KIND: dict(floor_variant=TOTALS_VARIANT, note=TOTALS_SEED_NOTE, variants=variants)}


def exclusion_buckets(exclusions: list) -> dict:
    """Count the unscored ledger rows by bucket. A state the back-test knowingly excludes
    (m2_backtest.LEDGER_EXCLUDED_STATES) buckets as excluded_state:<state>; an unscored state NOT in that
    list buckets as unexpected_state:<state> so a new ledger state is visible; unmapped rules as
    rule_not_mapped."""
    out = {}
    for e in exclusions:
        if e["reason"].startswith("rule_not_mapped:"):
            bucket = "rule_not_mapped"
        elif e["state"] in m2_backtest.LEDGER_EXCLUDED_STATES:
            bucket = "excluded_state:" + str(e["state"])
        else:
            bucket = "unexpected_state:" + str(e["state"])
        out[bucket] = out.get(bucket, 0) + 1
    return dict(sorted(out.items()))


LINEAGE_KEYS = ("contracts_source", "census_source")


def check_seed_lineage(seed_manifest: dict, backtest_manifest: dict) -> None:
    """The seed and the back-test must read the same contracts root and the same census root."""
    for key in LINEAGE_KEYS:
        seed_id = (seed_manifest.get(key) or {}).get("run_id")
        back_id = (backtest_manifest.get(key) or {}).get("run_id")
        if seed_id is None or seed_id != back_id:
            raise StageInvalidated("seed and back-test lineage differ on " + key + ".run_id: seed " + repr(seed_id)
                                   + " vs back-test " + repr(back_id))


def check_units(units: list, recorded: list, pair_ids: set) -> None:
    """The selected pairs' positive units must equal the back-test's own scoring of those pairs."""
    key = lambda u: (u["pair_id"], u["positive_id"], u["kind"], u["outcome"])
    mine = sorted(key(u) for u in units)
    theirs = sorted(key(u) for u in recorded if u["pair_id"] in pair_ids)
    if mine != theirs:
        raise StageInvalidated("replay positive units differ from the back-test scoring.json for the selected pairs")


# ---------------------------------------------------------------- rendering

def _cell(v) -> str:
    return "-" if v is None else str(v)


def _row(values) -> str:
    return "| " + " | ".join(_cell(v) for v in values) + " |"


def _table(header, rows) -> list:
    return [_row(header), "|" + "---|" * len(header)] + [_row(r) for r in rows]


def render_md(body: dict, queue: list) -> str:
    lines = ["# Drift replay Q4-2025 -> Q1-2026 (" + body["run_id"] + ")", "", "**" + body["sample_label"] + "**", "",
             "Pair rule: " + body["pair_rule"], "", body["negatives_caveat"], "", "## Pairs", ""]
    lines += _table(("cik", "pair_id", "learn", "eval", "gapped"),
                    [(c, p["pair_id"], p["learn_date"], p["eval_date"], p["gapped"]) for c, p in body["ciks"].items()])
    lines += ["", "## Per kind (" + body["sample_label"] + ")", ""]
    lines += _table(("kind", "pos units", "detected", "abstained", "missed", "recall", "neg n", "neg breach",
                     "adjudicated FA", "unadjudicated", "FA rate (upper)", "abstentions"),
                    [(k, m["pos_units"], m["detected"], m["abstained"], m["missed"], m["recall"], m["neg_n"],
                      m["neg_breach"], m["adjudicated_false_alarm_breaches"], m["unadjudicated_breaches"],
                      m["false_alarm_rate"], len(m["abstentions"])) for k, m in body["per_kind"].items()])
    lines += ["", "## Floors (spec criterion 3, pre-registered; " + body["sample_label"] + ")", ""]
    lines += _table(("kind", "verdict", "measured", "floor"),
                    [(k, f["verdict"], json.dumps(f["measured"], sort_keys=True), f["floor"])
                     for k, f in body["floors"].items()])
    lines += ["", "## Seeded (independent_totals)", ""]
    for kind, s in body["seeded"].items():
        m = totals_measured(s)
        lines += ["Floor variant " + s["floor_variant"] + ": detected " + m["detected_over_anchored"]
                  + " anchored filers at fraction <= " + str(TOTALS_FRACTION_FLOOR) + " (denominator = anchored "
                  "filers). Note: " + s["note"] + ".", ""]
        lines += _table(("kind", "variant", "median smallest detected (seed applicable set)", "detected ciks",
                         "applicable ciks"),
                        [(kind, v, c["median_smallest_detected"], c["detected_ciks"], c["applicable_ciks"])
                         for v, c in s["variants"].items()])
        lines += ["", "Per filer:", ""]
        lines += _table(("cik", "variant", "anchored", "applicable", "smallest detected", "reason"),
                        [(cik, v, r["anchored"], r["applicable"], r["smallest_detected"], r["reason"])
                         for v, c in s["variants"].items() for cik, r in c["per_cik"].items()])
    lines += ["", "## Ledger rows not scored (by bucket)", ""]
    lines += _table(("bucket", "rows"), sorted(body.get("exclusion_buckets", {}).items()))
    lines += ["", "## Abstentions", ""]
    lines += _table(("kind", "cik", "field", "cause"),
                    [(k, a[0], a[1], a[2]) for k, m in body["per_kind"].items() for a in m["abstentions"]])
    lines += ["", "## Ledger rows not scored", ""]
    lines += _table(("review_id", "cik", "date", "rule", "state", "reason"),
                    [(e["review_id"], e["cik"], e["date"], e["rule_name"], e["state"], e["reason"])
                     for e in body["exclusions"]])
    lines += ["", "## Drift queue (shadow, ranked by FV at risk)", ""]
    lines += _table(("review_id", "cik", "rule", "field", "status", "cause", "n violating", "fv at risk $m",
                     "fund FV $m"),
                    [(q["review_id"], q["cik"], q["rule_name"], q["field"], q["_status"], q["cause"], q["n_violating"],
                      q["fv_at_risk_m"], q["fund_quarter_fv_m"]) for q in queue])
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- the stage

def default_run_id(now: datetime | None = None) -> str:
    return RUN_PREFIX + (now or datetime.now(timezone.utc)).strftime("%Y%m%dt%H%M%Sz")


def _load(record: dict):
    return json.loads(Path(record["path"]).read_text(encoding="ascii"))


def _ledger_rows(paths, ciks) -> list:
    return m2_backtest._query(
        paths, "SELECT review_id, state, lpad(cik, 10, '0') AS cik, rule_name, substr(report_date, 1, 10) AS "
               "report_date, verdict_status FROM read_csv(?, all_varchar=true, header=true) WHERE lpad(cik, 10, '0') "
               "IN (SELECT unnest(?)) ORDER BY review_id", [str(paths.data_root / m2_backtest.LEDGER_CSV), list(ciks)])


def run(paths, *, backtest_run_id: str, seed_run_id: str) -> dict:
    broot = lineage.sibling_root(paths, backtest_run_id).run_root
    sroot = lineage.sibling_root(paths, seed_run_id).run_root
    recs = {name: m2_seed._record(broot / rel, "backtest_root/" + rel) for name, rel in (
        ("manifest", "manifest.json"), ("pairs", "results/pairs.json"), ("results", "results/backtest_results.json"),
        ("positives", "results/positives.json"), ("scoring", "results/scoring.json"))}
    recs["sensitivity"] = m2_seed._record(sroot / "results" / "sensitivity.json", "seed_root/results/sensitivity.json")
    recs["seed_manifest"] = m2_seed._record(sroot / "manifest.json", "seed_root/manifest.json")
    recs["seed_run_summary"] = m2_seed._record(sroot / "results" / "run_summary.json",
                                               "seed_root/results/run_summary.json")
    recs["ledger"] = m2_seed._record(paths.data_root / m2_backtest.LEDGER_CSV, "data/" + m2_backtest.LEDGER_CSV)
    bman = _load(recs["manifest"])
    check_seed_lineage(_load(recs["seed_manifest"]), bman)
    results = _load(recs["results"])["results"]
    positives = _load(recs["positives"])["rows"]
    scoring = _load(recs["scoring"])
    chosen = select_pairs(_load(recs["pairs"])["pairs"])
    if not chosen:
        raise StageInvalidated("the back-test holds no rolling pair evaluated at " + EVAL_DATE)
    missing = [p["pair_id"] for p in chosen.values() if p["status"] == "evaluated" and p["pair_id"] not in results]
    if missing:
        raise StageInvalidated("selected pairs have no back-test results: " + ", ".join(missing))
    scored = per_kind_scores(chosen, results, positives)
    check_units(scored["units"], scoring["positive_units"][MODE][READING], {p["pair_id"] for p in chosen.values()})
    loaded = _load(recs["seed_run_summary"]).get("financials_loaded")
    if not isinstance(loaded, dict):
        raise StageInvalidated("seed run_summary.json carries no financials_loaded map")
    seeded = seeded_cells(_load(recs["sensitivity"]), financials_loaded=loaded)

    # census FV of the eval quarter: exactly the files the back-test pinned
    census_run_id = bman["census_source"]["run_id"]
    pinned_files = bman["census_source"]["files"]
    ciks = list(chosen)
    probe = lineage.load_authoritative_census(paths, census_run_id, roles=(), ciks=ciks, hash_files=False)
    roles = sorted({r["role"] for r in probe["listing"]["fund_quarters"]
                    if r["cik"] in ciks and r["report_date"] == EVAL_DATE})
    census = lineage.load_authoritative_census(paths, census_run_id, roles=roles, ciks=ciks,
                                               label_prefix="census_root/")
    fv_by_quarter = {}
    for (cik, _role), row in sorted(census["rows"].items()):
        if row["report_date"] != EVAL_DATE:
            continue
        if pinned_files.get(row["census_relative"]) != row["census_sha256"]:
            raise StageInvalidated("eval census differs from the one the back-test pinned: " + row["census_relative"])
        if (cik, EVAL_DATE) in fv_by_quarter:
            raise StageInvalidated("two authoritative censuses for " + cik + " " + EVAL_DATE)
        fv_by_quarter[(cik, EVAL_DATE)] = fv_of_doc(contracts_run.load_census(row))

    ledger = _ledger_rows(paths, ciks)
    exclusions = []
    for cik, pair in chosen.items():
        dates = {r["report_date"] for r in ledger if r["cik"] == cik
                 and pair["learn_date"] < r["report_date"] <= pair["eval_date"]}
        exclusions += m2_backtest.ledger_exclusions(ledger, ciks={cik}, dates=dates)

    per_kind = scored["per_kind"]
    body = dict(run_id=paths.run_id, sample_label=SAMPLE_LABEL, pair_rule=PAIR_RULE,
                ciks={c: dict(pair_id=p["pair_id"], learn_date=p["learn_date"], eval_date=p["eval_date"],
                              gapped=p["gapped"]) for c, p in chosen.items()},
                per_kind=per_kind, floors=floors(per_kind, seeded), exclusions=exclusions,
                exclusion_buckets=exclusion_buckets(exclusions), seeded=seeded,
                unadjudicated=scored["unadjudicated"], unscorable=scored["unscorable"],
                negatives_caveat=m2_backtest.NEGATIVES_CAVEAT,
                source=dict(backtest_run_id=backtest_run_id, seed_run_id=seed_run_id, census_run_id=census_run_id,
                            mode=MODE, reading=READING, positive_set=POSITIVE_SET))
    queue = queue_rows(results, pairs=chosen, fv_by_quarter=fv_by_quarter)

    primary = manifest.load_inventory(census["paths"], "primary_quarter_inventory")
    built = manifest.build_manifest(paths, primary_inventory=primary)
    keep = ("label", "path", "status", "sha256", "bytes")
    pinned = list(recs.values()) + [census["authoritative"]] + census["files"]
    built["inputs"] += [{k: r[k] for k in keep if k in r} for r in pinned]
    built.update(stage="sp1_replay", version=REPLAY_VERSION, sample_label=SAMPLE_LABEL, sources=body["source"],
                 constants=dict(structural=list(STRUCTURAL), not_claimed=list(NOT_CLAIMED),
                                structural_recall_floor=STRUCTURAL_RECALL_FLOOR,
                                structural_fp_ceiling=STRUCTURAL_FP_CEILING,
                                totals_fraction_floor=TOTALS_FRACTION_FLOOR, totals_variant=TOTALS_VARIANT,
                                eval_date=EVAL_DATE))
    write_once_json(paths, "manifest.json", built)
    after = manifest.verify_inputs(dict(inputs=[{k: r[k] for k in keep if k in r} for r in pinned]))
    if not after["ok"]:
        raise StageInvalidated("pinned inputs changed during the replay: " + json.dumps(after)[:400])
    write_once_json(paths, "results/replay_q4_q1.json", body)
    m2_seed._write_text_once(confined(paths, "results/replay_q4_q1.md"), render_md(body, queue))
    m2_seed._write_text_once(confined(paths, "results/drift_queue.csv"),
                             drift_queue_csv(results, pairs=chosen, fv_by_quarter=fv_by_quarter))
    return dict(run_id=paths.run_id, git_head=built["git"]["head"], pairs=len(chosen), queue_rows=len(queue),
                floors={k: f["verdict"] for k, f in body["floors"].items()})


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
    cmd.add_argument("--backtest-run-id", required=True)
    cmd.add_argument("--seed-run-id", required=True)
    args = parser.parse_args(argv)
    try:
        main_root = args.main_root or discover_main_root(CODE_ROOT)
        paths = resolve_paths(main_repo_root=main_root, data_root=args.data_root,
                              code_root=args.code_root or CODE_ROOT, run_id=args.run_id or default_run_id())
        receipt = ("verification/" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                   + "_replay_preservation.json")
        with protection.protected_session(paths, receipt=receipt):
            summary = run(paths, backtest_run_id=args.backtest_run_id, seed_run_id=args.seed_run_id)
    except StageInvalidated as exc:
        print("STAGE INVALIDATED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_INVALIDATED
    except (PathError, protection.LeaseRefused) as exc:
        print("REFUSED: " + str(exc).encode("ascii", "backslashreplace").decode("ascii"))
        return EXIT_REFUSED
    print("run: " + summary["run_id"] + " | git_head " + summary["git_head"] + " | pairs " + str(summary["pairs"])
          + " | queue rows " + str(summary["queue_rows"]) + " | " + SAMPLE_LABEL)
    for kind, verdict in summary["floors"].items():
        print("  floor " + kind + ": " + verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
