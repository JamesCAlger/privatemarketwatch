"""Build blinded match-gold adjudication packets (chains + entity clusters).

Deterministic stratified sampling (frozen seed via md5 ordering, no RNG).
Chain strata: tier_random (per match tier), fv_jump (anomalous edges),
interior_singleton (missed-link hunting), drift_break (renamed-issuer pairs).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pipeline.match_quality import drift_break_candidates  # noqa: E402

SEED = "20260903"
SAMPLE_COLUMNS = ["packet_id", "packet_type", "stratum", "position_id", "cik"]
JW_LO, JW_HI = 0.86, 0.97


def _packet_id(*parts: str) -> str:
    digest = hashlib.md5(("|".join(parts) + SEED).encode("utf-8")).hexdigest()[:12]
    return f"MGP-{digest}"


def sample_chains(holdings_df, edges_df, *, per_tier=40, n_fv_jump=40,
                  n_interior_singleton=40, n_drift_break=40) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("h", holdings_df)
    con.register("e", edges_df)
    rows: list[dict] = []

    tier_sample = con.execute(f"""
        WITH ranked AS (
            SELECT position_id, cik, match_method,
                   ROW_NUMBER() OVER (
                       PARTITION BY match_method
                       ORDER BY md5(position_id || '{SEED}')) AS rn
            FROM (SELECT DISTINCT position_id, cik, match_method FROM e)
        )
        SELECT DISTINCT position_id, cik, match_method
        FROM ranked WHERE rn <= {per_tier}
        ORDER BY match_method, position_id
    """).df()
    for r in tier_sample.itertuples(index=False):   # sample-sized frame only
        rows.append({"packet_id": _packet_id("chain", "tier_random", r.position_id),
                     "packet_type": "chain", "stratum": "tier_random",
                     "position_id": r.position_id, "cik": str(r.cik)})

    jump = con.execute(f"""
        SELECT DISTINCT position_id, cik FROM e
        WHERE TRY_CAST(begin_fair_value AS DOUBLE) > 0
          AND TRY_CAST(end_fair_value AS DOUBLE) > 0
          AND GREATEST(TRY_CAST(begin_fair_value AS DOUBLE),
                       TRY_CAST(end_fair_value AS DOUBLE))
              / LEAST(TRY_CAST(begin_fair_value AS DOUBLE),
                      TRY_CAST(end_fair_value AS DOUBLE)) > 4.0
        ORDER BY md5(position_id || '{SEED}') LIMIT {n_fv_jump}
    """).df()
    for r in jump.itertuples(index=False):
        rows.append({"packet_id": _packet_id("chain", "fv_jump", r.position_id),
                     "packet_type": "chain", "stratum": "fv_jump",
                     "position_id": r.position_id, "cik": str(r.cik)})

    singles = con.execute(f"""
        WITH bdc AS (
            SELECT cik, report_date, position_id,
                   TRY_CAST(fair_value AS DOUBLE) AS fv
            FROM h WHERE source = 'bdc' AND position_id IS NOT NULL),
        pid1 AS (SELECT position_id FROM bdc GROUP BY position_id HAVING COUNT(*) = 1),
        bounds AS (SELECT cik, MIN(report_date) mn, MAX(report_date) mx
                   FROM bdc GROUP BY cik)
        SELECT b.position_id, b.cik FROM bdc b
        JOIN pid1 p ON b.position_id = p.position_id
        JOIN bounds bd ON b.cik = bd.cik
        WHERE b.fv > 0 AND b.report_date > bd.mn AND b.report_date < bd.mx
        ORDER BY md5(b.position_id || '{SEED}') LIMIT {n_interior_singleton}
    """).df()
    for r in singles.itertuples(index=False):
        rows.append({"packet_id": _packet_id("chain", "interior_singleton", r.position_id),
                     "packet_type": "chain", "stratum": "interior_singleton",
                     "position_id": r.position_id, "cik": str(r.cik)})

    drift = drift_break_candidates(holdings_df)
    if len(drift):
        drift = drift.assign(
            _o=[hashlib.md5((x + SEED).encode()).hexdigest()
                for x in drift["dropped_row_id"]]
        ).sort_values("_o").head(n_drift_break)
        pid_of = holdings_df.set_index("row_id")["position_id"]
        for r in drift.itertuples(index=False):
            rows.append({
                "packet_id": _packet_id("chain", "drift_break", r.dropped_row_id),
                "packet_type": "chain", "stratum": "drift_break",
                "position_id": pid_of.get(r.dropped_row_id, ""),
                "cik": str(r.cik)})

    out = pd.DataFrame(rows, columns=SAMPLE_COLUMNS)
    out = out.drop_duplicates(["stratum", "position_id"])
    return out.sort_values(["stratum", "packet_id"]).reset_index(drop=True)


def sample_entities(holdings_df, *, n_merge_verify=60,
                    n_cross_fund_near_miss=100, n_within_fund=40) -> pd.DataFrame:
    """Sample entity packets for manual adjudication.

    Produces packets with columns:
      - packet_id: unique blinded ID
      - packet_type: "entity"
      - stratum: "entity_merge_verify", "cross_fund_near_miss", "within_fund_name_cluster"
      - cluster_key: entity_id or "nameA||nameB" pair
      - ciks: semicolon-joined sorted CIK list
    """
    con = duckdb.connect()
    con.register("h", holdings_df)
    rows: list[dict] = []

    merge_verify = con.execute(f"""
        WITH clusters AS (
            SELECT entity_id,
                   COUNT(DISTINCT cik) AS n_ciks,
                   COUNT(DISTINCT issuer_name) AS n_names,
                   STRING_AGG(DISTINCT cik, ';' ORDER BY cik) AS ciks
            FROM h
            WHERE entity_id IS NOT NULL AND entity_id <> ''
            GROUP BY entity_id
            HAVING COUNT(DISTINCT cik) > 1 OR COUNT(DISTINCT issuer_name) > 1
        ),
        ranked AS (
            SELECT entity_id, ciks,
                   ROW_NUMBER() OVER (ORDER BY n_ciks DESC,
                                      md5(entity_id || '{SEED}')) AS rn
            FROM clusters
        )
        SELECT entity_id, ciks FROM ranked WHERE rn <= {n_merge_verify}
        ORDER BY entity_id
    """).df()
    for r in merge_verify.itertuples(index=False):
        rows.append({"packet_id": _packet_id("entity", "entity_merge_verify", r.entity_id),
                     "packet_type": "entity", "stratum": "entity_merge_verify",
                     "cluster_key": r.entity_id, "ciks": r.ciks})

    near = con.execute(f"""
        WITH names AS (
            SELECT DISTINCT cik, LOWER(TRIM(issuer_name)) AS nm,
                   COALESCE(entity_id, '') AS eid
            FROM h WHERE source = 'bdc' AND issuer_name IS NOT NULL
        )
        SELECT a.nm AS name_a, b.nm AS name_b,
               a.cik AS cik_a, b.cik AS cik_b
        FROM names a JOIN names b
          ON a.cik < b.cik
         AND LEFT(a.nm, 4) = LEFT(b.nm, 4)
         AND a.nm <> b.nm
         AND (a.eid = '' OR b.eid = '' OR a.eid <> b.eid)
         AND jaro_winkler_similarity(a.nm, b.nm) BETWEEN {JW_LO} AND {JW_HI}
        ORDER BY md5(a.nm || b.nm || '{SEED}')
        LIMIT {n_cross_fund_near_miss}
    """).df()
    for r in near.itertuples(index=False):
        key = f"{r.name_a}||{r.name_b}"
        ciks = ";".join(sorted([str(r.cik_a), str(r.cik_b)]))
        rows.append({"packet_id": _packet_id("entity", "cross_fund_near_miss", key),
                     "packet_type": "entity", "stratum": "cross_fund_near_miss",
                     "cluster_key": key, "ciks": ciks})

    within = con.execute(f"""
        WITH names AS (
            SELECT DISTINCT cik, LOWER(TRIM(issuer_name)) AS nm
            FROM h WHERE source = 'bdc' AND issuer_name IS NOT NULL
        )
        SELECT a.nm AS name_a, b.nm AS name_b, a.cik
        FROM names a JOIN names b
          ON a.cik = b.cik AND a.nm < b.nm
         AND LEFT(a.nm, 4) = LEFT(b.nm, 4)
         AND jaro_winkler_similarity(a.nm, b.nm) BETWEEN {JW_LO} AND {JW_HI}
        ORDER BY md5(a.nm || b.nm || '{SEED}')
        LIMIT {n_within_fund}
    """).df()
    for r in within.itertuples(index=False):
        key = f"{r.name_a}||{r.name_b}"
        rows.append({"packet_id": _packet_id("entity", "within_fund_name_cluster", key),
                     "packet_type": "entity", "stratum": "within_fund_name_cluster",
                     "cluster_key": key, "ciks": str(r.cik)})

    out = pd.DataFrame(rows, columns=["packet_id", "packet_type", "stratum",
                                      "cluster_key", "ciks"])
    out = out.drop_duplicates(["stratum", "cluster_key"])
    return out.sort_values(["stratum", "packet_id"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Packet writer
# ---------------------------------------------------------------------------

PACKET_ROW_FIELDS = [
    "row_id", "report_date", "issuer_name",
    "instrument_description", "bdc_investment_identifier",
    "fair_value", "principal_amount", "interest_rate",
    "basis_spread", "maturity_date", "accession_number",
]

_VERDICT_SCHEMA = """{
  "packet_id": "<string>",
  "packet_type": "<chain|entity>",
  "verdict": "<CONFIRMED|WRONG_MERGE|MISSED_LINK|MIXED|INSUFFICIENT_EVIDENCE>",
  "confidence": <0..1>,
  "edge_verdicts": [
    {
      "edge_index": <int>,
      "verdict": "<CONFIRMED|WRONG|UNCERTAIN>",
      "evidence": [{"accession": "<acc>", "table_index": <int>, "row_index": <int>, "quoted_text": "<str>"}]
    }
  ],
  "proposed_links": [
    {
      "row_id_a": "<string>",
      "row_id_b": "<string>",
      "evidence": [{"accession": "<acc>", "table_index": <int>, "row_index": <int>, "quoted_text": "<str>"}]
    }
  ],
  "evidence": [{"accession": "<acc>", "table_index": <int>, "row_index": <int>, "quoted_text": "<str>"}],
  "rationale": "<string>",
  "escalate": <true|false>
}"""

PROMPT_TEMPLATE = """# Match-Gold Adjudication: {packet_id}

