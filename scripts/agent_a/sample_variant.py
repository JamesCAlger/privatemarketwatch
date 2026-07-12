"""Agent A / P2 harness -- build a bounded, blinded variant-bundle for one CIK.

This is the deterministic A0/A1 step that produces the ONLY thing the (sandboxed Codex)
induction agent sees: per top (cik, signature) variant, ~N homogeneous sample rows with
their structured twins, plus the (none)-signature examples that reveal the missing
keyword dialect. The agent never scans the cluster; it reasons over this dozen-row bundle
and emits a proposed anchors + rate_grammar config, which the deterministic A3 gate
(pipeline.identifier_rate.evaluate_cik) must then clear.

Cache-only, read-only. Usage: python -m scripts.agent_a.sample_variant <CIK> [N]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter

from pipeline import config
from pipeline.identifier_signature import (
    _ANCHOR_PRESENCE_RE,
    _LEGAL_SUFFIX_RE,
    detect_regime,
    is_aggregate_candidate,
    keyword_signature,
    load_anchors,
    punctuation_shape,
)

_RATE_RE = re.compile(r"[0-9]+\.?[0-9]*\s*%")


def _era_stratified_pick(rows_for_sig: list, n_per_era: int) -> list:
    """Pick samples that cover EVERY distinct era (report_date at tuple index 7), <= n_per_era
    rows each, newest era first. A single-quarter sample lets the agent induce a grammar that
    fits only the current identifier format; the held-out gate then FAILs it on older quarters
    where the filer used a different format (the 2023-03-31 cluster). Stratifying by era forces
    the agent to see -- and cover -- the old + new formats in one grammar.
    """
    by_date: dict = {}
    for r in rows_for_sig:
        by_date.setdefault(r[7], []).append(r)
    picked = []
    for d in sorted(by_date, reverse=True):
        picked.extend(by_date[d][:n_per_era])
    return picked


_FS_PCT = re.compile(r"[0-9]+\.?[0-9]*\s*%")
_FS_DATE = re.compile(r"\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}\b")
_FS_REF = re.compile(r"reference rate|\bsofr\b|\blibor\b|\bprime\b|\beuribor\b|\bS\s*\+|\bSF\b", re.I)
_FS_PIK = re.compile(r"\bpik\b|\(incl", re.I)


def flattened_shape(ident: str) -> str:
    """COARSE structural shape for the FLATTENED regime. punctuation_shape is for the delimited
    regime and over-fragments here (issuer-name commas/parens + encoding artifacts -> dozens of
    skeletons), so shape-stratifying on it never reaches the minority layout. This keys only on
    the axes that actually break a rate grammar: a leading hierarchy breadcrumb (a '%' before the
    first issuer legal-entity suffix), the number of rate legs after the issuer (cash vs cash+PIK),
    and presence of a reference-rate/spread, a PIK parenthetical, and a maturity date. Bounded to
    a handful of classes, so >=1-per-shape sampling reliably surfaces the breadcrumb variant.
    """
    s = ident or ""
    m_legal = _LEGAL_SUFFIX_RE.search(s)
    legal_pos = m_legal.start() if m_legal else len(s)
    pcts = [m.start() for m in _FS_PCT.finditer(s)]
    lead_bc = int(any(p < legal_pos for p in pcts))
    legs = min(sum(1 for p in pcts if p >= legal_pos), 3)
    return (f"bc{lead_bc}|legs{legs}|ref{int(bool(_FS_REF.search(s)))}"
            f"|pik{int(bool(_FS_PIK.search(s)))}|mat{int(bool(_FS_DATE.search(s)))}")


def _shape_stratified_pick(rows_for_sig: list, n_per_era: int, max_shapes: int = 6,
                           shape_fn=flattened_shape) -> list:
    """Era-stratified, but WITHIN each era round-robin across distinct punctuation_shapes so a
    minority LAYOUT (e.g. a hierarchy-breadcrumb-prefixed position line) is sampled even when
    rare. The plain `_era_stratified_pick` takes `by_date[d][:n_per_era]` -- the first n rows in
    storage order -- and silently drops a low-frequency shape; that shape then surfaces as a
    held-out completeness FAIL on the quarter it dominates (the 2026-06-23 investigation: ~84%
    of the 8 completeness FAILs are real positions in a layout the head sample never showed the
    worker). Guarantees >=1 row per kept shape and >= n_per_era rows per era; caps kept shapes
    at `max_shapes` (most frequent first) to bound bundle growth. Keyword signature is unchanged
    -- this only diversifies WHICH rows of an already-chosen (cik, signature) variant are shown.
    """
    by_date: dict = {}
    for r in rows_for_sig:
        by_date.setdefault(r[7], []).append(r)
    picked = []
    for d in sorted(by_date, reverse=True):
        by_shape: dict = {}
        for r in by_date[d]:
            by_shape.setdefault(shape_fn(r[0]), []).append(r)
        order = sorted(by_shape, key=lambda k: (-len(by_shape[k]), k))[:max_shapes]
        idx = {k: 0 for k in order}
        budget = max(n_per_era, len(order))   # cover every kept shape, and >= n_per_era
        taken = 0
        while taken < budget:
            progressed = False
            for k in order:
                if taken >= budget:
                    break
                if idx[k] < len(by_shape[k]):
                    picked.append(by_shape[k][idx[k]])
                    idx[k] += 1
                    taken += 1
                    progressed = True
            if not progressed:
                break
    return picked


def build_bundle(cik: str, n_per_sig: int = 12, top_k: int = 4, n_none: int = 10,
                 report_date: str | None = None, multi_quarter: bool = False,
                 n_per_era: int = 3, shape_stratified: bool = False,
                 anchors=None) -> dict:
    """Build the bounded variant-bundle for one CIK.

    Sampling modes:
    - report_date given: scope to that one quarter (legacy single-quarter mode).
    - multi_quarter=True: pool ALL current-period rows and stratify each variant's samples
      across every era (<= n_per_era per distinct report_date) so the induced grammar must
      generalize across format changes the held-out gate tests. Recommended for induction.
    - neither: pool all current-period rows, first-n_per_sig sampling (no era guarantee).

    Carries accession_number + report_date per sample so the shared evidence_cli can roam the
    cached SOI and the agent can see which era each sample came from.
    """
    import duckdb

    con = duckdb.connect()
    parquet = str(config.OUTPUT_DIR / "bdc_holdings.parquet")
    quarter_clause = ("" if multi_quarter else
                      (f"AND CAST(report_date AS VARCHAR) = '{report_date}'"
                       if report_date else ""))
    rows = con.execute(
        f"""
        SELECT CAST(investment_identifier AS VARCHAR) ident,
               CAST(entity_name AS VARCHAR) nm,
               TRY_CAST(interest_rate AS DOUBLE) tw_int,
               TRY_CAST(basis_spread AS DOUBLE) tw_spread,
               TRY_CAST(pik_rate AS DOUBLE) tw_pik,
               CAST(maturity_date AS VARCHAR) tw_mat,
               CAST(accession_number AS VARCHAR) acc,
               CAST(report_date AS VARCHAR) rd
        FROM '{parquet}'
        WHERE CAST(cik AS VARCHAR) = '{cik}'
          AND investment_identifier IS NOT NULL
          AND CAST(period AS VARCHAR) = CAST(report_date AS VARCHAR)
          {quarter_clause}
        """
    ).fetchall()
    con.close()

    anchors = anchors or load_anchors(cik)
    n = len(rows)
    rate_pct = 100.0 * sum(1 for r in rows if _RATE_RE.search(r[0])) / n if n else 0.0
    anchor_pct = 100.0 * sum(1 for r in rows if _ANCHOR_PRESENCE_RE.search(r[0])) / n if n else 0.0
    regime = detect_regime(rate_pct, anchor_pct)

    def sig(ident):
        return keyword_signature(ident, anchors) if regime == "flattened" else punctuation_shape(ident)

    by_sig: dict = {}
    counts: Counter = Counter()
    none_examples = []
    for r in rows:
        s = sig(r[0])
        counts[s] += 1
        by_sig.setdefault(s, []).append(r)
        if s == "(none)" and len(none_examples) < n_none:
            none_examples.append(r[0][:300])

    def twin_block(r):
        return {"interest_rate": r[2], "basis_spread": r[3], "pik_rate": r[4], "maturity_date": r[5]}

    variants = []
    accessions: set = set()
    for s, c in counts.most_common(top_k):
        if s == "(none)":
            continue
        if multi_quarter:
            sample = (_shape_stratified_pick(by_sig[s], n_per_era) if shape_stratified
                      else _era_stratified_pick(by_sig[s], n_per_era))
        else:
            sample = by_sig[s][:n_per_sig]
        for r in sample:
            if r[6]:
                accessions.add(r[6])
        variants.append({
            "signature": s,
            "count": c,
            "pct": round(100.0 * c / n, 1),
            "aggregate_candidate_share": round(
                100.0 * sum(1 for r in by_sig[s] if is_aggregate_candidate(r[0], anchors)) / c, 1),
            "samples": [{"identifier": r[0][:400], "twins": twin_block(r),
                         "accession_number": r[6], "report_date": r[7]} for r in sample],
        })

    return {
        "cik": cik,
        "engine": "agentA",                 # tells the shared evidence_cli to use the BDC source
        # report_date = the as-of/target quarter (labeling + dispatch preflight contract);
        # report_dates = every era actually pooled into the samples (multi_quarter mode).
        "report_date": report_date or "",
        "report_dates": sorted({r[7] for r in rows}),
        "multi_quarter": multi_quarter,
        "entity_name": rows[0][1] if rows else "",
        "n_rows": n,
        "regime": regime,
        "rate_embed_pct": round(rate_pct, 1),
        "anchor_present_pct": round(anchor_pct, 1),
        "none_pct": round(100.0 * counts.get("(none)", 0) / n, 1) if n else 0.0,
        "current_anchor_labels": [lbl for lbl, _ in anchors],
        "top_variants": variants,
        "none_examples": none_examples,
        # evidence_items: the shape the SHARED scripts/review_agent/evidence_cli.py reads to
        # resolve an accession -> cached SOI -> roam/grid/tables/totals. One row per sampled
        # accession is enough for resolve_accessions_from_rows.
        "evidence_items": [{
            "evidence_id": "source_accessions",
            "data": [{"accession_number": a, "cik": cik} for a in sorted(accessions)],
        }],
        "instructions": (
            "Induce (1) a per-CIK anchor vocabulary that recognizes this filer's section "
            "markers so none_examples stop landing in (none); (2) a rate_grammar "
            "(schema agentA-rate-grammar.v1) extracting reference_rate_type, basis_spread "
            "(note bps vs pct), interest_rate fields, pik_rate, coupon_type, maturity_date. "
            "Set pik_convention (additive: 'cash plus X PIK'; inclusive: all-in incl PIK). "
            "Prefer the self-contained sum_identity gate where a fixed total is stated; the "
            "structured twins may themselves be mis-binned -- flag, do not fit to them."
            + (" SAMPLES SPAN MULTIPLE ERAS (see each sample's report_date): this filer may have "
               "changed its identifier format over time. Your ONE grammar must parse ALL eras "
               "present -- inspect the oldest report_dates, not just the newest, and use regex "
               "alternation where formats differ. The held-out gate tests every quarter; a "
               "grammar that only fits the recent format will FAIL on older ones."
               if multi_quarter else "")
        ),
    }


def main():
    # usage: sample_variant.py <CIK> [n_per_sig] [report_date]
    # report_date omitted -> multi-quarter era-stratified bundle (recommended for induction)
    cik = sys.argv[1] if len(sys.argv) > 1 else "0001278752"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    report_date = sys.argv[3] if len(sys.argv) > 3 else None
    bundle = build_bundle(cik, n_per_sig=n, report_date=report_date,
                          multi_quarter=report_date is None)
    out_dir = config.OUTPUT_DIR / "agent_a" / "bundles"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"_{report_date}" if report_date else ""
    path = out_dir / f"{cik}{suffix}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)
    n_acc = len(bundle["evidence_items"][0]["data"])
    print(f"Wrote bundle -> {path}")
    print(f"  cik={cik} quarter={report_date or 'ALL'} regime={bundle['regime']} "
          f"n={bundle['n_rows']} none%={bundle['none_pct']} "
          f"variants={len(bundle['top_variants'])} accessions={n_acc}")


if __name__ == "__main__":
    main()
