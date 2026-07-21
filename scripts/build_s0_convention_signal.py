"""Build the S0 tag-fingerprint convention signal artifact.

Aggregates two linkbase-analysis artifacts into a per-CIK S0 signal that
pipeline/rate_convention.py consumes (opt-in via load_s0_signal):

  inputs:
    data/output/linkbase_analysis/rate_tag_fingerprint_by_accession.csv
        (scripts/scan_rate_tag_fingerprint.py -- cached instance XML, zero
        network: which rate concept won the stored interest_rate column per
        context, plus the within-context bare ~= cash + pik sum test)
    data/output/linkbase_analysis/dataset_pre_rate_labels.csv
        (scripts/analyze_bdc_dataset_linkbase.py -- SEC BDC dataset pre.tsv:
        presentation-linkbase labels per rate concept; label guard against
        observed concept misuse)

  output:
    data/output/linkbase_analysis/s0_convention_signal.csv

Label guard rationale (measured 2026-07-20): of 34 CIKs tagging
InvestmentInterestRatePaidInCash, two misuse it -- Main Street labels it
"PIK Rate"; First Eagle labels it generically and tags PaidInKind as a
"PIK loan concentration" (not a rate). A cash_leg S0 conviction therefore
requires labels that do not contradict the concept.

Usage:
    python scripts/build_s0_convention_signal.py
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.rate_convention import s0_from_fingerprint  # noqa: E402
from pipeline.config import (  # noqa: E402
    LINKBASE_ANALYSIS_DIR,
    S0_CONVENTION_SIGNAL_FILE,
)

FINGERPRINT_FILE = LINKBASE_ANALYSIS_DIR / "rate_tag_fingerprint_by_accession.csv"
PRE_LABELS_FILE = LINKBASE_ANALYSIS_DIR / "dataset_pre_rate_labels.csv"
DATASET_SEM_FILE = LINKBASE_ANALYSIS_DIR / "dataset_rate_semantics.csv"

_GENERIC_RATE_LABELS = {
    "interest rate", "investment interest rate", "investment, interest rate",
    "interest rate (as a percent)",
}


def _label_status_by_cik() -> dict[int, str]:
    """Classify each CIK's PaidInCash/PaidInKind labels.

    Returns {cik: 'ok_cash' | 'contradiction' | 'no_labels'} for CIKs present
    in the dataset pre.tsv artifact; absent CIKs default to 'no_labels'.
    """
    if not (PRE_LABELS_FILE.exists() and DATASET_SEM_FILE.exists()):
        return {}
    adsh_cik: dict[str, int] = {}
    with open(DATASET_SEM_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                adsh_cik[row["adsh"]] = int(row["cik"])
            except (ValueError, KeyError):
                continue

    # cik -> {'ok': n_filings, 'bad': n_filings} over PaidInCash/PaidInKind labels
    votes: dict[int, dict] = defaultdict(lambda: {"ok": 0, "bad": 0})
    with open(PRE_LABELS_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cik = adsh_cik.get(row.get("adsh", ""))
            if cik is None:
                continue
            tag = row.get("tag", "")
            lbl = (row.get("plabel") or "").strip().lower()
            if tag == "InvestmentInterestRatePaidInCash":
                if "pik" in lbl or "paid in kind" in lbl:
                    votes[cik]["bad"] += 1        # Main Street pattern
                elif "spread" in lbl:
                    votes[cik]["bad"] += 1        # holds a spread, not a rate
                elif lbl in _GENERIC_RATE_LABELS:
                    votes[cik]["bad"] += 1        # First Eagle pattern
                elif "cash" in lbl and "cash equivalent" not in lbl:
                    votes[cik]["ok"] += 1
                elif "paid in cash" in lbl:
                    votes[cik]["ok"] += 1
                # other labels: silent (no vote)
            elif tag == "InvestmentInterestRatePaidInKind":
                if "concentration" in lbl:
                    votes[cik]["bad"] += 1        # First Eagle pattern
                elif "spread" in lbl:
                    votes[cik]["bad"] += 1

    out: dict[int, str] = {}
    for cik, v in votes.items():
        if v["bad"] > 0 and v["bad"] >= v["ok"]:
            out[cik] = "contradiction"
        elif v["ok"] > 0:
            out[cik] = "ok_cash"
        else:
            out[cik] = "no_labels"
    return out


def main() -> int:
    if not FINGERPRINT_FILE.exists():
        print(f"missing {FINGERPRINT_FILE}; run scan_rate_tag_fingerprint.py first")
        return 1

    agg: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    with open(FINGERPRINT_FILE, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                cik = int(row["cik"])
            except (ValueError, KeyError):
                continue
            for k in ("ir_won_by_bare", "ir_won_by_cash",
                      "n_ctx_bare_cash_pik", "n_sum_ok", "n_cash", "n_ctx_rate"):
                v = row.get(k) or 0
                try:
                    agg[cik][k] += int(v)
                except ValueError:
                    pass

    labels = _label_status_by_cik()

    rows = []
    for cik, a in sorted(agg.items()):
        wb = a["ir_won_by_bare"]
        wc = a["ir_won_by_cash"]
        status = labels.get(cik, "no_labels")
        s0 = s0_from_fingerprint(wb, wc, a["n_ctx_bare_cash_pik"],
                                 a["n_sum_ok"], label_status=status)
        rows.append({
            "cik": cik,
            "ir_won_by_bare": wb,
            "ir_won_by_cash": wc,
            "n_ctx_bare_cash_pik": a["n_ctx_bare_cash_pik"],
            "n_sum_ok": a["n_sum_ok"],
            "n_cash_facts": a["n_cash"],
            "label_status": status,
            "s0_vote": s0["s0_vote"] or "",
            "s0_confidence": s0["s0_confidence"] or "",
            "s0_mixed": s0["s0_mixed"],
            "s0_reason": s0["s0_reason"],
        })

    S0_CONVENTION_SIGNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(S0_CONVENTION_SIGNAL_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["cik"])
        w.writeheader()
        w.writerows(rows)

    n_vote = sum(1 for r in rows if r["s0_vote"])
    n_mixed = sum(1 for r in rows if r["s0_mixed"])
    print(f"DONE: {len(rows)} CIKs, {n_vote} S0 votes, {n_mixed} mixed flags")
    print(f"wrote {S0_CONVENTION_SIGNAL_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