You are a blinded adjudicator. Decide whether the rows in this packet are the
SAME instrument tracked over time (chain packets) or the SAME borrower
(entity packets). You know nothing about how the pipeline linked them, and you
must judge only from the packet rows and the cached SEC filings.

## Your packet
{packet_path}

## How to inspect source filings (cache-only, no network)
For each accession listed in the packet, a bundle file exists under
{filings_dir}. Roam the filing:

    python scripts/review_agent/evidence_cli.py --bundle {filings_dir}/<accession>.json overview
    python scripts/review_agent/evidence_cli.py --bundle {filings_dir}/<accession>.json roam --query "<issuer terms>"
    python scripts/review_agent/evidence_cli.py --bundle {filings_dir}/<accession>.json grid --table N

## Task
{task_text}

## Verdict contract
Write EXACTLY one JSON file to: {verdict_path}
Schema (all keys required unless noted):
{verdict_schema}

Rules:
- Every edge listed in the packet must receive an edge verdict (chain packets).
- A WRONG edge verdict and a WRONG_MERGE packet verdict require at least one
  evidence citation (quoted_text from the filing, or table_index+row_index).
- MISSED_LINK requires proposed_links naming row_ids from the packet.
- Entity packets put packet-level citations in the top-level "evidence" key.
- Chain packets cite inside edge_verdicts; MISSED_LINK links cite inside proposed_links.
- INSUFFICIENT_EVIDENCE with a clear rationale is a correct, non-penalized
  outcome. Never invent citations. Never guess.
