"""Score the BLIND Agent A conflict gold (value-labeled variant).

The human recorded the actual correct value in `true_value` (same displayed scale as the
candidates). We compare true_value to each candidate (numeric tol for rate fields, exact
string for dates) and attribute A vs XBRL via the sealed key. Rows with an empty/ambiguous
true_value (the source text did not state the value) are excluded and reported separately.
Read-only.
"""

from __future__ import annotations

from collections import defaultdict

from pipeline import config

_RATE_FIELDS = {"basis_spread", "interest_rate", "pik_rate"}
_TOL = 0.05


def _match(field, true_v, cand):
    if true_v is None or cand is None:
        return False
    tv, cv = str(true_v).strip(), str(cand).strip()
    if tv == "" or cv == "":
        return False
    if field in _RATE_FIELDS:
        try:
            return abs(float(tv) - float(cv)) <= _TOL
        except ValueError:
            return False
    return tv == cv  # dates: exact string


def main():
    import duckdb

    g = config.OUTPUT_DIR / "agent_a" / "gold"
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT s.review_id, s.field, s.true_value, s.candidate_1, s.candidate_2,
               k.candidate_1_source c1src, k.candidate_2_source c2src
        FROM '{g / "conflict_sample.csv"}' s
        JOIN '{g / "conflict_key.csv"}' k USING (review_id)
        ORDER BY s.review_id
        """
    ).fetchall()
    con.close()

    determinable, excluded = [], []
    for rid, field, tv, c1, c2, c1src, c2src in rows:
        tvs = (str(tv).strip().lower() if tv is not None else "")
        if tvs in ("", "none", "ambiguous", "nan"):
            excluded.append((rid, field))
            continue
        a_disp = c1 if c1src == "agentA" else c2
        x_disp = c1 if c1src == "xbrl_twin" else c2
        determinable.append((rid, field, _match(field, tv, a_disp), _match(field, tv, x_disp)))

    n = len(determinable)
    print(f"=== Agent A conflict gold -- scored ===")
    print(f"labeled & determinable: {n} of {len(rows)}  (excluded {len(excluded)}: "
          f"source did not state the value -- see note)")
    if n:
        a_ok = sum(1 for r in determinable if r[2])
        x_ok = sum(1 for r in determinable if r[3])
        both = sum(1 for r in determinable if r[2] and r[3])
        neither = sum(1 for r in determinable if not r[2] and not r[3])
        print(f"  Agent A correct:   {a_ok}/{n} = {100.0*a_ok/n:.0f}%")
        print(f"  XBRL twin correct: {x_ok}/{n} = {100.0*x_ok/n:.0f}%")
        print(f"  both correct (equal/scale-artifact, NOT a real conflict): {both}")
        print(f"  neither correct (both sources wrong): {neither}")
        bf = defaultdict(lambda: [0, 0, 0])
        for _, field, a, x in determinable:
            b = bf[field]; b[0] += 1; b[1] += a; b[2] += x
        print("\n  by datapoint:    field            n   A%   XBRL%")
        for fld, (nn, ac, xc) in sorted(bf.items()):
            print(f"    {fld:16s} {nn:>3}  {100.0*ac/nn:3.0f}  {100.0*xc/nn:4.0f}")
    if excluded:
        print(f"\n  excluded (undeterminable from source): "
              f"{', '.join(r for r, _ in excluded)}")


if __name__ == "__main__":
    main()
