"""Labeler agent -- constrained, source-reading, BLIND to pipeline output.

Reads ONLY the cached inline-XBRL filing and emits candidate labels + citations to
data/gold/candidates/candidates_<draw>.jsonl. It NEVER reads private_markets_
holdings or any pipeline artifact, and it does NOT look at the frame's pipeline
values -- only (cik, report_date, accession, source_identifier), i.e. which
position to find. The human is the final adjudicator; candidates just pre-fill the
harness so the human confirms instead of transcribing.

INDEPENDENCE: this module has its OWN minimal iXBRL fact reader (it does not call
pipeline.bdc_xbrl_html_bridge), so a pipeline extraction bug cannot leak into the
gold candidate. true_fair_value / true_cost come from the tagged
InvestmentOwnedAtFairValue / InvestmentOwnedAtCost facts (exact, per-position
contextRef, @scale-resolved). true_classification / true_lien are heuristic
candidates from the position text, tagged low-confidence for the human to confirm.

READ-ONLY except writing data/gold/candidates/. No network.

Usage: python scripts/gold/labeler_agent.py --draw batch1
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
BDC_HTML = ROOT / "data" / "raw" / "filings" / "bdc_html"
SAMPLES = ROOT / "data" / "gold" / "samples"
CANDIDATES = ROOT / "data" / "gold" / "candidates"
CANDIDATES.mkdir(parents=True, exist_ok=True)

FV_CONCEPT = "InvestmentOwnedAtFairValue"
COST_CONCEPT = "InvestmentOwnedAtCost"


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) and "}" in tag else (tag or "")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _num(text: str | None, scale: str | None, sign: str | None) -> float | None:
    t = re.sub(r"[^0-9.\-]", "", (text or "").replace("(", "-").replace(")", ""))
    if t in ("", "-", ".", "--"):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    if scale:
        try:
            v *= 10 ** int(scale)
        except ValueError:
            pass
    if sign == "-":
        v = -v
    return v


def doc_path(cik: str, accession: str) -> Path | None:
    p = BDC_HTML / str(int(cik)) / (accession.replace("-", "") + ".html")
    return p if p.exists() else None


def read_facts(path: Path, report_date: str) -> dict:
    """Own minimal iXBRL reader. Returns {by_ident: {norm_id: {...}}, total_fv}."""
    tree = etree.parse(str(path))
    root = tree.getroot()
    rd = _norm(report_date)

    # context id -> (identifier, instant, n_dims)
    ctx: dict[str, tuple[str, str, int]] = {}
    for c in root.iter():
        if _local(c.tag) != "context":
            continue
        cid = c.get("id")
        ident = instant = ""
        ndims = 0
        for sub in c.iter():
            st = _local(sub.tag)
            if st in ("typedMember", "explicitMember"):
                ndims += 1
                if "Investment" in (sub.get("dimension") or ""):
                    kids = list(sub)
                    ident = _norm((kids[0].text if kids else sub.text) or "")
            elif st == "instant":
                instant = _norm(sub.text)
        if cid:
            ctx[cid] = (ident, instant, ndims)

    by_ident: dict[str, dict] = {}
    total_fv = None
    for el in root.iter():
        if _local(el.tag) != "nonFraction":
            continue
        name = (el.get("name") or "").rsplit(":", 1)[-1]
        if name not in (FV_CONCEPT, COST_CONCEPT):
            continue
        ident, instant, ndims = ctx.get(el.get("contextRef"), ("", "", 0))
        if instant != rd:
            continue
        val = _num(el.text, el.get("scale"), el.get("sign"))
        if name == FV_CONCEPT and not ident and ndims == 0 and val is not None:
            # no-dimension balance-sheet total = fund total investments at FV
            total_fv = val if total_fv is None else max(total_fv, val)
            continue
        if not ident:
            continue
        rec = by_ident.setdefault(ident, {"fv": None, "cost": None,
                                          "context_id": el.get("contextRef")})
        if name == FV_CONCEPT:
            rec["fv"] = val
            rec["context_id"] = el.get("contextRef")
        elif name == COST_CONCEPT:
            rec["cost"] = val
    return {"by_ident": by_ident, "total_fv": total_fv}


def classify_text(identifier: str) -> str | None:
    t = identifier.lower()
    if re.search(r"\b(term loan|revolver|delayed draw|first lien|second lien|senior secured|"
                 r"unsecured|subordinated|note|loan|debt|credit facility)\b", t):
        return "DIRECT_LENDING"
    if re.search(r"\b(equity|common|preferred|warrant|units?|shares?|membership interest|"
                 r"llc interest|partnership interest)\b", t):
        return "DIRECT_EQUITY"
    return None


def lien_text(identifier: str, lien_section: str = "") -> str | None:
    try:
        from pipeline.lien_classification import classify_lien
    except Exception:
        return None
    return classify_lien("", identifier) or classify_lien("", lien_section) or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", default="batch1")
    args = ap.parse_args()

    frame = [json.loads(ln) for ln in
             (SAMPLES / f"sample_frame_{args.draw}.jsonl").read_text().splitlines() if ln.strip()]

    facts_cache: dict[tuple[str, str], dict] = {}
    out, stats = [], {"position": 0, "matched": 0, "fv_read": 0, "cik_quarter": 0,
                      "cikq_total_read": 0, "no_doc": 0, "skipped_flag": 0}

    for u in frame:
        ut = u["unit_type"]
        tag = u.get("source_identifier") or (u.get("flag") or {}).get("rule_name") or "-"
        key = f"{ut}|{u['cik']}|{u.get('report_date')}|{tag}"
        if ut == "flag":
            stats["skipped_flag"] += 1
            continue
        acc = u.get("accession")
        p = doc_path(u["cik"], acc) if acc else None
        if p is None:
            stats["no_doc"] += 1
            continue
        ck = (u["cik"], acc)
        if ck not in facts_cache:
            try:
                facts_cache[ck] = read_facts(p, u["report_date"])
            except Exception as e:
                facts_cache[ck] = {"by_ident": {}, "total_fv": None, "err": str(e)}
        facts = facts_cache[ck]

        base = {"_key": key, "record_type": ut, "cik": u["cik"],
                "report_date": u.get("report_date"), "accession": acc,
                "adjudicator": "agent:ixbrl-reader-v1", "label_status": "agent_candidate",
                "source_ref": {"doc": str(p.relative_to(ROOT)), "context_id": None,
                               "note": ""}}

        if ut == "cik_quarter":
            stats["cik_quarter"] += 1
            base["true_total_investments_fv"] = facts.get("total_fv")
            if facts.get("total_fv") is not None:
                stats["cikq_total_read"] += 1
                base["source_ref"]["note"] = "no-dimension InvestmentOwnedAtFairValue total"
            out.append(base)
            continue

        # position
        stats["position"] += 1
        rec = facts["by_ident"].get(_norm(u.get("source_identifier") or ""))
        match = "exact"
        if rec is None:
            # fallback: unique startswith on the normalized identifier prefix
            nid = _norm(u.get("source_identifier") or "")
            cands = [v for k, v in facts["by_ident"].items()
                     if nid and (k.startswith(nid[:24]) or nid.startswith(k[:24]))]
            rec = cands[0] if len(cands) == 1 else None
            match = "fallback" if rec else "unmatched"
        if rec:
            stats["matched"] += 1
            if rec.get("fv") is not None:
                stats["fv_read"] += 1
            base["true_fair_value"] = rec.get("fv")
            base["true_cost"] = rec.get("cost")
            base["source_ref"]["context_id"] = rec.get("context_id")
        else:
            base["true_fair_value"] = None
            base["true_cost"] = None
        ident = u.get("source_identifier") or ""
        base["true_classification"] = classify_text(ident)
        base["true_lien"] = lien_text(ident)
        base["match"] = match
        base["confidence"] = {"fair_value": "ixbrl_fact" if match != "unmatched" else "unmatched",
                              "cost": "ixbrl_fact" if rec and rec.get("cost") is not None else "missing",
                              "classification": "heuristic_text", "lien": "heuristic_text"}
        out.append(base)

    path = CANDIDATES / f"candidates_{args.draw}.jsonl"
    with path.open("w", encoding="ascii") as fh:
        for r in out:
            fh.write(json.dumps(r, default=str) + "\n")

    print(f"[labeler] draw={args.draw} units_processed={len(out)}")
    print(f"  positions={stats['position']} matched={stats['matched']} "
          f"fv_read={stats['fv_read']} "
          f"({100*stats['fv_read']/stats['position']:.0f}% of positions)" if stats['position'] else "")
    print(f"  cik_quarters={stats['cik_quarter']} total_fv_read={stats['cikq_total_read']}")
    print(f"  no_cached_doc={stats['no_doc']} flags_skipped={stats['skipped_flag']}")
    print(f"[labeler] wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
