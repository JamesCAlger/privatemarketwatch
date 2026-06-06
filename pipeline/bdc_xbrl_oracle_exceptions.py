"""Audited BDC XBRL wrapper oracle exception loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from pipeline.bdc_xbrl_wrapper import normalize_cik
from pipeline.config import BDC_XBRL_ORACLE_EXCEPTIONS_FILE


ORACLE_EXCEPTION_SCHEMA_VERSION = "bdc-xbrl-oracle-exceptions.v1"
ORACLE_EXCEPTION_MIN_CONFIDENCE = 0.80
ORACLE_EXCEPTION_COLUMNS = [
    "schema_version",
    "cik",
    "report_date",
    "oracle_reason",
    "wrapper_version",
    "status",
    "confidence",
    "reason",
    "evidence",
    "residual_risk",
    "created_by",
    "accepted_by",
    "updated_at",
]
_REQUIRED_COLUMNS = [
    "cik",
    "report_date",
    "oracle_reason",
    "wrapper_version",
    "status",
    "confidence",
    "reason",
    "evidence",
    "residual_risk",
    "created_by",
    "accepted_by",
    "updated_at",
]
_VALID_STATUSES = {"accepted", "proposed", "rejected"}


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    records = payload.get("exceptions", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError(
            "BDC XBRL oracle exceptions must be a JSON list or {'exceptions': [...]}"
        )
    return records


def load_bdc_xbrl_oracle_exceptions(path: Path | None = None) -> pd.DataFrame:
    """Load audited oracle exceptions.

    Only records with ``status == accepted`` and confidence at or above
    ``ORACLE_EXCEPTION_MIN_CONFIDENCE`` are eligible to waive soft promotion
    reasons.  The loader still returns proposed/rejected records so callers can
    audit inactive records, but malformed active records fail loudly.
    """
    exceptions_file = path or BDC_XBRL_ORACLE_EXCEPTIONS_FILE
    if not exceptions_file.exists():
        return pd.DataFrame(columns=ORACLE_EXCEPTION_COLUMNS)
    try:
        with exceptions_file.open(encoding="utf-8-sig") as fh:
            payload = json.load(fh)
    except Exception as exc:
        raise ValueError(f"Could not read {exceptions_file}") from exc

    records = _records_from_payload(payload)
    df = pd.DataFrame(records)
    for col in ORACLE_EXCEPTION_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    missing = {
        col for col in _REQUIRED_COLUMNS
        if df[col].fillna("").astype(str).str.strip().eq("").any()
    }
    if missing:
        raise ValueError(
            "BDC XBRL oracle exceptions missing required values: "
            + ", ".join(sorted(missing))
        )

    df = df[ORACLE_EXCEPTION_COLUMNS].copy()
    df["schema_version"] = df["schema_version"].replace("", ORACLE_EXCEPTION_SCHEMA_VERSION)
    bad_schema = set(df["schema_version"]) - {ORACLE_EXCEPTION_SCHEMA_VERSION}
    if bad_schema:
        raise ValueError(
            "Invalid BDC XBRL oracle exception schema version(s): "
            + ", ".join(sorted(str(v) for v in bad_schema))
        )

    df["cik"] = df["cik"].map(normalize_cik)
    for col in [
        "report_date",
        "oracle_reason",
        "wrapper_version",
        "status",
        "reason",
        "evidence",
        "residual_risk",
        "created_by",
        "accepted_by",
        "updated_at",
    ]:
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["status"] = df["status"].str.lower()
    bad_statuses = set(df["status"]) - _VALID_STATUSES
    if bad_statuses:
        raise ValueError(
            "Invalid BDC XBRL oracle exception status(es): "
            + ", ".join(sorted(bad_statuses))
        )

    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce")
    if df["confidence"].isna().any():
        raise ValueError("BDC XBRL oracle exceptions contain non-numeric confidence")
    outside_range = df[(df["confidence"] < 0.0) | (df["confidence"] > 1.0)]
    if not outside_range.empty:
        raise ValueError("BDC XBRL oracle exception confidence must be between 0 and 1")

    active_low_confidence = df[
        df["status"].eq("accepted")
        & (df["confidence"] < ORACLE_EXCEPTION_MIN_CONFIDENCE)
    ]
    if not active_low_confidence.empty:
        raise ValueError(
            "Accepted BDC XBRL oracle exceptions must have confidence >= "
            f"{ORACLE_EXCEPTION_MIN_CONFIDENCE:.2f}"
        )

    return df


def reason_is_waived(
    exceptions: pd.DataFrame | None,
    *,
    cik: str,
    report_date: str,
    oracle_reason: str,
    wrapper_version: str,
) -> bool:
    """Return whether an accepted exact-match exception waives one reason."""
    if exceptions is None or exceptions.empty or not wrapper_version:
        return False
    df = exceptions.copy()
    for col in ORACLE_EXCEPTION_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    mask = (
        df["cik"].map(normalize_cik).eq(normalize_cik(cik))
        & df["report_date"].astype(str).eq(str(report_date))
        & df["oracle_reason"].astype(str).eq(str(oracle_reason))
        & df["wrapper_version"].astype(str).eq(str(wrapper_version))
        & df["status"].astype(str).str.lower().eq("accepted")
        & (pd.to_numeric(df["confidence"], errors="coerce") >= ORACLE_EXCEPTION_MIN_CONFIDENCE)
    )
    return bool(mask.any())
