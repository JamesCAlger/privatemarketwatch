"""Convention Adjudicator driver -- discover / prep / verify / promote.

Anchor-shaped agent lane for the rate-convention classifier residual: one
verdict per CIK (all_in | cash_leg | indeterminate) with quoted filing
evidence, promoted to data/overrides/rate_convention/<cik>.json after the
deterministic verify gate. Spec:
docs/adjudication_architecture/convention_adjudicator_spec.md.

    python -m scripts.agent_convention.run_convention discover conv1 --cohort-only --top-n 21
    python -m scripts.agent_convention.run_convention prep    --cik 1812554 --target-quarter 2025-12-31
    python -m scripts.agent_convention.run_convention verify  --cik 1812554 --target-quarter 2025-12-31
    python -m scripts.agent_convention.run_convention promote --cik 1812554 --target-quarter 2025-12-31

The worker prompt is BLIND to the classifier's numeric signals (anti-anchoring;
keeps the verify cross-check non-circular). Cache-only, read-only until
promote. ASCII-only.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

from pipeline import config
from pipeline.convention_leaf import load_convention_leaf, validate_convention_leaf
from pipeline.convention_validation import verify_convention

BASE = config.OUTPUT_DIR / "agent_convention"
OVERRIDES = config.RATE_CONVENTION_OVERRIDES_DIR
BUNDLES = config.OUTPUT_DIR / "review_queue" / "review_bundles"
WORKER_PYTHON = sys.executable
DATA_QUERY = "scripts/review_agent/data_query_cli.py"
EVIDENCE_CLI = "scripts/review_agent/evidence_cli.py"


def _norm(cik) -> str:
    return str(cik or "").lstrip("0")


def _pad(cik) -> str:
    return _norm(cik).zfill(10)


def _abs(rel: str) -> str:
    return (config.PROJECT_ROOT / rel).as_posix()


def _holdings_sql(where: str) -> str:
    h = Path(config.UNIFIED_HOLDINGS_FILE).as_posix()
    return f"""
        SELECT ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') AS cik,
               CAST(report_date AS VARCHAR) AS q,
               issuer_name,
               TRY_CAST(interest_rate AS DOUBLE) AS ir,
               TRY_CAST(pik_rate AS DOUBLE) AS pik,
               TRY_CAST(fair_value AS DOUBLE) AS fv
        FROM read_csv_auto('{h}')
        WHERE lower(COALESCE(source, '')) = 'bdc' AND ({where})
    """


def _cik_bundles() -> dict[str, list[dict]]:
    """{cik: [{report_date, path}]} over existing review bundles (the seam
    evidence_cli opens filings through; roam covers the filing once one
    document resolves)."""
    out: dict[str, list[dict]] = {}
    if not BUNDLES.exists():
        return out
    for p in sorted(BUNDLES.glob("*.json")):
        try:
            b = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        cik = _norm(b.get("cik"))
        if cik:
            out.setdefault(cik, []).append(
                {"report_date": str(b.get("report_date") or ""), "path": str(p)})
    return out


def _best_bundle(bundles: list[dict], target_q: str) -> str:
    if not bundles:
        return ""
    exact = [b for b in bundles if b["report_date"][:10] == target_q[:10]]
    if exact:
        return exact[0]["path"]
    return sorted(bundles, key=lambda b: b["report_date"], reverse=True)[0]["path"]


def _cohort_ciks() -> set[str]:
    m = json.loads(Path(config.WRAPPER_COHORT_MANIFEST_FILE).read_text(encoding="utf-8-sig"))
    return {_norm(e.get("cik")) for e in m.get("entries", [])}


# --------------------------------------------------------------------- discover

def discover(batch_id: str, *, rate_convention_path: Path | None = None,
             cohort_only: bool = False, top_n: int | None = None) -> dict:
    """Targets = classifier unknowns without a current override, priority by
    latest-quarter PIK fair value. Run-once: an existing override skips."""
    rc_path = Path(rate_convention_path or config.RATE_CONVENTION_FILE)
    rc = pd.read_csv(rc_path, dtype={"cik": str})
    targets = rc[rc["convention"] == "unknown"].copy()
    targets["cik_n"] = targets["cik"].map(_norm)
    if cohort_only:
        targets = targets[targets["cik_n"].isin(_cohort_ciks())]
    has_override = targets["cik_n"].map(
        lambda c: (OVERRIDES / f"{_pad(c)}.json").exists())
    skipped_promoted = int(has_override.sum())
    targets = targets[~has_override]

    if len(targets) == 0:
        return {"batch_id": batch_id, "n_targets": 0, "skipped": skipped_promoted,
                "worklist": None}

    ciks = "', '".join(sorted(targets["cik_n"]))
    con = duckdb.connect()
    agg = con.execute(f"""
        WITH rows_ AS ({_holdings_sql(f"ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') IN ('{ciks}')")}),
        latest AS (
            SELECT cik, max(q) AS q FROM rows_ WHERE pik > 0 GROUP BY cik
        )
        SELECT r.cik, l.q AS target_quarter,
               SUM(CASE WHEN r.pik > 0 THEN r.fv ELSE 0 END) AS pik_fv,
               SUM(CASE WHEN r.pik > 0 THEN 1 ELSE 0 END) AS n_pik_rows
        FROM rows_ r JOIN latest l ON r.cik = l.cik AND r.q = l.q
        GROUP BY r.cik, l.q
    """).df()
    con.close()

    j = targets.merge(agg, left_on="cik_n", right_on="cik", how="inner",
                      suffixes=("", "_h"))
    j = j.sort_values("pik_fv", ascending=False)
    if top_n:
        j = j.head(top_n)

    by_cik_bundles = _cik_bundles()
    out_dir = BASE / "batch" / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)
    wl = out_dir / "convention_worklist.csv"
    with open(wl, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["cik", "target_quarter", "basis", "n_pik_rows", "pik_fv", "bundle_path"])
        for _, r in j.iterrows():
            bundle = _best_bundle(by_cik_bundles.get(r["cik_n"], []),
                                  str(r["target_quarter"]))
            w.writerow([_pad(r["cik_n"]), str(r["target_quarter"])[:10], r["basis"],
                        int(r["n_pik_rows"]), round(float(r["pik_fv"]), 0),
                        bundle or "NEEDS_BUNDLE"])
    n_needs = sum(1 for c in j["cik_n"]
                  if not by_cik_bundles.get(c))
    return {"batch_id": batch_id, "n_targets": len(j), "n_needs_bundle": n_needs,
            "skipped_promoted": skipped_promoted, "worklist": str(wl)}


# --------------------------------------------------------------------- prep

def _sample_positions(cik: str, target_quarter: str, n: int = 6) -> list[str]:
    con = duckdb.connect()
    try:
        rows = con.execute(f"""
            WITH rows_ AS ({_holdings_sql("1=1")})
            SELECT issuer_name FROM rows_
            WHERE cik = '{_norm(cik)}' AND substr(q, 1, 10) = '{target_quarter[:10]}'
              AND pik > 0
            ORDER BY fv DESC LIMIT {int(n)}
        """).fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows]


def _leaf_path(cik: str, target_quarter: str) -> Path:
    return BASE / _norm(cik) / "leaf" / f"convention.{target_quarter}.json"


def _prompt(cik: str, target_quarter: str, bundle_path: str,
            samples: list[str], leaf_path: Path) -> str:
    py = Path(WORKER_PYTHON).as_posix()
    names = "\n".join(f"- {s}" for s in samples) or "- (query the extracted data for PIK positions)"
    return f"""# What does this filer's stated interest rate MEAN? (cik {cik}, {target_quarter})

