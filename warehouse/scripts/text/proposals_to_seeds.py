"""Text slice R phase 2: turn the agent's PROPOSED rules of one run into three warehouse seeds.

The seeds hold proposals, not rules. Nothing downstream may publish from them; the dbt models that read them measure
them against checks (int_text_rate_proposed, int_text_check_*, int_text_proposal_verdict).

Usage: python proposals_to_seeds.py <run_dir> <seeds_dir>
  run_dir    a run folder of text_runs/ holding proposals/<unit_key>_{fwd,rev}.json (scripts/text/propose_rules.py)
  seeds_dir  where to write text_proposed_column.csv, text_proposed_shape_role.csv, text_proposed_code.csv

Standard library only. Deterministic: rows sorted, LF line ends, no time stamp. run_id = the run folder's name.

text_proposed_column      one row per unit: column_holds in each order, same_in_both_orders.
text_proposed_shape_role  one row per (unit, shape, number_index): the role of the k-th number in each order. A shape
                          with no number in both orders gets one row with number_index 0 and empty roles. Two role lists
                          of different length make every row of the shape "not same". roles_fit_shape: both lists hold
                          exactly as many roles as the shape has '#'. A shape answered in one order only is "not same".
text_proposed_code        one row per (unit, code): the reference rate named in each order, rate_name_fwd/_rev (the name
                          normalised to the rate_name vocabulary of seed base_rate_series plus CDOR and BBSY, empty when
                          it maps to none; CDOR, CORRA, BBSY and BBSW stay four names),
                          rate_name (the agreed name when both orders give the same normalised name, else empty),
                          rate_name_note (CDOR and BBSY: the level check uses the CORRA and BBSW proxy series), basis in
                          each order, same_in_both_orders (normalised names compared; two unmapped names are compared as
                          upper-cased text, so "NIBOR" and "Norwegian Interbank Offered Rate" are the same).
"""
import csv
import json
import sys
from pathlib import Path

# Normalisation, first match wins (upper-cased text searched for each needle). CDOR, CORRA, BBSY and BBSW are four
# rates (fix round 1): the shared proxy series is a matter for the level check only. Order matters: CDOR and BBSY are
# tested before CORRA and BBSW ("Bank Bill Swap Bid" would otherwise match the BBSW needle "Bank Bill
# Swap"); Canadian prime is tested before PRIME (not the US prime rate: no series).
NAME_RULES = [
    (("CANADIAN PRIME", "CAD PRIME", "CAD BASE RATE", "CANADIAN BASE"), "", "Canadian prime: no series"),
    (("CDOR", "CANADIAN DOLLAR OFFERED"), "CDOR", "the level check uses the CORRA proxy series"),
    (("CORRA", "CANADIAN OVERNIGHT REPO"), "CORRA", ""),
    (("BBSY", "BANK BILL SWAP BID"), "BBSY", "the level check uses the BBSW proxy series"),
    (("BBSW", "BANK BILL SWAP"), "BBSW", ""),
    (("BKBM", "BANK BILL BENCHMARK", "NEW ZEALAND BANK BILL"), "BKBM", ""),
    (("SOFR", "SECURED OVERNIGHT FINANCING"), "SOFR", ""),
    (("SONIA", "STERLING OVERNIGHT"), "SONIA", ""),
    (("EURIBOR", "EURO INTERBANK"), "EURIBOR", ""),
    (("STIBOR", "STOCKHOLM INTERBANK"), "STIBOR", ""),
    (("SARON", "SWISS AVERAGE RATE OVERNIGHT"), "SARON", ""),
    (("NIBOR", "NORWEGIAN INTERBANK"), "NIBOR", ""),
    (("TONAR", "TONA", "TOKYO OVERNIGHT"), "TONA", ""),
    (("KORIBOR", "KOREA INTERBANK", "KOREAN INTERBANK"), "KORIBOR", ""),
    (("FEDERAL FUNDS", "FED FUNDS", "FEDFUNDS"), "FEDFUNDS", ""),
    (("LIBOR", "LONDON INTERBANK"), "LIBOR", ""),
    (("PRIME",), "PRIME", ""),
]


