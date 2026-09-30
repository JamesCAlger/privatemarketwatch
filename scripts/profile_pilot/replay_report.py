"""Sub-project 1: score the single Q4-2025 -> Q1-2026 rolling pair per filer, evaluate the spec's
criterion 3 floors, and write the shadow drift queue in findings-ledger shape.

    python -m scripts.profile_pilot.replay_report run --data-root D
        --backtest-run-id B --seed-run-id S [--run-id sp1-replay-<stamp>] [--main-root M]

Inputs (read only, each pinned with its sha256 in this run's manifest): the back-test run root
(results/pairs.json, results/backtest_results.json, results/positives.json, results/scoring.json,
manifest.json), the seed run root (results/sensitivity.json), the census run root the back-test
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
TOTALS_KIND = "independent_totals"
STRUCTURAL_RECALL_FLOOR = 0.90
STRUCTURAL_FP_CEILING = 0.02
TOTALS_FRACTION_FLOOR = 0.20
TOTALS_VARIANT = "fair_value_scale_flip"
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
    "totals": "seed " + TOTALS_VARIANT + ": median_smallest_detected <= %.2f AND detected_ciks == applicable_ciks"
              % TOTALS_FRACTION_FLOOR,
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


def totals_verdict(cell: dict) -> str:
    """independent_totals floor from the seed run's fair_value_scale_flip sensitivity cell."""
    med = cell.get("median_smallest_detected")
    ok = (med is not None and med <= TOTALS_FRACTION_FLOOR and cell["applicable_ciks"] > 0
          and cell["detected_ciks"] == cell["applicable_ciks"])
    return "PASS" if ok else "FAIL"


def _fmt_m(value: float) -> str:
    return format(value / 1e6, ".1f")


def review_id(contract_id: str, eval_date: str) -> str:
    return "DRIFT_" + hashlib.sha1((contract_id + eval_date).encode("ascii")).hexdigest()[:12]


def queue_rows(results: dict, *, pairs: dict, fv_by_quarter: dict) -> list:
    """One ledger-shaped row per breach or newly-abstained result on the selected pairs, ranked by FV at risk."""
    out = []
    for cik, pair in sorted(pairs.items()):
        fv = fv_by_quarter.get((cik, pair["eval_date"])) or dict(total=0.0, by_key={})
        for r in results.get(pair["pair_id"]) or []:
            if r["status"] != "breach" and not r.get("newly_abstained"):
                continue
            keys = list(r.get("violating_keys") or [])
            at_risk = sum(float(fv["by_key"].get(k) or 0.0) for k in keys)
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
    for p in contracts_totals._current(doc):
        value = contracts_totals._num((p["fields"].get(FV_FIELD) or {}).get("value"))
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
            cell = seeded.get(TOTALS_KIND)
            out[kind] = dict(floor=FLOOR_TEXT["totals"], measured=dict(seed=cell, replay=measured),
                             verdict=totals_verdict(cell) if cell else "FAIL",
                             basis="seed run sensitivity (" + TOTALS_VARIANT + ")"
                                   + ("" if cell else ": cell missing") + "; " + SAMPLE_LABEL)
    return out


def seeded_cells(sens: dict) -> dict:
    cell = ((sens.get("cells") or {}).get(TOTALS_VARIANT) or {}).get(TOTALS_KIND)
    if cell is None:
        return {}
    return {TOTALS_KIND: dict(variant=TOTALS_VARIANT, median_smallest_detected=cell["median_smallest_detected"],
                              detected_ciks=cell["detected_ciks"], applicable_ciks=cell["applicable_ciks"])}


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
    lines += _table(("kind", "variant", "median smallest detected", "detected ciks", "applicable ciks"),
                    [(k, s["variant"], s["median_smallest_detected"], s["detected_ciks"], s["applicable_ciks"])
                     for k, s in body["seeded"].items()])
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
    recs["ledger"] = m2_seed._record(paths.data_root / m2_backtest.LEDGER_CSV, "data/" + m2_backtest.LEDGER_CSV)
    bman = _load(recs["manifest"])
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
    seeded = seeded_cells(_load(recs["sensitivity"]))

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
                per_kind=per_kind, floors=floors(per_kind, seeded), exclusions=exclusions, seeded=seeded,
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
