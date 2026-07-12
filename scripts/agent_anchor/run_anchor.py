"""Anchor-adjudicator driver -- the independent pre-pass that establishes a filer's GRAND total of
investments at fair value, so the B2 fixer reconciles to the right number instead of a possibly
incomplete companyfacts subtotal.

It is SEPARATE from the fixer (it never authors holdings rules) and its number is only promoted
after the deterministic balance-sheet closure check (anchor_validation.verify_grand_total) -- the
agent does not control total_assets, so it cannot fabricate a closing total.

Triggers (discover): a target is adjudicated only when there is a SIGNAL the anchor is suspect --
  (i)  B1 adjudicated mechanism/fix_class as anchor_bad/anchor_fix [rare; B1 misses these], or
  (ii) the B2 investigation worker wrote an anchor escalation (category == 'anchor'), or
  (iii) the cheap deterministic screen flags companyfacts_fv << total_assets.

    python -m scripts.agent_anchor.run_anchor discover <batch> --source-worklist <b1.csv>
    python -m scripts.agent_anchor.run_anchor prep    --cik 1715933 --target-quarter 2025-06-30
    python -m scripts.agent_anchor.run_anchor verify  --cik 1715933 --target-quarter 2025-06-30
    python -m scripts.agent_anchor.run_anchor promote --cik 1715933 --target-quarter 2025-06-30

ASCII-only. Cache-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

import duckdb

from pipeline import config
from pipeline.agent_rule import is_anchor_escalation, load_escalations
from pipeline.anchor_leaf import load_anchor_leaf, validate_anchor_leaf
from pipeline.anchor_validation import HIGH, MEDIUM, incomplete_anchor_screen, verify_grand_total

BASE = config.OUTPUT_DIR / "agent_anchor"
INVESTIGATE_BASE = config.OUTPUT_DIR / "agent_investigate"
ANCHOR_OVERRIDES = config.PROJECT_ROOT / "data" / "overrides" / "agent_anchor"
DEFAULT_VERDICTS = config.OUTPUT_DIR / "review_queue" / "verdicts"
WORKER_PYTHON = sys.executable
DATA_QUERY = "scripts/review_agent/data_query_cli.py"
EVIDENCE_CLI = "scripts/review_agent/evidence_cli.py"

_ANCHOR_MECHS = {"anchor_bad"}
_ANCHOR_FIXES = {"anchor_fix"}


def _norm(cik: str) -> str:
    return str(cik).lstrip("0")


def _abs(rel: str) -> str:
    return (config.PROJECT_ROOT / rel).as_posix()


_CASH_CONCEPTS = ("CashAndCashEquivalentsAtCarryingValue", "Cash",
                  "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")
_CF_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")


def _companyfacts_cash(cik: str) -> dict[str, float]:
    """{report_date -> cash} from the cached companyfacts (not in fund_financials.csv). A BDC's
    non-investment assets are mostly cash; subtracting it sharpens the incomplete-anchor screen."""
    p = config.COMPANYFACTS_CACHE_DIR / f"{str(cik).zfill(10)}.json"
    if not p.exists():
        return {}
    try:
        facts = json.loads(p.read_text(encoding="utf-8")).get("facts", {}).get("us-gaap", {})
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, float] = {}
    for concept in _CASH_CONCEPTS:                       # first concept that has data wins per quarter
        for v in facts.get(concept, {}).get("units", {}).get("USD", []):
            if v.get("form") in _CF_FORMS and v.get("end") and v.get("val") is not None:
                out.setdefault(str(v["end"]), float(v["val"]))
    return out


def fund_financials(cik: str) -> dict[str, dict]:
    """{report_date -> {total_assets, companyfacts_fv, cash}} for this cik (companyfacts source)."""
    out: dict[str, dict] = {}
    ff = config.FUND_FINANCIALS_FILE
    if not Path(ff).exists():
        return out
    con = duckdb.connect()
    try:
        rows = con.execute(
            f"SELECT CAST(report_date AS VARCHAR), "
            f"max(TRY_CAST(total_assets AS DOUBLE)), "
            f"max(TRY_CAST(investments_at_fair_value AS DOUBLE)) "
            f"FROM read_csv_auto('{Path(ff).as_posix()}', sample_size=-1) "
            f"WHERE source='companyfacts' AND ltrim(CAST(cik AS VARCHAR),'0')='{_norm(cik)}' "
            f"GROUP BY 1").fetchall()
    finally:
        con.close()
    cash = _companyfacts_cash(cik)
    for rd, ta, fv in rows:
        out[str(rd)] = {"total_assets": ta, "companyfacts_fv": fv, "cash": cash.get(str(rd))}
    return out


def _b1_anchor_flag(verdicts_dir: Path, review_ids) -> bool:
    """True if ANY of the review's B1 verdicts named an anchor mechanism/fix_class."""
    for rid in review_ids:
        try:
            v = json.loads((Path(verdicts_dir) / f"{rid}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(v.get("mechanism")) in _ANCHOR_MECHS or str(v.get("fix_class")) in _ANCHOR_FIXES:
            return True
        for f in (v.get("findings") or []):
            if str(f.get("mechanism")) in _ANCHOR_MECHS or str(f.get("fix_class")) in _ANCHOR_FIXES:
                return True
    return False


def _b2_anchor_escalation(cik: str) -> bool:
    """True if the B2 investigation worker left an anchor-category escalation for this cik."""
    return any(is_anchor_escalation(e)
               for e in load_escalations(INVESTIGATE_BASE / _norm(cik) / "escalations"))


def _discover_targets(source_worklist, verdicts_dir) -> dict:
    """{(cik, quarter): [triggers]} for real_errors whose anchor is suspect."""
    src = Path(source_worklist)
    targets: dict[tuple, dict] = {}
    if not src.exists():
        return targets
    rows: dict[tuple, set] = {}
    with open(src, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rid = (row.get("review_id") or "").strip()
            cik = _norm(row.get("cik") or "")
            q = (row.get("report_date") or row.get("target_quarter") or "").strip()
            if rid and cik and q:
                rows.setdefault((cik, q), set()).add(rid)
    for (cik, q), rids in rows.items():
        if (ANCHOR_OVERRIDES / _norm(cik) / f"{q}.json").exists():
            continue                                  # already adjudicated (run-once termination)
        ff = fund_financials(cik).get(q, {})
        triggers = []
        if _b1_anchor_flag(verdicts_dir, rids):
            triggers.append("b1_mechanism")
        if _b2_anchor_escalation(cik):
            triggers.append("b2_escalation")
        flagged, _ = incomplete_anchor_screen(ff.get("companyfacts_fv"), ff.get("total_assets"), ff.get("cash"))
        if flagged:
            triggers.append("screen")
        if ff.get("companyfacts_fv") is None or ff.get("total_assets") is None:
            triggers.append("no_companyfacts_anchor")   # (b): adjudicate the anchor from the filing
        if triggers:
            targets[(cik, q)] = triggers
    return targets


def discover(batch_id: str, *, source_worklist, verdicts_dir=DEFAULT_VERDICTS) -> dict:
    targets = _discover_targets(source_worklist, verdicts_dir)
    out_dir = BASE / "batch" / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    wl = out_dir / "anchor_worklist.csv"
    with open(wl, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cik", "target_quarter", "triggers"])
        for (cik, q) in sorted(targets):
            w.writerow([cik, q, ";".join(targets[(cik, q)])])
    return {"batch_id": batch_id, "n_targets": len(targets), "worklist": str(wl)}


def _leaf_path(cik: str, target_quarter: str) -> Path:
    return BASE / _norm(cik) / "leaf" / f"anchor.{target_quarter}.json"


def _prompt(cik: str, target_quarter: str, ff: dict, leaf_path: Path) -> str:
    py = Path(WORKER_PYTHON).as_posix()
    ta = ff.get("total_assets"); cf = ff.get("companyfacts_fv")
    return f"""# Find the GRAND total of investments at fair value (cik {cik}, {target_quarter})

You are the anchor-adjudicator. Your ONE job: report this filer's GRAND total of investments at
fair value for {target_quarter}. You do NOT fix holdings. The companyfacts tag is
investments_at_fair_value = {cf}; total_assets = {ta}. The companyfacts tag MAY be incomplete -- for
multi-schedule BDCs it often captures only the non-affiliated schedule and excludes a separately
presented affiliated/controlled schedule.

## Where the grand total may live (filer-idiosyncratic -- find it)
- a single undimensioned tag (then method=single_tag), OR
- the last "Total Investments" row of the schedule of investments (method=total_row), OR
- NO single grand-total row: SUM the per-schedule subtotals -- non-affiliated + affiliated +
  controlled (method=sum_of_schedules). This is the common hard case.

## Tools (read-only; this cik only)
- Filing (truth): {py} {_abs(EVIDENCE_CLI)} --bundle <bundle.json> totals|grid|roam|tables
- Extracted data:  {py} {_abs(DATA_QUERY)} --cik {cik} query --sql "<SELECT over fund_financials/holdings/staging>"

## It MUST close against the balance sheet (you cannot fabricate a closing number)
grand_total <= total_assets, grand_total >= the companyfacts tag, and grand_total should be a high
fraction of total_assets (BDCs are mostly invested). If your number leaves an implausible non-
investment remainder, you found a subtotal, not the grand total -- keep looking.

## If companyfacts total_assets is null (a recent quarter the API has not caught up to)
Read total_assets from the FILING'S OWN BALANCE SHEET (evidence_cli grid/tables -- the "Total assets"
line) and put it in the leaf as `total_assets` with a `total_assets_source` citation. The closure
check will then run off the filing's balance sheet instead of companyfacts. (Filing-sourced is
single-source, so it is capped at MEDIUM confidence -- that is expected.)

## Output: write ONE anchor leaf to {leaf_path.as_posix()}
{{"cik":"{cik}","target_quarter":"{target_quarter}","grand_total":<number>,
  "method":"single_tag|total_row|sum_of_schedules",
  "components":[{{"label":"...","value":<number>,"source":"<cite the row/tag>"}}, ...],
  "companyfacts_fv":{cf},
  "total_assets":<number, ONLY if companyfacts total_assets is null -- read from the filing balance sheet>,
  "total_assets_source":"<cite the balance-sheet 'Total assets' line, if total_assets is supplied>",
  "evidence":[{{"source":"filing|query","quote":"..."}}],
  "rationale":"<why this is the grand total and what the companyfacts tag captured>","confidence":0.0-1.0}}
For sum_of_schedules the components MUST sum to grand_total. Cite every component. ASCII only.
"""


def prep(cik: str, target_quarter: str) -> dict:
    ff = fund_financials(cik).get(target_quarter, {})
    out = BASE / _norm(cik)
    leaf_dir = out / "leaf"
    leaf_dir.mkdir(parents=True, exist_ok=True)
    leaf_path = _leaf_path(cik, target_quarter)
    prompt_path = out / f"prompt.{target_quarter}.md"
    prompt_path.write_text(_prompt(cik, target_quarter, ff, leaf_path), encoding="utf-8")
    manifest = {"cik": _norm(cik), "target_quarter": target_quarter,
                "total_assets": ff.get("total_assets"), "companyfacts_fv": ff.get("companyfacts_fv"),
                "leaf_path": str(leaf_path), "prompt": str(prompt_path),
                "data_query_cli": DATA_QUERY, "evidence_cli": EVIDENCE_CLI}
    (out / f"manifest.{target_quarter}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def verify(cik: str, target_quarter: str) -> dict:
    """Validate the worker's anchor leaf (schema) + run the balance-sheet closure check."""
    leaf_path = _leaf_path(cik, target_quarter)
    leaf = load_anchor_leaf(leaf_path)
    if leaf is None:
        return {"cik": _norm(cik), "target_quarter": target_quarter, "status": "no_leaf",
                "leaf_path": str(leaf_path)}
    schema_errs = validate_anchor_leaf(leaf)
    ff = fund_financials(cik).get(target_quarter, {})
    # (b) closure input: prefer companyfacts total_assets; fall back to the FILING-sourced total_assets
    # the worker cited (for a companyfacts-lagged quarter). Filing-sourced is single-source -> cap MEDIUM.
    cf_ta = ff.get("total_assets")
    ta = cf_ta if cf_ta is not None else leaf.get("total_assets")
    ta_source = "companyfacts" if cf_ta is not None else ("filing" if leaf.get("total_assets") is not None else "none")
    chk = verify_grand_total(leaf.get("grand_total"), total_assets=ta,
                             companyfacts_fv=ff.get("companyfacts_fv"), cash=ff.get("cash"))
    if ta_source == "filing" and chk.tier == HIGH:
        chk.tier = MEDIUM
        chk.reasons.append("total_assets is filing-sourced (companyfacts lagged) -- capped at MEDIUM")
    ok = (schema_errs == []) and chk.ok
    return {"cik": _norm(cik), "target_quarter": target_quarter,
            "grand_total": leaf.get("grand_total"), "method": leaf.get("method"),
            "schema_errors": schema_errs, "tier": chk.tier, "closure_reasons": chk.reasons,
            "total_assets_source": ta_source, "invested_frac": chk.invested_frac, "ok": ok}


def promote(cik: str, target_quarter: str) -> dict:
    """Copy a verified anchor leaf to the per-cik override the fixer reads. REFUSES unless verify ok."""
    v = verify(cik, target_quarter)
    if not v.get("ok"):
        return {**v, "status": "refused"}
    dst = ANCHOR_OVERRIDES / _norm(cik)
    dst.mkdir(parents=True, exist_ok=True)
    out = dst / f"{target_quarter}.json"
    shutil.copy2(_leaf_path(cik, target_quarter), out)
    return {**v, "status": "promoted", "override": str(out)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Anchor-adjudicator driver (independent pre-pass).")
    sub = ap.add_subparsers(dest="mode", required=True)
    for m in ("prep", "verify", "promote", "discover"):
        p = sub.add_parser(m)
        if m == "discover":
            p.add_argument("batch_id")
            p.add_argument("--source-worklist", type=Path, required=True)
            p.add_argument("--verdicts-dir", type=Path, default=DEFAULT_VERDICTS)
        else:
            p.add_argument("--cik", required=True)
            p.add_argument("--target-quarter", required=True)
    args = ap.parse_args(argv)
    if args.mode == "discover":
        print(json.dumps(discover(args.batch_id, source_worklist=args.source_worklist,
                                  verdicts_dir=args.verdicts_dir), indent=2, default=str))
    elif args.mode == "prep":
        print(json.dumps(prep(args.cik, args.target_quarter), indent=2, default=str))
    elif args.mode == "verify":
        res = verify(args.cik, args.target_quarter)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("ok") else 1
    elif args.mode == "promote":
        res = promote(args.cik, args.target_quarter)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("status") == "promoted" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
