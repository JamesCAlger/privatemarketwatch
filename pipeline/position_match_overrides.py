"""Position match override loading and application.

Per-CIK JSON files in data/overrides/position_match_overrides/ contain
reject and force_pair directives for individual match pairs.  Overrides
use a natural key (issuer_name + report_date + fair_value) rather than
session-local row IDs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb
import pandas as pd

from pipeline.config import POSITION_MATCH_OVERRIDES_DIR

logger = logging.getLogger(__name__)

OVERRIDE_COLUMNS = [
    "cik",
    "action",
    "begin_report_date",
    "end_report_date",
    "begin_issuer_name",
    "end_issuer_name",
    "begin_fair_value",
    "end_fair_value",
    "match_method",
    "mechanism",
    "evidence",
    "confidence",
    "residual_risk",
    "created_by",
    "review_id",
    "replace_end_issuer_name",
    "replace_end_fair_value",
]

REQUIRED_FIELDS = [
    "action",
    "begin_report_date",
    "end_report_date",
    "begin_issuer_name",
    "end_issuer_name",
    "begin_fair_value",
    "end_fair_value",
    "match_method",
    "mechanism",
    "evidence",
    "confidence",
    "residual_risk",
    "created_by",
    "review_id",
]

VALID_ACTIONS = {"reject", "force_pair"}


def load_position_match_overrides(
    cik: str | None = None,
    overrides_dir: Path | None = None,
) -> pd.DataFrame:
    """Load position match override records from JSON files.

    Returns DataFrame with columns matching OVERRIDE_COLUMNS.
    Optionally filtered to a single CIK.
    """
    base_dir = overrides_dir or POSITION_MATCH_OVERRIDES_DIR
    if not base_dir.exists():
        return pd.DataFrame(columns=OVERRIDE_COLUMNS)

    files = sorted(base_dir.glob("*.json"))
    if not files:
        return pd.DataFrame(columns=OVERRIDE_COLUMNS)

    all_records: list[dict] = []
    for fpath in files:
        try:
            with fpath.open(encoding="utf-8-sig") as fh:
                payload = json.load(fh)
        except Exception as exc:
            raise ValueError(f"Could not read override file {fpath}") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"Override file {fpath.name} must be a JSON object")

        schema_version = payload.get("schema_version", "")
        if schema_version != "position-match-override.v1":
            raise ValueError(
                f"Override file {fpath.name}: unsupported schema_version "
                f"{schema_version!r} (expected 'position-match-override.v1')"
            )

        file_cik = payload.get("cik", "")
        file_cik = str(file_cik).replace(" ", "").zfill(10)

        overrides = payload.get("overrides", [])
        if not isinstance(overrides, list):
            raise ValueError(
                f"Override file {fpath.name}: 'overrides' must be a list"
            )

        for i, record in enumerate(overrides):
            _validate_override_record(record, fpath.name, i)
            record = dict(record)  # shallow copy
            record["cik"] = file_cik
            all_records.append(record)

    if not all_records:
        return pd.DataFrame(columns=OVERRIDE_COLUMNS)

    df = pd.DataFrame(all_records)

    # Normalize CIK
    df["cik"] = (
        df["cik"].astype(str).str.replace(r"[^0-9]", "", regex=True).str.zfill(10)
    )

    # Ensure all columns present
    for col in OVERRIDE_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[OVERRIDE_COLUMNS].copy()

    # Normalize string columns
    for col in ["begin_report_date", "end_report_date", "begin_issuer_name",
                "end_issuer_name", "action", "match_method"]:
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["action"] = df["action"].str.lower()

    # Filter to requested CIK
    if cik is not None:
        cik_norm = str(cik).replace(" ", "").zfill(10)
        df = df[df["cik"] == cik_norm].copy()

    return df


def _validate_override_record(
    record: dict, filename: str, index: int
) -> None:
    """Validate a single override record, raising ValueError on problems."""
    prefix = f"Override file {filename}, entry {index}"

    # Check required fields
    missing = [f for f in REQUIRED_FIELDS if not record.get(f, "")]
    # confidence can be 0 which is falsy -- check separately
    if "confidence" in missing and isinstance(record.get("confidence"), (int, float)):
        missing.remove("confidence")
    if missing:
        raise ValueError(f"{prefix}: missing required fields: {', '.join(missing)}")

    # Validate action
    action = str(record.get("action", "")).lower()
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"{prefix}: invalid action {action!r} (must be one of {sorted(VALID_ACTIONS)})"
        )

    # force_pair requires replace_end_* fields
    if action == "force_pair":
        for field in ("replace_end_issuer_name", "replace_end_fair_value"):
            if not record.get(field, ""):
                raise ValueError(
                    f"{prefix}: force_pair action requires '{field}'"
                )

    # Validate confidence is numeric
    conf = record.get("confidence")
    if not isinstance(conf, (int, float)):
        raise ValueError(f"{prefix}: confidence must be numeric, got {type(conf).__name__}")


def apply_match_overrides(
    result_df: pd.DataFrame,
    overrides_df: pd.DataFrame,
) -> tuple[pd.DataFrame, int, int]:
    """Apply position match overrides to a matched-pairs DataFrame.

    Returns (result_df, n_rejected, n_forced).
    """
    if overrides_df.empty:
        return result_df, 0, 0

    # Add explicit index column (DuckDB registered DataFrames lack rowid)
    result_with_idx = result_df.copy()
    result_with_idx["_match_idx"] = range(len(result_with_idx))

    con = duckdb.connect()
    con.register("matches", result_with_idx)
    con.register("overrides", overrides_df)

    # Join overrides to matches on natural key with FV tolerance.
    # Case-insensitive name matching, FV within 1% or $1000 absolute.
    join_sql = """
    SELECT
        m._match_idx,
        o.action,
        o.replace_end_issuer_name,
        o.replace_end_fair_value,
        o.match_method AS o_match_method,
        o.mechanism
    FROM matches m
    JOIN overrides o
      ON LPAD(REGEXP_REPLACE(CAST(m.cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')
         = o.cik
      AND CAST(m.begin_report_date AS VARCHAR) = o.begin_report_date
      AND CAST(m.end_report_date AS VARCHAR) = o.end_report_date
      AND LOWER(TRIM(CAST(m.begin_issuer_name AS VARCHAR)))
         = LOWER(TRIM(o.begin_issuer_name))
      AND LOWER(TRIM(CAST(m.end_issuer_name AS VARCHAR)))
         = LOWER(TRIM(o.end_issuer_name))
      AND (
          ABS(COALESCE(TRY_CAST(m.begin_fair_value AS DOUBLE), 0)
              - COALESCE(TRY_CAST(o.begin_fair_value AS DOUBLE), 0))
          <= GREATEST(
              ABS(COALESCE(TRY_CAST(m.begin_fair_value AS DOUBLE), 0)) * 0.01,
              1000
          )
      )
      AND (
          ABS(COALESCE(TRY_CAST(m.end_fair_value AS DOUBLE), 0)
              - COALESCE(TRY_CAST(o.end_fair_value AS DOUBLE), 0))
          <= GREATEST(
              ABS(COALESCE(TRY_CAST(m.end_fair_value AS DOUBLE), 0)) * 0.01,
              1000
          )
      )
    """
    joined = con.execute(join_sql).fetchdf()
    con.close()

    if joined.empty:
        # Log warning for unmatched overrides
        n_overrides = len(overrides_df)
        if n_overrides > 0:
            logger.warning(
                "  %d position match override(s) did not match any pairs",
                n_overrides,
            )
        return result_df, 0, 0

    # Apply rejects: remove matched rows
    reject_idxs = set(
        joined.loc[joined["action"].str.lower() == "reject", "_match_idx"].astype(int)
    )
    n_rejected = len(reject_idxs)

    # Apply force_pairs: update end-side columns
    force_rows = joined[joined["action"].str.lower() == "force_pair"].copy()
    n_forced = len(force_rows)

    # Use the _match_idx column as positional index into the original result
    result = result_df.reset_index(drop=True).copy()

    # Mark force_pair replacements
    for _, frow in force_rows.iterrows():
        ridx = int(frow["_match_idx"])
        if ridx < len(result):
            result.at[ridx, "end_issuer_name"] = frow["replace_end_issuer_name"]
            result.at[ridx, "end_fair_value"] = frow["replace_end_fair_value"]
            orig_method = str(result.at[ridx, "match_method"])
            if not orig_method.endswith("_override"):
                result.at[ridx, "match_method"] = orig_method + "_override"

    # Remove rejected rows
    if reject_idxs:
        result = result.loc[~result.index.isin(reject_idxs)].copy()

    # Log unmatched overrides
    matched_override_count = len(joined)
    total_overrides = len(overrides_df)
    unmatched = total_overrides - matched_override_count
    if unmatched > 0:
        logger.warning(
            "  %d of %d position match override(s) did not match any pairs",
            unmatched, total_overrides,
        )

    return result, n_rejected, n_forced
