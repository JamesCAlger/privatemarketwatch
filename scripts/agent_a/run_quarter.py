"""Agent A / Layer 1 -- deterministic quarterly driver (A4).

The non-LLM orchestration spine the external Codex harness wraps. Two modes:

  discover <quarter>  -- find the flattened filers that need induction this quarter
                         (uninduced, or drift), build one bounded bundle per filer, and
                         write a worklist the Codex batch assigns one-bundle-per-agent.
  gate <quarter>      -- AFTER the sandboxed agents have written/updated their configs,
                         run the deterministic A3 held-out gate over each worklist filer
                         and record PASS/FAIL. PASS = promotion-eligible; FAIL -> human.

No network, no rebuild, no LLM. Read-only on production; writes only under
data/output/agent_a/quarter/<quarter>/. The agent step (Layer 2, the Codex sandbox) and
the schedule (Layer 3) live OUTSIDE the repo -- see
docs/adjudication_architecture/agent_a_batch_instructions.md.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import sys

from pipeline import config
from pipeline.identifier_rate import GRAMMAR_DIR, apply_grammar, load_grammar
from pipeline.identifier_held_out import held_out_report
from pipeline.identifier_signature import keyword_signature, load_anchors
from scripts.agent_a import cik_lock
from scripts.agent_a.sample_variant import build_bundle

SIGREPORT = config.OUTPUT_DIR / "identifier_signature_report.csv"
NONE_DRIFT_PCT = 10.0   # flattened filer with a grammar but none-share >= this -> drift candidate


def _quarter_dir(quarter: str):
    d = config.OUTPUT_DIR / "agent_a" / "quarter" / quarter
    d.mkdir(parents=True, exist_ok=True)
    return d


def _has_grammar(cik: str) -> bool:
    return (GRAMMAR_DIR / f"{cik}.json").exists()


def _proposal_paths(cik: str):
    base = config.OUTPUT_DIR / "agent_a" / "proposals"
    return base / f"{cik}.anchors.json", base / f"{cik}.grammar.json"


def _has_proposal(cik: str) -> bool:
    apath, gpath = _proposal_paths(cik)
    return apath.exists() and gpath.exists()


def _load_grammar_path(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_anchors_path(path):
    spec = json.loads(path.read_text(encoding="utf-8"))
    return [(a["label"], re.compile(a["regex"], re.I)) for a in spec["anchors"]]


def _is_not_applicable_rate_grammar(grammar: dict) -> bool:
    return (grammar.get("status") or grammar.get("verdict")) == "NOT_APPLICABLE_RATE_GRAMMAR"


def _worklist_rows(quarter: str, manifest_path: str | None = None):
    qdir = _quarter_dir(quarter)
    wl = qdir / "worklist.csv"
    if not wl.exists():
        raise SystemExit(f"no worklist at {wl} -- run discover first")
    with open(wl, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if manifest_path:
        manifest = json.loads(open(manifest_path, encoding="utf-8").read())
        selected = {r["cik"] for r in manifest.get("rows", [])}
        rows = [r for r in rows if r.get("cik") in selected]
        missing = selected - {r.get("cik") for r in rows}
        if missing:
            raise SystemExit(f"manifest CIK(s) absent from worklist: {', '.join(sorted(missing))}")
    return rows


def _flattened_filers():
    """Read the (deterministic) signature report; yield flattened filers + key signals."""
    if not SIGREPORT.exists():
        raise SystemExit(f"missing {SIGREPORT} -- run `python -m pipeline.identifier_signature` first")
    out = []
    with open(SIGREPORT, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["regime"] != "flattened":
                continue
            out.append({
                "cik": r["cik"], "entity_name": r["entity_name"],
                "n_rows": int(r["n_rows"]), "none_pct": float(r["none_pct"]),
                "rate_embed_pct": float(r.get("rate_embed_pct", 0) or 0),
                "top1_sig": r["top1_sig"],
            })
    return out


# #3 pre-dispatch rate-target floor: a filer whose identifier embeds essentially no rate
# (no '%' in the string) is NOT a rate-grammar target -- its rates live in structured XBRL /
# the SOI source table, not the identifier (e.g. Main Street "American Nuts, LLC | Secured
# Debt 1", rate_embed 0.2%). detect_regime can mislabel these flattened on keyword presence.
# Real rate targets measured >= 27%; this cleanly excludes the no-rate ones.
MIN_RATE_EMBED_PCT = 10.0


def discover(quarter: str, min_rows: int = 200):
    qdir = _quarter_dir(quarter)
    worklist, bundles_dir = [], qdir / "bundles"
    bundles_dir.mkdir(exist_ok=True)

    seen_ciks: set = set()
    skipped_no_rate = []
    for fr in _flattened_filers():
        cik = fr["cik"]
        if fr["n_rows"] < min_rows:
            continue
        # #3: skip no-rate-target filers (identifier carries no parseable rate)
        if fr["rate_embed_pct"] < MIN_RATE_EMBED_PCT:
            skipped_no_rate.append((cik, fr["entity_name"], fr["rate_embed_pct"]))
            continue
        # per-CIK serialization: never emit two rows for one CIK, and skip a CIK already
        # in-flight from another cycle (its config is being written -- would race).
        if cik in seen_ciks:
            continue
        if cik_lock.is_locked(cik):
            continue
        seen_ciks.add(cik)
        has = _has_grammar(cik)
        if not has:
            reason = "uninduced"
        elif fr["none_pct"] >= NONE_DRIFT_PCT:
            reason = "drift_candidate"
        else:
            continue  # covered -- skip the agent

        # Multi-quarter era-stratified bundle: the agent must see the filer's OLD + NEW
        # identifier formats, else its grammar fits only the current quarter and the held-out
        # gate FAILs it on the eras it never saw (the 2023-03-31 cluster). Gate the cadence on
        # the target quarter being present, not on a single-quarter row count.
        bundle = build_bundle(cik, n_per_sig=12, report_date=quarter, multi_quarter=True,
                              shape_stratified=True)
        if quarter not in bundle.get("report_dates", []):
            continue  # filer didn't file this quarter
        bpath = bundles_dir / f"{cik}_{quarter}.json"
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2)
        dom = bundle["top_variants"][0]["signature"] if bundle["top_variants"] else ""
        worklist.append({
            "cik": cik, "entity_name": fr["entity_name"], "quarter": quarter,
            "reason": reason, "regime": bundle["regime"], "n_rows": bundle["n_rows"],
            "none_pct": bundle["none_pct"], "dominant_signature": dom,
            "has_existing_grammar": has, "bundle_path": str(bpath),
        })

    wl = qdir / "worklist.csv"
    if worklist:
        with open(wl, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(worklist[0].keys()))
            w.writeheader(); w.writerows(worklist)
    else:
        wl.write_text("cik,entity_name,quarter,reason\n", encoding="utf-8")
    # #3: record the no-rate-target skips so coverage isn't silently truncated
    if skipped_no_rate:
        nr = qdir / "skipped_no_rate_target.csv"
        with open(nr, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["cik", "entity_name", "rate_embed_pct"])
            w.writerows(skipped_no_rate)
    print(f"discover {quarter}: {len(worklist)} filers need induction "
          f"({sum(1 for r in worklist if r['reason']=='uninduced')} uninduced, "
          f"{sum(1 for r in worklist if r['reason']=='drift_candidate')} drift) -> {wl}")
    print(f"  skipped {len(skipped_no_rate)} no-rate-target filer(s) "
          f"(rate_embed < {MIN_RATE_EMBED_PCT}% -- not a rate grammar; e.g. Main Street)")
    print(f"  bundles in {bundles_dir}  (assign one-per-agent; see agent_a_batch_instructions.md)")
    return worklist


def resolve_applies_to(
    cik: str,
    parquet: str | None = None,
    write: bool = True,
    grammar_path=None,
    anchor_path=None,
):
    """Deterministic harness step (#1): the agent's applies_to.signature can disagree with
    the anchors it committed (it labels from the bundle's GLOBAL-anchor signatures, then
    writes anchors that shift the real signature). The harness, not the agent, owns this:
    recompute the dominant signature as the most frequent one the grammar PARSES TO
    COMPLETENESS under the COMMITTED anchors, and write it into applies_to.signature.
    Returns (old_sig, new_sig, n_parsed).
    """
    import json
    import duckdb
    from collections import Counter

    parquet = parquet or str(config.OUTPUT_DIR / "bdc_holdings.parquet")
    gpath = grammar_path or (GRAMMAR_DIR / f"{cik}.json")
    grammar = _load_grammar_path(gpath) if grammar_path else load_grammar(cik)
    anchors = _load_anchors_path(anchor_path) if anchor_path else load_anchors(cik)
    required = grammar.get("required_fields", [])
    old_sig = grammar.get("applies_to", {}).get("signature", "")

    con = duckdb.connect()
    ids = [r[0] for r in con.execute(
        f"SELECT CAST(investment_identifier AS VARCHAR) FROM '{parquet}' "
        f"WHERE CAST(cik AS VARCHAR)='{cik}' AND investment_identifier IS NOT NULL "
        f"AND CAST(period AS VARCHAR)=CAST(report_date AS VARCHAR)"
    ).fetchall()]
    con.close()

    complete = Counter()
    for ident in ids:
        if all(apply_grammar(ident, grammar).get(k) is not None for k in required):
            complete[keyword_signature(ident, anchors)] += 1
    new_sig = complete.most_common(1)[0][0] if complete else old_sig
    n = complete.get(new_sig, 0)

    if write and new_sig and new_sig != old_sig:
        grammar.setdefault("applies_to", {})["signature"] = new_sig
        grammar["applies_to"]["_resolved_by"] = "harness resolve_applies_to (committed anchors)"
        with open(gpath, "w", encoding="utf-8") as f:
            json.dump(grammar, f, indent=2)
    return old_sig, new_sig, n


def finalize(quarter: str, staged: bool = False, manifest_path: str | None = None):
    """Run resolve_applies_to over every worklist filer that produced a grammar."""
    rows = _worklist_rows(quarter, manifest_path)
    fixed = 0
    for r in rows:
        cik = r["cik"]
        if staged:
            apath, gpath = _proposal_paths(cik)
            if not (apath.exists() and gpath.exists()):
                continue
            if _is_not_applicable_rate_grammar(_load_grammar_path(gpath)):
                continue
            old, new, n = resolve_applies_to(cik, grammar_path=gpath, anchor_path=apath)
        elif not _has_grammar(cik):
            continue
        else:
            old, new, n = resolve_applies_to(cik)
        if old != new:
            fixed += 1
            print(f"  {cik}: applies_to '{old}' -> '{new}' ({n} rows parse-complete)")
    scope = "staged proposals" if staged else "production grammar(s)"
    print(f"finalize {quarter}: resolved applies_to on {fixed} {scope}")


def _failing_quarters(v, none_spike_delta=10.0):
    """Quarters that caused the FAIL -- the residual A must re-induce on (the feedback the
    grammar gaps go BACK to A, not a human edit). Includes BOTH per-quarter completeness/
    invariant dips (sig_rows>0) AND none-share spikes (which can have 0 sig_rows because the
    quarter's format isn't recognized at all -- that quarter is the prime re-induce target)."""
    from statistics import median
    out = []
    med = median([q["none_pct"] for q in v.quarters]) if v.quarters else 0.0
    for q in v.quarters:
        comp, inv = q.get("completeness_pct"), q.get("invariant_pct")
        bad_parse = q["sig_rows"] > 0 and (
            (comp is not None and comp < 90.0) or (inv is not None and inv < 85.0))
        none_spike = q["none_pct"] > med + none_spike_delta
        if bad_parse or none_spike:
            out.append(q["quarter"])
    return out


def claim(cik: str, owner: str = "dispatch"):
    """Per-CIK serialization: the orchestrator MUST call this before launching an agent for a
    CIK. Returns 0 if the lock was acquired (safe to launch), 1 if the CIK is already in flight
    (do NOT launch a second concurrent agent -- it would race the per-CIK config files)."""
    import time
    ok = cik_lock.acquire(cik, owner=owner, now=time.time())
    print(f"claim {cik}: {'ACQUIRED -- safe to launch one agent' if ok else 'IN-FLIGHT -- do NOT launch (serial per CIK)'}")
    return 0 if ok else 1


def release(cik: str):
    cik_lock.release(cik)
    print(f"release {cik}: lock cleared")
    return 0


def _gate_row(cik: str, row: dict, parquet: str, staged: bool):
    if staged:
        apath, gpath = _proposal_paths(cik)
        if not (apath.exists() and gpath.exists()):
            return {"cik": cik, "entity_name": row.get("entity_name", ""),
                    "dominant_signature": "", "verdict": "NO_PROPOSAL",
                    "confidence": "", "n_quarters": 0, "remediate_quarters": "",
                    "reason": "worker did not produce both staged proposal files"}
        grammar = _load_grammar_path(gpath)
        if _is_not_applicable_rate_grammar(grammar):
            return {"cik": cik, "entity_name": row.get("entity_name", ""),
                    "dominant_signature": grammar.get("applies_to", {}).get("signature", ""),
                    "verdict": "NOT_APPLICABLE_RATE_GRAMMAR",
                    "confidence": grammar.get("confidence", ""),
                    "n_quarters": 0, "remediate_quarters": "",
                    "reason": grammar.get("not_applicable_reason", "identifier carries no rate grammar")}
        _, sig, _ = resolve_applies_to(
            cik, parquet, grammar_path=gpath, anchor_path=apath
        )
        anchors = _load_anchors_path(apath)
        v = held_out_report(cik, sig, parquet, grammar=grammar, anchors=anchors)
    else:
        if not _has_grammar(cik):
            if row.get("dominant_signature"):
                return {"cik": cik, "entity_name": row.get("entity_name", ""),
                        "dominant_signature": "", "verdict": "NO_CONFIG",
                        "confidence": "", "n_quarters": 0, "remediate_quarters": "",
                        "reason": "agent did not produce a grammar"}
            return None
        # #1 deterministic: trust the COMMITTED anchors, not the agent's applies_to label
        _, sig, _ = resolve_applies_to(cik, parquet)
        v = held_out_report(cik, sig, parquet)

    # #2 reframed: name the quarters A must re-induce on (feedback to the agent)
    remediate = _failing_quarters(v) if v.verdict == "FAIL" else []
    return {"cik": cik, "entity_name": row["entity_name"],
            "dominant_signature": sig, "verdict": v.verdict,
            "confidence": v.confidence,
            "n_quarters": len([q for q in v.quarters
                               if q["sig_rows"] > 0 and q.get("era_match", True)]),
            "remediate_quarters": "|".join(remediate),
            "reason": "; ".join(v.reasons)[:300]}


def gate(quarter: str, staged: bool = False, manifest_path: str | None = None):
    qdir = _quarter_dir(quarter)
    parquet = str(config.OUTPUT_DIR / "bdc_holdings.parquet")
    results = []
    rows = _worklist_rows(quarter, manifest_path)
    for r in rows:
        cik = r["cik"]
        result = _gate_row(cik, r, parquet, staged)
        if result:
            results.append(result)

    # the CIK's cycle is complete once gated -> release its serialization lock so a later
    # (sequential) remediation pass can claim it.
    for r in results:
        cik_lock.release(r["cik"])

    out = qdir / ("staged_gate_results.csv" if staged else "gate_results.csv")
    if results:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader(); w.writerows(results)

    # A3 FAIL -> re-process: build re-induction bundles for the failing quarters and emit a
    # remediation worklist the operator re-dispatches to A (closes the gate->re-induce loop).
    n_remediate = _emit_remediation(quarter, results, staged=staged)

    npass = sum(1 for r in results if r["verdict"] == "PASS")
    nfail = sum(1 for r in results if r["verdict"] == "FAIL")
    scope = "staged gate" if staged else "gate"
    print(f"{scope} {quarter}: {npass} PASS (promotion-eligible) / {nfail} FAIL / "
          f"{len(results)-npass-nfail} other -> {out}")
    for r in results:
        if r["verdict"] != "PASS":
            rq = r.get("remediate_quarters", "")
            tail = f"  [A re-induce: {rq}]" if rq else ""
            print(f"  {r['verdict']:9s} {r['cik']}  {r.get('reason','')[:80]}{tail}")
    if n_remediate:
        print(f"  -> {n_remediate} CIK(s) queued for re-induction in "
              f"{qdir / 'remediation_worklist.csv'} (triage first: encoding/era FAILs need a "
              f"harness fix, not re-induction)")
    return results


def _emit_remediation(quarter: str, results: list, staged: bool = False) -> int:
    """For each FAIL, build a quarter-scoped re-induction bundle on the failing quarter (or the
    batch quarter for whole-CIK failures) and write remediation_worklist.csv. Returns count."""
    qdir = _quarter_dir(quarter)
    bundles_dir = qdir / "bundles"
    bundles_dir.mkdir(exist_ok=True)
    rem = []
    for r in results:
        if r.get("verdict") not in ("FAIL", "NO_CONFIG", "NO_PROPOSAL"):
            continue
        cik = r["cik"]
        rq = (r.get("remediate_quarters") or "").split("|")
        target_q = next((q for q in rq if q), quarter)   # worst failing quarter (for labeling)
        try:
            anchors = None
            if staged:
                apath, _ = _proposal_paths(cik)
                anchors = _load_anchors_path(apath) if apath.exists() else None
            # re-induce on the full era-stratified population (incl. the failing quarter), not
            # just target_q -- a single-quarter re-bundle would reproduce the same drift FAIL.
            # shape_stratified: within each era, round-robin across distinct flattened_shapes so a
            # minority LAYOUT (e.g. the hierarchy-breadcrumb-prefixed position) is shown to the
            # worker -- head selection drops it and the gate FAILs on its quarter (2026-06-23
            # investigation: ~84% of completeness FAILs are real positions in an unsampled layout).
            bundle = build_bundle(cik, n_per_sig=12, report_date=target_q, multi_quarter=True,
                                  shape_stratified=True, anchors=anchors)
        except Exception:  # noqa: BLE001 -- a filer with no rows
            bundle = None
        bpath = ""
        if bundle and bundle.get("n_rows"):
            bpath = str(bundles_dir / f"{cik}_{target_q}.json")
            with open(bpath, "w", encoding="utf-8") as f:
                json.dump(bundle, f, indent=2)
        rem.append({"cik": cik, "entity_name": r.get("entity_name", ""),
                    "verdict": r["verdict"], "remediate_quarter": target_q,
                    "reason": r.get("reason", "")[:200], "bundle_path": bpath})
    if rem:
        with open(qdir / "remediation_worklist.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rem[0].keys()))
            w.writeheader(); w.writerows(rem)
    return len(rem)


def promote(quarter: str):
    qdir = _quarter_dir(quarter)
    gate_path = qdir / "staged_gate_results.csv"
    if not gate_path.exists():
        raise SystemExit(f"no staged gate results at {gate_path} -- run gate <quarter> --staged first")
    with open(gate_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    promoted = []
    anchor_dir = config.DATA_DIR / "overrides" / "identifier_anchors"
    grammar_dir = config.DATA_DIR / "overrides" / "identifier_rate_grammars"
    anchor_dir.mkdir(parents=True, exist_ok=True)
    grammar_dir.mkdir(parents=True, exist_ok=True)

    for r in rows:
        if r.get("verdict") != "PASS":
            continue
        cik = r["cik"]
        apath, gpath = _proposal_paths(cik)
        if not (apath.exists() and gpath.exists()):
            print(f"  skip {cik}: PASS result but missing staged proposal file(s)")
            continue
        shutil.copyfile(apath, anchor_dir / f"{cik}.json")
        shutil.copyfile(gpath, grammar_dir / f"{cik}.json")
        promoted.append({"cik": cik, "entity_name": r.get("entity_name", ""),
                         "confidence": r.get("confidence", "")})

    out = qdir / "promote_results.csv"
    if promoted:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(promoted[0].keys()))
            w.writeheader(); w.writerows(promoted)
    else:
        out.write_text("cik,entity_name,confidence\n", encoding="utf-8")
    print(f"promote {quarter}: copied {len(promoted)} PASS proposal(s) -> production overrides; {out}")
    return promoted


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    quarter_modes = {"discover": discover, "finalize": finalize, "gate": gate, "promote": promote}
    cik_modes = {"claim": claim, "release": release}
    if len(argv) < 2 or argv[0] not in (quarter_modes | cik_modes):
        print("usage: python -m scripts.agent_a.run_quarter "
              "{discover|finalize|gate|promote} <quarter YYYY-MM-DD> [--staged]  |  "
              "{claim|release} <CIK>")
        return 1
    if argv[0] in cik_modes:
        return cik_modes[argv[0]](argv[1])
    staged = "--staged" in argv[2:]
    manifest_path = None
    if "--manifest" in argv[2:]:
        idx = argv.index("--manifest")
        if idx + 1 >= len(argv):
            print("--manifest requires a path")
            return 1
        manifest_path = argv[idx + 1]
    if staged and argv[0] not in {"finalize", "gate"}:
        print("--staged is only valid for finalize and gate")
        return 1
    if argv[0] in {"finalize", "gate"}:
        quarter_modes[argv[0]](argv[1], staged=staged, manifest_path=manifest_path)
    else:
        quarter_modes[argv[0]](argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
