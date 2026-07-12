"""Agent A -- small BLIND gold sample over the P3 staged conflicts.

The conflicts are rows where A's parse disagrees with the structured XBRL twin. The
human reads the raw identifier (the source) and records the TRUE value, BLIND to which
candidate is A vs XBRL (the two values are relabeled candidate_1/candidate_2 with a
hidden key). Scoring then yields: A precision on conflicts AND the XBRL-twin error rate.

Kept deliberately small (~2 rows per non-trivial (cik, field) stratum, FV-weighted) --
the user runs several gold sets concurrently. Read-only; writes only NEW gold files.
"""

from __future__ import annotations

import csv

from pipeline import config

_NAMES = {
    "0001993402": "Antares Strategic Credit Fund",
    "0001278752": "MidCap Financial Investment Corp",
    "0001655050": "Bain Capital Specialty Finance",
    "0001633336": "Crescent Capital BDC",
}
MIN_STRATUM = 5     # skip trivial strata (<5 conflicts)
PER_STRATUM = 2     # rows sampled per (cik, field)
_RATE_FIELDS = {"basis_spread", "interest_rate", "pik_rate"}


def _display(fieldname, raw):
    """Normalize to a common scale so format does not telegraph the source.
    Production rate twins are decimals (0.0535); A parses percent (5.25). Show both as
    percent. A production twin already on percent scale (a known MidCap scale bug) will
    show as ~10x and reveal itself."""
    if fieldname in _RATE_FIELDS:
        try:
            return round(float(raw) * 100.0, 4) if abs(float(raw)) < 1.0 else round(float(raw), 4)
        except (TypeError, ValueError):
            return raw
    return raw


def main():
    import duckdb

    src = str(config.OUTPUT_DIR / "agent_a" / "p3_staged_conflicts.csv")
    con = duckdb.connect()
    # strata with enough conflicts to matter
    strata = con.execute(
        f"SELECT cik, field, count(*) n FROM '{src}' GROUP BY 1,2 HAVING count(*) >= {MIN_STRATUM} "
        f"ORDER BY field, cik"
    ).fetchall()

    sample, key = [], []
    rid = 0
    for cik, fieldname, n in strata:
        rows = con.execute(
            f"SELECT report_date, production_value, agentA_value, fair_value, identifier "
            f"FROM '{src}' WHERE cik = '{cik}' AND field = '{fieldname}' "
            f"ORDER BY fair_value DESC LIMIT {PER_STRATUM}"
        ).fetchall()
        for i, (rd, prod, a_val, fv, ident) in enumerate(rows):
            rid += 1
            review_id = f"A{rid:03d}"
            # normalize to a common scale so format does not reveal the source
            a_disp, prod_disp = _display(fieldname, a_val), _display(fieldname, prod)
            # blind relabel: alternate which source is candidate_1 (deterministic by rid)
            a_first = (rid % 2 == 0)
            c1, c2 = (a_disp, prod_disp) if a_first else (prod_disp, a_disp)
            sample.append({
                "review_id": review_id, "field": fieldname, "entity_name": _NAMES.get(cik, cik),
                "report_date": rd, "fair_value": round(fv or 0),
                "candidate_1": c1, "candidate_2": c2,
                "identifier_source": ident,
                "true_value": "", "true_source": "", "note": "",
            })
            key.append({
                "review_id": review_id, "cik": cik, "field": fieldname,
                "candidate_1_source": "agentA" if a_first else "xbrl_twin",
                "candidate_2_source": "xbrl_twin" if a_first else "agentA",
                "agentA_value": a_val, "xbrl_twin_value": prod,
            })
    con.close()

    out = config.OUTPUT_DIR / "agent_a" / "gold"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "conflict_sample.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(sample[0].keys())); w.writeheader(); w.writerows(sample)
    with open(out / "conflict_key.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0].keys())); w.writeheader(); w.writerows(key)
    with open(out / "REVIEW_GUIDE.md", "w", encoding="utf-8") as f:
        f.write(
            "# Agent A conflict gold review (BLIND)\n\n"
            f"{len(sample)} rows where A's parse disagrees with the structured XBRL twin.\n\n"
            "For each row: read `identifier_source` (the filer's raw text). Decide the TRUE\n"
            "value for `field` from that text. Fill:\n"
            "- `true_value`: the correct value (a percent like 7.00, or ISO date), or `ambiguous`.\n"
            "- `true_source`: `candidate_1`, `candidate_2`, `both`, or `neither`.\n"
            "- `note`: optional.\n\n"
            "You are BLIND to which candidate is A vs XBRL (relabeled; key sealed in\n"
            "conflict_key.csv -- do not open while labeling). Judge only from the source text.\n"
            "Scoring (after labeling) reveals A precision AND the XBRL-twin error rate.\n"
        )
    print(f"Wrote {len(sample)} blind gold rows over {len(strata)} strata -> {out}")
    print("  conflict_sample.csv (label this, blind), conflict_key.csv (SEALED), REVIEW_GUIDE.md")


if __name__ == "__main__":
    main()
