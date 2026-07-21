"""Scan cached BDC XBRL instance documents for linkbase-adjacent semantics.

One streaming pass over data/raw/filings/bdc_xbrl/{cik}/{accession}.xml
producing two artifacts (zero network):

1. rate_tag_fingerprint_by_accession.csv -- per accession, which rate-family
   concepts the filer used (bare InvestmentInterestRate vs PaidInCash vs
   PaidInKind vs floor), whether cash + PIK == bare within contexts
   (arithmetic proof the bare element is all-in), and which concept "won"
   the pipeline's interest_rate column under bdc_filings first-match-wins
   semantics.

2. fv_dimension_buckets_by_accession.csv -- per accession + period, fair
   value facts bucketed by dimension shape: typed/explicit member on an
   investment-identifier axis (leaf positions), dims-but-no-identifier
   (category-level facts), and no dims at all (fund-level totals, i.e.
   XBRL domain-default semantics).  Feeds the domain-default conservation
   test for subtotal leakage.

Usage:
    python scripts/scan_rate_tag_fingerprint.py [--limit N] [--cik CIK]

ASCII-only logging (Windows cp1252).
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parents[1]
XBRL_DIR = REPO / "data" / "raw" / "filings" / "bdc_xbrl"
OUT_DIR = REPO / "data" / "output" / "linkbase_analysis"

# Rate-family classification by lowercase local name.
# Order matters: most specific first (mirrors the hazard in CONCEPT_MAP).
_RATE_KINDS = [
    ("investmentinterestratepaidincash", "cash"),
    ("investmentinterestratepaidinkind", "pik"),
    ("investmentinterestratefloor", "floor"),
    ("investmentinterestrate", "bare"),
    ("investmentpikrate", "pik_alt"),
]

# Pipeline CONCEPT_MAP order for the interest_rate/pik_rate columns
# (bdc_filings.CONCEPT_MAP): paidinkind->pik_rate, floor->floor,
# investmentinterestrate->interest_rate (catches paidincash too!),
# investmentpikrate->pik_rate.
_PIPELINE_COL = {
    "cash": "interest_rate",   # collapses via bare substring match
    "pik": "pik_rate",
    "floor": "interest_rate_floor",
    "bare": "interest_rate",
    "pik_alt": "pik_rate",
}

_ID_AXIS_SUBSTRINGS = ("investmentidentifier", "investmentcompany")
_FV_SUBSTRINGS = ("investmentownedatfairvalue", "investmentownedfairvalue")

_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"

_RATE_TOL = 5e-4  # rates are decimals (0.085 = 8.5%); 0.05pp tolerance


def _local(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _is_usgaap(tag: str) -> bool:
    return "fasb.org/us-gaap" in tag


def scan_file(path: Path):
    """Parse one instance document; return (rate_row_dict, fv_rows list)."""
    ctx_period: dict[str, str] = {}
    ctx_bucket: dict[str, str] = {}  # ctx id -> 'leaf' | 'dims_no_id' | 'no_dims'
    ctx_idval: dict[str, str] = {}   # leaf ctx id -> identifier member value
    ctx_ndims: dict[str, int] = {}   # ctx id -> number of dimension members
    # rate facts: ctx -> list[(kind, value, is_ext, order_index)]
    rate_facts: dict[str, list] = defaultdict(list)
    # fv facts: (ctx) -> first value  (mirror pipeline first-wins)
    fv_first: dict[str, float] = {}

    def _clear(elem) -> None:
        """Clear a top-level element and any already-processed siblings."""
        elem.clear()
        parent = elem.getparent()
        if parent is not None:
            while elem.getprevious() is not None:
                del parent[0]

    order = 0
    try:
        for _, elem in etree.iterparse(
            str(path), events=("end",), recover=True, huge_tree=True
        ):
            parent = elem.getparent()
            # Only handle direct children of the document root.  Children of
            # <context> (period, members) must stay intact until the parent
            # context's own end event fires.
            if parent is None or parent.getparent() is not None:
                continue

            tag = elem.tag
            ln = _local(tag)
            if ln == "context":
                cid = elem.get("id")
                if cid:
                    instant = None
                    end = None
                    n_dims = 0
                    has_id_axis = False
                    id_val = ""
                    for sub in elem.iter():
                        sln = _local(sub.tag)
                        if sln == "instant":
                            instant = (sub.text or "").strip()
                        elif sln == "endDate":
                            end = (sub.text or "").strip()
                        elif sln in ("explicitMember", "typedMember"):
                            n_dims += 1
                            dim = (sub.get("dimension") or "").lower()
                            if any(s in dim for s in _ID_AXIS_SUBSTRINGS):
                                has_id_axis = True
                                if sln == "typedMember":
                                    id_val = "".join(sub.itertext()).strip()
                                else:
                                    id_val = "".join(sub.itertext()).strip()
                    ctx_period[cid] = instant or end or ""
                    ctx_bucket[cid] = (
                        "leaf" if has_id_axis
                        else ("dims_no_id" if n_dims else "no_dims")
                    )
                    ctx_ndims[cid] = n_dims
                    if has_id_axis:
                        ctx_idval[cid] = id_val
                _clear(elem)
                continue

            cref = elem.get("contextRef")
            if cref is None:
                _clear(elem)
                continue
            nil = elem.get(_XSI_NIL)
            if nil and nil.lower() == "true":
                _clear(elem)
                continue
            text = (elem.text or "").strip()
            if not text:
                _clear(elem)
                continue
            lnl = ln.lower()

            kind = None
            for pat, k in _RATE_KINDS:
                if pat in lnl:
                    kind = k
                    break
            if kind is not None:
                try:
                    val = float(text.replace(",", ""))
                except ValueError:
                    val = None
                order += 1
                rate_facts[cref].append((kind, val, not _is_usgaap(tag), order))
            elif any(s in lnl for s in _FV_SUBSTRINGS):
                try:
                    fval = float(text.replace(",", ""))
                except ValueError:
                    fval = None
                if fval is not None and cref not in fv_first:
                    fv_first[cref] = fval
            _clear(elem)
    except etree.XMLSyntaxError as exc:
        return {"parse_error": str(exc)[:120]}, []

    # ---- rate fingerprint aggregation ----
    counts = defaultdict(int)
    n_ctx_rate = 0
    n_ctx_cash_pik = 0        # context has both cash and pik facts
    n_ctx_bare_cash_pik = 0   # has all three
    n_sum_ok = 0              # bare ~= cash + pik
    n_bare_eq_cash = 0        # bare ~= cash (bare tagged as cash duplicate)
    n_ext_rate = 0
    ir_winner = defaultdict(int)  # which kind won pipeline interest_rate col

    for cref, facts in rate_facts.items():
        n_ctx_rate += 1
        kinds_present = {}
        for kind, val, is_ext, order_idx in sorted(facts, key=lambda f: f[3]):
            counts[kind] += 1
            if is_ext:
                n_ext_rate += 1
            if kind not in kinds_present and val is not None:
                kinds_present[kind] = val
        # pipeline simulation: first fact whose column is interest_rate wins
        for kind, val, is_ext, order_idx in sorted(facts, key=lambda f: f[3]):
            if _PIPELINE_COL[kind] == "interest_rate":
                ir_winner[kind] += 1
                break
        c = kinds_present.get("cash")
        p = kinds_present.get("pik", kinds_present.get("pik_alt"))
        b = kinds_present.get("bare")
        if c is not None and p is not None:
            n_ctx_cash_pik += 1
            if b is not None:
                n_ctx_bare_cash_pik += 1
                if abs(b - (c + p)) <= _RATE_TOL:
                    n_sum_ok += 1
                if abs(b - c) <= _RATE_TOL:
                    n_bare_eq_cash += 1

    rate_row = {
        "n_ctx_rate": n_ctx_rate,
        "n_bare": counts["bare"],
        "n_cash": counts["cash"],
        "n_pik": counts["pik"] + counts["pik_alt"],
        "n_floor": counts["floor"],
        "n_ext_rate_facts": n_ext_rate,
        "n_ctx_cash_and_pik": n_ctx_cash_pik,
        "n_ctx_bare_cash_pik": n_ctx_bare_cash_pik,
        "n_sum_ok": n_sum_ok,
        "n_bare_eq_cash": n_bare_eq_cash,
        "ir_won_by_bare": ir_winner["bare"],
        "ir_won_by_cash": ir_winner["cash"],
        "parse_error": "",
    }

    # ---- fv dimension buckets per period ----
    per_period = defaultdict(lambda: {
        "leaf_raw_sum": 0.0, "leaf_raw_n": 0,
        # (id_val) -> (n_dims, fval): keep fact from minimal-dimension ctx
        "leaf_by_id": {},
        "dims_no_id_sum": 0.0, "dims_no_id_n": 0,
        "no_dims_values": [],
    })
    for cref, fval in fv_first.items():
        bucket = ctx_bucket.get(cref)
        period = ctx_period.get(cref, "")
        if bucket is None or not period:
            continue
        slot = per_period[period]
        if bucket == "leaf":
            slot["leaf_raw_sum"] += fval
            slot["leaf_raw_n"] += 1
            idv = ctx_idval.get(cref, "") or f"__ctx__{cref}"
            nd = ctx_ndims.get(cref, 99)
            prev = slot["leaf_by_id"].get(idv)
            if prev is None or nd < prev[0]:
                slot["leaf_by_id"][idv] = (nd, fval)
        elif bucket == "dims_no_id":
            slot["dims_no_id_sum"] += fval
            slot["dims_no_id_n"] += 1
        else:
            slot["no_dims_values"].append(fval)

    fv_rows = []
    for period, slot in per_period.items():
        if slot["leaf_raw_n"] == 0 and not slot["no_dims_values"]:
            continue
        dedup_sum = sum(v for _, v in slot["leaf_by_id"].values())
        dedup_n = len(slot["leaf_by_id"])
        totals = slot["no_dims_values"]
        best_total = ""
        best_gap_pct = ""
        if totals and dedup_sum > 0:
            best_total = min(totals, key=lambda t: abs(t - dedup_sum))
            best_gap_pct = round(
                100.0 * (dedup_sum - best_total) / best_total, 4
            ) if best_total else ""
        fv_rows.append({
            "period": period,
            "leaf_raw_n": slot["leaf_raw_n"],
            "leaf_raw_sum": round(slot["leaf_raw_sum"], 2),
            "leaf_dedup_n": dedup_n,
            "leaf_dedup_sum": round(dedup_sum, 2),
            "dims_no_id_n": slot["dims_no_id_n"],
            "dims_no_id_sum": round(slot["dims_no_id_sum"], 2),
            "n_no_dims_totals": len(totals),
            "closest_no_dims_total": best_total,
            "leaf_vs_total_gap_pct": best_gap_pct,
        })
    return rate_row, fv_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max files (0=all)")
    ap.add_argument("--cik", default=None, help="restrict to one CIK dir")
    args = ap.parse_args()

    files = []
    for cik_dir in sorted(XBRL_DIR.iterdir()):
        if not cik_dir.is_dir():
            continue
        if args.cik and cik_dir.name != args.cik.lstrip("0"):
            if cik_dir.name != args.cik:
                continue
        for f in sorted(cik_dir.glob("*.xml")):
            files.append((cik_dir.name, f))
    if args.limit:
        files = files[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rate_path = OUT_DIR / "rate_tag_fingerprint_by_accession.csv"
    fv_path = OUT_DIR / "fv_dimension_buckets_by_accession.csv"

    rate_cols = ["cik", "accession", "n_ctx_rate", "n_bare", "n_cash", "n_pik",
                 "n_floor", "n_ext_rate_facts", "n_ctx_cash_and_pik",
                 "n_ctx_bare_cash_pik", "n_sum_ok", "n_bare_eq_cash",
                 "ir_won_by_bare", "ir_won_by_cash", "parse_error"]
    fv_cols = ["cik", "accession", "period", "leaf_raw_n", "leaf_raw_sum",
               "leaf_dedup_n", "leaf_dedup_sum",
               "dims_no_id_n", "dims_no_id_sum", "n_no_dims_totals",
               "closest_no_dims_total", "leaf_vs_total_gap_pct"]

    t0 = time.time()
    with open(rate_path, "w", newline="", encoding="utf-8") as rf, \
            open(fv_path, "w", newline="", encoding="utf-8") as ff:
        rw = csv.DictWriter(rf, fieldnames=rate_cols)
        fw = csv.DictWriter(ff, fieldnames=fv_cols)
        rw.writeheader()
        fw.writeheader()
        for i, (cik, path) in enumerate(files):
            rate_row, fv_rows = scan_file(path)
            base = {"cik": cik, "accession": path.stem}
            full = dict.fromkeys(rate_cols, "")
            full.update(base)
            full.update(rate_row)
            rw.writerow(full)
            for row in fv_rows:
                out = dict(base)
                out.update(row)
                fw.writerow(out)
            if (i + 1) % 100 == 0:
                el = time.time() - t0
                print(f"[{i + 1}/{len(files)}] {el:.0f}s elapsed", flush=True)
    print(f"DONE {len(files)} files in {time.time() - t0:.0f}s")
    print(f"wrote {rate_path}")
    print(f"wrote {fv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