You are the convention-adjudicator. ONE question, answered from the FILING: when this filer
states a position-level interest rate, is it the ALL-IN coupon (PIK included in the stated
rate) or the CASH leg only (PIK quoted separately, on top)? You do NOT fix holdings and you
do NOT judge whether any rate is correct -- only what the stated rate MEANS.

## The three disclosure patterns (find which one this filer uses)
1. ALL-IN: one rate column showing the total, PIK parenthetical or footnoted --
   e.g. "12.50% (incl. 3.00% PIK)", or a footnote "includes paid-in-kind interest".
2. CASH LEG: separate Cash and PIK columns, or text like "6.70% Cash, 7.60% PIK".
3. CASH LEG (additive quote): a spread-form rate with PIK appended --
   e.g. "SOFR + 5.50%, 2.00% PIK" (the stated rate/spread EXCLUDES the PIK).

Column HEADERS and rate FOOTNOTES are first-class evidence -- quote them. Then confirm on
actual schedule rows. These PIK positions exist in this filer's schedule (navigation aid
only -- find their printed rate text):
{names}

## Tools (read-only; this cik only)
- Filing (truth): {py} {_abs(EVIDENCE_CLI)} --bundle {bundle_path} totals|grid|roam|tables
- Extracted data (to LOCATE positions, never to decide): {py} {_abs(DATA_QUERY)} --cik {cik} query --sql "<SELECT ...>"

## Output: write ONE convention leaf to {leaf_path.as_posix()}
{{"cik":"{cik}","target_quarter":"{target_quarter}",
  "convention":"all_in|cash_leg|indeterminate",
  "column_semantics":"<what the rate column(s) actually show>",
  "citations":[
    {{"kind":"header","quote":"<rate column header>","where":"<page/section>"}},
    {{"kind":"footnote","quote":"<PIK footnote text>","where":"..."}},
    {{"kind":"position","issuer":"<name as printed>","quote":"<the printed rate text>",
      "printed_total":<number or omit>,"printed_pik":<number>,"printed_cash":<number or omit>}}],
  "applies_from":"<YYYY-MM-DD, ONLY if you checked an earlier filing too>",
  "rationale":"...","confidence":0.0-1.0}}

