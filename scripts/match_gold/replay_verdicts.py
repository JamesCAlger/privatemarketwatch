"""Replay match-gold verdicts against the matcher's tier predicates.

For every adjudicated pair (WRONG / CONFIRMED edges from chain packets and
MISSED pairs from proposed_links) recompute, deterministically, what each
matcher tier would have done with the two rows and why:

    ADMIT                     the tier's join + guards accept the pair
    VETO:<reason>[,<reason>]  the guards that reject it
    N/A                       the tier cannot be replayed from unified rows

Tier A (within-filing comparatives) is not replayable from unified holdings
because it consumes raw comparative-period rows; it is reported as N/A and the
produced tier is still recorded so its share can be measured.

For WRONG edges the harness also finds the begin row's "twin" in the end
quarter -- the same-name row with equal maturity and the closest principal --
so the operator can see whether a better candidate existed and whether the
matcher lost it to a veto or to the 1:1 contest.

Read-only. Never touches data/output.

Usage:
    python scripts/match_gold/replay_verdicts.py \
        --batch-dir data/output/match_quality/gold/mg3 \
        --holdings data/output/private_markets_holdings.csv \
        --out scratch/<session>/replay_mg3.csv
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.position_matching import (  # noqa: E402
    MAX_FV_RATIO,
    MAX_FV_RATIO_IDENTIFIER,
    MAX_MATURITY_GAP_DAYS,
    MAX_NAME_MULTIPLICITY,
    MIN_JW_SIMILARITY,
    _normalize_name_sql,
    _quarter_label_sql,
    _strong_position_key_sql,
)

_ROW_ID_RE = re.compile(r"^ROW-[0-9A-Za-z]+$")

PAIR_COLS = ["packet_id", "stratum", "kind", "tier", "cik",
             "row_a", "row_b", "edge_index"]

TIERS = ["B1b", "B2", "C", "D", "E", "SUPP"]


# ---------------------------------------------------------------------------
# 1. Collect pairs from a scored batch
# ---------------------------------------------------------------------------

def _valid_row_id(value) -> bool:
    return isinstance(value, str) and bool(_ROW_ID_RE.match(value.strip()))


def load_gold_pairs(batch_dir: Path) -> tuple[pd.DataFrame, dict]:
    """Return (pairs, stats). One row per adjudicated pair.

    kind: WRONG / CONFIRMED / UNCERTAIN for chain edges (from edge_verdicts
    joined to packet edges and blinded tier sidecars); MISSED for
    proposed_links of MISSED_LINK verdicts whose row ids resolve.
    """
    batch_dir = Path(batch_dir)
    rows: list[dict] = []
    stats = {"packets": 0, "unresolvable_missed": 0, "missed_links": 0}
    for vpath in sorted((batch_dir / "verdicts").glob("*.json")):
        pid = vpath.stem
        verdict = json.loads(vpath.read_text(encoding="utf-8-sig"))
        packet = json.loads((batch_dir / "packets" / f"{pid}.json")
                            .read_text(encoding="utf-8-sig"))
        meta = json.loads((batch_dir / "packets_meta" / f"{pid}.json")
                          .read_text(encoding="utf-8-sig"))
        stats["packets"] += 1
        stratum = meta.get("stratum", "")
        cik = packet.get("cik", "")
        edge_rows = {e["edge_index"]: e for e in packet.get("edges", [])}
        edge_tier = {e["edge_index"]: e.get("match_method", "")
                     for e in meta.get("edges", [])}
        for ev in verdict.get("edge_verdicts", []):
            idx = ev.get("edge_index")
            edge = edge_rows.get(idx)
            if edge is None:
                continue
            rows.append({
                "packet_id": pid, "stratum": stratum, "kind": ev.get("verdict", ""),
                "tier": edge_tier.get(idx, ""), "cik": cik,
                "row_a": edge.get("begin_row_id", ""),
                "row_b": edge.get("end_row_id", ""), "edge_index": idx,
            })
        if verdict.get("verdict") == "MISSED_LINK":
            for pl in verdict.get("proposed_links", []) or []:
                stats["missed_links"] += 1
                a, b = pl.get("row_id_a"), pl.get("row_id_b")
                if not (_valid_row_id(a) and _valid_row_id(b)):
                    stats["unresolvable_missed"] += 1
                    continue
                rows.append({
                    "packet_id": pid, "stratum": stratum, "kind": "MISSED",
                    "tier": "", "cik": cik, "row_a": a.strip(),
                    "row_b": b.strip(), "edge_index": "",
                })
    pairs = pd.DataFrame(rows, columns=PAIR_COLS)
    return pairs, stats


# ---------------------------------------------------------------------------
# 2. Replay tier predicates on unified rows
# ---------------------------------------------------------------------------

_INST_SUBTYPE_SQL = """
CASE
  WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
       '(?i)(^|\\W)(?:revolv(?:er|ing)|rcf|revolving credit)(\\W|$)') THEN 'REVOLVER'
  WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
       '(?i)(^|\\W)(?:ddtl|delayed draw)(\\W|$)') THEN 'DDTL'
  WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
       '(?i)(^|\\W)(?:term loan|tl[a-d]?)(\\W|$)') THEN 'TERM_LOAN'
  WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
       '(?i)(^|\\W)warrants?(\\W|$)') THEN 'WARRANT'
  WHEN regexp_matches(CAST(instrument_description AS VARCHAR),
       '(?i)(^|\\W)(?:common (?:stock|equity|units?)|preferred (?:stock|equity|units?)|membership interest|llc interest|equity interest|class [a-c](\\W|$)|ordinary shares)(\\W|$)') THEN 'EQUITY'
  ELSE NULL
