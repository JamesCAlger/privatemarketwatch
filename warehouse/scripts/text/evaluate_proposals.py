"""Text slice R: compare the two proposals per column (options forward and reversed) and test them against the
evidence in the bundle. Evidence used: tag_profile (which tagged field sits in the column), legs (which printed
number equals which tagged value), legend (the filer's own code definitions). Nothing here accepts a rule.

Usage: python evaluate_proposals.py <run_dir>   (run_dir holds bundles/ and proposals/). ASCII output.
"""
import json
import sys
from collections import Counter
from pathlib import Path

run = Path(sys.argv[1])
TAG_TO_COLUMN = {"spread": {"spread", "rate_terms"}, "interest_rate": {"all_in_rate", "rate_terms"}, "interest_rate_tag": {"all_in_rate", "rate_terms"}, "interest_rate_cash_tag": {"cash_rate", "rate_terms"},
                 "interest_rate_cash": {"cash_rate", "rate_terms"}, "pik_rate": {"pik_spread_or_rate", "rate_terms"},
                 "pct_of_net_assets": {"pct_of_net_assets"}}
ROLE_TO_FIELD = {"spread_bps": ("spread", "equal_bps"), "spread_pct": ("spread", "equal"),
                 "all_in_rate_pct": ("interest_rate", "equal"), "cash_rate_pct": ("interest_rate_cash", "equal"),
                 "pik_rate_pct": ("pik_rate", "equal"), "pik_spread_pct": ("pik_rate", "equal")}
NAMES = {"sofr": "SOFR", "secured overnight financing rate": "SOFR", "euribor": "EURIBOR",
         "euro interbank offered rate": "EURIBOR", "sonia": "SONIA", "sterling overnight index average": "SONIA",
         "libor": "LIBOR", "prime": "PRIME", "corra": "CORRA", "canadian overnight repo rate average": "CORRA"}


def norm_rate(s):
    s = (s or "").strip().lower()
    for k, v in NAMES.items():
        if k in s:
            return v
    return s.upper()


tot = Counter()
print("unit\theader\trows\tcolumn_fwd\tcolumn_rev\ttag_says\tcol_check\tshapes\tshape_same\trows_same_pct\tlegs_ok\tlegs_bad\tcodes\tcode_same\tlegend_ok\tlegend_bad\tno_legend")
detail = []
for bp in sorted((run / "bundles").glob("*.json")):
    b = json.loads(bp.read_text(encoding="utf-8"))
    p = {}
    for o in ("fwd", "rev"):
        f = run / "proposals" / f"{bp.stem}_{o}.json"
        p[o] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    if not p["fwd"] or not p["rev"]:
        print(bp.stem, "MISSING PROPOSAL")
        continue
    rows = sum(s["rows"] for s in b["shapes"])
    tags = {t["field"]: t["rows"] for t in (b.get("tag_profile") or [])}
    top = max(tags, key=tags.get) if tags else None
    tag_share = tags[top] / rows if top and rows else 0
    cf_, cr_ = p["fwd"]["column_holds"], p["rev"]["column_holds"]
    if cf_ != cr_:
        col_check = "ORDERS_DIFFER"
    elif not top or tag_share < 0.5:
        col_check = "no_tag_check"
    elif cf_ in TAG_TO_COLUMN.get(top, set()):
        col_check = "tags_agree"
    else:
        col_check = "TAGS_DISAGREE"
    sf = {s["shape"]: s.get("roles", []) for s in p["fwd"].get("shapes", [])}
    sr = {s["shape"]: s.get("roles", []) for s in p["rev"].get("shapes", [])}
    same = rows_same = legs_ok = legs_bad = 0
    for s in b["shapes"]:
        k = s["shape"]
        nh = k.count("#")
        a, c = sf.get(k), sr.get(k)
        ok = a is not None and a == c and len(a) == nh
        same += ok
        rows_same += s["rows"] if ok else 0
        if not ok:
            detail.append(f"  SHAPE {bp.stem} [{b['header_text']}] '{k}' rows={s['rows']} fwd={a} rev={c}")
            continue
        for i, role in enumerate(a, 1):
            if role not in ROLE_TO_FIELD:
                continue
            fld, col = ROLE_TO_FIELD[role]
            for leg in s.get("legs") or []:
                if leg["number"] == f"n{i}" and leg["field"] == fld and leg["compared"] >= 5:
                    if leg[col] / leg["compared"] >= 0.9:
                        legs_ok += 1
                    else:
                        legs_bad += 1
                        detail.append(f"  LEGS {bp.stem} [{b['header_text']}] '{k}' n{i} role={role} {fld}: {leg[col]}/{leg['compared']}")
    codes_b = sorted({s["code"] for s in b["shapes"] if s.get("code")})
    cfw = {c["code"]: c for c in p["fwd"].get("codes", [])}
    crv = {c["code"]: c for c in p["rev"].get("codes", [])}
    legend = {}
    for e in b.get("legend") or []:
        legend.setdefault(e["code"], set()).add(norm_rate(e.get("abbreviation") or e.get("name")))
    code_same = leg_ok = leg_bad = no_leg = 0
    for code in codes_b:
        a, c = cfw.get(code), crv.get(code)
        ra, rc = norm_rate(a and a.get("reference_rate")), norm_rate(c and c.get("reference_rate"))
        if a and c and ra == rc:
            code_same += 1
        else:
            detail.append(f"  CODE {bp.stem} [{b['header_text']}] '{code}' fwd={a and a.get('reference_rate')} rev={c and c.get('reference_rate')}")
            continue
        if code in legend:
            if ra in legend[code]:
                leg_ok += 1
            else:
                leg_bad += 1
                detail.append(f"  LEGEND {bp.stem} [{b['header_text']}] '{code}' proposed={ra} legend={sorted(legend[code])}")
        else:
            no_leg += 1
            detail.append(f"  NOLEGEND {bp.stem} [{b['header_text']}] '{code}' proposed={a.get('reference_rate')} basis={a.get('basis')}")
    print("\t".join(str(x) for x in (bp.stem[:8], (b["header_text"] or "")[:28] + ("/" + b["group_header_text"][:10] if b.get("group_header_text") else ""),
                                      rows, cf_, cr_, f"{top}:{tag_share:.2f}" if top else "-", col_check, len(b["shapes"]), same,
                                      round(100 * rows_same / rows) if rows else 0, legs_ok, legs_bad, len(codes_b), code_same, leg_ok, leg_bad, no_leg)))
    tot.update(units=1, col_same=cf_ == cr_, shapes=len(b["shapes"]), shape_same=same, rows=rows, rows_same=rows_same,
               legs_ok=legs_ok, legs_bad=legs_bad, codes=len(codes_b), code_same=code_same, leg_ok=leg_ok, leg_bad=leg_bad, no_leg=no_leg)
    tot[col_check] += 1
print("TOTAL", dict(tot))
print("\n".join(detail))