def norm_name(raw):
    s = (raw or "").strip().upper()
    if not s:
        return "", ""
    for needles, name, note in NAME_RULES:
        if any(n in s for n in needles):
            return name, note
    return "", ""


def compare_key(raw):
    """The key two answers are compared on: the matching rule (so "CAD Base Rate (Canadian prime)" and "Canadian
    base rate (CAD prime)" are one), else the upper-cased text."""
    s = (raw or "").strip().upper()
    for i, (needles, name, _note) in enumerate(NAME_RULES):
        if any(n in s for n in needles):
            return name or f"rule{i}"
    return s


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


run_dir, seeds_dir = Path(sys.argv[1]), Path(sys.argv[2])
run_id = run_dir.name
units = sorted({p.stem.rsplit("_", 1)[0] for p in (run_dir / "proposals").glob("*_*.json")})
col_rows, shape_rows, code_rows = [], [], []
for unit in units:
    fwd = load(run_dir / "proposals" / f"{unit}_fwd.json") or {}
    rev = load(run_dir / "proposals" / f"{unit}_rev.json") or {}
    cf, cr = fwd.get("column_holds") or "", rev.get("column_holds") or ""
    col_rows.append([run_id, unit, cf, cr, str(bool(cf) and cf == cr).lower()])

    sf = {s["shape"]: list(s.get("roles") or []) for s in fwd.get("shapes") or []}
    sr = {s["shape"]: list(s.get("roles") or []) for s in rev.get("shapes") or []}
    for shape in sorted(set(sf) | set(sr)):
        a, b = sf.get(shape), sr.get(shape)
        n_hash = shape.count("#")
        both = a is not None and b is not None
        same_len = both and len(a) == len(b)
        fit = both and len(a) == n_hash and len(b) == n_hash
        width = max(len(a or []), len(b or []))
        if width == 0:
            shape_rows.append([run_id, unit, shape, 0, "", "", str(both).lower(), str(fit).lower()])
            continue
        for k in range(1, width + 1):
            ra = a[k - 1] if a is not None and k <= len(a) else ""
            rb = b[k - 1] if b is not None and k <= len(b) else ""
            same = same_len and ra == rb
            shape_rows.append([run_id, unit, shape, k, ra, rb, str(same).lower(), str(fit).lower()])

    cfm = {c["code"]: c for c in fwd.get("codes") or []}
    crm = {c["code"]: c for c in rev.get("codes") or []}
    for code in sorted(set(cfm) | set(crm)):
        a, b = cfm.get(code), crm.get(code)
        ra = (a or {}).get("reference_rate") or ""
        rb = (b or {}).get("reference_rate") or ""
        na, note_a = norm_name(ra)
        nb, note_b = norm_name(rb)
        same = a is not None and b is not None and compare_key(ra) == compare_key(rb)
        agreed = na if same else ""
        note = (note_a or note_b) if same else ""
        code_rows.append([run_id, unit, code, ra, rb, na, nb, agreed, note,
                          (a or {}).get("basis") or "", (b or {}).get("basis") or "", str(same).lower()])


def write(name, header, rows):
    rows = sorted(rows, key=lambda r: [str(x) if not isinstance(x, int) else f"{x:06d}" for x in r])
    with open(seeds_dir / name, "w", newline="\n", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


write("text_proposed_column.csv",
      ["run_id", "unit_key", "column_holds_fwd", "column_holds_rev", "same_in_both_orders"], col_rows)
write("text_proposed_shape_role.csv",
      ["run_id", "unit_key", "shape", "number_index", "role_fwd", "role_rev", "same_in_both_orders",
       "roles_fit_shape"], shape_rows)
write("text_proposed_code.csv",
      ["run_id", "unit_key", "code", "reference_rate_fwd", "reference_rate_rev", "rate_name_fwd", "rate_name_rev",
       "rate_name", "rate_name_note", "basis_fwd", "basis_rev", "same_in_both_orders"], code_rows)