A DECIDED verdict needs at least 2 position citations with the printed numbers parsed out,
plus (strongly preferred) a header/footnote citation. If the filing genuinely does not
disclose which convention it uses, answer "indeterminate" and include
"search_trail":["<what you checked and found silent>", ...] -- that is a VALID answer;
do not guess. ASCII only.
"""


def prep(cik: str, target_quarter: str, bundle_path: str | None = None) -> dict:
    if not bundle_path:
        bundle_path = _best_bundle(_cik_bundles().get(_norm(cik), []), target_quarter)
    if not bundle_path:
        return {"cik": _norm(cik), "target_quarter": target_quarter,
                "status": "no_bundle",
                "note": "generate a review bundle for this cik-quarter first "
                        "(prepare_fresh_batch bundle-gen seam)"}
    samples = _sample_positions(cik, target_quarter)
    out = BASE / _norm(cik)
    leaf_path = _leaf_path(cik, target_quarter)
    leaf_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path = out / f"prompt.{target_quarter}.md"
    prompt_path.write_text(
        _prompt(cik, target_quarter, bundle_path, samples, leaf_path), encoding="utf-8")
    manifest = {"cik": _norm(cik), "target_quarter": target_quarter,
                "bundle_path": bundle_path, "sample_positions": samples,
                "leaf_path": str(leaf_path), "prompt": str(prompt_path),
                "data_query_cli": DATA_QUERY, "evidence_cli": EVIDENCE_CLI}
    (out / f"manifest.{target_quarter}.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# --------------------------------------------------------------------- verify / promote

def _stored_rates(cik: str, target_quarter: str) -> dict:
    """{issuer_lower: [(ir, pik), ...]} for the target quarter (verify input)."""
    con = duckdb.connect()
    try:
        rows = con.execute(f"""
            WITH rows_ AS ({_holdings_sql("1=1")})
            SELECT lower(issuer_name), ir, pik FROM rows_
            WHERE cik = '{_norm(cik)}' AND substr(q, 1, 10) = '{target_quarter[:10]}'
              AND issuer_name IS NOT NULL
        """).fetchall()
    finally:
        con.close()
    out: dict[str, list] = {}
    for name, ir, pik in rows:
        out.setdefault(str(name), []).append((ir, pik))
    return out


def _classifier_stats(cik: str) -> dict:
    p = Path(config.RATE_CONVENTION_FILE)
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if _norm(r.get("cik")) == _norm(cik):
                return r
    return {}


def verify(cik: str, target_quarter: str) -> dict:
    leaf_path = _leaf_path(cik, target_quarter)
    leaf = load_convention_leaf(leaf_path)
    if leaf is None:
        return {"cik": _norm(cik), "target_quarter": target_quarter,
                "status": "no_leaf", "leaf_path": str(leaf_path), "ok": False}
    schema_errs = validate_convention_leaf(leaf)
    if schema_errs:
        return {"cik": _norm(cik), "target_quarter": target_quarter,
                "status": "schema_errors", "schema_errors": schema_errs, "ok": False}
    chk = verify_convention(leaf, _stored_rates(cik, target_quarter),
                            _classifier_stats(cik))
    return {"cik": _norm(cik), "target_quarter": target_quarter,
            "convention": leaf.get("convention"), "tier": chk.tier,
            "n_reconciled": chk.n_reconciled, "n_pik_only": chk.n_pik_only,
            "n_opposite": chk.n_opposite, "n_unmatched": chk.n_unmatched,
            "reasons": chk.reasons, "ok": chk.ok}


def promote(cik: str, target_quarter: str) -> dict:
    """Copy a verified leaf (with verify provenance) to the override store.
    REFUSES unless verify ok -- same contract as anchor promote."""
    v = verify(cik, target_quarter)
    if not v.get("ok"):
        return {**v, "status": "refused"}
    leaf = load_convention_leaf(_leaf_path(cik, target_quarter))
    leaf["verify_tier"] = v["tier"]
    leaf["verify_n_reconciled"] = v["n_reconciled"]
    OVERRIDES.mkdir(parents=True, exist_ok=True)
    out = OVERRIDES / f"{_pad(cik)}.json"
    out.write_text(json.dumps(leaf, indent=2), encoding="utf-8")
    return {**v, "status": "promoted", "override": str(out)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convention Adjudicator driver.")
    sub = ap.add_subparsers(dest="mode", required=True)
    d = sub.add_parser("discover")
    d.add_argument("batch_id")
    d.add_argument("--rate-convention", type=Path, default=None)
    d.add_argument("--cohort-only", action="store_true")
    d.add_argument("--top-n", type=int, default=None)
    for m in ("prep", "verify", "promote"):
        p = sub.add_parser(m)
        p.add_argument("--cik", required=True)
        p.add_argument("--target-quarter", required=True)
        if m == "prep":
            p.add_argument("--bundle", default=None)
    args = ap.parse_args(argv)
    if args.mode == "discover":
        print(json.dumps(discover(args.batch_id, rate_convention_path=args.rate_convention,
                                  cohort_only=args.cohort_only, top_n=args.top_n),
                         indent=2, default=str))
        return 0
    if args.mode == "prep":
        print(json.dumps(prep(args.cik, args.target_quarter, args.bundle),
                         indent=2, default=str))
        return 0
    if args.mode == "verify":
        res = verify(args.cik, args.target_quarter)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("ok") else 1
    if args.mode == "promote":
        res = promote(args.cik, args.target_quarter)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("status") == "promoted" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
