"""Deterministic anchor-scored diagnosis battery for conservation overshoot (Agent B2, no LLM).

Given a CIK's gate-counted holdings frame and an INDEPENDENT anchor (the filer's own
schedule/fund total), run a fixed battery of structural probes. Each probe proposes a
row-set to remove and is SCORED only by whether removing it moves ``value_sum`` toward the
anchor. The agent cannot game this: the score is the filer's own number, not the agent's.

This replaces a GUESSED B1 ``mechanism`` on Stage-3 symptom flags (e.g. ``fv_conservation``)
with a MEASURED decomposition -- which deterministic mechanism(s) actually close the
residual, by how much, and how much residual remains UNEXPLAINED (-> escalate to a human /
wrapper investigation, never fabricate a fix). It is the "Option 3" diagnosis step: the
discovery I can do by hand with arbitrary anchor-scored queries, encoded as a fixed battery.

Pure over an in-memory frame (one CIK x report_date is small). No network, no LLM, ASCII only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

import pandas as pd

# Rows the conservation gate actually sums (see scripts/shadow_conservation_engine.py:run_rule).
GATE_FILTER = "bdc_dimensions_raw"          # summed only where this is non-null
VALUE_COL = "fair_value"
DETAIL_COLS = ["interest_rate", "maturity_date", "principal_amount", "shares_held", "cusip"]
DEFAULT_TOL = 0.01                           # reconcile within 1% of the anchor (gate tight tier)
_LABEL_AGG_RE = re.compile(r"\b(?:sub\s*total|total\s+investments|net\s+assets)\b", re.I)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _gate_rows(df: pd.DataFrame) -> pd.Series:
    """Boolean mask of rows the conservation value_sum includes. is_subsidiary=1
    look-through rows are excluded (retain-and-flag, 2026-08-29): the consolidated
    anchor already contains them once, so summing them again double-counts."""
    keep = df[GATE_FILTER].notna() if GATE_FILTER in df.columns else pd.Series(True, index=df.index)
    if "is_subsidiary" in df.columns:
        keep = keep & (pd.to_numeric(df["is_subsidiary"], errors="coerce").fillna(0) != 1)
    return keep


def value_sum(df: pd.DataFrame, drop: pd.Series | None = None) -> float:
    """Gate-equivalent value_sum, optionally after removing ``drop`` rows."""
    keep = _gate_rows(df)
    if drop is not None:
        keep = keep & ~drop
    return float(_num(df.loc[keep, VALUE_COL]).fillna(0).sum())


def _has_detail(df: pd.DataFrame) -> pd.Series:
    """True where a row carries instrument-level detail (i.e. it is a real position, not an
    aggregate). Aggregates/rollups carry a fair_value but no rate/maturity/principal/shares."""
    present = pd.Series(False, index=df.index)
    for c in DETAIL_COLS:
        if c in df.columns:
            col = df[c]
            nonempty = col.notna() & (col.astype(str).str.strip() != "")
            if c in ("principal_amount", "shares_held"):
                nonempty = nonempty & (_num(col).fillna(0) != 0)
            present = present | nonempty
    return present


# ---- probes ---------------------------------------------------------------------------
# Each probe returns a removal MASK (over all rows; non-gate rows are ignored by value_sum)
# plus the constrained correction TEMPLATE that would implement the same removal downstream.

@dataclass
class ProbeResult:
    name: str
    fix_class: str
    template: dict
    removed_mask: pd.Series = field(repr=False)
    note: str = ""


def probe_exact_dedup(df: pd.DataFrame) -> ProbeResult | None:
    """True repeated rows on an identity key (keep first). Catches multi-tag dimension
    duplicates that survived staging dedup. Tries keys most-specific first; reports the
    first that removes anything."""
    keys = [
        ["issuer_name", "instrument_description", "fair_value", "report_date"],
        ["bdc_investment_identifier", "fair_value", "report_date"],
        ["issuer_name", "instrument_description", "report_date"],
    ]
    g = _gate_rows(df)
    for key in keys:
        if not all(k in df.columns for k in key):
            continue
        sub = df[g]
        dup = sub.duplicated(subset=key, keep="first")
        mask = pd.Series(False, index=df.index)
        mask.loc[sub.index] = dup
        if mask.any():
            return ProbeResult("exact_dedup", "dedup",
                               {"fix_class": "dedup", "match_fields": key, "keep": "first"},
                               mask, f"key={key}")
    # Report a null result (0 removed) on the most specific available key for transparency.
    return ProbeResult("exact_dedup", "dedup",
                       {"fix_class": "dedup", "match_fields": keys[0], "keep": "first"},
                       pd.Series(False, index=df.index), "no exact duplicates")


def probe_label_aggregate(df: pd.DataFrame) -> ProbeResult | None:
    """Rows whose identifier/issuer label is a textual aggregate (Sub Total / Total
    Investments / Net Assets). This is what the existing subtotal_filter expresses."""
    g = _gate_rows(df)
    text = pd.Series("", index=df.index)
    for c in ("bdc_investment_identifier", "issuer_name", "instrument_description"):
        if c in df.columns:
            text = text.str.cat(df[c].fillna("").astype(str), sep=" | ")
    mask = g & text.str.contains(_LABEL_AGG_RE)
    return ProbeResult("label_aggregate", "subtotal_filter",
                       {"fix_class": "subtotal_filter", "patterns": ["sub total", "total investments"],
                        "match_mode": "contains"},
                       mask, "textual total/sub-total labels")


def probe_no_detail_aggregate(df: pd.DataFrame) -> ProbeResult | None:
    """Rows that carry a fair_value but NO instrument detail -> nested category/industry
    rollups masquerading as positions. Filer-agnostic structural signal (the one that
    cleanly isolates this CIK's industry-rollup leak)."""
    g = _gate_rows(df)
    fv_present = _num(df[VALUE_COL]).fillna(0) != 0
    mask = g & fv_present & ~_has_detail(df)
    return ProbeResult("no_detail_aggregate", "aggregate_row_filter",
                       {"fix_class": "aggregate_row_filter", "predicate": "no_instrument_detail"},
                       mask, "fair_value present, no rate/maturity/principal/shares/cusip")


def probe_dimension_rollup(df: pd.DataFrame) -> ProbeResult | None:
    """A row whose fair_value equals (within tol) the sum of OTHER gate rows whose identifier
    EXTENDS its own (parent-prefix). Detects nested subtotals even when they carry a stray
    detail field. Heuristic; the over-deletion guard in compose() bounds any false positive."""
    col = "bdc_investment_identifier"
    if col not in df.columns:
        return None
    g = _gate_rows(df)
    sub = df[g].copy()
    sub["_fv"] = _num(sub[VALUE_COL]).fillna(0)
    ident = sub[col].fillna("").astype(str)
    mask = pd.Series(False, index=df.index)
    SEP = " - "
    for i, lab in ident.items():
        if not lab:
            continue
        children = ident.index[(ident != lab) & ident.str.startswith(lab + SEP)]
        if len(children) == 0:
            continue
        child_sum = sub.loc[children, "_fv"].sum()
        if child_sum > 0 and abs(child_sum - sub.at[i, "_fv"]) <= 0.005 * abs(child_sum):
            mask.at[i] = True
    return ProbeResult("dimension_rollup", "aggregate_row_filter",
                       {"fix_class": "aggregate_row_filter", "predicate": "parent_prefix_sum_equals_fv"},
                       mask, "fair_value reconciles to sum of prefix-children")


def probe_comparative_period(df: pd.DataFrame) -> ProbeResult | None:
    """Prior-period comparative rows (period < report_date) leaking under the filing's
    report_date. Only applicable when the frame carries `period` (staging-level)."""
    if "period" not in df.columns or "report_date" not in df.columns:
        return None
    g = _gate_rows(df)
    mask = g & (df["period"].astype(str) != df["report_date"].astype(str))
    return ProbeResult("comparative_period", "comparative_period_filter",
                       {"fix_class": "comparative_period_filter"},
                       mask, "period != report_date")


# -- SPV / consolidated-subsidiary look-through: a READ-ONLY VIEW (not an auto-decider) ---
# Deliberately NOT in PROBES. Resolving idiosyncratic structure is the AGENT's job (Layer 2:
# the agent authors a `spv_lookthrough` correction, B3 gates it). This view only SURFACES the
# structure the blinded worker cannot aggregate through its keyhole -- per legalentityaxis
# member: the underlying sleeve (FV+cost) vs the mapped parent equity line(s), and a SUGGESTED
# decision under the rule "look through iff unlevered (underlying ~= equity), else use equity".
# The agent decides (including the messy parts -- compound defects, partial-ownership JVs,
# whether to net debt); this function never applies or commits anything.
_LE_RE = re.compile(r"legalentityaxis=([^|]+)", re.I)


def _legal_entity(dims) -> str | None:
    m = _LE_RE.search(str(dims or ""))
    return m.group(1).strip() if m else None


def _collapse(s) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def map_legalentity_to_equity(member, parent_df: pd.DataFrame,
                              ident_cols=("issuer_name", "bdc_investment_identifier")) -> list:
    """Parent equity rows (index list) naming this legalentityaxis member. Deterministic
    collapse-and-substring match -- robust to punctuation and digit-grouping
    ('SaratogaInvestmentCorpCLO20131LtdMember' <-> 'Saratoga Investment Corp. CLO 2013-1, Ltd.').
    FAIL-CLOSED: returns [] when the key is too generic or nothing matches; the caller then
    defaults to `use_equity` (drop the look-through), the conservation-safe choice."""
    key = _collapse(re.sub(r"(?i)member$", "", str(member or "")))
    if len(key) < 10:
        return []
    cols = [c for c in ident_cols if c in parent_df.columns]
    return [idx for idx, row in parent_df.iterrows()
            if key in _collapse(" ".join(str(row.get(c) or "") for c in cols))]


def spv_lookthrough_view(df: pd.DataFrame) -> list[dict]:
    """READ-ONLY reconciliation view for the B2 agent (a TOOL, never an auto-decider). For each
    legalentityaxis member: underlying sleeve (FV+cost) vs the mapped parent equity line(s), the
    reconciliation flag, and a SUGGESTED decision. The agent confirms against source, decides,
    and authors the `spv_lookthrough` correction; B3 gates it. Does not apply or commit."""
    if "bdc_dimensions_raw" not in df.columns:
        return []
    g = _gate_rows(df)
    ent = df["bdc_dimensions_raw"].map(_legal_entity)
    members = sorted({e for e in ent[g].dropna().unique() if e})
    if not members:
        return []
    parent = df[g & ent.isna()]
    fv = _num(df["fair_value"]).fillna(0)
    cost = _num(df["cost"]).fillna(0) if "cost" in df.columns else None
    out = []
    for m in members:
        look = g & (ent == m)
        eq_idx = map_legalentity_to_equity(m, parent)
        eq_mask = pd.Series(df.index.isin(eq_idx), index=df.index)
        u_fv, e_fv = float(fv[look].sum()), float(fv[eq_mask].sum())
        u_cost = float(cost[look].sum()) if cost is not None else None
        e_cost = float(cost[eq_mask].sum()) if cost is not None else None
        fv_match = abs(u_fv - e_fv) <= DEFAULT_TOL * max(abs(u_fv), 1.0)
        cost_match = True if cost is None else abs((u_cost or 0) - (e_cost or 0)) <= DEFAULT_TOL * max(abs(u_cost or 0), 1.0)
        reconciles = bool(len(eq_idx) and fv_match and cost_match)
        out.append({
            "legal_entity": m, "n_underlying": int(look.sum()), "underlying_fv": round(u_fv, 2),
            "underlying_cost": (round(u_cost, 2) if u_cost is not None else None),
            "equity_rows": len(eq_idx), "equity_fv": round(e_fv, 2),
            "equity_cost": (round(e_cost, 2) if e_cost is not None else None),
            "mapped": bool(len(eq_idx)), "reconciles_to_equity": reconciles,
            "suggested_decision": "keep_lookthrough" if reconciles else "use_equity",
            "note": ("unlevered pass-through: underlying ~= equity -> agent may keep look-through"
                     if reconciles else
                     "levered or unmapped: underlying != equity -> agent confirms + likely uses equity line"),
        })
    return out


PROBES = [probe_exact_dedup, probe_label_aggregate, probe_no_detail_aggregate,
          probe_dimension_rollup, probe_comparative_period]


# ---- raw-staging cross-reference (probe (a)) ------------------------------------------
# The unified frame is a post-construction VIEW; it cannot see the schedule hierarchy or
# `period`. The raw BDC staging (bdc_holdings) carries both. This bucket-maps the raw
# current-period rows into structural classes and checks which class reconciles to the
# anchor -- surfacing the root structure for an honest escalation when the unified battery
# cannot close the residual. Raw columns differ: dimensions_raw / investment_identifier,
# no issuer_name / cusip.

_RAW_IDENT = "investment_identifier"
_RAW_DETAIL = ["interest_rate", "maturity_date", "principal_amount", "shares_held"]


def _raw_has_detail(df: pd.DataFrame) -> pd.Series:
    present = pd.Series(False, index=df.index)
    for c in _RAW_DETAIL:
        if c in df.columns:
            col = df[c]
            nz = col.notna() & (col.astype(str).str.strip() != "")
            if c in ("principal_amount", "shares_held"):
                nz = nz & (_num(col).fillna(0) != 0)
            present = present | nz
    return present


def raw_structural_map(raw_df: pd.DataFrame, anchor: float, report_date: str | None = None,
                       tol: float = DEFAULT_TOL) -> dict:
    """Bucket raw current-period rows into structural classes and report which reconciles to
    the anchor. Pure. raw_df should already be scoped to one (cik, report_date)."""
    df = raw_df
    if report_date is not None and "period" in df.columns:
        df = df[df["period"].astype(str) == str(report_date)]
    fv = _num(df[VALUE_COL]).fillna(0)
    ident = df[_RAW_IDENT].fillna("").astype(str) if _RAW_IDENT in df.columns else pd.Series("", index=df.index)
    is_total = ident.str.contains(r"\btotal\b", case=False, regex=True)
    detail = _raw_has_detail(df)
    classes = {
        "textual_total":      is_total,
        "no_detail_aggregate": (~is_total) & (~detail) & (fv != 0),
        "has_detail_leaf":     (~is_total) & detail,
    }
    buckets = {name: {"rows": int(m.sum()), "fv_sum": round(float(fv[m].sum()), 2)}
               for name, m in classes.items()}
    # Which non-total class sums to the anchor (a complete partition of the portfolio)?
    reconciling = [name for name in ("no_detail_aggregate", "has_detail_leaf")
                   if abs(buckets[name]["fv_sum"] - anchor) <= tol * abs(anchor)]
    leaf, agg = buckets["has_detail_leaf"]["fv_sum"], buckets["no_detail_aggregate"]["fv_sum"]
    # Anomaly: the position-detail rows and the aggregate rows should describe the SAME total.
    inconsistent = (buckets["has_detail_leaf"]["rows"] > 0 and buckets["no_detail_aggregate"]["rows"] > 0
                    and abs(leaf - agg) > tol * abs(anchor))
    finding = None
    if reconciling == ["no_detail_aggregate"] and inconsistent:
        finding = (f"raw aggregate-row class sums to the anchor exactly ({agg:,.0f}) but the "
                   f"position-detail rows over-sum it by {leaf - anchor:,.0f} with NO duplication "
                   f"(distinct identifiers) -- extraction/disclosure anomaly: position rows exceed "
                   f"the filer's own schedule total. Not a removable-row defect; source/wrapper review.")
    elif reconciling == ["has_detail_leaf"]:
        finding = (f"raw position-detail rows reconcile to the anchor; the aggregate rows are the "
                   f"leak -> aggregate_row_filter on the no-detail class.")
    return {"buckets": buckets, "reconciling_class": reconciling,
            "leaf_minus_anchor": round(leaf - anchor, 2),
            "partition_inconsistent": bool(inconsistent), "finding": finding}


def select_mechanism(diagnosis: dict) -> dict:
    """Pure decision over a diagnose() result: USE the composed mechanisms (deterministically
    reconciles) or ESCALATE with the most specific available reason. This is what replaces a
    guessed B1 mechanism on a Stage-3 symptom flag."""
    if diagnosis.get("reconciles"):
        return {"action": "use", "fix_classes": diagnosis.get("recommended_mechanisms", []),
                "reason": "deterministic probes reconcile value_sum to the anchor"}
    xref = diagnosis.get("raw_cross_reference") or {}
    reason = xref.get("finding") or diagnosis.get("escalation_reason")
    return {"action": "escalate", "fix_classes": [], "reason": reason}


# ---- battery --------------------------------------------------------------------------

def _score(df, mask, anchor):
    vs = value_sum(df, drop=mask)
    return vs, abs(vs - anchor), vs < anchor * (1 - DEFAULT_TOL)


def diagnose(df: pd.DataFrame, anchor: float, tol: float = DEFAULT_TOL,
             raw_df: pd.DataFrame | None = None, report_date: str | None = None) -> dict:
    """Run the battery; score every probe and a greedy composition against the anchor. When
    ``raw_df`` (BDC staging for the same CIK) is supplied, attach the raw structural map so an
    un-closeable residual escalates with the precise root structure."""
    base_vs = value_sum(df)
    base_resid = abs(base_vs - anchor)
    results = []
    probe_objs = []
    for p in PROBES:
        pr = p(df)
        if pr is None:
            continue
        probe_objs.append(pr)
        vs, resid, over = _score(df, pr.removed_mask, anchor)
        results.append({
            "name": pr.name, "fix_class": pr.fix_class,
            "rows_removed": int(pr.removed_mask.sum()),
            "fv_removed": round(base_vs - vs, 2),
            "residual_after": round(resid, 2),
            "pct_of_overshoot_closed": round(100.0 * (base_resid - resid) / base_resid, 1) if base_resid else None,
            "over_deletes_below_anchor": bool(over),
            "reconciles_alone": bool(resid <= tol * abs(anchor)),
            "note": pr.note, "template": pr.template,
        })

    # Greedy composition with a B3-style over-deletion guard: add the probe that most reduces
    # residual without pushing value_sum below the anchor; stop when reconciled or stuck.
    chosen, union = [], pd.Series(False, index=df.index)
    cur_resid = base_resid
    remaining = [pr for pr in probe_objs if pr.removed_mask.any()]
    while remaining:
        best, best_resid, best_union = None, cur_resid, None
        for pr in remaining:
            u = union | pr.removed_mask
            vs, resid, over = _score(df, u, anchor)
            if not over and resid < best_resid - 1e-6:
                best, best_resid, best_union = pr, resid, u
        if best is None:
            break
        chosen.append({"name": best.name, "fix_class": best.fix_class,
                       "residual_after": round(best_resid, 2), "template": best.template})
        union, cur_resid = best_union, best_resid
        remaining = [pr for pr in remaining if pr.name != best.name]
        if cur_resid <= tol * abs(anchor):
            break

    reconciles = cur_resid <= tol * abs(anchor)
    out = {
        "value_sum": round(base_vs, 2), "anchor": round(float(anchor), 2),
        "residual": round(base_resid, 2),
        "residual_pct": round(100.0 * base_resid / abs(anchor), 3) if anchor else None,
        "probes": results,
        "composition": chosen,
        "residual_after_composition": round(cur_resid, 2),
        "residual_explained_pct": round(100.0 * (base_resid - cur_resid) / base_resid, 1) if base_resid else None,
        "reconciles": bool(reconciles),
        "recommended_mechanisms": [c["fix_class"] for c in chosen] if reconciles else [],
        "escalate": not reconciles,
        "escalation_reason": (None if reconciles else
                              f"deterministic probes explain {round(base_resid - cur_resid, 2)} of "
                              f"{round(base_resid, 2)}; residual {round(cur_resid, 2)} unattributed "
                              f"-> human / wrapper investigation (do NOT fabricate a fix)"),
    }
    if raw_df is not None and not reconciles:
        xref = raw_structural_map(raw_df, anchor, report_date=report_date, tol=tol)
        out["raw_cross_reference"] = xref
        if xref.get("finding"):
            out["escalation_reason"] = xref["finding"]
    return out


# ---- thin CLI -------------------------------------------------------------------------

def _load_raw_cik(raw_path, cik: str, report_date: str) -> pd.DataFrame:
    """Pull only one CIK's BDC staging rows for one report_date (the 670K-row parquet filtered
    cheaply via DuckDB) so the raw cross-reference stays low-memory."""
    import duckdb
    c = cik.lstrip("0")
    q = (f"SELECT * FROM read_parquet('{str(raw_path).replace(chr(92), '/')}') "
         f"WHERE ltrim(CAST(cik AS VARCHAR),'0')='{c}' AND CAST(report_date AS VARCHAR)='{report_date}'")
    return duckdb.connect().execute(q).fetch_df()


def _load_anchor(conservation_csv, cik: str, report_date: str, rule="fv_conservation") -> float | None:
    df = pd.read_csv(conservation_csv, dtype=str)
    c = cik.lstrip("0")
    m = ((df["rule_name"] == rule) & (df["cik"].str.lstrip("0") == c)
         & (df["report_date"].astype(str) == report_date))
    sel = df.loc[m, "anchor_value"].dropna()
    return float(sel.iloc[0]) if len(sel) else None


def main():
    import argparse, json
    ap = argparse.ArgumentParser(description="Anchor-scored conservation diagnosis battery (no LLM).")
    ap.add_argument("--holdings", required=True, help="per-CIK unified holdings csv/parquet")
    ap.add_argument("--cik", required=True)
    ap.add_argument("--target-quarter", required=True)
    ap.add_argument("--conservation", required=True, help="shadow/conservation_gate_results.csv")
    ap.add_argument("--anchor", type=float, default=None, help="override anchor instead of loading it")
    ap.add_argument("--raw-holdings", default=None,
                    help="bdc_holdings.parquet (enables the raw-staging cross-reference for escalation)")
    args = ap.parse_args()

    df = (pd.read_parquet(args.holdings) if str(args.holdings).endswith(".parquet")
          else pd.read_csv(args.holdings, low_memory=False))
    df = df[df["report_date"].astype(str) == args.target_quarter].copy()
    anchor = args.anchor if args.anchor is not None else _load_anchor(args.conservation, args.cik, args.target_quarter)
    if anchor is None:
        raise SystemExit(f"no fv_conservation anchor for {args.cik} {args.target_quarter}")
    raw_df = _load_raw_cik(args.raw_holdings, args.cik, args.target_quarter) if args.raw_holdings else None
    out = diagnose(df, anchor, raw_df=raw_df, report_date=args.target_quarter)
    out["selector"] = select_mechanism(out)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