- Write the file as UTF-8 WITHOUT BOM using your file-edit tool. Do NOT use
  PowerShell Out-File or Set-Content.
"""

_TASK_TEXT = {
    "chain": (
        "For every edge (begin_row_id -> end_row_id), verify in the two "
        "filings that both rows describe the same instrument: same "
        "borrower, same tranche/lien/type, coherent principal and terms. "
        "Verdict CONFIRMED / WRONG per edge."
    ),
    "interior_singleton": (
        "The single row in `rows` appears in only one "
        "quarter. Check `candidate_rows` (adjacent quarters, "
        "same fund) and the filings: does this instrument "
        "actually continue under a different name? If yes: "
        "MISSED_LINK with proposed_links. If it truly "
        "appears once: CONFIRMED."
    ),
    "drift_break": (
        "Row 1 leaves the portfolio and row 2 appears the next "
        "quarter with similar terms. Same instrument renamed "
        "(MISSED_LINK) or genuinely different (CONFIRMED)?"
    ),
    "entity": (
        "Are all issuer-name variants in `rows` the same borrower "
        "(legal-entity level)? CONFIRMED if yes, WRONG_MERGE if the "
        "cluster mixes distinct companies, MISSED_LINK if variants "
        "shown as separate are actually one borrower."
    ),
}


def _safe_str(v: Any) -> str | None:
    """Return None for pandas/numpy NA-like values, else str."""
    if v is None:
        return None
    import math
    try:
        if math.isnan(float(v)):  # type: ignore[arg-type]
            return None
    except (TypeError, ValueError):
        pass
    s = str(v)
    return None if s.lower() == "nan" else s


def _row_to_dict(row: Any, con: duckdb.DuckDBPyConnection) -> dict:
    """Convert a holdings row (namedtuple or dict-like) to a blinded packet row dict."""
    d: dict = {}
    for f in PACKET_ROW_FIELDS:
        d[f] = _safe_str(getattr(row, f, None))
    return d


def _pull_chain_rows(holdings_df: pd.DataFrame, position_id: str,
                     con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Pull up to 12 most-recent report_date rows for a position_id, sorted ASC."""
    rows = con.execute("""
        WITH dated AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY report_date
                ORDER BY row_id
            ) AS rn_date
            FROM h WHERE position_id = ?
        ),
        top12 AS (
            SELECT DISTINCT report_date
            FROM dated
            ORDER BY report_date DESC
            LIMIT 12
        )
        SELECT d.*
        FROM dated d JOIN top12 t ON d.report_date = t.report_date
        ORDER BY d.report_date ASC, d.row_id ASC
    """, [position_id]).df()
    result = []
    for r in rows.itertuples(index=False):
        d: dict = {}
        for f in PACKET_ROW_FIELDS:
            d[f] = _safe_str(getattr(r, f, None))
        result.append(d)
    return result


