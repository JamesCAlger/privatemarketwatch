"""Analyze SEC BDC dataset zips for linkbase-derived rate + subtotal signals.

Reads every zip in data/raw/sec_datasets/bdc_monthly/ (plus the legacy
bdc_data.zip) and produces three artifacts under
data/output/linkbase_analysis/:

1. dataset_rate_semantics.csv -- per (cik, adsh): how many soi.tsv rows carry
   "Investment, Interest Rate, Paid in Cash" / "Paid in Kind" / bare
   "Investment Interest Rate" values, and row-level arithmetic tests
   bare ~= cash + pik / bare ~= cash.  This is SEC's own flattening of the
   filer's SOI tagging -- independent of our extraction.

2. dataset_cal_rate_arcs.csv -- calculation-linkbase arcs (cal.tsv) touching
   the investment rate family: filer-declared total = cash + PIK style
   decompositions.

3. dataset_pre_rate_labels.csv -- presentation-linkbase rows (pre.tsv) for
   rate-family tags: the rendered column-header text (plabel) and preferred
   label role (prole) per filing.  These are the machine-readable column
   headers an adjudicator would otherwise read from the filing by eye.

Zero writes outside data/output/linkbase_analysis/.  ASCII-only logging.

Usage:
    python scripts/analyze_bdc_dataset_linkbase.py
"""

from __future__ import annotations

import csv
import io
import sys
import time
import zipfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ZIP_DIRS = [
    REPO / "data" / "raw" / "sec_datasets" / "bdc_monthly",
]
LEGACY_ZIP = REPO / "data" / "raw" / "sec_datasets" / "bdc_data.zip"
OUT_DIR = REPO / "data" / "output" / "linkbase_analysis"

_RATE_TOL = 5e-4  # rates in soi.tsv are decimals (0.085 = 8.5%)

# soi.tsv column-name candidates (label-style headers)
_COL_BARE = ("Investment Interest Rate",)
_COL_CASH = ("Investment, Interest Rate, Paid in Cash",)
_COL_PIK = ("Investment, Interest Rate, Paid in Kind",)
_COL_ID_AXIS = ("Investment, Identifier Axis",)

# tag-name substrings for cal.tsv / pre.tsv (element names, not labels)
_RATE_TAG_SUB = "investmentinterestrate"


def _open_tsv(zf: zipfile.ZipFile, names: list[str], candidates: list[str]):
    for cand in candidates:
        if cand in names:
            raw = zf.open(cand)
            return csv.DictReader(
                io.TextIOWrapper(raw, encoding="utf-8", errors="replace"),
                delimiter="\t",
            )
    return None


