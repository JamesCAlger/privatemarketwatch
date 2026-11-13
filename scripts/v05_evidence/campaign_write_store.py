"""Write the D-252 store for one rule of the 2026-11-13 retirement campaign from the check's build output.

    python scripts/v05_evidence/campaign_write_store.py --rule PP03 --results res_PP03.json --verdict-dir <dir> --out <store.json>

Only entries whose check PASSED are written. Each entry records the verdict file's sha256 (the ledger
matches on it), every published row the check tested (cited_rows), the filed total context where the
rule uses one, and verbatim printed lines (each confirmed a substring of the cached page). Every entry is
validated with pipeline.verdict_retirements.validate before the file is written. Read-only otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "v05_evidence"))
import campaign_retirement_check as chk  # noqa: E402
from fund_gate import page_text  # noqa: E402
from pipeline import verdict_retirements as vr  # noqa: E402

OWNER = ("run as recommended (standing rule D-252): an agent may retire a real-error verdict when a deterministic check "
         "shows every row the verdict cites is published at its filed (printed) values in today's published data, "
         "or is correctly excluded")
APPLIED = ("agent:retire-campaign-20261113-opus under the standing rule (owner ruling D-252, 2026-11-10); "
           "owner 2026-11-13: \"do it\" (rule-by-rule retirement campaign on real_error_check_silent findings)")
SHORT = {"fv_conservation": "FVC"}

CLAIM = {
    "PP03": ("The verdict found earlier-period (comparative schedule) rows retained in the %(rd)s holdings. Every one of "
             "the %(n)d published rows of the quarter comes from the quarter's own filing (%(acc)s), sits on a context "
             "dated %(rd)s, and where it has a fair value equals the fair-value fact of its own context printed on its "
             "own schedule line; no comparative-period context is published."),
    "fv_conservation": ("The verdict found the published fair value did not sum to the filed total investments. Every one of "
                        "the %(n)d published rows equals the fair value printed for its own context (dated %(rd)s), and "
                        "the published sum (%(basis)s) equals the filed total investments %(total).0f within %(tol).0f."),
    "B01": ("The verdict found the quarter's position population polluted (comparative, structural or duplicate leaves) or "
            "short of the filed total. Every one of the %(n)d published rows has a fair-value fact in its own context "
            "dated %(rd)s and equals it, and the published sum (%(basis)s) equals the filed total investments %(total).0f "
            "within %(tol).0f."),
    "C04": ("The verdict found equity rows published without the share count the filing prints. Every one of the %(n)d "
            "published equity rows sits on a context dated %(rd)s and its shares_held equals the count printed on its "
            "own line."),
}
CODE = {
    "PP03": "every published row: own filing, context instant = report date, fair value = own context's printed fact",
    "fv_conservation": "every published row = own context's printed fair-value fact; published sum = filed total investments (undimensioned InvestmentOwnedAtFairValue fact at the report date) within two units of its rounding",
    "B01": "fv_conservation test plus every published row must carry a fair-value fact in its own context",
    "C04": "every published equity row (C04 population): context dated the report date; shares_held = the count fact on its own <tr> (InvestmentOwnedBalanceShares / PrincipalAmount), or, untagged, the count printed on the line",
}


def _lines(res: dict, k: int = 2) -> list[dict]:
    """Verbatim printed lines: the filed total line (if any) and k published rows' own lines."""
    out = []
    acc = res["detail"]["accessions"][0]
    page = page_text(res["cik"], acc) or ""
    fl = chk.filing(res["cik"], acc)
    tot = (res["detail"].get("total") or {}).get("total_line")
    cands = ([tot] if tot else []) + [fl.printed_line(c) for c in res.get("_contexts", [])]
    for line in cands:
        if line and line in page and line not in [o["quote"] for o in out]:
            out.append({"source": "filing", "accession": acc, "quote": line, "verbatim": True})
        if len(out) >= k + (1 if tot else 0):
            break
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--verdict-dir", required=True)
    ap.add_argument("--holdings", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = json.loads(Path(a.results).read_text(encoding="utf-8"))
    con = chk._con()
    entries = []
    for r in res:
        if not r["ok"]:
            continue
        rid, rule = r["review_id"], r["rule_name"]
        vp = [Path(a.verdict_dir) / s / (rid + ".json") for s in ("review_queue", "bdc_cik_review")]
        vp = [p for p in vp if p.exists()][0]
        rows = chk.quarter_rows(con, Path(a.holdings).as_posix(), r["cik"], r["report_date"])
        pool = [x for x in rows if rule != "C04" or chk.is_equity(x)]
        big = sorted(pool, key=lambda x: -abs(x["fair_value"] or 0.0))
        r["_contexts"] = [x["src_context_id"] for x in big[:6]]
        tot = r["detail"].get("total") or {}
        params = {"rd": r["report_date"], "n": len(pool), "acc": r["detail"]["accessions"][0],
                  "basis": tot.get("basis", ""), "total": tot.get("total") or 0.0, "tol": tot.get("tol") or 0.0}
        query = ("private_markets_holdings.parquet (batch b1112b build), published basis (JV look-through rows excluded): "
                 "%d rows of %s %s from %s" % (len(rows), r["cik"], r["report_date"], ", ".join(r["detail"]["accessions"])))
        if tot:
            query += "; published sum all rows %.0f, non-CASH %.0f, CASH %.0f (%d rows); filed total %.0f (context %s); basis %s" % (
                tot["sum_all"], tot["sum_ex_cash"], tot["sum_cash"], tot["n_cash"], tot["total"], tot["total_context"], tot["basis"])
        if rule in ("PP03", "B01", "fv_conservation"):
            fl = chk.filing(r["cik"], r["detail"]["accessions"][0])
            prior = {cx for (n, cx) in fl.facts if n == chk.FV and (fl.contexts.get(cx) or {}).get("instant")
                     and fl.contexts[cx]["instant"] < r["report_date"]
                     and "us-gaap:InvestmentIdentifierAxis" in fl.contexts[cx]["dims"]}
            pub_ctx = {x["src_context_id"] for x in rows}
            query += ("; the filing carries %d position fair-value contexts dated before %s (its comparative "
                      "schedule), of which %d are published" % (len(prior), r["report_date"], len(prior & pub_ctx)))
        ev = [{"source": "code", "quote": "scripts/v05_evidence/campaign_retirement_check.py (%s): %s; every realistic plant fails"
               % (rule, CODE[rule])},
              {"source": "query", "quote": query}] + _lines(r)
        n = len([e for e in entries]) + 1
        e = {"retirement_id": "VR-CMP-%s-%03d" % (SHORT.get(rule, rule), n), "review_id": rid,
             "verdict_sha256": hashlib.sha256(vp.read_bytes()).hexdigest(), "cik": r["cik"], "engine": r["engine"],
             "rule_name": rule, "report_date": r["report_date"],
             "reason": "Standing rule D-252: " + CLAIM[rule] % params,
             "evidence": ev, "cited_rows": [x["row_id"] for x in pool], "published_rows": len(rows),
             "rerun": ("python scripts/v05_evidence/campaign_retirement_check.py verify --store %s --holdings <batch output>/"
                       "private_markets_holdings.parquet (the b1112b build was used); add --plant: every plant must fail. "
                       "Needs the cached filings under data/raw/filings/bdc_html."
                       % ("data/overrides/verdict_retirements/" + Path(a.out).name)),
             "owner_words": OWNER, "decided_by": "owner", "decided_on": "2026-11-10", "applied_by": APPLIED,
             "cohort_left": False}
        if tot.get("total_context"):
            e["filed_total_context"] = tot["total_context"]
        probs = vr.validate(e)
        if probs:
            raise SystemExit("invalid entry %s: %s" % (rid, probs))
        if not any(x["source"] == "filing" for x in ev):
            raise SystemExit("no verbatim printed line for %s" % rid)
        entries.append(e)
        chk.filing.cache_clear()
    note = ("Verdict-retirement campaign 2026-11-13, rule %s: real-error verdicts whose claim the deterministic check "
            "shows is no longer true of the published data (standing rule D-252). Generated by "
            "scripts/v05_evidence/campaign_write_store.py." % a.rule)
    Path(a.out).write_text(json.dumps({"_note": note, "retirements": entries}, indent=1, ensure_ascii=True) + "\n",
                           encoding="utf-8")
    print("written %d entries to %s" % (len(entries), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
