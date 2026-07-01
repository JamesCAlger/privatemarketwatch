"""Agent A / P3 (STAGED) -- provenance-tagged overlay + impact diff.

Computes what A's parsed fields WOULD change if merged into the BDC staging layer,
WITHOUT merging. The merge rule is blank-only / no-clobber (mirroring the existing
iXBRL + HTML-bridge overlays in staging_bdc.py):

  - production field BLANK + A has a value      -> FILL      (the coverage lift)
  - production field PRESENT + A agrees          -> CONFIRM   (corroboration)
  - production field PRESENT + A disagrees        -> CONFLICT  (FLAG, never overwrite)
  - production field BLANK + A blank              -> (skip)

CONFLICT rows are the finding population (e.g. MidCap's mis-binned basis_spread); they
are routed to a flag artifact, never written over. This module is READ-ONLY on production
and writes only NEW artifacts under data/output/agent_a/. It does NOT merge.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

from pipeline import config
from pipeline.identifier_rate import apply_grammar, load_grammar, normalize_rate_pct
from pipeline.identifier_signature import keyword_signature, load_anchors
from pipeline.sofr_reference import adjudicate_spread, reconcile_residual, sofr_for


def _spread_reconcile(rd, p_int, p_pik, p_floor, a_spread, xbrl_spread):
    """Adjudicate a basis_spread conflict via spread + SOFR ~= all-in (XBRL all-in trusted)."""
    all_in = normalize_rate_pct(p_int)
    cash = None if all_in is None else round(all_in - (normalize_rate_pct(p_pik) or 0.0), 4)
    floor = normalize_rate_pct(p_floor)
    sofr = sofr_for(rd)
    xbrl_pct = normalize_rate_pct(xbrl_spread)
    return {
        "sofr_pct": sofr,
        "cash_all_in_pct": cash,
        "a_residual": reconcile_residual(cash, a_spread, floor, sofr),
        "xbrl_residual": reconcile_residual(cash, xbrl_pct, floor, sofr),
        "reconcile_verdict": adjudicate_spread(cash, a_spread, xbrl_pct, floor, sofr),
    }

# production bdc_holdings column -> (A parsed field, comparison kind)
_FIELD_MAP = {
    "reference_rate_type": ("reference_rate_type", "str"),
    "basis_spread": ("basis_spread", "pct_dec"),
    "interest_rate": ("interest_rate_all_in", "pct_dec"),
    "pik_rate": ("pik_rate", "pct_dec"),
    "maturity_date": ("maturity_date", "date"),
}
# fields A contributes that have NO production column (pure additions)
_CONTRIB_FIELDS = ["coupon_type", "interest_rate_cash_leg"]

_TOL = 0.05


def _prod_blank(v, kind):
    if v is None:
        return True
    if kind == "pct_dec":
        try:
            return float(v) == 0.0
        except (TypeError, ValueError):
            return True  # unparseable string (e.g. "1M SOFR + 6.00%") -> numerically blank
    s = str(v).strip()
    return s == "" or s.lower() in ("none", "nan")


def _agree(prod, a_val, kind):
    if kind == "pct_dec":
        # normalize ONLY the prod twin to percent (it may be decimal OR percent-scale);
        # A's value is already percent (and may legitimately be <1, so must NOT be scaled).
        np = normalize_rate_pct(prod)
        try:
            return np is not None and abs(np - float(a_val)) <= _TOL
        except (TypeError, ValueError):
            return False
    if kind == "date":
        return str(prod)[:10] == str(a_val)[:10]
    return str(prod).strip().upper() == str(a_val).strip().upper()


@dataclass
class FieldImpact:
    fill: int = 0
    confirm: int = 0
    conflict: int = 0
    not_mergeable: int = 0      # A has a value but in a format incompatible with the prod column
    fill_fv: float = 0.0
    conflict_fv: float = 0.0
    not_mergeable_fv: float = 0.0


@dataclass
class OverlayImpact:
    cik: str
    signature: str
    n_rows: int = 0
    fields: dict = field(default_factory=dict)
    contrib: dict = field(default_factory=dict)   # contributed field -> count
    contrib_fv: dict = field(default_factory=dict)
    conflict_rows: list = field(default_factory=list)


def stage_overlay(cik: str, signature: str, parquet_path: str) -> OverlayImpact:
    import duckdb

    grammar = load_grammar(cik)
    anchors = load_anchors(cik)
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT CAST(investment_identifier AS VARCHAR) ident,
               CAST(report_date AS VARCHAR) rd,
               TRY_CAST(fair_value AS DOUBLE) fv,
               CAST(reference_rate_type AS VARCHAR) p_ref,
               TRY_CAST(basis_spread AS DOUBLE) p_spread,
               TRY_CAST(interest_rate AS DOUBLE) p_int,
               TRY_CAST(pik_rate AS DOUBLE) p_pik,
               CAST(maturity_date AS VARCHAR) p_mat,
               TRY_CAST(interest_rate_floor AS DOUBLE) p_floor
        FROM '{parquet_path}'
        WHERE CAST(cik AS VARCHAR) = '{cik}'
          AND investment_identifier IS NOT NULL
          AND CAST(period AS VARCHAR) = CAST(report_date AS VARCHAR)
        """
    ).fetchall()
    con.close()

    imp = OverlayImpact(cik=cik, signature=signature)
    for col in _FIELD_MAP:
        imp.fields[col] = FieldImpact()
    for cf in _CONTRIB_FIELDS:
        imp.contrib[cf] = 0
        imp.contrib_fv[cf] = 0.0

    prod_index = {"reference_rate_type": 3, "basis_spread": 4, "interest_rate": 5,
                  "pik_rate": 6, "maturity_date": 7}

    for r in rows:
        ident, rd, fv = r[0], r[1], r[2] or 0.0
        if keyword_signature(ident, anchors) != signature:
            continue
        imp.n_rows += 1
        parsed = apply_grammar(ident, grammar)

        for col, (a_field, kind) in _FIELD_MAP.items():
            a_val = parsed.get(a_field)
            prod = r[prod_index[col]]
            fi = imp.fields[col]
            if a_val is None:
                continue
            # date column requires an ISO value; mm/yyyy text (e.g. Crescent) is NOT
            # mergeable into maturity_date -> bucket separately, never fill/conflict.
            if kind == "date" and not _ISO_DATE_RE.match(str(a_val)):
                fi.not_mergeable += 1
                fi.not_mergeable_fv += fv
                continue
            if _prod_blank(prod, kind):
                fi.fill += 1
                fi.fill_fv += fv
            elif _agree(prod, a_val, kind):
                fi.confirm += 1
            else:
                fi.conflict += 1
                fi.conflict_fv += fv
                if len(imp.conflict_rows) < 500:
                    crow = {
                        "cik": cik, "report_date": rd, "field": col,
                        "production_value": prod, "agentA_value": a_val,
                        "fair_value": round(fv, 0),
                        # FULL identifier -- the rate segment sits at the end of flattened
                        # strings; truncating (was 160) hid the evidence the gold needs.
                        "identifier": ident,
                    }
                    # spread conflicts: adjudicate via spread + SOFR ~= all-in (SOFR proxy)
                    if col == "basis_spread":
                        crow.update(_spread_reconcile(rd, r[5], r[6], r[8], a_val, prod))
                    imp.conflict_rows.append(crow)
        for cf in _CONTRIB_FIELDS:
            if parsed.get(cf) is not None:
                imp.contrib[cf] += 1
                imp.contrib_fv[cf] += fv
    return imp