def _fnum(v: str):
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def main() -> int:
    zips: list[Path] = []
    for d in ZIP_DIRS:
        if d.is_dir():
            zips.extend(sorted(d.glob("*.zip")))
    if LEGACY_ZIP.exists():
        zips.append(LEGACY_ZIP)
    if not zips:
        print("no zips found")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # (cik, adsh) -> aggregate dict; first zip containing an adsh wins
    seen_adsh: set[str] = set()
    rate_rows: dict[tuple, dict] = {}
    cal_rows: list[dict] = []
    pre_rows: list[dict] = []
    seen_cal_adsh: set[str] = set()
    seen_pre_adsh: set[str] = set()

    t0 = time.time()
    for zp in zips:
        try:
            zf = zipfile.ZipFile(zp)
        except zipfile.BadZipFile:
            print(f"BADZIP {zp.name}")
            continue
        names = zf.namelist()

        # ---- soi.tsv ----
        rdr = _open_tsv(zf, names, ["soi.tsv", "datasets/soi.tsv"])
        n_soi = 0
        if rdr is not None:
            cols = rdr.fieldnames or []
            c_bare = next((c for c in cols if c in _COL_BARE), None)
            c_cash = next((c for c in cols if c in _COL_CASH), None)
            c_pik = next((c for c in cols if c in _COL_PIK), None)
            c_id = next((c for c in cols if c in _COL_ID_AXIS), None)
            for row in rdr:
                adsh = row.get("adsh", "")
                if not adsh or adsh in seen_adsh:
                    continue
                n_soi += 1
                key = (row.get("cik", ""), adsh)
                agg = rate_rows.get(key)
                if agg is None:
                    agg = rate_rows[key] = {
                        "name": row.get("name", ""),
                        "period": row.get("period", ""),
                        "form": row.get("form", ""),
                        "n_rows": 0, "n_id_rows": 0,
                        "n_bare": 0, "n_cash": 0, "n_pik": 0,
                        "n_cash_and_pik": 0, "n_bare_cash_pik": 0,
                        "n_sum_ok": 0, "n_bare_eq_cash": 0,
                        "src_zip": zp.name,
                    }
                agg["n_rows"] += 1
                if c_id and (row.get(c_id) or "").strip():
                    agg["n_id_rows"] += 1
                b = _fnum(row.get(c_bare)) if c_bare else None
                c = _fnum(row.get(c_cash)) if c_cash else None
                p = _fnum(row.get(c_pik)) if c_pik else None
                if b is not None:
                    agg["n_bare"] += 1
                if c is not None:
                    agg["n_cash"] += 1
                if p is not None:
                    agg["n_pik"] += 1
                if c is not None and p is not None:
                    agg["n_cash_and_pik"] += 1
                    if b is not None:
                        agg["n_bare_cash_pik"] += 1
                        if abs(b - (c + p)) <= _RATE_TOL:
                            agg["n_sum_ok"] += 1
                        if abs(b - c) <= _RATE_TOL:
                            agg["n_bare_eq_cash"] += 1

        # mark adsh as seen only after full soi pass of this zip
        for (cik, adsh) in list(rate_rows.keys()):
            seen_adsh.add(adsh)

        # ---- cal.tsv ----
        rdr = _open_tsv(zf, names, ["datasets/cal.tsv", "cal.tsv"])
        if rdr is not None:
            for row in rdr:
                adsh = row.get("adsh", "")
                if adsh in seen_cal_adsh:
                    continue
                pt = (row.get("ptag") or "").lower()
                ct = (row.get("ctag") or "").lower()
                if _RATE_TAG_SUB in pt or _RATE_TAG_SUB in ct:
                    cal_rows.append({
                        "adsh": adsh,
                        "ptag": row.get("ptag", ""),
                        "pversion": row.get("pversion", ""),
                        "ctag": row.get("ctag", ""),
                        "cversion": row.get("cversion", ""),
                        "negative": row.get("negative", ""),
                        "src_zip": zp.name,
                    })

        # ---- pre.tsv ----
        rdr = _open_tsv(zf, names, ["datasets/pre.tsv", "pre.tsv"])
        if rdr is not None:
            for row in rdr:
                adsh = row.get("adsh", "")
                if adsh in seen_pre_adsh:
                    continue
                tag = (row.get("tag") or "")
                if _RATE_TAG_SUB in tag.lower():
                    pre_rows.append({
                        "adsh": adsh,
                        "tag": tag,
                        "version": row.get("version", ""),
                        "prole": row.get("prole", ""),
                        "plabel": row.get("plabel", ""),
                        "negating": row.get("negating", ""),
                        "stmt": row.get("stmt", ""),
                        "src_zip": zp.name,
                    })

        # mark cal/pre adsh seen (any adsh present in this zip's sub.tsv)
        rdr = _open_tsv(zf, names, ["datasets/sub.tsv", "sub.tsv"])
        if rdr is not None:
            for row in rdr:
                a = row.get("adsh", "")
                if a:
                    seen_cal_adsh.add(a)
                    seen_pre_adsh.add(a)

        zf.close()
        print(f"{zp.name}: soi_rows={n_soi} elapsed={time.time() - t0:.0f}s",
              flush=True)

    # ---- write artifacts ----
    p1 = OUT_DIR / "dataset_rate_semantics.csv"
    with open(p1, "w", newline="", encoding="utf-8") as f:
        cols = ["cik", "adsh", "name", "period", "form", "n_rows", "n_id_rows",
                "n_bare", "n_cash", "n_pik", "n_cash_and_pik",
                "n_bare_cash_pik", "n_sum_ok", "n_bare_eq_cash", "src_zip"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for (cik, adsh), agg in sorted(rate_rows.items()):
            out = {"cik": cik, "adsh": adsh}
            out.update(agg)
            w.writerow(out)

    p2 = OUT_DIR / "dataset_cal_rate_arcs.csv"
    with open(p2, "w", newline="", encoding="utf-8") as f:
        cols = ["adsh", "ptag", "pversion", "ctag", "cversion", "negative",
                "src_zip"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(cal_rows)

    p3 = OUT_DIR / "dataset_pre_rate_labels.csv"
    with open(p3, "w", newline="", encoding="utf-8") as f:
        cols = ["adsh", "tag", "version", "prole", "plabel", "negating",
                "stmt", "src_zip"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(pre_rows)

    print(f"DONE: {len(rate_rows)} filings, {len(cal_rows)} cal arcs, "
          f"{len(pre_rows)} pre rows in {time.time() - t0:.0f}s")
    print(f"wrote {p1}\nwrote {p2}\nwrote {p3}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
