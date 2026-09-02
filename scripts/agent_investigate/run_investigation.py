"""Agentic investigation driver -- the path that BYPASSES the deterministic B2 battery.

The agent investigates a conservation FV discrepancy for ONE cik using two read-only tools
(agent_data_query over the extracted data + evidence_cli over the filing), finds the root
cause itself, and AUTHORS auditable rule(s). This driver only: builds the agent's prompt
(`prep`), applies the agent's authored rules to a trial (`apply`), and runs the B3 conservation
re-check (`gate`). No probes, no template registry, no mechanism-deciding here.

    python -m scripts.agent_investigate.run_investigation prep  --cik 1377936 --target-quarter 2026-02-28
    python -m scripts.agent_investigate.run_investigation apply --cik 1377936
    python -m scripts.agent_investigate.run_investigation gate  --cik 1377936 --target-quarter 2026-02-28

ASCII-only. Cache-only. The `apply`/`gate` outputs land under data/output/agent_investigate/.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import duckdb
import pandas as pd

from pipeline import config
from pipeline.agent_rule import (
    apply_rules, dedupe_escalations, gate_rules, load_escalations, load_rules,
    validate_escalation, validate_rule, value_sum_by_quarter,
)
from pipeline.anchor_leaf import load_anchor_leaf, validate_anchor_leaf
from pipeline.anchor_validation import classify_anchors, flag_anchor_outliers

BASE = config.OUTPUT_DIR / "agent_investigate"
CONSERVATION = config.OUTPUT_DIR / "shadow" / "conservation_gate_results.csv"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
DEFAULT_OVERRIDES = config.AGENT_INVESTIGATE_RULES_DIR
# Per-cik verified GRAND-total anchors written by the anchor-adjudicator (agent_anchor). When
# present for a cik-quarter, this REPLACES the (possibly incomplete) companyfacts subtotal as the
# strong anchor the fixer + gate reconcile to. See pipeline/anchor_leaf.py.
ANCHOR_OVERRIDES = config.PROJECT_ROOT / "data" / "overrides" / "agent_anchor"
WORKER_PYTHON = sys.executable
DATA_QUERY = "scripts/review_agent/data_query_cli.py"
EVIDENCE_CLI = "scripts/review_agent/evidence_cli.py"
REVIEW_BUNDLES = config.OUTPUT_DIR / "review_queue" / "review_bundles"


def _find_bundle(cik: str, target_quarter: str):
    """The review bundle (-> cached filing) for this cik-quarter, so the B2 worker can READ THE
    FILING via evidence_cli -- not just query the extracted data. Returns the path or None."""
    c, q = _norm(cik), str(target_quarter)
    for p in sorted(REVIEW_BUNDLES.glob("*.json")) if REVIEW_BUNDLES.exists() else []:
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (_norm(b.get("cik")) == c and str(b.get("report_date")) == q
                and str(b.get("rule_name") or "") == "fv_conservation"):
            return p
    return None
# Stop tolerance = the shared engine reconcile band (pipeline.config), so a
# loop-level "success" is also an engine-level reconcile. Was 1.0 while the
# engine flagged at 0.5 -- two Wave-1 targets landed in the gap (1930087,
# 1930679) and stayed flagged after promotion.
STOP_TOL_PCT = config.FV_CONSERVATION_BAND_PCT
MAX_ITER = 5            # ... or after 5 iterations


def _noop_gate_verdict(residual_pct, anchor_tier) -> dict | None:
    """PASS_NOOP short-circuit for ZERO-RULE investigations: the baseline already
    reconciles to a validated anchor, so there is no correction to overfit and
    held_out_coverage's rationale is vacuous (2083477 q1p3: a first-time filer with
    one anchored quarter and residual 0.0 could never pass). Mirrors the
    residual_improved already-reconciled carve-out inside the gate. Over-band or
    unvalidated-anchor no-ops return None and fall through to the full gate FAIL --
    that is a worker that gave up, not a clean quarter."""
    if anchor_tier not in ("HIGH", "MEDIUM"):
        return None
    if residual_pct is None or abs(residual_pct) > STOP_TOL_PCT:
        return None
    return {"verdict": "PASS_NOOP", "reasons": [
        f"no rules authored; baseline already reconciles to validated anchor "
        f"(tier {anchor_tier}, residual {residual_pct}%) -- nothing to promote"]}


def loop_decision(residual_pct, iteration, *, gate_verdict=None, n_escalations=0, max_iter=MAX_ITER,
                  tol_pct=STOP_TOL_PCT) -> dict:
    """Stop successfully only when FV matches within tol_pct and the held-out gate passes.
    Stop unsuccessfully after max_iter iterations; otherwise iterate.
    If a worker escalated and we are past iteration 1, treat escalation as a terminal outcome."""
    if residual_pct is not None and abs(residual_pct) <= tol_pct:
        if gate_verdict in ("PASS", "PASS_NOOP"):
            return {"stop": True, "success": True,
                    "reason": f"FV within {tol_pct}% and gate {gate_verdict} (residual {residual_pct}%)"}
        if iteration >= max_iter:
            return {"stop": True, "success": False,
                    "reason": f"max iterations ({max_iter}) reached with gate {gate_verdict} "
                              f"(residual {residual_pct}%)"}
        if n_escalations > 0 and iteration >= 2:
            return {"stop": True, "success": False,
                    "reason": f"worker escalated (n={n_escalations}); honest stop -- "
                              "escalation is the outcome, do not re-iterate"}
        return {"stop": False, "success": False,
                "reason": f"FV within {tol_pct}% but gate {gate_verdict}; iterate"}
    if iteration >= max_iter:
        return {"stop": True, "success": False,
                "reason": f"max iterations ({max_iter}) reached (residual {residual_pct}%)"}
    if n_escalations > 0 and iteration >= 2:
        return {"stop": True, "success": False,
                "reason": f"worker escalated (n={n_escalations}); honest stop -- "
                          "escalation is the outcome, do not re-iterate"}
    return {"stop": False, "success": False,
            "reason": f"residual {residual_pct}% exceeds {tol_pct}%; iterate"}


def _norm(cik: str) -> str:
    return str(cik).lstrip("0")


def load_anchors(cik: str, rule_name="fv_conservation") -> dict[str, float]:
    anchors: dict[str, float] = {}
    if not CONSERVATION.exists():
        return anchors
    c = _norm(cik)
    with open(CONSERVATION, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("rule_name") != rule_name or _norm(r.get("cik") or "") != c:
                continue
            av = (r.get("anchor_value") or "").strip()
            if av:
                try:
                    anchors[str(r.get("report_date"))] = float(av)
                except ValueError:
                    pass
    return anchors


def load_anchor_candidates(cik: str) -> dict[str, dict[str, float]]:
    """Per-quarter INDEPENDENT anchor values for validation: {report_date -> {name -> value}}.

    Pulls the one STRONG anchor the cache produces without a rebuild:
      - ``companyfacts_fv`` -- the XBRL-tagged investments_at_fair_value, a measurement independent
        of the schedule-of-investments extraction.
    Deliberately does NOT include this repo's ``schedule_total`` (sum of the extracted staging rows):
    that is a RE-AGGREGATION of the same extraction, so its disagreement with companyfacts_fv is the
    DEFECT being fixed, not evidence the anchor is bad -- using it would make the gate escalate on
    exactly the CIKs that have a real defect. The truly independent 2nd STRONG anchor (the filer's
    PRINTED schedule total) is not yet structured; wiring it is the path to a HIGH FV tier. The
    driver layers a cross-quarter outlier check on top (flag_anchor_outliers). See
    pipeline.anchor_validation.
    """
    c = _norm(cik)
    out: dict[str, dict[str, float]] = {}
    ff = config.FUND_FINANCIALS_FILE
    if Path(ff).exists():
        con = duckdb.connect()
        try:
            rows = con.execute(
                f"SELECT CAST(report_date AS VARCHAR), max(TRY_CAST(investments_at_fair_value AS DOUBLE)) "
                f"FROM read_csv_auto('{Path(ff).as_posix()}', sample_size=-1) "
                f"WHERE source='companyfacts' AND ltrim(CAST(cik AS VARCHAR),'0')='{c}' "
                f"AND investments_at_fair_value IS NOT NULL GROUP BY 1").fetchall()
        finally:
            con.close()
        for rd, v in rows:
            if v is not None:
                out.setdefault(str(rd), {})["companyfacts_fv"] = float(v)
    # Verified grand-total override (anchor-adjudicator): a STRONG anchor for that quarter.
    #  - if it AGREES with companyfacts -> keep both -> classify_anchors = HIGH (corroborated).
    #  - if it DISAGREES (the incomplete-subtotal case) -> companyfacts was the wrong/partial tag;
    #    DROP it and keep only the verified grand total as the (MEDIUM) truth, so the loop reconciles
    #    to the right number instead of going NONE on a two-strong-disagree.
    for rd, gt in load_anchor_overrides(cik).items():
        cf = out.get(rd, {}).get("companyfacts_fv")
        out.setdefault(rd, {})["printed_schedule_total"] = gt
        if cf is not None and abs(cf - gt) > 0.01 * max(abs(cf), abs(gt)):
            out[rd].pop("companyfacts_fv", None)
    return out


def load_anchor_overrides(cik: str) -> dict[str, float]:
    """{report_date -> verified grand_total} from data/overrides/agent_anchor/<cik>/*.json."""
    d = ANCHOR_OVERRIDES / _norm(cik)
    out: dict[str, float] = {}
    for p in (sorted(d.glob("*.json")) if d.exists() else []):
        leaf = load_anchor_leaf(p)
        if leaf and validate_anchor_leaf(leaf) == []:
            q = str(leaf.get("target_quarter") or "").strip()
            try:
                if q:
                    out[q] = float(leaf["grand_total"])
            except (TypeError, ValueError, KeyError):
                pass
    return out


def _candidates_with_outlier_filter(cik: str):
    """(candidates, outlier_flags): drop any companyfacts_fv that is a cross-quarter outlier (a
    likely mis-extracted anchor) so that quarter validates as NONE -> escalate, not reconcile."""
    candidates = load_anchor_candidates(cik)
    series = {q: c["companyfacts_fv"] for q, c in candidates.items() if "companyfacts_fv" in c}
    flags = flag_anchor_outliers(series)
    for q, fl in flags.items():
        if fl.flagged:
            candidates[q] = {}      # suspect anchor removed -> classify_anchors -> NONE
    return candidates, flags


def _load_holdings(cik: str) -> pd.DataFrame:
    p = (config.UNIFIED_HOLDINGS_PARQUET_FILE if config.UNIFIED_HOLDINGS_PARQUET_FILE.exists()
         else config.UNIFIED_HOLDINGS_FILE)
    df = pd.read_parquet(p) if str(p).endswith(".parquet") else pd.read_csv(p, low_memory=False)
    return df[df["cik"].astype(str).str.lstrip("0") == _norm(cik)].copy()


def _abs(rel: str) -> str:
    return (config.PROJECT_ROOT / rel).as_posix()


def _feedback_block(cik: str, state: dict) -> str:
    py = Path(WORKER_PYTHON).as_posix()
    rules = "\n".join(f"  - {r['rule_id']}: {r['predicate_sql']}" for r in state.get("rule_summary", [])) or "  (none)"
    reasons = "\n".join(f"  - {x}" for x in state.get("gate_reasons", [])) or "  (none)"
    noop = state.get("noop_rules") or []
    noop_block = ("\n*** NO-OP RULE(S): %s changed ZERO rows -- they do not fix anything. Your "
                  "mechanism is WRONG for these. Revise to the rule_type that matches the actual "
                  "defect, or ESCALATE. A no-op is not an acceptable answer. ***\n" % ", ".join(noop)
                  if noop else "")
    invalid = state.get("invalid_rules") or []
    invalid_block = ("\n*** INVALID RULE(S) were NOT applied -- fix and rewrite them:\n%s\n***\n" %
                     "\n".join("  - %s: %s" % (iv.get("rule_id"), "; ".join(iv.get("errors") or []))
                               for iv in invalid)
                     if invalid else "")
    return f"""## Iteration {state['iteration']} -- the previous attempt did NOT reconcile

Rules authored so far (do NOT re-drop what these already remove; ADD a new rule or revise a file):
{rules}
{noop_block}{invalid_block}After applying them, the residual in {state['target_quarter']} is {state['residual_pct']}% of the
anchor ({state['anchor']}). The deterministic gate said:
{reasons}

Investigate WHAT REMAINS -- query the CORRECTED holdings (post your rules) to see the leftover
residual or the held-out gate failure:
  {py} {_abs(DATA_QUERY)} --cik {cik} --holdings {state['corrected_holdings']} query --sql "<SELECT>"
Find the cause and author the next rule. Repeat until FV is within 0.5% of the anchor (a sub-0.5%
remainder is rounding -- stop) AND the held-out gate passes.

"""


def _prompt(cik: str, target_quarter: str, anchors: dict, rules_out: Path,
           iteration: int = 1, state: dict | None = None, anchor_tier: str = "",
           anchor_reason: str = "", bundle_path: str = "",
           existing_escalations: list | None = None) -> str:
    a = anchors.get(target_quarter)
    py = Path(WORKER_PYTHON).as_posix()
    evid = (f"2. Read the FILING (truth) -- this cik's cached filing. START with `overview` to see the\n"
            f"   schedule-of-investments tables, then `tables`/`grid`/`roam`/`totals` to read them. Use this\n"
            f"   to identify look-through / collateral / subtotal rows the EXTRACTED data cannot distinguish:\n"
            f"   {py} {_abs(EVIDENCE_CLI)} --bundle {bundle_path} overview|tables|grid|roam|totals\n"
            if bundle_path else
            "2. (No filing bundle for this cik-quarter -- work from the extracted data only.)\n")
    feedback = _feedback_block(cik, {**state, "iteration": iteration}) if (state and iteration > 1) else ""
    anchor_note = (f"\nThis anchor is the VALIDATED figure the gate reconciles to (tier {anchor_tier}). "
                   f"If an anchor-adjudicator override is in place it is the filer's GRAND total of "
                   f"investments (not the companyfacts subtotal) -- reconcile value_sum to THIS number "
                   f"and do NOT delete real rows to reach a smaller figure. ({anchor_reason})\n"
                   if anchor_tier else "")
    esc_list = existing_escalations or []
    esc_lines = (
        "\n".join(f"  - [{e.get('category')}] {e.get('summary')}" for e in esc_list)
        or "  (none)"
    )
    esc_block = (
        f"\n## Existing escalations for this target (do not re-author these; write a NEW escalation"
        f" file ONLY for a materially different finding):\n{esc_lines}\n"
    )
    return f"""# Investigate and resolve a fair-value conservation discrepancy (cik {cik})

{feedback}{esc_block}
You are a data-quality analyst. For BDC cik {cik}, the holdings the pipeline EXTRACTED do not
reconcile to the filing's own stated total in quarter {target_quarter}
(conservation anchor = {a}).{anchor_note} Find the ROOT CAUSE and author rule(s) that drive the residual to
within 0.5% of the anchor -- without deleting below the anchor and without regressing other quarters.
ROUNDING TOLERANCE: a residual within 0.5% of the anchor is filer ROUNDING (rounded line items vs a
rounded grand total -- they will not sum to exactly equal) and counts as RECONCILED. Do NOT author more
rules, and do NOT escalate, to close a sub-0.5% remainder -- stop and report success.

## Tools (read-only; this cik only). Use these ABSOLUTE paths; your CWD may differ.
1. Query the EXTRACTED data (the agent's DuckDB):
   {py} {_abs(DATA_QUERY)} --cik {cik} schema
   {py} {_abs(DATA_QUERY)} --cik {cik} query --sql "<ONE SELECT over: holdings, staging, fund_financials, conservation>"
   - `holdings` = unified rows the gate sums; `staging` = raw bdc_holdings (has `period`,
     `dimensions_raw`); `fund_financials` = balance-sheet anchor; `conservation` = the residual.
   - fair_value/cost load as text -> wrap in TRY_CAST(... AS DOUBLE).
{evid}
## Method (investigate, do NOT guess)
- Start with `schema` to see the residual (value_sum vs anchor). Form a hypothesis, TEST it with
  a query (group by period, by dimensions_raw / legalentityaxis, by has-detail, cross-check
  fund_financials). Discard wrong hypotheses. Confirm against the filing where possible.
- Identify exactly which rows are wrong and WHY (over-included, under-included, mis-valued).

## Output: author auditable rule(s)
Write one JSON file per rule under: {rules_out.as_posix()}/<rule_id>.json. Common fields on EVERY
rule: cik, rule_id, rule_type, action, scope ({{"quarters": ["all"] or [report_dates]}}),
evidence ([{{"source":"filing"|"query","quote":"..."}}], >=1), rationale, confidence (0..1), and
measured_impact ({{"<quarter>": {{"rows":N,"fv":X,"residual_before":..,"residual_after":..}}}}).
Pick the rule_type that MATCHES THE DEFECT -- never delete a real position to mask a value/anchor bug:

- OVER-count / leaked rows -> rule_type "row_exclusion", action "exclude":
    predicate_sql = a BOOLEAN SQL WHERE expression over holdings columns selecting rows to drop
    (no SELECT/DML/`;` -- just the expression).
- DUPLICATES (same position under two axes/representations) -> rule_type "dedup", action "dedup":
    match_fields = [columns that define the duplicate key], keep = "first"|"last",
    optional predicate_sql to scope which rows are dedup candidates.
- WRONG SCALE/unit (e.g. fair_value 1000x too large) -> rule_type "value_rescale", action "rescale":
    predicate_sql = rows to fix, field = the numeric column, factor = multiplier (e.g. 0.001).
    PREFER this over deleting a real position whose only problem is a mis-scaled value.
- WRONG DERIVED VALUE (a field should equal a formula of the row's OTHER numeric columns, e.g.
  fair_value extracted as garbage but principal_amount and a price are right) -> rule_type
  "value_expression", action "set": predicate_sql = rows to fix, field = the numeric column,
  expression = arithmetic over {{fair_value, cost, principal_amount, shares_held, interest_rate,
  pik_rate, basis_spread, pct_of_net_assets}} + numeric literals (+ - * / and parentheses) ONLY --
  e.g. "principal_amount * 0.985". No functions, no other names. PREFER this over deletion.
- UNDER-count (FV < anchor: the extractor DROPPED a real position) -> rule_type "row_add", action "add":
    positions = [{{report_date, fair_value, bdc_dimensions_raw (REQUIRED, so it is counted),
      issuer_name or bdc_investment_identifier, source_row_id (REQUIRED: the iXBRL/staging row you
      recovered it from -- query `staging` to find rows present there but missing from holdings),
      cost?, principal_amount?, ...}}]. Only recover rows that EXIST in the source.

B1's adjudication may be in your context as a STARTING HINT. It is NOT a contract -- if the data
shows a different mechanism than B1 guessed, follow the DATA and pick the matching rule_type. (B1
called these "comparative" leaks that were really duplicates + mis-scaled rows; do not repeat that.)

A single discrepancy may need MORE THAN ONE rule (an over-count AND an under-count, or a dedup AND a
rescale). If the ANCHOR itself looks wrong (implausible vs the schedule total and the CIK's other
quarters), do NOT delete holdings to match it -- say so and escalate. If you cannot drive the
residual to within 0.5% with evidence, author what you can and state what remains (but a sub-0.5%
remainder is rounding -- do not chase it).

## Self-verify BEFORE you finish (a no-op is a failure, not an answer)
After writing your rule file(s), CONFIRM they actually move the residual: re-query the corrected
holdings and check value_sum changed toward the anchor. The driver records a `noop` flag for any
rule that changed ZERO rows -- such a rule means your mechanism is WRONG. Do not finish on a no-op:
revise to the correct rule_type, or escalate (below).

## Escalate instead of forcing a wrong fix
If NO rule_type above (including value_expression) can express the real mechanism, do NOT author a
rule that balances the number some other way. Write ONE escalation file to
{rules_out.parent.as_posix()}/escalations/<name>.json:
  {{"cik":"{cik}","target_quarter":"{target_quarter}","kind":"proposed_mechanism",
    "category":"anchor|vocab|other",
    "summary":"<the mechanism in one line>","evidence":[{{"source":"query|filing","quote":"..."}}],
    "why_no_vocab_fits":"<why none of the rule types express it>",
    "suggested_applier":"<optional: the new op you'd need>","confidence":0.0-1.0}}
Set category="anchor" when the residual is undefined because the ANCHOR is wrong/incomplete (e.g. the
companyfacts total is a subtotal that excludes a separately presented schedule) -- that routes to the
anchor-adjudicator, which finds the grand total and reconciles you to it. Use "vocab" when a new rule
type is needed, "other" otherwise. An honest escalation beats a confident wrong fix.

## The anchor is validated before you reconcile to it
The gate cross-checks the anchor for INDEPENDENCE. The strong anchor is the XBRL-tagged fund total
(companyfacts_fv); the schedule_total is only a re-sum of the same extraction (weak corroborator).
If the strong anchor and the re-sum DISAGREE, the residual is UNDEFINED and the gate FAILS with
`anchor_validated` -- reconciling to either number would be guessing. When that happens, do NOT
delete-to-balance: investigate whether the anchor is mis-extracted (cross-check the CIK's other
quarters and the filing's printed total) and ESCALATE. A correction is only meaningful when the
anchor it targets is itself trustworthy.

## Hard rules
Cache-only. No network/SEC/git. No tests/rebuilds. No production writes (only the rules dir
above). ASCII only. The driver re-applies your rules deterministically and runs the held-out
conservation gate -- a rule that only balances {target_quarter} or deletes below the anchor is
rejected, so ground every rule in the data + filing.
"""


def _measure(cik: str, target_quarter: str) -> dict:
    """Apply the rules authored so far, write corrected holdings, and measure the target-quarter
    residual + run the gate. The loop's per-iteration assessment."""
    out = BASE / _norm(cik)
    out.mkdir(parents=True, exist_ok=True)
    rules = load_rules(out / "rules")
    base = _load_holdings(cik)
    corrected, audits = (apply_rules(base, rules) if rules else (base.copy(), []))
    corrected_path = out / f"corrected_holdings.{_norm(cik)}.csv"
    corrected.to_csv(corrected_path, index=False)
    anchors = load_anchors(cik)
    candidates, flags = _candidates_with_outlier_filter(cik)
    tq = str(target_quarter)
    av = classify_anchors(candidates.get(tq, {}))
    out_flag = flags.get(tq)
    anchor_reason = (out_flag.reason if (out_flag and out_flag.flagged) else av.reason)
    anchor = av.consensus if av.consensus is not None else anchors.get(target_quarter)
    vs = value_sum_by_quarter(corrected).get(tq, 0.0)
    residual_pct = round((vs - anchor) / anchor * 100.0, 3) if anchor else None
    g = (gate_rules(base, corrected, cik=cik, target_quarter=target_quarter,
                    anchor_candidates=candidates) if rules else None)
    noop_rules = [a.get("rule_id") for a in audits if a.get("noop")]
    invalid_rules = [{"rule_id": a.get("rule_id"), "errors": a.get("errors")}
                     for a in audits if a.get("status") == "invalid"]
    raw_escalations = load_escalations(out / "escalations")
    escalations = dedupe_escalations(raw_escalations)
    noop = None if rules else _noop_gate_verdict(residual_pct, av.tier)
    return {"cik": _norm(cik), "target_quarter": target_quarter, "n_rules": len(rules),
            "value_sum": round(vs, 2), "anchor": anchor, "residual_pct": residual_pct,
            "anchor_tier": av.tier, "anchor_reason": anchor_reason,
            "noop_rules": noop_rules, "invalid_rules": invalid_rules,
            "n_escalations": len(escalations), "n_escalation_files": len(raw_escalations),
            "gate_verdict": (g.verdict if g else (noop["verdict"] if noop else "NO_RULES")),
            "gate_reasons": (list(g.reasons) if g else (noop["reasons"] if noop else [])),
            "rule_summary": [{"rule_id": r.get("rule_id"), "predicate_sql": r.get("predicate_sql"),
                              "measured_impact": r.get("measured_impact")} for r in rules],
            "corrected_holdings": str(corrected_path), "audits": audits}


def status(cik: str, target_quarter: str, iteration: int) -> dict:
    """Loop assessment for one iteration: residual + gate + the stop/continue decision."""
    m = _measure(cik, target_quarter)
    m["iteration"] = iteration
    m["decision"] = loop_decision(m["residual_pct"], iteration, gate_verdict=m["gate_verdict"],
                                  n_escalations=m["n_escalations"])
    return m


def _resolved_anchor(cik: str, target_quarter: str):
    """(anchor, tier, reason) the GATE will use -- override/outlier aware -- so the prompt shows the
    SAME number the gate reconciles to (e.g. an anchor-adjudicator grand-total override that
    supersedes the companyfacts subtotal), not the raw conservation anchor."""
    candidates, flags = _candidates_with_outlier_filter(cik)
    tq = str(target_quarter)
    av = classify_anchors(candidates.get(tq, {}))
    fl = flags.get(tq)
    reason = (fl.reason if (fl and fl.flagged) else av.reason)
    anchor = av.consensus if av.consensus is not None else load_anchors(cik).get(target_quarter)
    return anchor, av.tier, reason


def prep(cik: str, target_quarter: str, iteration: int = 1) -> dict:
    anchors = load_anchors(cik)
    out = BASE / _norm(cik)
    rules_out = out / "rules"
    out.mkdir(parents=True, exist_ok=True)
    rules_out.mkdir(parents=True, exist_ok=True)
    (out / "escalations").mkdir(parents=True, exist_ok=True)   # the worker writes escalations here
    # Pre-warm the per-cik query cache here (outside the worker sandbox, where writes work) so
    # the agent's queries read tiny pre-built slices instead of full-scanning global parquets.
    try:
        from pipeline.agent_data_query import describe as _dq_describe
        _dq_describe(cik=cik)
    except Exception:
        pass
    # Show the worker the VALIDATED anchor (the same one the gate uses), not the raw companyfacts
    # subtotal -- so when an anchor-adjudicator override is in place the worker reconciles to the
    # filer's grand total directly instead of re-discovering it.
    resolved, tier, reason = _resolved_anchor(cik, target_quarter)
    anchors_display = dict(anchors)
    if resolved is not None:
        anchors_display[str(target_quarter)] = resolved
    state = _measure(cik, target_quarter) if iteration > 1 else None
    bundle = _find_bundle(cik, target_quarter)          # give the worker the FILING, not just data
    bundle_path = bundle.as_posix() if bundle else ""
    existing_escalations = dedupe_escalations(load_escalations(out / "escalations"))
    prompt_path = out / "prompt.md"
    prompt_path.write_text(_prompt(cik, target_quarter, anchors_display, rules_out, iteration, state,
                                   anchor_tier=tier, anchor_reason=reason, bundle_path=bundle_path,
                                   existing_escalations=existing_escalations),
                           encoding="utf-8")
    manifest = {"cik": _norm(cik), "target_quarter": target_quarter, "iteration": iteration,
                "anchor": resolved, "anchor_tier": tier, "anchor_reason": reason, "bundle": bundle_path,
                "n_quarters_with_anchor": len(anchors),
                "current_residual_pct": (state["residual_pct"] if state else None),
                "rules_dir": str(rules_out), "prompt": str(prompt_path),
                "worker_python": WORKER_PYTHON, "data_query_cli": DATA_QUERY,
                "evidence_cli": EVIDENCE_CLI}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def apply(cik: str) -> dict:
    out = BASE / _norm(cik)
    rules = load_rules(out / "rules")
    if not rules:
        return {"cik": _norm(cik), "status": "no_rules", "rules_dir": str(out / "rules")}
    invalid = [{"rule_id": r.get("rule_id"), "errors": validate_rule(r)} for r in rules if validate_rule(r)]
    base = _load_holdings(cik)
    corrected, audits = apply_rules(base, rules)
    corrected_path = out / f"corrected_holdings.{_norm(cik)}.csv"
    corrected.to_csv(corrected_path, index=False)
    raw_escalations = load_escalations(out / "escalations")
    deduped_escalations = dedupe_escalations(raw_escalations)
    bad_esc = [{"errors": validate_escalation(e)} for e in raw_escalations if validate_escalation(e)]
    res = {"cik": _norm(cik), "n_rules": len(rules), "rows_in": int(len(base)),
           "rows_out": int(len(corrected)), "audits": audits, "invalid_rules": invalid,
           "noop_rules": [a.get("rule_id") for a in audits if a.get("noop")],
           "n_escalations": len(deduped_escalations), "n_escalation_files": len(raw_escalations),
           "invalid_escalations": bad_esc,
           "corrected_holdings": str(corrected_path)}
    (out / "apply_audit.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def gate(cik: str, target_quarter: str) -> dict:
    out = BASE / _norm(cik)
    corrected_path = out / f"corrected_holdings.{_norm(cik)}.csv"
    if not corrected_path.exists():
        return {"cik": _norm(cik), "status": "no_corrected_holdings (run apply first)"}
    base = _load_holdings(cik)
    corrected = pd.read_csv(corrected_path, low_memory=False)
    candidates, flags = _candidates_with_outlier_filter(cik)
    tq = str(target_quarter)
    av = classify_anchors(candidates.get(tq, {}))
    out_flag = flags.get(tq)
    anchor_reason = (out_flag.reason if (out_flag and out_flag.flagged) else av.reason)
    if not load_rules(out / "rules"):
        vs = value_sum_by_quarter(base).get(tq, 0.0)
        residual_pct = (round((vs - av.consensus) / av.consensus * 100.0, 3)
                        if av.consensus else None)
        noop = _noop_gate_verdict(residual_pct, av.tier)
        if noop:
            return {"cik": _norm(cik), "target_quarter": target_quarter,
                    "verdict": noop["verdict"], "anchor_tier": av.tier,
                    "anchor_reason": anchor_reason,
                    "checks": {"noop_reconciled": True}, "reasons": noop["reasons"]}
    g = gate_rules(base, corrected, cik=cik, target_quarter=target_quarter,
                   anchor_candidates=candidates)
    return {"cik": _norm(cik), "target_quarter": target_quarter, "verdict": g.verdict,
            "anchor_tier": av.tier, "anchor_reason": anchor_reason,
            "checks": g.checks, "reasons": g.reasons}


def _discover_targets(source_worklist, verdicts_dir) -> dict:
    """Pure: read the B1 worklist + verdicts, return {(cik, quarter): {review_ids}} for real_errors."""
    src, verdicts_dir = Path(source_worklist), Path(verdicts_dir)
    targets: dict[tuple, set] = {}
    if not src.exists():
        return targets
    with open(src, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rid = (row.get("review_id") or "").strip()
            cik = _norm(row.get("cik") or "")
            q = (row.get("report_date") or row.get("target_quarter") or "").strip()
            if not (rid and cik and q):
                continue
            try:
                verdict = json.loads((verdicts_dir / f"{rid}.json").read_text(encoding="utf-8")).get("verdict")
            except (OSError, json.JSONDecodeError):
                verdict = None
            if verdict == "real_error":
                targets.setdefault((cik, q), set()).add(rid)
    return targets


def discover(batch_id: str, *, source_worklist, verdicts_dir=DEFAULT_VERDICTS) -> dict:
    """B1 -> agentic. Read the B1 batch worklist (review_id -> cik/report_date) + its verdicts,
    and emit an INVESTIGATION worklist of (cik, target_quarter) for every real_error. The agent
    then finds the MECHANISM by investigating the extracted data -- B1's mechanism guess is NOT
    used (the deterministic template-author no-op'd on those guesses). This is the B1->investigation
    wiring that replaces run_remediation's verdict->fix_class->template-worker path."""
    targets = _discover_targets(source_worklist, verdicts_dir)
    out_dir = BASE / "batch" / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    wl = out_dir / "investigation_worklist.csv"
    with open(wl, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cik", "target_quarter", "n_verdicts", "review_ids"])
        for (cik, q) in sorted(targets):
            w.writerow([cik, q, len(targets[(cik, q)]), ";".join(sorted(targets[(cik, q)]))])
    return {"batch_id": batch_id, "n_targets": len(targets), "worklist": str(wl)}


def promote(cik: str, target_quarter: str, *, overrides_dir=DEFAULT_OVERRIDES) -> dict:
    """Copy a CIK's gate-PASS rules to production overrides. REFUSES unless the held-out gate
    PASSes -- the un-gameable check is the promotion bar (mirrors run_remediation.promote_passes)."""
    g = gate(cik, target_quarter)
    if g.get("verdict") == "PASS_NOOP":
        # Clean zero-rule investigation: nothing to copy, and not a refusal.
        return {"cik": _norm(cik), "status": "no_rules_to_promote", "gate": "PASS_NOOP",
                "reasons": g.get("reasons")}
    if g.get("verdict") != "PASS":
        return {"cik": _norm(cik), "status": "refused", "gate": g.get("verdict"),
                "reasons": g.get("reasons")}
    src = BASE / _norm(cik) / "rules"
    # Audit guard (q1p3 Fiesta dedup): the conservation gate can PASS trivially for an
    # FV-neutral rule on an already-reconciled quarter, so gate-PASS alone does not prove
    # every rule in the set is sound. An invalid or nothing-matches rule reaching
    # production is a guaranteed inert promotion -- refuse the SET and force reauthoring
    # rather than silently copying a partial one (the gate evaluated the set as a whole).
    rules = load_rules(src)
    invalid = [{"rule_id": r.get("rule_id"), "errors": validate_rule(r)}
               for r in rules if validate_rule(r)]
    if invalid:
        return {"cik": _norm(cik), "status": "refused_invalid_rules", "gate": "PASS",
                "invalid_rules": invalid}
    _, audits = apply_rules(_load_holdings(cik), rules)
    noops = [a.get("rule_id") for a in audits if a.get("noop")]
    if noops:
        return {"cik": _norm(cik), "status": "refused_noop_rules", "gate": "PASS",
                "noop_rules": noops}
    dst = Path(overrides_dir) / _norm(cik)
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for r in (sorted(src.glob("*.json")) if src.exists() else []):
        shutil.copy2(r, dst / r.name)
        copied.append(r.name)
    return {"cik": _norm(cik), "status": "promoted", "n_rules": len(copied),
            "rules": copied, "overrides_dir": str(dst)}


_ROUTE_MAP = {"anchor": "anchor_lane", "vocab": "extraction_review"}
_SKIP_DIRS = {"batch", "_qcache", "routing"}


def route_escalations(base_dir=BASE, out_dir=None) -> dict:
    """Scan <base_dir>/<cik>/escalations/*.json, dedupe per CIK, route by category.

    Routes: anchor -> anchor_lane, vocab -> extraction_review, else -> human_review.
    Writes <out_dir>/escalation_routing.csv.
    Returns {n_files, n_distinct, by_route, csv}.
    """
    base_dir = Path(base_dir)
    if out_dir is None:
        out_dir = base_dir / "routing"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    n_files = 0
    n_distinct = 0
    by_route: dict[str, int] = {}
    rows = []

    for child in sorted(base_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name in _SKIP_DIRS:
            continue
        cik = child.name
        esc_dir = child / "escalations"
        if not esc_dir.exists():
            continue
        raw = load_escalations(esc_dir)
        if not raw:
            continue
        n_files += len(raw)

        # Count raw files per (target_quarter, category) key for duplicate reporting
        key_counts: dict[tuple, int] = {}
        for e in raw:
            k = (str(e.get("target_quarter") or ""), str(e.get("category") or ""))
            key_counts[k] = key_counts.get(k, 0) + 1

        distinct = dedupe_escalations(raw)
        n_distinct += len(distinct)

        for e in distinct:
            cat = str(e.get("category") or "")
            route = _ROUTE_MAP.get(cat, "human_review")
            by_route[route] = by_route.get(route, 0) + 1
            k = (str(e.get("target_quarter") or ""), cat)
            n_dup = key_counts.get(k, 1)
            rows.append({
                "cik": cik,
                "target_quarter": str(e.get("target_quarter") or ""),
                "category": cat,
                "route": route,
                "summary": str(e.get("summary") or ""),
                "confidence": str(e.get("confidence") or ""),
                "escalation_path": str(esc_dir),
                "n_duplicate_files": str(n_dup),
            })

    csv_path = out_dir / "escalation_routing.csv"
    fieldnames = ["cik", "target_quarter", "category", "route", "summary",
                  "confidence", "escalation_path", "n_duplicate_files"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    return {"n_files": n_files, "n_distinct": n_distinct, "by_route": by_route,
            "csv": str(csv_path)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Agentic investigation driver (bypasses the B2 battery).")
    sub = ap.add_subparsers(dest="mode", required=True)
    for m in ("prep", "apply", "gate", "status", "discover", "promote"):
        p = sub.add_parser(m)
        if m == "discover":
            p.add_argument("batch_id")
            p.add_argument("--source-worklist", type=Path, required=True,
                           help="B1 batch worklist.csv (review_id -> cik/report_date)")
            p.add_argument("--verdicts-dir", type=Path, default=DEFAULT_VERDICTS)
        else:
            p.add_argument("--cik", required=True)
        if m in ("prep", "gate", "status", "promote"):
            p.add_argument("--target-quarter", required=True)
        if m in ("prep", "status"):
            p.add_argument("--iteration", type=int, default=1)
    # escalations subcommand: no --cik; scans all CIK dirs
    p_esc = sub.add_parser("escalations")
    p_esc.add_argument("--out-dir", type=Path, default=None,
                       help="Output directory for escalation_routing.csv (default: <base>/routing)")
    args = ap.parse_args(argv)
    if args.mode == "prep":
        print(json.dumps(prep(args.cik, args.target_quarter, args.iteration), indent=2, default=str))
    elif args.mode == "apply":
        print(json.dumps(apply(args.cik), indent=2, default=str))
    elif args.mode == "gate":
        res = gate(args.cik, args.target_quarter)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("verdict") in ("PASS", "PASS_NOOP") else 1
    elif args.mode == "status":
        res = status(args.cik, args.target_quarter, args.iteration)
        print(json.dumps(res, indent=2, default=str))
        return 0 if (res["decision"]["stop"] and res["decision"]["success"]) else 1
    elif args.mode == "discover":
        print(json.dumps(discover(args.batch_id, source_worklist=args.source_worklist,
                                  verdicts_dir=args.verdicts_dir), indent=2, default=str))
    elif args.mode == "promote":
        res = promote(args.cik, args.target_quarter)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("status") == "promoted" else 1
    elif args.mode == "escalations":
        res = route_escalations(base_dir=BASE, out_dir=args.out_dir)
        print(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