def print_impact(imp: OverlayImpact, log=print):
    log(f"--- {imp.cik}  (sig: {imp.signature})  rows={imp.n_rows:,} ---")
    log("  field                fill   confirm  conflict  not_merge   fill_FV($M)  conflict_FV($M)")
    for col, fi in imp.fields.items():
        log(f"  {col:18s} {fi.fill:>6} {fi.confirm:>8} {fi.conflict:>8} {fi.not_mergeable:>8}    "
            f"{fi.fill_fv/1e6:>10.0f}     {fi.conflict_fv/1e6:>10.0f}")
    for cf in _CONTRIB_FIELDS:
        log(f"  +{cf:17s} contributed on {imp.contrib[cf]:>6} rows "
            f"(${imp.contrib_fv[cf]/1e6:,.0f}M)")


def main():  # pragma: no cover
    parquet = str(config.OUTPUT_DIR / "bdc_holdings.parquet")
    targets = [
        ("0001993402", "AFFIL SECDEBT ASSETTYPE REFRATE RATE MAT"),
        ("0001278752", "SECDEBT REFRATE RATE MAT"),
        ("0001655050", "AFFIL SECLOAN REFRATE RATE MAT"),
        ("0001633336", "DEBT INVTYPE REFRATE RATE MAT"),
    ]
    out_dir = config.OUTPUT_DIR / "agent_a"
    out_dir.mkdir(exist_ok=True)
    all_conflicts = []
    summary_rows = []
    tot = {"rows": 0, "ref_fill": 0, "ref_fill_fv": 0.0, "mat_fill": 0, "conflict": 0}
    print("=== Agent A P3 STAGED impact (NO MERGE) ===")
    for cik, sig in targets:
        imp = stage_overlay(cik, sig, parquet)
        print_impact(imp)
        all_conflicts.extend(imp.conflict_rows)
        tot["rows"] += imp.n_rows
        tot["ref_fill"] += imp.fields["reference_rate_type"].fill
        tot["ref_fill_fv"] += imp.fields["reference_rate_type"].fill_fv
        tot["mat_fill"] += imp.fields["maturity_date"].fill
        tot["conflict"] += sum(f.conflict for f in imp.fields.values())
        for col, fi in imp.fields.items():
            summary_rows.append({"cik": cik, "signature": sig, "field": col,
                                 "rows": imp.n_rows, "fill": fi.fill, "confirm": fi.confirm,
                                 "conflict": fi.conflict, "not_mergeable": fi.not_mergeable,
                                 "fill_fv": round(fi.fill_fv), "conflict_fv": round(fi.conflict_fv)})

    # write staged artifacts (NEW files only; nothing in production touched)
    with open(out_dir / "p3_staged_impact_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys())); w.writeheader(); w.writerows(summary_rows)
    if all_conflicts:
        # union of keys (spread conflicts carry extra reconciliation columns)
        fieldnames = list(dict.fromkeys(k for row in all_conflicts for k in row))
        with open(out_dir / "p3_staged_conflicts.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, restval="")
            w.writeheader(); w.writerows(all_conflicts)
    # spread-conflict adjudication tally
    sp = [c for c in all_conflicts if c["field"] == "basis_spread" and "reconcile_verdict" in c]
    from collections import Counter
    verdicts = Counter(c["reconcile_verdict"] for c in sp)
    print(f"\nTOTAL over 4 gated filers: {tot['rows']:,} rows")
    print(f"  reference_rate_type FILL: {tot['ref_fill']:,} rows (${tot['ref_fill_fv']/1e9:.1f}B) -- native ~0%")
    print(f"  maturity_date FILL:       {tot['mat_fill']:,} rows")
    print(f"  total CONFLICTs (flagged, NOT overwritten): {tot['conflict']:,}")
    print(f"  basis_spread conflicts adjudicated by spread+SOFR=all-in: {dict(verdicts)}")
    print("Staged artifacts: agent_a/p3_staged_impact_summary.csv, p3_staged_conflicts.csv")
    print("NO MERGE performed; production bdc_holdings/unified untouched.")


if __name__ == "__main__":  # pragma: no cover
    main()