def _resolve_edges(edges_df: pd.DataFrame, position_id: str,
                   rows: list[dict]) -> list[dict]:
    """Resolve edge row (begin/end report dates) to row_ids from the rows list."""
    # Build lookup: report_date -> list of {row_id, fair_value}
    from collections import defaultdict
    date_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        date_rows[r["report_date"]].append(r)

    # Get edges for this position_id
    pos_edges = edges_df[edges_df["position_id"].astype(str) == str(position_id)]
    resolved: list[dict] = []
    for ei, e in enumerate(pos_edges.itertuples(index=False)):
        bdate = _safe_str(getattr(e, "begin_report_date", None))
        edate = _safe_str(getattr(e, "end_report_date", None))
        bfv = _safe_str(getattr(e, "begin_fair_value", None))
        efv = _safe_str(getattr(e, "end_fair_value", None))

        # Pick begin row_id
        begin_rid = _pick_row_id(date_rows.get(bdate, []), bfv)
        end_rid = _pick_row_id(date_rows.get(edate, []), efv)

        resolved.append({
            "edge_index": ei,
            "begin_row_id": begin_rid,
            "end_row_id": end_rid,
        })
    return resolved


def _pick_row_id(candidates: list[dict], fv_match: str | None) -> str | None:
    """Pick a row_id from candidates by FV exact match first, then lowest row_id."""
    if not candidates:
        return None
    if fv_match is not None:
        for c in candidates:
            if c.get("fair_value") == fv_match:
                return c["row_id"]
    # fallback: lowest row_id (deterministic)
    return min(c["row_id"] for c in candidates if c.get("row_id"))