END
"""

_NEEDED = ["row_id", "cik", "source", "report_date", "issuer_name", "fair_value",
           "principal_amount", "basis_spread", "maturity_date",
           "index_classification", "instrument_description", "cusip",
           "position_key", "entity_id", "lien_position", "coupon_type",
           "asset_class"]


def _prepare(con: duckdb.DuckDBPyConnection, holdings: pd.DataFrame) -> None:
    h = holdings.copy()
    for c in _NEEDED:
        if c not in h.columns:
            h[c] = None
    h = h[_NEEDED].astype(object).where(h[_NEEDED].notna(), None)
    con.register("h_raw", h)
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE feat AS
    WITH base AS (
        SELECT
            CAST(row_id AS VARCHAR) AS row_id,
            CAST(cik AS VARCHAR) AS cik,
            CAST(source AS VARCHAR) AS source,
            CAST(report_date AS VARCHAR) AS report_date,
            {_quarter_label_sql('report_date')} AS quarter,
            CAST(issuer_name AS VARCHAR) AS issuer_name,
            LOWER(TRIM(CAST(issuer_name AS VARCHAR))) AS name_lower,
            LOWER(TRIM(regexp_replace(regexp_replace(CAST(issuer_name AS VARCHAR),
                '\\s*\\(\\d+\\)\\s*$', ''), '\\s+\\d{{1,2}}\\s*$', ''))) AS name_key,
            {_normalize_name_sql('CAST(issuer_name AS VARCHAR)')} AS norm_name,
            TRY_CAST(fair_value AS DOUBLE) AS fv,
            TRY_CAST(principal_amount AS DOUBLE) AS pa,
            TRY_CAST(basis_spread AS DOUBLE) AS bs,
            TRY_CAST(maturity_date AS DATE) AS mat,
            COALESCE(CAST(index_classification AS VARCHAR), '') AS ic,
            {_INST_SUBTYPE_SQL} AS subtype,
            NULLIF(TRIM(CAST(cusip AS VARCHAR)), '') AS cusip,
            COALESCE(CAST(position_key AS VARCHAR), '') AS pk,
            ({_strong_position_key_sql('position_key')}) AS pk_strong,
            NULLIF(TRIM(CAST(entity_id AS VARCHAR)), '') AS eid,
            COALESCE(CAST(asset_class AS VARCHAR), '') AS asset_class
        FROM h_raw
    ),
    eligible AS (
        SELECT *,
            (fv IS NOT NULL AND fv != 0
             AND asset_class NOT IN ('CASH', 'DERIVATIVE')
             AND ic != 'CASH') AS in_universe
        FROM base
    )
    SELECT e.*,
        COUNT(*) OVER (PARTITION BY cik, quarter, name_lower) AS n_name,
        COUNT(*) OVER (PARTITION BY cik, quarter, name_key) AS n_key,
        COUNT(*) OVER (PARTITION BY cik, quarter, norm_name) AS n_norm,
        COUNT(*) OVER (PARTITION BY cik, source, quarter, pk) AS n_pk,
        COUNT(*) OVER (PARTITION BY cik, source, quarter, eid, ic) AS n_eid
    FROM eligible e
    WHERE in_universe
    """)


