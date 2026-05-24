"""Audited BDC aggregate-row override loading."""

from __future__ import annotations

import json

import pandas as pd

from pipeline.config import BDC_AGGREGATE_ROW_OVERRIDES_FILE


AGGREGATE_OVERRIDE_COLUMNS = [
    "cik",
    "report_date",
    "accession_number",
    "match_text",
    "match_mode",
    "action",
    "reason",
    "evidence",
    "review_id",
    "updated_at",
]


def load_bdc_aggregate_overrides() -> pd.DataFrame:
    """Load audited aggregate-row include/exclude overrides, if present."""
    columns = [*AGGREGATE_OVERRIDE_COLUMNS, "match_text_lower"]
    if not BDC_AGGREGATE_ROW_OVERRIDES_FILE.exists():
        return pd.DataFrame(columns=columns)
    try:
        with BDC_AGGREGATE_ROW_OVERRIDES_FILE.open(encoding="utf-8-sig") as fh:
            payload = json.load(fh)
    except Exception as exc:
        raise ValueError(
            f"Could not read {BDC_AGGREGATE_ROW_OVERRIDES_FILE}"
        ) from exc

    records = payload.get("overrides", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("BDC aggregate overrides must be a JSON list or {'overrides': [...]}")

    df = pd.DataFrame(records)
    for col in AGGREGATE_OVERRIDE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    required = ["cik", "match_text", "action", "reason", "evidence", "review_id", "updated_at"]
    missing = {
        col for col in required
        if df[col].fillna("").astype(str).str.strip().eq("").any()
    }
    if missing:
        raise ValueError(
            "BDC aggregate overrides missing required values: "
            + ", ".join(sorted(missing))
        )

    df = df[AGGREGATE_OVERRIDE_COLUMNS].copy()
    df["cik"] = df["cik"].astype(str).str.replace(r"[^0-9]", "", regex=True).str.zfill(10)
    for col in ["report_date", "accession_number", "match_text", "action", "match_mode"]:
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["action"] = df["action"].str.lower()
    df["match_mode"] = df["match_mode"].replace("", "contains").str.lower()

    bad_actions = set(df["action"]) - {"include", "exclude"}
    if bad_actions:
        raise ValueError(f"Invalid BDC aggregate override action(s): {sorted(bad_actions)}")
    bad_modes = set(df["match_mode"]) - {"contains", "exact"}
    if bad_modes:
        raise ValueError(f"Invalid BDC aggregate override match_mode(s): {sorted(bad_modes)}")

    df["match_text_lower"] = df["match_text"].str.lower()
    return df
