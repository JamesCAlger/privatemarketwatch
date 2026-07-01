"""B-trial evidence CLI: the agent's ONLY window into raw source.

Resolves the cached filing for a bundle and lets a (blinded) adjudicator ROAM it
freely: list tables, page a full table grid, free-text search across the whole
filing, and pull the filing's own total/subtotal lines (the conservation anchor).
Uncapped roaming over the raw parsed tables (pipeline.html_extract._extract_tables);
no derived pipeline conclusion is exposed. Cache-only, read-only, no network
(fails closed on a cache miss).

Usage (run from repo root):
    python scripts/review_agent/evidence_cli.py --bundle <b.json> overview
    python scripts/review_agent/evidence_cli.py --bundle <b.json> tables
    python scripts/review_agent/evidence_cli.py --bundle <b.json> grid --table 7 [--start 0 --count 100]
    python scripts/review_agent/evidence_cli.py --bundle <b.json> roam --query "Acme,First Lien,PIK"
    python scripts/review_agent/evidence_cli.py --bundle <b.json> totals
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.html_extract import _extract_tables  # noqa: E402
from pipeline.html_soi_evidence import (  # noqa: E402
    _html_path,
    _load_filing_meta,
    normalize_text,
    resolve_accessions_from_rows,
)

_ENGINE_SOURCE = {
    "conservation": "BDC", "identity": "BDC", "weak": "BDC", "cross_source": "BDC",
    "row_validation": "BDC", "oracle": "BDC", "gav_recon": "BDC",
    "aggregate_header": "BDC", "fund_financials": "BDC",
    "agentA": "BDC",   # Agent A identifier-grammar induction roams the same cached BDC SOI
}

# generic SOI words dropped when extracting a distinctive issuer search token
_GENERIC = {
    "investments", "investment", "united", "states", "debt", "insurance", "senior",
    "secured", "first", "second", "third", "lien", "term", "loan", "loans", "delayed",
    "draw", "revolving", "revolver", "type", "portfolio", "fund", "securities",
    "subordinated", "common", "stock", "preferred", "equity", "units", "unit", "the",
    "inc", "llc", "ltd", "lp", "corp", "co", "and", "of", "clo", "structured",
    "finance", "notes", "note", "company", "holdings", "group", "warrants", "warrant",
}


def _rows_from_bundle(bundle: dict) -> list[dict]:
    rows: list[dict] = []
    for ev in bundle.get("evidence_items", []):
        data = ev.get("data")
        if isinstance(data, list):
            rows.extend(r for r in data if isinstance(r, dict))
        elif isinstance(data, dict):
            rows.append(data)
    return rows


def _cons_from_bundle(bundle: dict) -> dict | None:
    for ev in bundle.get("evidence_items", []):
        if ev.get("evidence_id") == "source_artifact_rows":
            for r in ev.get("data", []) or []:
                if r.get("value_sum") is not None and r.get("anchor_value") is not None:
                    return {k: r.get(k) for k in
                            ("value_sum", "anchor_value", "residual_pct",
                             "status", "anchor_used")}
    return None


def _load(bundle: dict):
    """Return (accession, meta, tables) or (None, reason_dict, None)."""
    rows = _rows_from_bundle(bundle)
    accs = resolve_accessions_from_rows(rows)
    cik = bundle.get("cik", "")
    report_date = bundle.get("report_date", "")
    source = _ENGINE_SOURCE.get(bundle.get("engine", ""), "BDC")
    if not accs:
        return None, {"status": "no_accession_resolved", "cik": cik,
                      "report_date": report_date, "rows_seen": len(rows)}, None
    acc = accs[0]
    path = _html_path(source, cik, acc)
    if not path.exists():
        return None, {"status": "missing_cached_html", "cik": cik,
                      "accession": acc, "path": str(path)}, None
    meta = _load_filing_meta(source, cik, acc, report_date)
    raw = path.read_text(encoding="utf-8", errors="replace")
    tables = _extract_tables(raw)
    return acc, meta, tables


def _nonempty(row: list) -> list[int]:
    return [i for i, c in enumerate(row) if normalize_text(c)]


def _row_text(row: list) -> str:
    return " | ".join(normalize_text(c) for c in row if normalize_text(c))


def _header(t: list) -> str:
    """First content-bearing row (SOI tables often have blank leading rows)."""
    for row in t[:6]:
        if sum(1 for c in row if normalize_text(c)) >= 2:
            return _row_text(row)[:200]
    return _row_text(t[0])[:200] if t else ""


def _search(tables, terms: list[str], limit: int = 80):
    terms_l = [t.lower() for t in terms]
    hits, scanned = [], 0
    for ti, tbl in enumerate(tables):
        for ri, row in enumerate(tbl):
            scanned += 1
            txt = _row_text(row)
            if txt and any(t in txt.lower() for t in terms_l):
                hits.append({"table_index": ti, "row_index": ri,
                             "cell_indices": _nonempty(row), "row_text": txt[:500]})
                if len(hits) >= limit:
                    return hits, scanned, True
    return hits, scanned, False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Roam cached raw source for a bundle.")
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("cmd", choices=["claim", "flagged", "overview", "tables", "grid", "roam", "totals"])
    ap.add_argument("--query", default="")
    ap.add_argument("--table", type=int, default=None)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=100)
    args = ap.parse_args(argv)

    bundle = json.loads(args.bundle.read_text())

    if args.cmd == "claim":
        # The trusted boundary: emit ONLY the question, never the pipeline's
        # verdict/confidence/mechanism. The adjudicator gets this, not the bundle.
        rule = bundle.get("rule_name", "")
        claim = {"rule_name": rule, "cik": bundle.get("cik"),
                 "report_date": bundle.get("report_date"),
                 "asserted": {
                     "fv_conservation": "Sum of this fund-quarter's position fair values does NOT reconcile to the independent fund-level total investments at fair value.",
                     "pik_le_interest_rate": "A position has a PIK rate GREATER than its total interest rate (PIK should be <= interest).",
                     "C113": "A position has an interest_rate OUTSIDE the plausible range 0-25%.",
                 }.get(rule, f"Rule {rule} fired on this unit.")}
        cons = _cons_from_bundle(bundle)
        if cons:
            claim["discrepancy"] = cons
        print(json.dumps(claim, indent=2))
        return 0

    if args.cmd == "flagged":
        # The QUESTION made concrete: the holdings rows the rule actually fired on
        # (issuer + the questioned rate). Derived data, but it is the subject of the
        # flag, not the pipeline's verdict -- so it is fair to show for review.
        import duckdb
        rule = bundle.get("rule_name", "")
        cik = str(bundle.get("cik", ""))
        rd = str(bundle.get("report_date", ""))
        preds = {
            "C113": "TRY_CAST(interest_rate AS DOUBLE) > 25 OR TRY_CAST(interest_rate AS DOUBLE) < 0",
            "pik_le_interest_rate": "TRY_CAST(pik_rate AS DOUBLE) > TRY_CAST(interest_rate AS DOUBLE) "
                                    "AND TRY_CAST(pik_rate AS DOUBLE) > 0 AND TRY_CAST(interest_rate AS DOUBLE) > 0",
        }
        pred = preds.get(rule)
        if pred is None:
            print(json.dumps({"note": f"no per-row flag for rule {rule}; see claim/discrepancy"}))
            return 0
        H = REPO / "data/output/private_markets_holdings.csv"
        q = f"""
            SELECT issuer_name, instrument_description, interest_rate, pik_rate, basis_spread,
                   asset_class, bdc_investment_identifier
            FROM read_csv_auto('{H.as_posix()}', sample_size=-1)
            WHERE lpad(CAST(cik AS VARCHAR), 10, '0') = '{cik}'
              AND CAST(report_date AS VARCHAR) = '{rd}' AND ({pred})
            LIMIT 50
        """
        rows = duckdb.connect().execute(q).df().to_dict("records")
        # Auto-locate each flagged row in the cached filing (issuer token + the
        # stored rate value to pin the exact tranche).
        import re
        _, _, tables = _load(bundle)

        def _terms(s: str) -> list[str]:
            toks = re.findall(r"[A-Za-z0-9]+", s or "")
            return [t for t in toks if t.lower() not in _GENERIC and len(t) > 2]

        def _rate_cands(v):
            try:
                f = float(v)
            except (TypeError, ValueError):
                return []
            if f != f:                                   # NaN
                return []
            # match how filings print the rate (no rounding: 25.75 stays 25.75)
            return list({f"{f:g}", f"{f:.1f}", f"{f:.2f}"})

        def _locate(row: dict):
            if not tables:
                return None
            terms = _terms(row.get("issuer_name") or row.get("bdc_investment_identifier") or "")
            if not terms:
                return None
            key = terms[0].lower()
            cands = _rate_cands(row.get("interest_rate")) or _rate_cands(row.get("pik_rate"))
            best = None
            for ti, tbl in enumerate(tables):
                for ri, r in enumerate(tbl):
                    txt = _row_text(r)
                    if key in txt.lower():
                        cand = {"table_index": ti, "row_index": ri, "row_text": txt[:300]}
                        nospace = txt.replace(" ", "")
                        if cands and any(c in nospace for c in cands):
                            return cand          # exact tranche (issuer + rate)
                        if best is None:
                            best = cand          # issuer-only fallback
            return best

        for row in rows:
            row["filing_location"] = _locate(row)
        print(json.dumps({"rule": rule, "cik": cik, "report_date": rd,
                          "n_flagged": len(rows), "flagged_rows": rows}, indent=2, default=str))
        return 0

    acc, meta, tables = _load(bundle)
    if acc is None:
        print(json.dumps(meta, indent=2))
        return 0

    if args.cmd == "overview":
        out = {
            "accession": acc,
            "entity_name": meta.get("entity_name"),
            "form_type": meta.get("form_type"),
            "report_date": meta.get("report_date"),
            "table_count": len(tables),
            "soi_like_tables": [
                {"table_index": ti, "n_rows": len(t),
                 "n_cols": max((len(r) for r in t), default=0),
                 "header": _header(t)}
                for ti, t in enumerate(tables) if len(t) >= 8
            ][:40],
            "hint": "use `tables` for all tables, `grid --table N` to read one, "
                    "`roam --query ...` to search, `totals` for total/subtotal lines.",
        }
    elif args.cmd == "tables":
        out = {"accession": acc, "tables": [
            {"table_index": ti, "n_rows": len(t),
             "n_cols": max((len(r) for r in t), default=0),
             "header": _header(t)}
            for ti, t in enumerate(tables)]}
    elif args.cmd == "grid":
        if args.table is None or not (0 <= args.table < len(tables)):
            out = {"error": f"--table in [0,{len(tables)-1}] required"}
        else:
            t = tables[args.table]
            end = min(args.start + args.count, len(t))
            out = {"accession": acc, "table_index": args.table, "n_rows": len(t),
                   "start": args.start, "end": end,
                   "rows": [{"row_index": args.start + i,
                             "cells": [normalize_text(c) for c in row]}
                            for i, row in enumerate(t[args.start:end])]}
    elif args.cmd == "roam":
        terms = [s.strip() for s in args.query.split(",") if s.strip()]
        if not terms:
            out = {"error": "roam needs --query 'term1,term2'"}
        else:
            hits, scanned, trunc = _search(tables, terms)
            out = {"accession": acc, "query": terms, "rows_scanned": scanned,
                   "n_hits": len(hits), "truncated": trunc, "matches": hits}
    else:  # totals
        hits, scanned, trunc = _search(tables, ["total"], limit=120)
        out = {"accession": acc, "rows_scanned": scanned, "n_hits": len(hits),
               "truncated": trunc, "total_lines": hits}

    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