def _pull_candidate_rows(holdings_df: pd.DataFrame, cik: str,
                         singleton_row: dict,
                         con: duckdb.DuckDBPyConnection) -> list[dict]:
    """Pull up to 8 same-CIK rows from immediately prev/next report_date, ordered by ABS(fv diff)."""
    singleton_date = singleton_row.get("report_date") or ""
    try:
        singleton_fv = float(singleton_row.get("fair_value") or 0)
    except (ValueError, TypeError):
        singleton_fv = 0.0

    candidates = con.execute("""
        WITH dates AS (
            SELECT DISTINCT report_date FROM h
            WHERE cik = ? AND report_date <> ?
            ORDER BY ABS(DATEDIFF('day',
                TRY_CAST(report_date AS DATE),
                TRY_CAST(? AS DATE)))
            LIMIT 2
        )
        SELECT h.*
        FROM h JOIN dates d ON h.report_date = d.report_date
        WHERE h.cik = ?
        ORDER BY ABS(TRY_CAST(h.fair_value AS DOUBLE) - ?) ASC
        LIMIT 8
    """, [cik, singleton_date, singleton_date, cik, singleton_fv]).df()

    result = []
    for r in candidates.itertuples(index=False):
        d: dict = {}
        for f in PACKET_ROW_FIELDS:
            d[f] = _safe_str(getattr(r, f, None))
        result.append(d)
    return result


def _pull_entity_rows(holdings_df: pd.DataFrame, ciks: list[str],
                      con: duckdb.DuckDBPyConnection,
                      cluster_key: str, stratum: str) -> list[dict]:
    """Pull up to 8 rows per issuer-name variant, most-recent first."""
    if stratum == "entity_merge_verify":
        # cluster_key is an entity_id — get all name variants
        df = con.execute("""
            WITH variants AS (
                SELECT DISTINCT issuer_name FROM h
                WHERE entity_id = ?
            ),
            ranked AS (
                SELECT h.*, ROW_NUMBER() OVER (
                    PARTITION BY h.issuer_name
                    ORDER BY h.report_date DESC, h.row_id ASC
                ) AS rn
                FROM h JOIN variants v ON h.issuer_name = v.issuer_name
                WHERE entity_id = ?
            )
            SELECT * FROM ranked WHERE rn <= 8
            ORDER BY issuer_name, report_date DESC, row_id ASC
        """, [cluster_key, cluster_key]).df()
    else:
        # cluster_key is "name_a||name_b"; ciks is the list of CIKs
        parts = cluster_key.split("||", 1)
        name_a = parts[0] if parts else ""
        name_b = parts[1] if len(parts) > 1 else ""
        cik_str = "','".join(ciks)
        df = con.execute(f"""
            WITH variants AS (
                SELECT DISTINCT issuer_name FROM h
                WHERE cik IN ('{cik_str}')
                  AND (LOWER(TRIM(issuer_name)) = ? OR LOWER(TRIM(issuer_name)) = ?)
            ),
            ranked AS (
                SELECT h.*, ROW_NUMBER() OVER (
                    PARTITION BY h.issuer_name
                    ORDER BY h.report_date DESC, h.row_id ASC
                ) AS rn
                FROM h JOIN variants v ON LOWER(TRIM(h.issuer_name)) = LOWER(TRIM(v.issuer_name))
                WHERE h.cik IN ('{cik_str}')
            )
            SELECT * FROM ranked WHERE rn <= 8
            ORDER BY issuer_name, report_date DESC, row_id ASC
        """, [name_a, name_b]).df()

    result = []
    for r in df.itertuples(index=False):
        d: dict = {}
        for f in PACKET_ROW_FIELDS:
            d[f] = _safe_str(getattr(r, f, None))
        result.append(d)
    return result


def _has_cached_filing(cik: str, accession: str) -> bool:
    """Check whether the cached HTML filing exists."""
    try:
        from pipeline.html_soi_evidence import _html_path
        return _html_path("BDC", cik, accession).exists()
    except Exception:
        return False