def _tier_outcomes(r: dict) -> dict:
    """Pure-Python evaluation of each tier's guards for one feature row."""
    out = {}
    same_cik = r["a_cik"] == r["b_cik"] and r["a_source"] == r["b_source"]
    adjacent = r["b_quarter"] == r["a_next_quarter"]
    fv_ok = (r["a_fv"] or 0) > 0 and (r["b_fv"] or 0) > 0
    ratio = (r["a_fv"] / r["b_fv"]) if fv_ok else None

    def common(cap, need_class=True, need_mat=False):
        v = []
        if not same_cik:
            v.append("cik_or_source")
        if not adjacent:
            v.append("not_adjacent_quarter")
        if not fv_ok:
            v.append("fv_nonpositive")
        elif not (1.0 / cap <= ratio <= cap):
            v.append(f"fv_ratio>{int(cap)}")
        if need_class and r["a_ic"] and r["b_ic"] and r["a_ic"] != r["b_ic"]:
            v.append("classification_flip")
        if r["a_subtype"] and r["b_subtype"] and r["a_subtype"] != r["b_subtype"]:
            v.append("inst_subtype")
        if need_mat and r["mat_gap_days"] is not None \
                and r["mat_gap_days"] > MAX_MATURITY_GAP_DAYS:
            v.append("maturity_gap")
        return v

    # B1b position key
    v = []
    if not (r["a_pk"] and r["a_pk"] == r["b_pk"]):
        v.append("position_key_differs")
    elif not (r["a_pk_strong"] and r["b_pk_strong"]):
        v.append("position_key_weak")
    elif r["a_n_pk"] > 1 or r["b_n_pk"] > 1:
        v.append("position_key_not_unique")
    v += common(MAX_FV_RATIO_IDENTIFIER, need_class=False)
    out["t_B1b"] = "ADMIT" if not v else "VETO:" + ",".join(v)

    # B2 exact name
    v = []
    if r["a_name_lower"] != r["b_name_lower"]:
        v.append("name_differs")
    if r["a_n_name"] > MAX_NAME_MULTIPLICITY or r["b_n_name"] > MAX_NAME_MULTIPLICITY:
        v.append("multiplicity")
    v += common(MAX_FV_RATIO_IDENTIFIER)
    out["t_B2"] = "ADMIT" if not v else "VETO:" + ",".join(v)

    # C normalized name
    v = []
    if r["a_norm_name"] != r["b_norm_name"]:
        v.append("norm_name_differs")
    if r["a_n_norm"] > MAX_NAME_MULTIPLICITY or r["b_n_norm"] > MAX_NAME_MULTIPLICITY:
        v.append("multiplicity")
    v += common(MAX_FV_RATIO_IDENTIFIER, need_mat=True)
    out["t_C"] = "ADMIT" if not v else "VETO:" + ",".join(v)

    # D fuzzy
    v = []
    if (r["a_norm_name"] or "")[:4] != (r["b_norm_name"] or "")[:4]:
        v.append("block_prefix")
    if r["jw"] is None or r["jw"] < MIN_JW_SIMILARITY:
        v.append(f"jw<{MIN_JW_SIMILARITY}")
    if r["a_n_norm"] > MAX_NAME_MULTIPLICITY or r["b_n_norm"] > MAX_NAME_MULTIPLICITY:
        v.append("multiplicity")
    v += common(MAX_FV_RATIO, need_mat=True)
    out["t_D"] = "ADMIT" if not v else "VETO:" + ",".join(v)

    # E entity fingerprint
    v = []
    if not (r["a_eid"] and r["a_eid"] == r["b_eid"]):
        v.append("entity_differs")
    if r["a_ic"] != r["b_ic"]:
        v.append("classification_differs")
    if r["a_n_eid"] > 1 or r["b_n_eid"] > 1:
        v.append("entity_not_unique")
    v += common(MAX_FV_RATIO, need_class=False, need_mat=True)
    out["t_E"] = "ADMIT" if not v else "VETO:" + ",".join(v)

    # Supplementary B2 (unique exact name, |FV| ratio <= 5)
    v = []
    if r["a_name_lower"] != r["b_name_lower"]:
        v.append("name_differs")
    if r["a_n_name"] != 1 or r["b_n_name"] != 1:
        v.append("name_not_unique")
    if not same_cik:
        v.append("cik_or_source")
    if not adjacent:
        v.append("not_adjacent_quarter")
    if r["a_fv"] and r["b_fv"]:
        ar = abs(r["a_fv"]) / max(abs(r["b_fv"]), 1.0)
        br = abs(r["b_fv"]) / max(abs(r["a_fv"]), 1.0)
        if not (1.0 / MAX_FV_RATIO <= ar <= MAX_FV_RATIO
                and 1.0 / MAX_FV_RATIO <= br <= MAX_FV_RATIO):
            v.append(f"fv_ratio>{int(MAX_FV_RATIO)}")
    else:
        v.append("fv_missing")
    out["t_SUPP"] = "ADMIT" if not v else "VETO:" + ",".join(v)
    out["t_A"] = "N/A"
    return out


