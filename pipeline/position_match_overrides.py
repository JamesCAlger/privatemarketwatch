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
    *,
    unified_df: pd.DataFrame | None = None,
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
    indexed_overrides = overrides_df.copy()
    indexed_overrides["_override_idx"] = range(len(indexed_overrides))
    con.register("overrides", indexed_overrides)

    # Join overrides to matches on natural key with FV tolerance.
    # Case-insensitive name matching, FV within 1% or $1000 absolute.
    join_sql = """
    SELECT
        m._match_idx,
        o._override_idx,
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

    if unified_df is not None:
        from pipeline.reviewed_position_identity import reconcile_financial_matches
        result = reconcile_financial_matches(result, unified_df, preserve_indices=set(force_rows['_match_idx']))

    _rebind_forced_endpoints(result, force_rows, unified_df, reject_idxs)

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


def _rebind_forced_endpoints(result, force_rows, unified, rejected_indices):
    """Replace the whole selected endpoint, never just its name and value.

    Replacement name/FV are exact selectors into the current corrected
    holdings. Missing or ambiguous targets fail closed. Only the small set
    of applied directives is iterated; full holdings lookup stays in SQL.
    """
    if force_rows.empty:
        return
    if unified is None:
        raise ValueError("force_pair requires unified holdings to resolve the complete endpoint")
    endpoint_fields = ("issuer_name", "fair_value", "cost", "principal_amount",
                       "interest_rate", "basis_spread", "shares_held")
    metadata_fields = ("index_classification", "asset_category", "issuer_category",
                       "maturity_date", "coupon_type")
    replacements = {"end_" + field: field for field in endpoint_fields
                    if "end_" + field in result}
    replacements.update({field: field for field in metadata_fields if field in result})
    required = {"cik", "source", "report_date", "issuer_name", "fair_value"} | set(replacements.values())
    missing = required - set(unified.columns)
    if missing:
        raise ValueError("force_pair destination holdings lack columns: " + ", ".join(sorted(missing)))
    if "source" not in result:
        raise ValueError("force_pair matched endpoint requires source")
    if force_rows["_match_idx"].duplicated().any():
        raise ValueError("Multiple force_pair directives select the same matched endpoint")
    if force_rows["_override_idx"].duplicated().any():
        raise ValueError("A force_pair directive selects multiple matched pairs")
    # A destination may legitimately replace an integer with a decimal, null
    # or a numeric string. Keep exact source values without dtype coercion.
    for output_field in replacements:
        result[output_field] = result[output_field].astype(object)
    from pipeline.matching_contract import scope_sql

    with duckdb.connect() as con:
        con.register("holdings", unified)
        con.register("paired", result.assign(_pair_idx=result.index))
        excluded_indices = set(force_rows["_match_idx"].astype(int)) | rejected_indices
        con.register("excluded_indices", pd.DataFrame({"_match_idx": sorted(excluded_indices)}))
        scope = scope_sql(unified.columns, row_id="_override_uid")
        con.execute("CREATE VIEW destinations AS SELECT *, " + scope + " AS _override_scope "
                    "FROM (SELECT *, row_number() OVER () AS _override_uid FROM holdings)")
        selector = """FROM destinations WHERE
            lpad(CAST(cik AS VARCHAR), 10, '0') = lpad(CAST(? AS VARCHAR), 10, '0')
            AND CAST(source AS VARCHAR) = ?
            AND TRY_CAST(report_date AS DATE) = TRY_CAST(? AS DATE)
            AND lower(trim(CAST(issuer_name AS VARCHAR))) = lower(trim(CAST(? AS VARCHAR)))
            AND TRY_CAST(fair_value AS DOUBLE) = TRY_CAST(? AS DOUBLE)"""
        seen_destinations = set()
        for _, directive in force_rows.iterrows():
            ridx = int(directive["_match_idx"])
            original = result.loc[ridx]
            prefix = [str(original["cik"]), str(original["source"]), str(original["end_report_date"])]
            target = con.execute("SELECT * " + selector, prefix + [
                str(directive["replace_end_issuer_name"]), str(directive["replace_end_fair_value"])]).fetchdf()
            if len(target) != 1:
                raise ValueError("force_pair requires exactly one destination holding; found " + str(len(target)))
            selected = target.iloc[0]
            destination_key = (str(pd.Timestamp(original["begin_report_date"]).date()),
                               str(pd.Timestamp(selected["report_date"]).date()),
                               str(selected["cik"]).zfill(10), str(selected["source"]),
                               str(selected["issuer_name"]).strip().lower(),
                               float(selected["fair_value"]), str(selected["_override_scope"]))
            if destination_key in seen_destinations:
                raise ValueError("force_pair directives would share a destination holding")
            seen_destinations.add(destination_key)
            old_selector = selector
            if "bdc_investment_identifier" in unified:
                old_selector = old_selector.replace(
                    "lower(trim(CAST(issuer_name AS VARCHAR))) = lower(trim(CAST(? AS VARCHAR)))",
                    "lower(trim(CAST(? AS VARCHAR))) IN (lower(trim(CAST(issuer_name AS VARCHAR))), "
                    "lower(trim(CAST(bdc_investment_identifier AS VARCHAR))))")
            old_scopes = con.execute("SELECT DISTINCT _override_scope " + old_selector,
                                     prefix + [str(original["end_issuer_name"]), str(original["end_fair_value"])]).fetchall()
            if len(old_scopes) != 1 or old_scopes[0][0] != target.iloc[0]["_override_scope"]:
                raise ValueError("force_pair destination accounting scope is unresolved or differs")
            destination = target.iloc[0]
            destination_names = [str(destination["issuer_name"]),
                                 str(destination.get("bdc_investment_identifier", destination["issuer_name"]))]
            collisions = con.execute("""SELECT count(*) FROM
                paired p
                WHERE _pair_idx NOT IN (SELECT _match_idx FROM excluded_indices)
                  AND lpad(CAST(cik AS VARCHAR),10,'0')=lpad(CAST(? AS VARCHAR),10,'0')
                  AND CAST(source AS VARCHAR)=?
                  AND TRY_CAST(begin_report_date AS DATE)=TRY_CAST(? AS DATE)
                  AND TRY_CAST(end_report_date AS DATE)=TRY_CAST(? AS DATE)
                  AND lower(trim(CAST(end_issuer_name AS VARCHAR))) IN
                      (lower(trim(CAST(? AS VARCHAR))),lower(trim(CAST(? AS VARCHAR))))
                  AND TRY_CAST(end_fair_value AS DOUBLE)=TRY_CAST(? AS DOUBLE)""",
                [str(original["cik"]), str(original["source"]), str(original["begin_report_date"]),
                 str(original["end_report_date"]), *destination_names, str(destination["fair_value"])]).fetchone()[0]
            if collisions:
                raise ValueError("force_pair destination already has an ordinary matched pair for this period")
            for output_field, holding_field in replacements.items():
                result.at[ridx, output_field] = target.iloc[0][holding_field]
            method = str(original["match_method"])
            if not method.endswith("_override"):
                result.at[ridx, "match_method"] = method + "_override"