def _write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def write_batch(
    holdings_df: pd.DataFrame,
    edges_df: pd.DataFrame,
    chain_sample: pd.DataFrame,
    entity_sample: pd.DataFrame,
    batch_dir: Path,
) -> dict:
    """Write blinded adjudication packets, prompts, mini-bundles, and worklist.

    Returns {"n_packets": int, "n_missing_filing": int, "worklist_path": str}.
    """
    # --- ensure required columns exist on holdings_df (for tests) -----------
    for col in PACKET_ROW_FIELDS:
        if col not in holdings_df.columns:
            holdings_df = holdings_df.copy()
            holdings_df[col] = None

    # --- subdirectory layout -------------------------------------------------
    packets_dir = batch_dir / "packets"
    meta_dir = batch_dir / "packets_meta"
    filings_dir = batch_dir / "filings"
    prompts_dir = batch_dir / "prompts"
    verdicts_dir = batch_dir / "verdicts"
    for d in (packets_dir, meta_dir, filings_dir, prompts_dir, verdicts_dir):
        d.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    con.register("h", holdings_df)

    worklist_rows: list[dict] = []
    n_missing = 0

    # ---- helper for drift_break row extraction using dropped_row_id ---------
    # Build a map: dropped_row_id -> (dropped_row, start_row) from drift_break_candidates
    _drift_map: dict[str, tuple[dict, dict]] = {}
    if len(chain_sample) and "drift_break" in chain_sample["stratum"].values:
        drift_df = drift_break_candidates(holdings_df)
        row_lookup = holdings_df.set_index("row_id")
        for dr in drift_df.itertuples(index=False):
            dropped_rid = str(dr.dropped_row_id)
            start_rid = str(dr.start_row_id)

            def _row_dict(rid: str) -> dict:
                if rid in row_lookup.index:
                    d = {}
                    for f in PACKET_ROW_FIELDS:
                        d[f] = _safe_str(row_lookup.at[rid, f]
                                         if f in row_lookup.columns else None)
                    return d
                return {}

            _drift_map[dropped_rid] = (_row_dict(dropped_rid), _row_dict(start_rid))

    # ---- chain packets ------------------------------------------------------
    for sr in chain_sample.itertuples(index=False):
        pid = str(sr.packet_id)
        stratum = str(sr.stratum)
        cik = str(sr.cik)
        position_id = str(sr.position_id) if hasattr(sr, "position_id") else ""

        # Build rows + edges
        if stratum == "drift_break":
            dropped_rid = position_id  # packet_id was built from dropped_row_id
            # For drift_break, position_id in sample is the dropped_row_id
            # (see sample_chains: position_id = pid_of.get(r.dropped_row_id, ""))
            # but we stored the dropped_row_id separately; recover from _drift_map
            # We need to find the dropped_row_id for this packet:
            # packet_id = _packet_id("chain", "drift_break", dropped_row_id)
            # So we reverse-search _drift_map by packet_id
            pkt_rows: list[dict] = []
            candidate_rows: list[dict] = []
            for d_rid, (dr_dict, st_dict) in _drift_map.items():
                if _packet_id("chain", "drift_break", d_rid) == pid:
                    pkt_rows = [r for r in [dr_dict, st_dict] if r]
                    break
        elif stratum == "interior_singleton":
            all_pos_rows = _pull_chain_rows(holdings_df, position_id, con)
            # singleton: should be just one row
            pkt_rows = all_pos_rows[:1]
            candidate_rows = _pull_candidate_rows(holdings_df, cik,
                                                   pkt_rows[0] if pkt_rows else {},
                                                   con)
        else:
            # tier_random or fv_jump: full chain rows
            pkt_rows = _pull_chain_rows(holdings_df, position_id, con)
            candidate_rows = []

        # Truncation flag
        truncated = len(pkt_rows) >= 12

        # Resolve edges (not for singleton/drift_break)
        if stratum in ("interior_singleton", "drift_break"):
            resolved_edges: list[dict] = []
            sidecar_edges: list[dict] = []
        else:
            resolved_edges = _resolve_edges(edges_df, position_id, pkt_rows)
            # Sidecar: include match_method/match_score from edges_df
            pos_edges = edges_df[edges_df["position_id"].astype(str) == str(position_id)]
            sidecar_edges = []
            for ei2, e2 in enumerate(pos_edges.itertuples(index=False)):
                sidecar_edges.append({
                    "edge_index": ei2,
                    "match_method": _safe_str(getattr(e2, "match_method", None)),
                    "match_score": _safe_str(getattr(e2, "match_score", None)),
                })

        # Accession list
        accessions = sorted({
            r["accession_number"]
            for r in pkt_rows + candidate_rows
            if r.get("accession_number")
        })

        # Filing bundles mapping
        filing_bundles = {
            acc: f"filings/{pid}/{acc}.json"
            for acc in accessions
        }

        # Check filing cache
        all_cached = all(_has_cached_filing(cik, acc) for acc in accessions) if accessions else False
        if accessions and not all_cached:
            n_missing += 1

        # Build packet JSON (blinded — no match_method/match_score)
        packet: dict = {
            "schema_version": "match-gold-packet.v1",
            "packet_id": pid,
            "packet_type": "chain",
            "cik": cik,
            "rows": pkt_rows,
            "edges": resolved_edges,
            "candidate_rows": candidate_rows,
            "accessions": accessions,
            "filing_bundles": filing_bundles,
        }
        if truncated:
            packet["truncated"] = True

        _write_json(packets_dir / f"{pid}.json", packet)

        # Sidecar meta (with tier for scorer)
        meta: dict = {
            "packet_id": pid,
            "packet_type": "chain",
            "stratum": stratum,
            "edges": sidecar_edges,
        }
        _write_json(meta_dir / f"{pid}.json", meta)

        # Mini-bundles per accession
        pkt_filing_dir = filings_dir / pid
        pkt_filing_dir.mkdir(parents=True, exist_ok=True)
        for acc in accessions:
            # Find matching rows for this accession
            acc_rows = [r for r in pkt_rows + candidate_rows
                        if r.get("accession_number") == acc]
            # Use earliest report_date in acc_rows
            dates = sorted({r["report_date"] for r in acc_rows if r.get("report_date")})
            rpt_date = dates[0] if dates else ""
            bundle = {
                "schema_version": "review-bundle.v1",
                "engine": "match_gold",
                "cik": cik,
                "report_date": rpt_date,
                "evidence_items": [
                    {
                        "evidence_id": "rows",
                        "description": "packet rows for this filing",
                        "data": [{"accession_number": acc}],
                    }
                ],
            }
            _write_json(pkt_filing_dir / f"{acc}.json", bundle)

        # Prompt
        task_text = _TASK_TEXT.get(stratum, _TASK_TEXT["chain"])
        filings_rel = f"filings/{pid}"
        prompt = PROMPT_TEMPLATE.format(
            packet_id=pid,
            packet_path=f"packets/{pid}.json",
            filings_dir=filings_rel,
            task_text=task_text,
            verdict_path=f"verdicts/{pid}.json",
            verdict_schema=_VERDICT_SCHEMA,
        )
        (prompts_dir / f"{pid}.md").write_text(prompt, encoding="utf-8")

        worklist_rows.append({
            "packet_id": pid,
            "packet_type": "chain",
            "stratum": stratum,
            "cik": cik,
            "n_rows": len(pkt_rows),
            "n_edges": len(resolved_edges),
            "prompt_path": str(prompts_dir / f"{pid}.md"),
            "packet_path": str(packets_dir / f"{pid}.json"),
            "verdict_path": str(verdicts_dir / f"{pid}.json"),
            "has_cached_filing": all_cached,
        })

    # ---- entity packets -----------------------------------------------------
    for sr in entity_sample.itertuples(index=False):
        pid = str(sr.packet_id)
        stratum = str(sr.stratum)
        cluster_key = str(sr.cluster_key)
        ciks_raw = str(sr.ciks)
        ciks_list = [c.strip() for c in ciks_raw.split(";") if c.strip()]
        cik_repr = ciks_list[0] if ciks_list else ""

        pkt_rows = _pull_entity_rows(holdings_df, ciks_list, con,
                                     cluster_key, stratum)

        accessions = sorted({
            r["accession_number"]
            for r in pkt_rows
            if r.get("accession_number")
        })
        filing_bundles = {
            acc: f"filings/{pid}/{acc}.json"
            for acc in accessions
        }

        all_cached = all(_has_cached_filing(cik_repr, acc) for acc in accessions) if accessions else False
        if accessions and not all_cached:
            n_missing += 1

        packet = {
            "schema_version": "match-gold-packet.v1",
            "packet_id": pid,
            "packet_type": "entity",
            "cik": cik_repr,
            "rows": pkt_rows,
            "edges": [],
            "candidate_rows": [],
            "accessions": accessions,
            "filing_bundles": filing_bundles,
        }
        _write_json(packets_dir / f"{pid}.json", packet)

        meta = {
            "packet_id": pid,
            "packet_type": "entity",
            "stratum": stratum,
            "edges": [],
        }
        _write_json(meta_dir / f"{pid}.json", meta)

        pkt_filing_dir = filings_dir / pid
        pkt_filing_dir.mkdir(parents=True, exist_ok=True)
        for acc in accessions:
            acc_rows = [r for r in pkt_rows if r.get("accession_number") == acc]
            dates = sorted({r["report_date"] for r in acc_rows if r.get("report_date")})
            rpt_date = dates[0] if dates else ""
            bundle = {
                "schema_version": "review-bundle.v1",
                "engine": "match_gold",
                "cik": cik_repr,
                "report_date": rpt_date,
                "evidence_items": [
                    {
                        "evidence_id": "rows",
                        "description": "packet rows for this filing",
                        "data": [{"accession_number": acc}],
                    }
                ],
            }
            _write_json(pkt_filing_dir / f"{acc}.json", bundle)

        task_text = _TASK_TEXT.get(stratum, _TASK_TEXT["entity"])
        filings_rel = f"filings/{pid}"
        prompt = PROMPT_TEMPLATE.format(
            packet_id=pid,
            packet_path=f"packets/{pid}.json",
            filings_dir=filings_rel,
            task_text=task_text,
            verdict_path=f"verdicts/{pid}.json",
            verdict_schema=_VERDICT_SCHEMA,
        )
        (prompts_dir / f"{pid}.md").write_text(prompt, encoding="utf-8")

        worklist_rows.append({
            "packet_id": pid,
            "packet_type": "entity",
            "stratum": stratum,
            "cik": cik_repr,
            "n_rows": len(pkt_rows),
            "n_edges": 0,
            "prompt_path": str(prompts_dir / f"{pid}.md"),
            "packet_path": str(packets_dir / f"{pid}.json"),
            "verdict_path": str(verdicts_dir / f"{pid}.json"),
            "has_cached_filing": all_cached,
        })

    # ---- worklist CSV -------------------------------------------------------
    worklist_rows.sort(key=lambda r: r["packet_id"])
    worklist_path = batch_dir / "worklist.csv"
    if worklist_rows:
        fieldnames = ["packet_id", "packet_type", "stratum", "cik",
                      "n_rows", "n_edges", "prompt_path", "packet_path",
                      "verdict_path", "has_cached_filing"]
        with worklist_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(worklist_rows)
    else:
        worklist_path.write_text(
            "packet_id,packet_type,stratum,cik,n_rows,n_edges,"
            "prompt_path,packet_path,verdict_path,has_cached_filing\n",
            encoding="utf-8",
        )

    return {
        "n_packets": len(worklist_rows),
        "n_missing_filing": n_missing,
        "worklist_path": str(worklist_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build blinded match-gold adjudication packets."
    )
    parser.add_argument("--batch-id", required=True,
                        help="Batch identifier, e.g. mg1")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory (default: config.MATCH_GOLD_DIR / batch_id)")
    parser.add_argument("--max-chains", type=int, default=None,
                        help="Cap on chain packets per stratum")
    parser.add_argument("--max-entities", type=int, default=None,
                        help="Cap on entity packets total")
    args = parser.parse_args()

    from pipeline import config
    from pipeline.cohort_guard import load_cohort_ciks

    out_dir = Path(args.out_dir) if args.out_dir else (config.MATCH_GOLD_DIR / args.batch_id)

    # Load production CSVs
    _con = duckdb.connect()
    holdings_df = _con.execute(
        f"SELECT * FROM read_csv_auto('{config.UNIFIED_HOLDINGS_FILE}', all_varchar=true)"
    ).df()
    edges_df = _con.execute(
        f"SELECT * FROM read_csv_auto('{config.POSITION_MATCHES_FILE}', all_varchar=true)"
    ).df()

    # Filter to cohort CIKs
    cohort = load_cohort_ciks()
    holdings_df = holdings_df[holdings_df["cik"].isin(cohort)].reset_index(drop=True)

    per_tier = args.max_chains or 40
    chain_sample = sample_chains(
        holdings_df, edges_df,
        per_tier=per_tier,
        n_fv_jump=per_tier,
        n_interior_singleton=per_tier,
        n_drift_break=per_tier,
    )
    n_ent = args.max_entities or 60
    entity_sample = sample_entities(
        holdings_df,
        n_merge_verify=n_ent,
        n_cross_fund_near_miss=n_ent,
        n_within_fund=n_ent,
    )

    stats = write_batch(holdings_df, edges_df, chain_sample, entity_sample, out_dir)
    print(f"n_packets={stats['n_packets']}  n_missing_filing={stats['n_missing_filing']}")
    print(f"worklist: {stats['worklist_path']}")


if __name__ == "__main__":
    main()
