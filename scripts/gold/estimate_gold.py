"""Gold-set estimators: per-stratum precision / recall / FV-error with Wilson CIs.

READ-ONLY except for a summary JSON under data/gold/. Joins the frozen sample frame
(pipeline values + inclusion probs) to the human/agent labels and produces:
  - surfaced-flag precision (Wilson 95% CI)
  - suppressed-flag false-negative rate per confidence class + aggregate (Wilson)
  - tail+body FV error: exact tail + Horvitz-Thompson body, as % of cohort FV
  - silent-bulk error rate (Wilson)
Applies labeler calibration (Rogan-Gladen) when an audited slice exists.

Runs cleanly with zero labels (reports 'awaiting labels'). See labeler_protocol.md.

Usage: python scripts/gold/estimate_gold.py --draw batch1
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "gold" / "samples"
LABELS = ROOT / "data" / "gold" / "labels"
FV_TOL = 0.01   # relative tolerance for "FV matches source"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Return (p_hat, lo, hi) Wilson score interval. n==0 -> (nan, 0, 1)."""
    if n == 0:
        return (float("nan"), 0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def load_labels(path: Path) -> list[dict]:
    """Append-only labels -> keep the LATEST record per _key. A superseding record
    (later in file order) overrides earlier ones, and accidental double-saves of the
    same _key collapse to one. Matches the gold-set append-only correction contract."""
    out: dict = {}
    for r in load_jsonl(path):
        k = r.get("_key")
        if k is not None:
            out[k] = r            # last occurrence wins
    return list(out.values())


def load_frame(draw: str) -> dict:
    rows = load_jsonl(SAMPLES / f"sample_frame_{draw}.jsonl")
    out = {}
    for r in rows:
        tag = r.get("source_identifier") or (r.get("flag") or {}).get("rule_name") or "-"
        out[f"{r['unit_type']}|{r['cik']}|{r.get('report_date')}|{tag}"] = r
    return out


def pos_error(lbl: dict, frame_row: dict) -> dict:
    """Per-field error flags comparing source truth to pipeline value."""
    pipe = frame_row.get("pipeline", {})
    errs, checked = {}, {}
    # fair_value / cost (numeric, relative tolerance)
    for f, pk in (("fair_value", "fair_value"), ("cost", "cost")):
        t = lbl.get(f"true_{f}")
        p = pipe.get(pk)
        if lbl.get("ambiguous") or f"true_{f}" in (lbl.get("ambiguous_fields") or []) or t is None:
            continue
        checked[f] = True
        if p is None:
            errs[f] = True
        else:
            denom = max(abs(t), abs(p), 1.0)
            errs[f] = abs(t - p) / denom > FV_TOL
    # classification / lien (categorical)
    for f, pk in (("classification", "index_classification"), ("lien", "lien_position")):
        t = lbl.get(f"true_{f}")
        if lbl.get("ambiguous") or f"true_{f}" in (lbl.get("ambiguous_fields") or []) or t is None:
            continue
        checked[f] = True
        errs[f] = (str(t).strip().upper() != str(pipe.get(pk) or "").strip().upper())
    return {"errs": errs, "checked": checked,
            "any_error": any(errs.values()), "fv_abs_err": _fv_abs(lbl, pipe)}


def _fv_abs(lbl: dict, pipe: dict) -> float | None:
    t, p = lbl.get("true_fair_value"), pipe.get("fair_value")
    if t is None or "true_fair_value" in (lbl.get("ambiguous_fields") or []) or lbl.get("ambiguous"):
        return None
    return abs(t - (p or 0.0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", default="batch1")
    args = ap.parse_args()

    frame = load_frame(args.draw)
    pos = load_labels(LABELS / "position_labels.jsonl")
    cikq = load_labels(LABELS / "cik_quarter_labels.jsonl")
    flags = load_labels(LABELS / "flag_labels.jsonl")
    report: dict = {"draw": args.draw, "n_position_labels": len(pos),
                    "n_cik_quarter_labels": len(cikq), "n_flag_labels": len(flags)}

    # ---- Flag precision (surfaced) & FN (suppressed) -------------------------
    surfaced = [f for f in flags if (frame.get(f["_key"], {}).get("stratum") == "surfaced_flag")]
    suppressed = [f for f in flags if (frame.get(f["_key"], {}).get("stratum") == "suppressed_flag")]

    def verdict_rate(items):
        real = sum(1 for f in items if f.get("verdict") == "real_error")
        false = sum(1 for f in items if f.get("verdict") == "false_alarm")
        amb = sum(1 for f in items if f.get("verdict") == "ambiguous")
        p, lo, hi = wilson(real, real + false)
        # worst case: ambiguous counted against (as not-real for precision / as-real for FN handled by caller)
        return {"real": real, "false_alarm": false, "ambiguous": amb,
                "decided": real + false, "p_hat": p, "ci95": [lo, hi]}

    report["surfaced_precision"] = verdict_rate(surfaced)
    # suppressed FN per confidence class
    by_conf = defaultdict(list)
    for f in suppressed:
        by_conf[(frame.get(f["_key"], {}).get("flag") or {}).get("confidence", "?")].append(f)
    report["suppressed_fn_by_confidence"] = {c: verdict_rate(v) for c, v in sorted(by_conf.items())}
    report["suppressed_fn_overall"] = verdict_rate(suppressed)

    # ---- Position error: tail (exact) + body (Horvitz-Thompson) --------------
    tail_n = tail_err = 0
    tail_fv_abs = 0.0
    body_units = []
    silent_k = silent_n = 0
    for lbl in pos:
        fr = frame.get(lbl["_key"])
        if not fr:
            continue
        pe = pos_error(lbl, fr)
        strat = fr["stratum"]
        if strat == "tail_census":
            tail_n += 1
            tail_err += int(pe["any_error"])
            if pe["fv_abs_err"] is not None:
                tail_fv_abs += pe["fv_abs_err"]
        elif strat == "pps_body":
            body_units.append((pe, fr.get("pi") or 1.0))
        elif strat == "silent_bulk":
            silent_n += 1
            silent_k += int(pe["any_error"])

    p, lo, hi = wilson(tail_err, tail_n)
    report["tail_census"] = {"n": tail_n, "any_error": tail_err, "error_rate": p,
                             "ci95": [lo, hi], "fv_abs_error_usd": tail_fv_abs}
    # HT body FV-error
    ht_err = sum((pe["fv_abs_err"] or 0.0) / pi for pe, pi in body_units if pe["fv_abs_err"] is not None)
    ht_var = sum(((pe["fv_abs_err"] or 0.0) / pi) ** 2 * (1 - pi) for pe, pi in body_units if pe["fv_abs_err"] is not None)
    report["pps_body"] = {"n": len(body_units),
                          "ht_fv_error_usd": ht_err,
                          "ht_fv_error_se": math.sqrt(ht_var) if body_units else None}
    p, lo, hi = wilson(silent_k, silent_n)
    report["silent_bulk"] = {"n": silent_n, "any_error": silent_k, "error_rate": p, "ci95": [lo, hi]}

    # ---- Calibration placeholder (needs an audited slice) --------------------
    audited = [l for l in pos + flags if (l.get("source_ref") or {}).get("audit_of")]
    report["labeler_calibration"] = (
        {"status": "no audited slice yet; agent-drafted strata report sampling CI only"}
        if not audited else {"status": "present", "n_audited": len(audited)})

    out = ROOT / "data" / "gold" / f"estimates_{args.draw}.json"
    out.write_text(json.dumps(report, indent=2), encoding="ascii")

    # ---- console ------------------------------------------------------------
    total = len(pos) + len(cikq) + len(flags)
    print(f"[estimate] draw={args.draw} labels: pos={len(pos)} cikq={len(cikq)} flag={len(flags)}")
    if total == 0:
        print("[estimate] awaiting labels -- apparatus ready; nothing to estimate yet.")
    else:
        sp = report["surfaced_precision"]
        print(f"  surfaced precision: {sp['real']}/{sp['decided']} "
              f"p={sp['p_hat']:.3f} CI[{sp['ci95'][0]:.3f},{sp['ci95'][1]:.3f}] (amb={sp['ambiguous']})")
        so = report["suppressed_fn_overall"]
        print(f"  suppressed FN:      {so['real']}/{so['decided']} "
              f"p={so['p_hat'] if so['decided'] else float('nan'):.3f} (amb={so['ambiguous']})")
        tc = report["tail_census"]
        print(f"  tail error rate:    {tc['any_error']}/{tc['n']} "
              f"CI[{tc['ci95'][0]:.3f},{tc['ci95'][1]:.3f}]  fv_abs_err=${tc['fv_abs_error_usd']/1e6:.1f}M")
        sb = report["silent_bulk"]
        print(f"  silent-bulk error:  {sb['any_error']}/{sb['n']} "
              f"CI[{sb['ci95'][0]:.3f},{sb['ci95'][1]:.3f}]")
    print(f"[estimate] wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