def replay_pairs(pairs: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    """Attach per-tier outcomes, pair features and (for WRONG) the twin row."""
    con = duckdb.connect()
    _prepare(con, holdings)
    con.register("pairs", pairs.astype(object))
    feat = con.execute("""
    SELECT p.*,
        a.cik AS a_cik, b.cik AS b_cik, a.source AS a_source, b.source AS b_source,
        a.quarter AS a_quarter, b.quarter AS b_quarter,
        a.report_date AS a_report_date, b.report_date AS b_report_date,
        a.issuer_name AS a_name, b.issuer_name AS b_name,
        a.name_lower AS a_name_lower, b.name_lower AS b_name_lower,
        a.name_key AS a_name_key, b.name_key AS b_name_key,
        a.norm_name AS a_norm_name, b.norm_name AS b_norm_name,
        jaro_winkler_similarity(a.norm_name, b.norm_name) AS jw,
        a.fv AS a_fv, b.fv AS b_fv, a.pa AS a_pa, b.pa AS b_pa,
        a.bs AS a_bs, b.bs AS b_bs,
        CAST(a.mat AS VARCHAR) AS a_mat, CAST(b.mat AS VARCHAR) AS b_mat,
        CASE WHEN a.mat IS NOT NULL AND b.mat IS NOT NULL
             THEN ABS(DATEDIFF('day', a.mat, b.mat)) END AS mat_gap_days,
        a.ic AS a_ic, b.ic AS b_ic, a.subtype AS a_subtype, b.subtype AS b_subtype,
        a.pk AS a_pk, b.pk AS b_pk, a.pk_strong AS a_pk_strong, b.pk_strong AS b_pk_strong,
        a.eid AS a_eid, b.eid AS b_eid,
        a.n_name AS a_n_name, b.n_name AS b_n_name,
        a.n_key AS a_n_key, b.n_key AS b_n_key,
        a.n_norm AS a_n_norm, b.n_norm AS b_n_norm,
        a.n_pk AS a_n_pk, b.n_pk AS b_n_pk,
        a.n_eid AS a_n_eid, b.n_eid AS b_n_eid,
        (a.row_id IS NOT NULL) AS a_found, (b.row_id IS NOT NULL) AS b_found
    FROM pairs p
    LEFT JOIN feat a ON a.row_id = p.row_a
    LEFT JOIN feat b ON b.row_id = p.row_b
    """).fetchdf()

    # next quarter label for the begin side (mirror _next_quarter_sql)
    def _next_q(q):
        if not isinstance(q, str) or "q" not in q:
            return None
        y, n = q.split("q")
        y, n = int(y), int(n)
        return f"{y + 1}q1" if n == 4 else f"{y}q{n + 1}"
    feat["a_next_quarter"] = feat["a_quarter"].map(_next_q)

    # Twin search for WRONG edges: same cik/source/name_key in the end quarter,
    # excluding the chosen end row; prefer equal maturity, then closest principal.
    twins = con.execute("""
    WITH cand AS (
        SELECT p.row_a, p.row_b, t.row_id AS twin_row_id,
            CASE WHEN a.mat IS NOT NULL AND t.mat IS NOT NULL AND a.mat = t.mat THEN 0
                 WHEN a.mat IS NULL OR t.mat IS NULL THEN 1 ELSE 2 END AS mat_rank,
            CASE WHEN a.pa IS NOT NULL AND t.pa IS NOT NULL AND a.pa > 0 AND t.pa > 0
                 THEN GREATEST(a.pa, t.pa) / LEAST(a.pa, t.pa) END AS twin_pa_ratio,
            t.fv AS twin_fv, t.pa AS twin_pa, CAST(t.mat AS VARCHAR) AS twin_mat,
            ROW_NUMBER() OVER (
                PARTITION BY p.row_a, p.row_b
                ORDER BY
                    CASE WHEN a.mat IS NOT NULL AND t.mat IS NOT NULL AND a.mat = t.mat THEN 0
                         WHEN a.mat IS NULL OR t.mat IS NULL THEN 1 ELSE 2 END,
                    COALESCE(GREATEST(a.pa, t.pa) / NULLIF(LEAST(a.pa, t.pa), 0), 1e9),
                    t.row_id
            ) AS rn
        FROM pairs p
        JOIN feat a ON a.row_id = p.row_a
        JOIN feat b ON b.row_id = p.row_b
        JOIN feat t ON t.cik = a.cik AND t.source = a.source
                   AND t.quarter = b.quarter AND t.name_key = a.name_key
                   AND t.row_id != b.row_id
        WHERE p.kind = 'WRONG'
    )
    SELECT row_a, row_b, twin_row_id, twin_pa_ratio, twin_fv, twin_pa, twin_mat, mat_rank AS twin_mat_rank
    FROM cand WHERE rn = 1
    """).fetchdf()
    con.close()

    feat = feat.merge(twins, on=["row_a", "row_b"], how="left")

    def _pa_ratio(r):
        if r["a_pa"] and r["b_pa"] and r["a_pa"] > 0 and r["b_pa"] > 0:
            return max(r["a_pa"], r["b_pa"]) / min(r["a_pa"], r["b_pa"])
        return None
    feat["pa_ratio"] = feat.apply(_pa_ratio, axis=1)  # small frame, fine

    outcomes = []
    for rec in feat.to_dict("records"):
        if not (rec["a_found"] and rec["b_found"]):
            outcomes.append({f"t_{t}": "ROW_NOT_FOUND" for t in TIERS + ["A"]})
            continue
        rec = {k: (None if (isinstance(v, float) and pd.isna(v)) else v)
               for k, v in rec.items()}
        outcomes.append(_tier_outcomes(rec))
    out = pd.concat([feat.reset_index(drop=True), pd.DataFrame(outcomes)], axis=1)
    out["any_admit"] = out[[f"t_{t}" for t in TIERS]].eq("ADMIT").any(axis=1)
    return out


# ---------------------------------------------------------------------------
# 3. Summaries
# ---------------------------------------------------------------------------

def summarize(out: pd.DataFrame) -> str:
    lines = ["# Replay summary", ""]
    lines.append(f"pairs: {len(out)}  by kind: "
                 + ", ".join(f"{k}={v}" for k, v in out["kind"].value_counts().items()))
    nf = (~(out["a_found"].fillna(False) & out["b_found"].fillna(False))).sum()
    lines.append(f"pairs with a row missing from holdings: {nf}")
    missed = out[out["kind"] == "MISSED"]
    if len(missed):
        lines += ["", "## MISSED pairs: would any tier admit them today?",
                  f"admitted by >=1 tier: {int(missed['any_admit'].sum())} / {len(missed)}"]
        for t in TIERS:
            col = missed[f"t_{t}"]
            adm = int((col == "ADMIT").sum())
            reasons = (col[col.str.startswith("VETO:", na=False)]
                       .str.slice(5).str.split(",").explode().value_counts())
            lines.append(f"- {t}: ADMIT {adm}; top vetoes: "
                         + ", ".join(f"{k}={v}" for k, v in reasons.head(5).items()))
    wrong = out[out["kind"] == "WRONG"]
    if len(wrong):
        lines += ["", "## WRONG edges: produced tier and whether a twin existed"]
        lines.append("produced tier: " + ", ".join(
            f"{k}={v}" for k, v in wrong["tier"].value_counts().items()))
        has_twin = wrong["twin_row_id"].notna()
        lines.append(f"twin present in end quarter: {int(has_twin.sum())} / {len(wrong)}")
        close = wrong[has_twin & (wrong["twin_pa_ratio"] <= 1.10)]
        lines.append(f"twin with principal within 10%: {len(close)}")
        eqm = wrong[has_twin & (wrong["twin_mat_rank"] == 0)]
        lines.append(f"twin with equal maturity: {len(eqm)}")
        lines.append("chosen pair principal ratio > 2: "
                     f"{int((wrong['pa_ratio'] > 2).sum())}; "
                     f"maturity differs (both known): "
                     f"{int((wrong['mat_gap_days'].fillna(0) > 0).sum())}; "
                     f"name_key differs: {int((wrong['a_name_key'] != wrong['b_name_key']).sum())}")
        lines.append("begin-side name multiplicity >1 (contested): "
                     f"{int((wrong['a_n_key'] > 1).sum())}; end-side: {int((wrong['b_n_key'] > 1).sum())}")
    conf = out[out["kind"] == "CONFIRMED"]
    if len(conf):
        lines += ["", "## CONFIRMED edges (control)"]
        lines.append(f"n={len(conf)}; principal ratio > 2: {int((conf['pa_ratio'] > 2).sum())}; "
                     f"maturity differs: {int((conf['mat_gap_days'].fillna(0) > 0).sum())}; "
                     f"contested begin: {int((conf['a_n_key'] > 1).sum())}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--batch-dir", required=True, type=Path)
    ap.add_argument("--holdings", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    pairs, stats = load_gold_pairs(args.batch_dir)
    print(f"[replay] pairs={len(pairs)} stats={stats}")
    ciks = sorted(set(pairs["cik"]))
    con = duckdb.connect()
    cols = ", ".join(_NEEDED)
    holdings = con.execute(
        f"SELECT {cols} FROM read_csv(?, all_varchar=true, sample_size=2000) "
        f"WHERE cik IN ({','.join('?' * len(ciks))})",
        [str(args.holdings), *ciks],
    ).fetchdf()
    con.close()
    print(f"[replay] holdings rows for {len(ciks)} CIKs: {len(holdings)}")
    out = replay_pairs(pairs, holdings)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    summary = summarize(out)
    args.out.with_suffix(".md").write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
