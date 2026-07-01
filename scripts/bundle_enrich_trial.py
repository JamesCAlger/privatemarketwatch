"""Bundle-enrichment trial v2: resolved-issuer FV arithmetic.

The pilot (v1) refuted "resolve coordinate ambiguity". The real blocker is FV
reconciliation: bare-issuer XBRL axis facts are often ISSUER-LEVEL ROLLUPS (sum of
tranche leaves), not single positions. v2 injects, per blocker row, the signed
resolved-issuer arithmetic: does the bare-issuer fact FV reconcile to the sum of
same-issuer tranche leaves? -> ROLLUP (do not add) vs genuine single position vs
ambiguous (escalate). FV-grounded and able to conclude NO_PATCH, fixing v1's threat #3.

Read-only on production (writes only data/output/bdc_cik_review_exp/).
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
import duckdb
from pipeline.config import OUTPUT_DIR

SAND = OUTPUT_DIR / "bdc_cik_review_exp"
BUNDLES = OUTPUT_DIR / "bdc_cik_review" / "bundles"
DETAIL = OUTPUT_DIR / "source_reconciliation_detail.csv"

TRANCHE_RE = re.compile(r"(series|preferred|common|term|note|warrant|loan|lien|membership|"
                        r"unit|revolver|subordinat|senior|\$|\d+\.\d+\s*%)", re.I)
AGG_RE = re.compile(r"^\s*(total|subtotal)\b", re.I)


def _ev(bundle: dict) -> dict:
    return {it["evidence_id"]: it.get("data", it) for it in bundle["evidence_items"]}


def _f(x):
    try: return float(x)
    except (TypeError, ValueError): return 0.0


def resolve(bundle: dict, con) -> list[dict]:
    ev = _ev(bundle)
    blockers = ev.get("source_only_blocker_rows") or ev.get("source_residual_rows") or []
    cik, rd = bundle["cik"], bundle["report_date"]
    out = []
    for b in blockers:
        ident = (b.get("raw_investment_identifier") or "").strip()
        bare_fv = _f(b.get("source_fair_value"))
        tok = re.split(r"[,(]", ident)[0].strip().lower()[:18].replace("'", "''")
        rows = con.execute(f"""
            SELECT raw_investment_identifier,
                   TRY_CAST(source_fair_value AS DOUBLE), TRY_CAST(output_fair_value AS DOUBLE), status
            FROM D WHERE cik='{cik}' AND report_date='{rd}'
              AND lower(raw_investment_identifier) LIKE '%{tok}%'""").fetchall() if tok else []
        tranches = [r for r in rows if r[0] and r[0].strip().lower() != ident.lower()
                    and TRANCHE_RE.search(r[0]) and not AGG_RE.search(r[0])]
        sum_tr = sum(_f(r[1]) for r in tranches)
        n_tr = len(tranches)
        n_tr_out = sum(1 for r in tranches if _f(r[2]) > 0 or str(r[3] or "").lower() in ("matched", "reconciled"))
        ratio = (sum_tr / bare_fv) if bare_fv else None

        if n_tr >= 2 and ratio and 0.9 <= ratio <= 1.1:
            hint = "ROLLUP"
            concl = (f"Bare-issuer fact FV {bare_fv:,.0f} reconciles to the sum of {n_tr} same-issuer "
                     f"tranche leaves ({sum_tr:,.0f}, ratio {ratio:.2f}); {n_tr_out}/{n_tr} reached output. "
                     f"ISSUER-LEVEL ROLLUP, not a single position -> do NOT add as a position. "
                     + ("Tranches already in output -> NO_PATCH_NEEDED (or aggregate-filter the rollup fact)."
                        if n_tr_out >= max(1, n_tr - 1) else
                        "Tranches under-attributed in output -> a separate tranche-attribution defect, "
                        "still do not add the rollup."))
        elif n_tr == 0 and bare_fv > 0:
            hint = "SINGLE_POSITION_CANDIDATE"
            concl = (f"No same-issuer tranche leaves found; bare-issuer FV {bare_fv:,.0f} does not decompose "
                     f"-> may be a genuine single position missing from output (verify it equals one SOI line).")
        else:
            hint = "AMBIGUOUS"
            concl = (f"{n_tr} tranche leaves sum {sum_tr:,.0f} vs bare-issuer {bare_fv:,.0f} "
                     f"(ratio {('%.2f' % ratio) if ratio else 'NA'}); only partial reconciliation -> ESCALATE.")
        out.append({
            "raw_investment_identifier": ident,
            "bare_issuer_source_fv": round(bare_fv, 0),
            "n_same_issuer_tranche_leaves": n_tr,
            "sum_tranche_source_fv": round(sum_tr, 0),
            "tranche_sum_over_bare_ratio": round(ratio, 3) if ratio else None,
            "tranche_leaves_reaching_output": n_tr_out,
            "tranche_samples": [{"id": str(r[0])[:60], "sfv": _f(r[1])} for r in tranches[:6]],
            "resolution": hint,
            "deterministic_conclusion": concl,
        })
    return out


def raw_source_rows(bundle: dict, con) -> list[dict]:
    """v3: the RAW current-period source rows for this filing -- unparsed, undeduped of
    issuer, just identifier + FV + output-match status. NO derived conclusion. The agent
    locates the blocker issuer's name within these identifiers and reconciles by reading
    source (which deterministic parsing cannot do for flattened identifiers)."""
    cik, rd = bundle["cik"], bundle["report_date"]
    rows = con.execute(f"""
        SELECT DISTINCT raw_investment_identifier,
               TRY_CAST(source_fair_value AS DOUBLE), TRY_CAST(output_fair_value AS DOUBLE), status
        FROM D WHERE cik='{cik}' AND report_date='{rd}' AND period='{rd}'
          AND raw_investment_identifier IS NOT NULL
        ORDER BY TRY_CAST(source_fair_value AS DOUBLE) DESC NULLS LAST""").fetchall()
    return [{"raw_investment_identifier": r[0], "source_fv": _f(r[1]),
             "output_fv": _f(r[2]), "match_status": str(r[3] or "")} for r in rows]


def main(argv=None):
    args = argv if argv is not None else sys.argv[1:]
    con = duckdb.connect()
    con.execute(f"CREATE TABLE D AS SELECT * FROM read_csv_auto('{DETAIL.as_posix()}', sample_size=-1, all_varchar=true)")
    if len(args) == 1 and args[0].endswith(".txt"):
        cands = [Path(line) for line in Path(args[0]).read_text().splitlines() if line.strip()]
    elif args:
        cands = [Path(a) for a in args]
    else:  # diverse: 3 new CIKs + Tilson (0000081955) positive control
        ciks = ["0001508655", "0001280784", "0001370755", "0000081955"]
        cands = []
        for c in ciks:
            g = sorted(BUNDLES.glob(f"*_{c}_*POSITION_LIKE*.json")) or sorted(BUNDLES.glob(f"*_{c}_*PCT_LEAF*.json"))
            if g: cands.append(g[0])
    SAND.mkdir(parents=True, exist_ok=True)
    for bp in cands:
        bundle = json.loads(bp.read_text())
        raw = raw_source_rows(bundle, con)
        (SAND / f"CONTROL_{bp.name}").write_text(json.dumps(bundle, indent=2))
        treat = json.loads(bp.read_text())
        treat["evidence_items"].append({
            "evidence_id": "raw_source_rows_current_period",
            "data": raw,
            "note": "RAW current-period source rows for this filing (identifier + FV + output-match "
                    "status), unparsed. To reconcile a bare-issuer blocker: find the issuer name within "
                    "these identifiers, sum source_fv across its tranches, compare to the blocker FV, and "
                    "note which tranches reached output. No derived conclusion is provided.",
        })
        (SAND / f"TREATMENT_{bp.name}").write_text(json.dumps(treat, indent=2))
        blk = (_ev(bundle).get("source_only_blocker_rows") or _ev(bundle).get("source_residual_rows") or [{}])[0]
        print(f"\n=== {bp.name}: {len(raw)} raw current-period rows injected; "
              f"blocker='{(blk.get('raw_investment_identifier') or '')[:50]}' ===")
        for r in raw[:4]:
            print(f"   sFV={r['source_fv']:>14,.0f} oFV={r['output_fv']:>12,.0f} {r['match_status'][:14]:14s} {r['raw_investment_identifier'][:55]}")
    print(f"\nwrote {len(cands)} control/treatment pairs to {SAND}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
