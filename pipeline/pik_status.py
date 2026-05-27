"""Build position-level current PIK status and transition CSVs."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd

from pipeline.config import (
    BDC_POSITION_PIK_EVIDENCE_FILE,
    PIK_SCHEDULE_PROXY_SUMMARY_FILE,
    PIK_SCHEDULE_PROXY_TRANSITIONS_FILE,
    PIK_TRANSITIONS_FILE,
    POSITION_PIK_STATUS_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

STATUS_COLUMNS = [
    "holding_row_id", "source", "cik", "entity_name", "accession_number",
    "report_date", "report_quarter", "issuer_name", "instrument_description",
    "position_id", "fair_value", "index_classification",
    "pik_current_status", "pik_current_flag", "pik_current_evidence",
    "pik_current_amount", "pik_terms_flag", "pik_terms_rate",
]

TRANSITION_COLUMNS = [
    "transition_type", "source", "cik", "entity_name", "position_id",
    "prior_report_date", "current_report_date", "prior_status",
    "current_status", "prior_evidence", "current_evidence",
    "prior_fair_value", "current_fair_value",
]

SCHEDULE_PROXY_SUMMARY_COLUMNS = [
    "scope", "source", "index_classification", "report_date",
    "report_quarter", "total_rows", "pik_terms_rows",
    "pik_terms_row_pct", "total_fair_value", "pik_terms_fair_value",
    "pik_terms_fair_value_pct", "unique_positions",
    "pik_terms_unique_positions", "first_seen_with_pik_terms_rows",
    "first_seen_with_pik_terms_positions",
]

SCHEDULE_PROXY_TRANSITION_COLUMNS = [
    "transition_type", "source", "cik", "entity_name", "position_id",
    "prior_report_date", "current_report_date", "issuer_name",
    "index_classification", "prior_pik_terms_flag",
    "current_pik_terms_flag", "prior_pik_terms_rate",
    "current_pik_terms_rate", "prior_fair_value", "current_fair_value",
]


def _quarter_label(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    return dates.dt.year.astype("Int64").astype(str) + "q" + dates.dt.quarter.astype("Int64").astype(str)


def _normalize_identifier(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def _normalize_cik(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.replace(r"[^0-9]", "", regex=True).str.zfill(10)


def _bool_text(series: pd.Series) -> pd.Series:
    return series.map({True: "True", False: "False"}).fillna("")


def _parse_bool_series(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(["true", "1", "yes", "y"])
    )


def _amount_summary(series: pd.Series) -> float | None:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return None
    return float(vals.sum())


def _aggregate_evidence(evidence_df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    if evidence_df.empty:
        return pd.DataFrame(columns=key_cols + ["_ev_status", "_ev_evidence", "_ev_amount"])

    grouped = evidence_df.groupby(key_cols, dropna=False)
    agg = grouped.agg(
        _ev_amount=("amount", _amount_summary),
        _positive=("amount", lambda s: (pd.to_numeric(s, errors="coerce").fillna(0) > 0).any()),
        _kinds=("evidence_kind", lambda s: "|".join(sorted(set(str(x) for x in s if str(x) and str(x) != "nan")))),
    ).reset_index()
    agg["_ev_status"] = agg["_positive"].map({True: "paying", False: "not_paying"})
    agg["_ev_evidence"] = agg["_kinds"].where(agg["_kinds"] != "", "bdc_position_pik_income_zero")
    return agg[key_cols + ["_ev_status", "_ev_evidence", "_ev_amount"]]


def _prepare_bdc_evidence(evidence_df: pd.DataFrame) -> pd.DataFrame:
    if evidence_df.empty:
        return pd.DataFrame(columns=[
            "cik_norm", "accession_number", "report_date", "period",
            "dimensions_raw", "matched_identifier_norm", "amount", "evidence_kind",
        ])
    ev = evidence_df.copy()
    if "position_level" in ev.columns:
        ev = ev[ev["position_level"].astype(str).str.lower().isin(["true", "1", "yes"])]
    ev["cik_norm"] = _normalize_cik(ev.get("cik", pd.Series(dtype=str)))
    ev["matched_identifier_norm"] = _normalize_identifier(ev.get("matched_identifier", pd.Series(dtype=str)))
    for col in ["accession_number", "report_date", "period", "dimensions_raw", "evidence_kind"]:
        if col not in ev.columns:
            ev[col] = ""
    ev["amount"] = pd.to_numeric(ev.get("amount", pd.Series(dtype=str)), errors="coerce")
    return ev


def _match_bdc_evidence(status: pd.DataFrame, evidence_df: pd.DataFrame) -> pd.DataFrame:
    """Attach BDC evidence using dimensions, exact identifier, then 1:1 identifier."""
    status = status.copy()
    status["_match_rank"] = 999
    status["_ev_status"] = ""
    status["_ev_evidence"] = ""
    status["_ev_amount"] = pd.NA

    ev = _prepare_bdc_evidence(evidence_df)
    if ev.empty:
        return status

    bdc_mask = status["source"].str.lower() == "bdc"
    base_cols = ["holding_row_id", "cik_norm", "accession_number", "report_date"]

    # 1. Exact raw dimension path.
    ev_dim = _aggregate_evidence(
        ev[ev["dimensions_raw"].fillna("") != ""],
        ["cik_norm", "accession_number", "report_date", "dimensions_raw"],
    )
    dim_merge = status.loc[bdc_mask, base_cols + ["bdc_dimensions_raw"]].merge(
        ev_dim,
        left_on=["cik_norm", "accession_number", "report_date", "bdc_dimensions_raw"],
        right_on=["cik_norm", "accession_number", "report_date", "dimensions_raw"],
        how="left",
    )
    status = _apply_matches(status, dim_merge, rank=1)

    # 2. Exact normalized identifier.
    ev_id = _aggregate_evidence(
        ev[ev["matched_identifier_norm"] != ""],
        ["cik_norm", "accession_number", "report_date", "matched_identifier_norm"],
    )
    id_merge = status.loc[bdc_mask, base_cols + ["bdc_identifier_norm"]].merge(
        ev_id,
        left_on=["cik_norm", "accession_number", "report_date", "bdc_identifier_norm"],
        right_on=["cik_norm", "accession_number", "report_date", "matched_identifier_norm"],
        how="left",
    )
    status = _apply_matches(status, id_merge, rank=2)

    # 3. One-to-one normalized identifier within filing/report date.
    id_counts = ev[ev["matched_identifier_norm"] != ""].groupby(
        ["cik_norm", "accession_number", "report_date", "matched_identifier_norm"],
        dropna=False,
    ).size().reset_index(name="_ev_count")
    holding_counts = status.loc[bdc_mask & (status["bdc_identifier_norm"] != "")].groupby(
        ["cik_norm", "accession_number", "report_date", "bdc_identifier_norm"],
        dropna=False,
    ).size().reset_index(name="_holding_count")
    one_to_one_keys = holding_counts.merge(
        id_counts,
        left_on=["cik_norm", "accession_number", "report_date", "bdc_identifier_norm"],
        right_on=["cik_norm", "accession_number", "report_date", "matched_identifier_norm"],
        how="inner",
    )
    one_to_one_keys = one_to_one_keys[
        (one_to_one_keys["_holding_count"] == 1) & (one_to_one_keys["_ev_count"] == 1)
    ][["cik_norm", "accession_number", "report_date", "bdc_identifier_norm"]]
    if not one_to_one_keys.empty:
        ev_oto = ev_id.rename(columns={"matched_identifier_norm": "bdc_identifier_norm"})
        oto = status.loc[bdc_mask, base_cols + ["bdc_identifier_norm"]].merge(
            one_to_one_keys,
            on=["cik_norm", "accession_number", "report_date", "bdc_identifier_norm"],
            how="inner",
        ).merge(
            ev_oto,
            on=["cik_norm", "accession_number", "report_date", "bdc_identifier_norm"],
            how="left",
        )
        status = _apply_matches(status, oto, rank=3)

    return status


def _apply_matches(status: pd.DataFrame, matches: pd.DataFrame, rank: int) -> pd.DataFrame:
    if matches.empty or "_ev_status" not in matches.columns:
        return status
    usable = matches[matches["_ev_status"].notna() & (matches["_ev_status"] != "")]
    if usable.empty:
        return status
    usable = usable.sort_values(["holding_row_id"], kind="mergesort").drop_duplicates("holding_row_id")
    idx = status["holding_row_id"].isin(usable["holding_row_id"]) & (status["_match_rank"] > rank)
    if not idx.any():
        return status
    mapped = usable.set_index("holding_row_id")
    ids = status.loc[idx, "holding_row_id"]
    status.loc[idx, "_match_rank"] = rank
    status.loc[idx, "_ev_status"] = ids.map(mapped["_ev_status"]).values
    status.loc[idx, "_ev_evidence"] = ids.map(mapped["_ev_evidence"]).values
    status.loc[idx, "_ev_amount"] = ids.map(mapped["_ev_amount"]).values
    return status


def build_position_pik_status(
    unified_df: pd.DataFrame | None = None,
    bdc_evidence_df: pd.DataFrame | None = None,
    output_path: Path = POSITION_PIK_STATUS_FILE,
    transitions_path: Path = PIK_TRANSITIONS_FILE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build ``position_pik_status.csv`` and ``pik_transitions.csv``."""
    t0 = time.time()
    if unified_df is None:
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
    if bdc_evidence_df is None:
        if BDC_POSITION_PIK_EVIDENCE_FILE.exists():
            bdc_evidence_df = pd.read_csv(BDC_POSITION_PIK_EVIDENCE_FILE, dtype=str)
        else:
            bdc_evidence_df = pd.DataFrame()

    h = unified_df.copy().reset_index(drop=True)
    h["holding_row_id"] = h.index.astype(str)
    h["cik_norm"] = _normalize_cik(h.get("cik", pd.Series(dtype=str)))
    h["report_quarter"] = _quarter_label(h.get("report_date", pd.Series(dtype=str)))
    h["bdc_identifier_norm"] = _normalize_identifier(h.get("bdc_investment_identifier", pd.Series(dtype=str)))
    h["pik_terms_rate"] = pd.to_numeric(h.get("pik_rate", pd.Series(dtype=str)), errors="coerce")
    h["pik_terms_flag_bool"] = h["pik_terms_rate"].fillna(0) > 0

    for col in [
        "source", "entity_name", "accession_number", "report_date",
        "issuer_name", "instrument_description", "position_id", "fair_value",
        "index_classification", "bdc_dimensions_raw", "nport_is_paid_in_kind",
    ]:
        if col not in h.columns:
            h[col] = ""

    h["pik_current_status"] = "unknown"
    h["pik_current_evidence"] = "none"
    h["pik_current_amount"] = pd.NA

    nport_mask = h["source"].str.lower() == "nport"
    nport_flag = h["nport_is_paid_in_kind"].fillna("").astype(str).str.strip().str.upper()
    h.loc[nport_mask & (nport_flag == "Y"), "pik_current_status"] = "paying"
    h.loc[nport_mask & (nport_flag == "Y"), "pik_current_evidence"] = "nport_paid_in_kind_flag"
    h.loc[nport_mask & (nport_flag == "N"), "pik_current_status"] = "not_paying"
    h.loc[nport_mask & (nport_flag == "N"), "pik_current_evidence"] = "nport_paid_in_kind_flag"

    h = _match_bdc_evidence(h, bdc_evidence_df)
    bdc_has_ev = h["_ev_status"].fillna("") != ""
    h.loc[bdc_has_ev, "pik_current_status"] = h.loc[bdc_has_ev, "_ev_status"]
    h.loc[bdc_has_ev, "pik_current_evidence"] = h.loc[bdc_has_ev, "_ev_evidence"]
    h.loc[bdc_has_ev, "pik_current_amount"] = h.loc[bdc_has_ev, "_ev_amount"]

    terms_only = (
        h["pik_terms_flag_bool"]
        & (h["pik_current_status"] == "unknown")
    )
    h.loc[terms_only, "pik_current_evidence"] = "terms_only"
    h["pik_current_flag"] = h["pik_current_status"].map({"paying": True, "not_paying": False})
    h["pik_terms_flag"] = _bool_text(h["pik_terms_flag_bool"])
    h["pik_current_flag"] = _bool_text(h["pik_current_flag"])

    status = h.copy()
    for col in STATUS_COLUMNS:
        if col not in status.columns:
            status[col] = ""
    status = status[STATUS_COLUMNS].sort_values(
        ["source", "cik", "report_date", "position_id", "holding_row_id"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)

    transitions = build_pik_transitions(status)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    status.to_csv(output_path, index=False)
    transitions_path.parent.mkdir(parents=True, exist_ok=True)
    transitions.to_csv(transitions_path, index=False)

    logger.info(
        "PIK status: %d holding rows, %d transitions in %.1f s",
        len(status), len(transitions), time.time() - t0,
    )
    return status, transitions


def build_pik_transitions(status_df: pd.DataFrame) -> pd.DataFrame:
    """Build observable ``not_paying -> paying`` and unknown evidence transitions."""
    if status_df.empty:
        return pd.DataFrame(columns=TRANSITION_COLUMNS)

    df = status_df.copy()
    df = df[df["position_id"].fillna("").astype(str).str.strip() != ""].copy()
    if df.empty:
        logger.warning("PIK transitions skipped: no nonblank position_id coverage")
        return pd.DataFrame(columns=TRANSITION_COLUMNS)

    df["_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df = df.sort_values(["source", "cik", "position_id", "_date"], kind="mergesort")
    group_cols = ["source", "cik", "position_id"]
    for col in ["report_date", "pik_current_status", "pik_current_evidence", "fair_value", "entity_name"]:
        df[f"prior_{col}"] = df.groupby(group_cols, dropna=False)[col].shift(1)

    pairs = df[df["prior_pik_current_status"].notna()].copy()
    main = pairs[
        (pairs["prior_pik_current_status"] == "not_paying")
        & (pairs["pik_current_status"] == "paying")
    ].copy()
    main["transition_type"] = "started_paying_pik"

    new_ev = pairs[
        (pairs["prior_pik_current_status"] == "unknown")
        & (pairs["pik_current_status"] == "paying")
    ].copy()
    new_ev["transition_type"] = "new_pik_evidence"

    out = pd.concat([main, new_ev], ignore_index=True)
    if out.empty:
        return pd.DataFrame(columns=TRANSITION_COLUMNS)

    result = pd.DataFrame({
        "transition_type": out["transition_type"],
        "source": out["source"],
        "cik": out["cik"],
        "entity_name": out["entity_name"].fillna(out["prior_entity_name"]),
        "position_id": out["position_id"],
        "prior_report_date": out["prior_report_date"],
        "current_report_date": out["report_date"],
        "prior_status": out["prior_pik_current_status"],
        "current_status": out["pik_current_status"],
        "prior_evidence": out["prior_pik_current_evidence"],
        "current_evidence": out["pik_current_evidence"],
        "prior_fair_value": out["prior_fair_value"],
        "current_fair_value": out["fair_value"],
    })
    return result[TRANSITION_COLUMNS].sort_values(
        ["transition_type", "source", "cik", "position_id", "current_report_date"],
        kind="mergesort",
    ).reset_index(drop=True)


def _prepare_schedule_proxy_status(status_df: pd.DataFrame) -> pd.DataFrame:
    df = status_df.copy()
    for col in [
        "source", "cik", "entity_name", "position_id", "report_date",
        "report_quarter", "issuer_name", "index_classification",
        "fair_value", "pik_terms_flag", "pik_terms_rate",
    ]:
        if col not in df.columns:
            df[col] = ""
    if "report_quarter" not in status_df.columns or df["report_quarter"].fillna("").eq("").all():
        df["report_quarter"] = _quarter_label(df["report_date"])
    df["_date"] = pd.to_datetime(df["report_date"], errors="coerce")
    df["_fair_value"] = pd.to_numeric(df["fair_value"], errors="coerce").fillna(0.0)
    df["_pik_terms_rate"] = pd.to_numeric(df["pik_terms_rate"], errors="coerce")
    df["_pik_terms_flag"] = _parse_bool_series(df["pik_terms_flag"]) | df["_pik_terms_rate"].fillna(0).gt(0)
    df["_pik_terms_fair_value"] = df["_fair_value"].where(df["_pik_terms_flag"], 0.0)
    df["_has_position_id"] = df["position_id"].fillna("").astype(str).str.strip().ne("")
    return df


def _first_seen_with_terms_counts(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    base = df[df["_has_position_id"]].sort_values(
        ["source", "cik", "position_id", "_date"],
        kind="mergesort",
    ).copy()
    if base.empty:
        return pd.DataFrame(columns=group_cols + [
            "first_seen_with_pik_terms_rows",
            "first_seen_with_pik_terms_positions",
        ])
    first_idx = base.groupby(["source", "cik", "position_id"], dropna=False).head(1).index
    first = base.loc[first_idx]
    first = first[first["_pik_terms_flag"]]
    if first.empty:
        return pd.DataFrame(columns=group_cols + [
            "first_seen_with_pik_terms_rows",
            "first_seen_with_pik_terms_positions",
        ])
    return first.groupby(group_cols, dropna=False).agg(
        first_seen_with_pik_terms_rows=("position_id", "size"),
        first_seen_with_pik_terms_positions=("position_id", "nunique"),
    ).reset_index()


def _build_schedule_summary_for_scope(
    df: pd.DataFrame,
    scope: str,
    group_cols: list[str],
) -> pd.DataFrame:
    work = df.copy()
    for col in group_cols:
        if col not in work.columns:
            work[col] = "ALL"
    grouped = work.groupby(group_cols, dropna=False)
    summary = grouped.agg(
        total_rows=("position_id", "size"),
        pik_terms_rows=("_pik_terms_flag", "sum"),
        total_fair_value=("_fair_value", "sum"),
        pik_terms_fair_value=("_pik_terms_fair_value", "sum"),
        unique_positions=("position_id", lambda s: s[work.loc[s.index, "_has_position_id"]].nunique()),
        pik_terms_unique_positions=(
            "position_id",
            lambda s: s[
                work.loc[s.index, "_has_position_id"]
                & work.loc[s.index, "_pik_terms_flag"]
            ].nunique(),
        ),
    ).reset_index()
    summary["pik_terms_row_pct"] = summary["pik_terms_rows"] / summary["total_rows"].where(summary["total_rows"] != 0)
    summary["pik_terms_fair_value_pct"] = (
        summary["pik_terms_fair_value"]
        / summary["total_fair_value"].where(summary["total_fair_value"] != 0)
    )
    first_seen = _first_seen_with_terms_counts(work, group_cols)
    summary = summary.merge(first_seen, on=group_cols, how="left")
    summary["first_seen_with_pik_terms_rows"] = (
        pd.to_numeric(summary["first_seen_with_pik_terms_rows"], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    summary["first_seen_with_pik_terms_positions"] = (
        pd.to_numeric(summary["first_seen_with_pik_terms_positions"], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    summary["scope"] = scope
    for col in ["source", "index_classification"]:
        if col not in summary.columns:
            summary[col] = "ALL"
    return summary


def build_pik_schedule_proxy_summary(status_df: pd.DataFrame) -> pd.DataFrame:
    """Build researcher-comparable PIK terms exposure summary.

    This is a schedule-rate proxy: ``pik_terms_rate > 0`` indicates disclosed
    PIK terms, not independently verified current PIK income/accrual.
    """
    if status_df.empty:
        return pd.DataFrame(columns=SCHEDULE_PROXY_SUMMARY_COLUMNS)
    df = _prepare_schedule_proxy_status(status_df)

    all_df = df.assign(source="ALL", index_classification="ALL")
    by_source = df.assign(index_classification="ALL")
    by_index = df.assign(source="ALL")
    bdc_dl = df[
        (df["source"].str.lower() == "bdc")
        & (df["index_classification"] == "DIRECT_LENDING")
    ].copy()
    if not bdc_dl.empty:
        bdc_dl = bdc_dl.assign(source="bdc", index_classification="DIRECT_LENDING")

    pieces = [
        _build_schedule_summary_for_scope(
            all_df,
            "all",
            ["report_date", "report_quarter", "source", "index_classification"],
        ),
        _build_schedule_summary_for_scope(
            by_source,
            "by_source",
            ["report_date", "report_quarter", "source", "index_classification"],
        ),
        _build_schedule_summary_for_scope(
            by_index,
            "by_index",
            ["report_date", "report_quarter", "source", "index_classification"],
        ),
        _build_schedule_summary_for_scope(
            df,
            "by_source_index",
            ["report_date", "report_quarter", "source", "index_classification"],
        ),
    ]
    if not bdc_dl.empty:
        pieces.append(_build_schedule_summary_for_scope(
            bdc_dl,
            "bdc_direct_lending_headline",
            ["report_date", "report_quarter", "source", "index_classification"],
        ))

    result = pd.concat(pieces, ignore_index=True)
    for col in SCHEDULE_PROXY_SUMMARY_COLUMNS:
        if col not in result.columns:
            result[col] = ""
    return result[SCHEDULE_PROXY_SUMMARY_COLUMNS].sort_values(
        ["report_date", "scope", "source", "index_classification"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


def build_pik_schedule_proxy_transitions(status_df: pd.DataFrame) -> pd.DataFrame:
    """Build same-position no-PIK-terms to PIK-terms transition proxy."""
    if status_df.empty:
        return pd.DataFrame(columns=SCHEDULE_PROXY_TRANSITION_COLUMNS)
    df = _prepare_schedule_proxy_status(status_df)
    df = df[df["_has_position_id"]].copy()
    if df.empty:
        logger.warning("PIK schedule proxy transitions skipped: no nonblank position_id coverage")
        return pd.DataFrame(columns=SCHEDULE_PROXY_TRANSITION_COLUMNS)

    df = df.sort_values(["source", "cik", "position_id", "_date"], kind="mergesort")
    group_cols = ["source", "cik", "position_id"]
    for col in [
        "report_date", "pik_terms_flag", "_pik_terms_flag", "pik_terms_rate",
        "fair_value", "issuer_name", "entity_name", "index_classification",
    ]:
        df[f"prior_{col}"] = df.groupby(group_cols, dropna=False)[col].shift(1)

    starts = df[
        (df["prior__pik_terms_flag"] == False)
        & (df["_pik_terms_flag"] == True)
    ].copy()
    if starts.empty:
        return pd.DataFrame(columns=SCHEDULE_PROXY_TRANSITION_COLUMNS)

    result = pd.DataFrame({
        "transition_type": "pik_terms_started",
        "source": starts["source"],
        "cik": starts["cik"],
        "entity_name": starts["entity_name"].fillna(starts["prior_entity_name"]),
        "position_id": starts["position_id"],
        "prior_report_date": starts["prior_report_date"],
        "current_report_date": starts["report_date"],
        "issuer_name": starts["issuer_name"].fillna(starts["prior_issuer_name"]),
        "index_classification": starts["index_classification"].fillna(starts["prior_index_classification"]),
        "prior_pik_terms_flag": _bool_text(starts["prior__pik_terms_flag"]),
        "current_pik_terms_flag": _bool_text(starts["_pik_terms_flag"]),
        "prior_pik_terms_rate": starts["prior_pik_terms_rate"],
        "current_pik_terms_rate": starts["pik_terms_rate"],
        "prior_fair_value": starts["prior_fair_value"],
        "current_fair_value": starts["fair_value"],
    })
    return result[SCHEDULE_PROXY_TRANSITION_COLUMNS].sort_values(
        ["source", "cik", "position_id", "current_report_date"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)


def build_pik_schedule_proxy_outputs(
    status_df: pd.DataFrame | None = None,
    summary_path: Path = PIK_SCHEDULE_PROXY_SUMMARY_FILE,
    transitions_path: Path = PIK_SCHEDULE_PROXY_TRANSITIONS_FILE,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Write PIK schedule-rate proxy summary and transition artifacts."""
    t0 = time.time()
    if status_df is None:
        status_df = pd.read_csv(POSITION_PIK_STATUS_FILE, dtype=str)
    summary = build_pik_schedule_proxy_summary(status_df)
    transitions = build_pik_schedule_proxy_transitions(status_df)

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    transitions_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False)
    transitions.to_csv(transitions_path, index=False)
    logger.info(
        "PIK schedule proxy: %d summary rows, %d transition rows in %.1f s",
        len(summary), len(transitions), time.time() - t0,
    )
    return summary, transitions
