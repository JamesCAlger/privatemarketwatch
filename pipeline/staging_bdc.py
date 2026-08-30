"""BDC holdings staging for the unified holdings pipeline."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Union

import duckdb
import pandas as pd

from pipeline.bdc_identifier import (
    _AFFILIATION_PIPE_SUFFIX_RE,
    _AFFILIATION_PREFIX_RE,
    _AFFILIATION_SUFFIX_RE,
    _AFFILIATION_TAGS,
    _CRESCENT_HIERARCHY_INDUSTRIES,
    _INVESTMENTS_HIERARCHY_RE,
    _sql_is_bdc_aggregate,
)
from pipeline.bdc_xbrl_wrapper import (
    classify_identifier,
    get_wrapper_spec,
    is_non_private_market_identifier,
    supported_wrapper_ciks,
)
from pipeline.bdc_xbrl_html_bridge import (
    BRIDGE_TABLE_COLUMNS,
    apply_html_section_bridge_field_overlays,
    load_html_section_bridge_rows,
)
from pipeline.bdc_aggregate_overrides import load_bdc_aggregate_overrides
from pipeline.classification import (
    _INDUSTRY_LABELS,
    _BDC_FUND_VEHICLE_KEYWORDS,
    _BDC_FUND_VEHICLE_POS_GUARD,
    _CASH_KEYWORDS,
    _LEGAL_SUFFIX_RE_SQL,
    _MONEY_MARKET_KEYWORDS,
    _PIPE_INSTRUMENT_KEYWORDS,
    _is_named_coinvest,
    _sql_classify_bdc_asset,
    _sql_exact_match,
    _sql_industry_label_in,
    _sql_is_bad_issuer_name,
    _sql_is_named_coinvest,
    _sql_keyword_check,
    _sql_money_market_check,
    _sql_normalize_name,
)
from pipeline.config import (
    AGGREGATE_HEADER_FLAGS_FILE,
    FX_RATES_FILE,
    OVERRIDES_DIR,
)

logger = logging.getLogger(__name__)

_WRAPPER_DEFINITIONS_DIR = OVERRIDES_DIR / "bdc_xbrl_wrappers"


def _repair_weak_position_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Repair non-identifying BDC position keys produced by generic parsing."""
    if df.empty or "position_key" not in df.columns:
        return df

    key = df["position_key"].fillna("").astype(str).str.strip()
    key_norm = (
        key.str.lower()
        .str.replace(r"[^a-z0-9]+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    weak = (
        key_norm.str.len().lt(12)
        | key_norm.str.fullmatch(r"(?:lass|nits|units|nc)(?:\s+(?:lass|nits|units|nc))*")
    )
    if not weak.any():
        return df

    issuer = df.get("issuer_name", pd.Series("", index=df.index)).fillna("").astype(str)
    instrument = (
        df.get("instrument_description", pd.Series("", index=df.index))
        .fillna("")
        .astype(str)
    )
    raw_id = (
        df.get("bdc_investment_identifier", pd.Series("", index=df.index))
        .fillna("")
        .astype(str)
    )

    fallback = (
        (issuer + " " + instrument)
        .str.lower()
        .str.replace(r"[^a-z0-9]+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    raw_fallback = (
        raw_id.str.lower()
        .str.replace(r"[^a-z0-9]+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    fallback = fallback.mask(fallback.str.len().lt(12), raw_fallback)
    repair_mask = weak & fallback.str.len().ge(12)

    if repair_mask.any():
        df = df.copy()
        df.loc[repair_mask, "position_key"] = fallback.loc[repair_mask]
        logger.info("  Repaired %d weak BDC position_key values", repair_mask.sum())
    return df


def _expand_placeholders(text: str, placeholders: dict[str, str]) -> str:
    """Replace placeholder tokens in JSON regex patterns with runtime values."""
    for token, expansion in placeholders.items():
        text = text.replace(token, expansion)
    # DuckDB regex does not accept JSON-style unicode escapes such as \u2013.
    # Decode escaped Unicode after JSON loading while keeping config files
    # ASCII-friendly.
    text = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        text,
    )
    return text


def _expand_staging_strings(obj: Any, placeholders: dict[str, str]) -> None:
    """Recursively expand placeholder tokens in all string values of a dict."""
    if isinstance(obj, dict):
        for key in obj:
            if isinstance(obj[key], str):
                obj[key] = _expand_placeholders(obj[key], placeholders)
            elif isinstance(obj[key], (dict, list)):
                _expand_staging_strings(obj[key], placeholders)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str):
                obj[i] = _expand_placeholders(item, placeholders)
            elif isinstance(item, (dict, list)):
                _expand_staging_strings(item, placeholders)


def _load_staging_configs() -> dict[str, dict[str, Any]]:
    """Load v3 JSON staging configs keyed by normalized CIK."""
    configs: dict[str, dict[str, Any]] = {}
    if not _WRAPPER_DEFINITIONS_DIR.exists():
        return configs
    for path in sorted(_WRAPPER_DEFINITIONS_DIR.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        if raw.get("schema_version") != "bdc-xbrl-wrapper.v3":
            continue
        staging = raw.get("staging")
        if staging is None:
            continue
        cik = raw["cik"]
        cik_norm = cik.lstrip("0").zfill(10)
        configs[cik_norm] = {
            "cik": cik,
            "entity_name": raw.get("entity_name", ""),
            "staging": staging,
        }
    if configs:
        logger.info("Loaded staging configs for %d CIKs: %s",
                     len(configs),
                     ", ".join(sorted(configs)))
    return configs


def _load_identifier_parsers() -> dict[str, dict]:
    """Load identifier_parser configs from v3 wrapper JSON files.

    Returns dict mapping normalized CIK (10-digit zero-padded) to the
    identifier_parser config dict.  Only returns parsers with a known type.
    """
    parsers: dict[str, dict] = {}
    if not _WRAPPER_DEFINITIONS_DIR.exists():
        return parsers
    for path in sorted(_WRAPPER_DEFINITIONS_DIR.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        if raw.get("schema_version") != "bdc-xbrl-wrapper.v3":
            continue
        parser = raw.get("identifier_parser")
        if parser is None or parser.get("type") not in ("hierarchical_pct",):
            continue
        cik = raw["cik"]
        cik_norm = cik.lstrip("0").zfill(10)
        parsers[cik_norm] = parser
    if parsers:
        logger.info("Loaded identifier_parser configs for %d CIKs: %s",
                     len(parsers),
                     ", ".join(sorted(parsers)))
    return parsers


def _load_issuer_bridges_from_json() -> list[dict[str, str]]:
    """Load issuer bridge rows from all v3 JSON files with issuer_bridge strategy."""
    configs = _load_staging_configs()
    bridges: list[dict[str, str]] = []
    for cik_norm, cfg in configs.items():
        staging = cfg["staging"]
        if staging.get("strategy") != "issuer_bridge":
            continue
        for bridge in staging.get("issuer_bridges") or []:
            bridges.append({
                "cik": cfg["cik"],
                "report_date": bridge["report_date"],
                "raw_id_lower": bridge["raw_id_lower"],
                "issuer_name": bridge["issuer_name"],
                "instrument_description": bridge["instrument_description"],
            })
    return bridges


def _load_html_section_bridges_from_json() -> pd.DataFrame:
    """Load audited static HTML-section bridge rows for BDC XBRL staging."""
    return load_html_section_bridge_rows()


def _get_comma_delimited_ciks() -> list[str]:
    """Return CIKs whose wrapper uses ', ' delimiter with issuer_name first.

    For these CIKs, bare entity names (without instrument description after
    the comma delimiter) are always entity-level rollups, never standalone
    equity positions. Used for single-child prefix rollup detection.
    """
    result: list[str] = []
    wrapper_dir = _WRAPPER_DEFINITIONS_DIR
    if not wrapper_dir.exists():
        return result
    for path in sorted(wrapper_dir.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        if raw.get("schema_version") != "bdc-xbrl-wrapper.v3":
            continue
        idf = raw.get("identifier_format", {})
        if idf.get("delimiter") == ", " and "issuer_name" in (idf.get("field_order") or []):
            result.append(raw["cik"])
    return result


def _get_prefix_rules_data() -> dict[str, list[str]]:
    """Return CIK -> list of prefix_rules keys from wrapper JSON dispatch.

    Used to build an aggregate-filter bypass: CIKs with declared prefix_rules
    should not have real positions filtered by the aggregate check when the
    identifier starts with a declared prefix AND contains entity/leaf detail
    after the prefix.
    """
    result: dict[str, list[str]] = {}
    wrapper_dir = _WRAPPER_DEFINITIONS_DIR
    if not wrapper_dir.exists():
        return result
    for path in sorted(wrapper_dir.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        if raw.get("schema_version") != "bdc-xbrl-wrapper.v3":
            continue
        dispatch = raw.get("dispatch", {})
        prefix_rules = dispatch.get("prefix_rules", {})
        if not prefix_rules:
            continue
        cik = raw["cik"]
        result[cik] = list(prefix_rules.keys())
    return result


def _load_aggregate_header_flags() -> pd.DataFrame:
    """Load CC-reviewed aggregate header flags, if present.

    Returns a DataFrame with ``name_norm`` (lowercase, legal suffixes
    stripped) and ``identifier_raw`` (lowercased raw investment_identifier
    from bdc_holdings, populated by backfill script) columns.  The CTE
    join uses ``identifier_raw`` for exact matching against ``_lower_id``
    when available, falling back to normalised ``issuer_name`` matching
    via ``name_norm``.

    Only rows with verdict = 'AGGREGATE_HEADER' and confidence in
    ('high', 'medium') are returned -- JV_SUBSIDIARY and UNRESOLVABLE
    verdicts are informational and do NOT trigger exclusion.
    """
    if not AGGREGATE_HEADER_FLAGS_FILE.exists():
        return pd.DataFrame(columns=["name_norm", "identifier_raw"])
    try:
        df = pd.read_csv(AGGREGATE_HEADER_FLAGS_FILE, dtype=str)
    except Exception:
        return pd.DataFrame(columns=["name_norm", "identifier_raw"])
    if "verdict" not in df.columns or "name_norm" not in df.columns:
        return pd.DataFrame(columns=["name_norm", "identifier_raw"])
    mask = (
        (df["verdict"] == "AGGREGATE_HEADER")
        & df["confidence"].isin(["high", "medium"])
    )
    cols = ["name_norm"]
    if "identifier_raw" in df.columns:
        cols.append("identifier_raw")
    result = df.loc[mask, cols].copy()
    result["name_norm"] = result["name_norm"].str.strip().str.lower()
    if "identifier_raw" not in result.columns:
        result["identifier_raw"] = ""
    result["identifier_raw"] = result["identifier_raw"].fillna("").str.strip().str.lower()
    result = result[result["name_norm"].str.len() > 0].drop_duplicates()
    return result


def _reclassify_named_fund_positions(df: pd.DataFrame) -> pd.DataFrame:
    """Reclassify named co-invest and LP interest positions from FUND to EQUITY.

    For rows where asset_category == "FUND" and the holding identifies a
    specific operating company (via _is_named_coinvest), override:
      - asset_category -> EQUITY_PREFERRED if "preferred" in name, else EQUITY_COMMON
      - issuer_category -> CORPORATE

    This ensures _classify_index() returns PREFERRED_EQUITY or COMMON_EQUITY for these rows.
    """
    if "asset_category" not in df.columns or len(df) == 0:
        return df

    fund_mask = df["asset_category"] == "FUND"
    if not fund_mask.any():
        return df

    # Evaluate _is_named_coinvest for FUND rows only
    fund_idx = df.index[fund_mask]
    named_mask = df.loc[fund_idx].apply(
        lambda row: _is_named_coinvest(
            row.get("issuer_name", ""),
            row.get("instrument_description", ""),
            row.get("bdc_investment_identifier", row.get("investment_identifier", "")),
        ),
        axis=1,
    )
    named_idx = fund_idx[named_mask]

    if len(named_idx) == 0:
        return df

    # Determine preferred vs common
    for idx in named_idx:
        combined = ""
        for col in ["issuer_name", "instrument_description"]:
            val = df.at[idx, col] if col in df.columns else ""
            if val and isinstance(val, str):
                combined += " " + val.lower()
        if "preferred" in combined:
            df.at[idx, "asset_category"] = "EQUITY_PREFERRED"
        else:
            df.at[idx, "asset_category"] = "EQUITY_COMMON"
        df.at[idx, "issuer_category"] = "CORPORATE"

    logger.info("  Reclassified %d named co-invest/LP positions from FUND to EQUITY",
                len(named_idx))

    return df


# ---------------------------------------------------------------------------
# BDC preparation
# ---------------------------------------------------------------------------

def _prepare_bdc(
    bdc_df: pd.DataFrame | None = None,
    bdc_file: Union[Path, str, None] = None,
    raw_exclusions: list[dict] | None = None,
    raw_exclusion_audits: list[dict] | None = None,
) -> pd.DataFrame:
    """Filter, parse, classify, and map BDC holdings to unified schema.

    Uses a DuckDB CTE pipeline for all data manipulation.

    Parameters
    ----------
    bdc_df : pd.DataFrame, optional
        Pre-loaded BDC holdings DataFrame.
    bdc_file : Path or str, optional
        Path to BDC holdings file (Parquet or CSV). When provided, DuckDB
        reads the file directly -- much faster than loading via pandas then
        registering.  Falls back to *bdc_df* when the file does not exist.
    raw_exclusions : list of dict, optional
        Promoted comparative-period targets [{cik, report_date}] (see
        ``pipeline.agent_promoted.raw_staging_exclusions``). Applied as
        DELETEs on the raw frame while it still carries XBRL ``period`` --
        the layer where the comparative fix semantically applies.
    raw_exclusion_audits : list, optional
        When provided, application audit rows are appended to it (the caller
        persists the rebuild audit artifact).
    """
    from pipeline.unified_holdings import UNIFIED_COLUMNS

    _optional_cols = (
        "fair_value_unit", "cost_unit", "principal_amount_unit",
        "industry", "investment_type", "affiliation",
        "nonaccrual_footnote", "nonaccrual_dimension",
        "src_context_id",
        "dedupe_context_count", "dedupe_conflict_fields",
        "src_facts", "dedupe_filled_fields",
    )

    con = duckdb.connect()

    # --- data source selection ------------------------------------------------
    if bdc_file is not None and Path(bdc_file).exists():
        fpath = str(bdc_file).replace("\\", "/")
        if str(bdc_file).endswith(".parquet"):
            read_expr = f"read_parquet('{fpath}')"
        else:
            read_expr = f"read_csv_auto('{fpath}', header=true, all_varchar=true)"

        # Materialise once into DuckDB columnar storage (faster than a VIEW
        # when the table is referenced by many downstream CTEs).
        con.execute(f"CREATE TABLE bdc_raw AS SELECT * FROM {read_expr}")
        input_count = con.execute("SELECT COUNT(*) FROM bdc_raw").fetchone()[0]
        logger.info("Preparing BDC holdings: %d input rows (from %s)",
                     input_count, Path(bdc_file).name)

        if input_count == 0:
            con.close()
            return pd.DataFrame(columns=UNIFIED_COLUMNS)

        # Ensure optional columns exist
        existing_cols = {
            r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'bdc_raw'"
            ).fetchall()
        }
        for col in _optional_cols:
            if col not in existing_cols:
                con.execute(f"ALTER TABLE bdc_raw ADD COLUMN {col} VARCHAR DEFAULT ''")

    elif bdc_df is not None:
        input_count = len(bdc_df)
        logger.info("Preparing BDC holdings: %d input rows", input_count)

        if bdc_df.empty:
            con.close()
            return pd.DataFrame(columns=UNIFIED_COLUMNS)

        bdc_df = bdc_df.copy()
        for col in _optional_cols:
            if col not in bdc_df.columns:
                bdc_df[col] = ""
        # Materialise into a TABLE (not a view) so pre-filter DELETEs work
        con.register("_bdc_raw_view", bdc_df)
        con.execute("CREATE TABLE bdc_raw AS SELECT * FROM _bdc_raw_view")

    else:
        raise ValueError("Either bdc_df or bdc_file must be provided")
    # --- end data source selection --------------------------------------------
    if raw_exclusions:
        from pipeline.agent_promoted import apply_raw_staging_exclusions
        audits = apply_raw_staging_exclusions(con, raw_exclusions)
        if raw_exclusion_audits is not None:
            raw_exclusion_audits.extend(audits)
    if FX_RATES_FILE.exists():
        fx_path = str(FX_RATES_FILE).replace("\\", "/")
        con.execute(f"""
            CREATE TEMP TABLE fx_rates AS
            SELECT upper(trim(CAST(currency AS VARCHAR))) AS currency,
                   CAST(rate_date AS VARCHAR) AS rate_date,
                   TRY_CAST(usd_per_currency AS DOUBLE) AS usd_per_currency
            FROM read_csv_auto('{fx_path}', header=true, all_varchar=true)
            WHERE TRY_CAST(usd_per_currency AS DOUBLE) > 0
        """)
    else:
        con.register("fx_rates", pd.DataFrame(columns=[
            "currency", "rate_date", "usd_per_currency",
        ]))
    aggregate_overrides = load_bdc_aggregate_overrides()
    con.register("bdc_aggregate_overrides", aggregate_overrides)
    agg_header_flags = _load_aggregate_header_flags()
    con.register("cc_aggregate_header_flags", agg_header_flags)
    _issuer_bridges = _load_issuer_bridges_from_json()
    _html_section_bridges = _load_html_section_bridges_from_json()
    con.register(
        "saratoga_issuer_bridges",
        pd.DataFrame(
            _issuer_bridges,
            columns=[
                "cik",
                "report_date",
                "raw_id_lower",
                "issuer_name",
                "instrument_description",
            ],
        ),
    )
    _html_bridge_table = pd.DataFrame(
        _html_section_bridges,
        columns=BRIDGE_TABLE_COLUMNS,
    ).rename(columns={
        "cik": "bridge_cik",
        "accession_number": "bridge_accession_number",
        "report_date": "bridge_report_date",
        "raw_id_lower": "bridge_raw_id_lower",
    })
    con.register("html_section_bridges", _html_bridge_table)
    _has_agg_flags = len(agg_header_flags) > 0

    # Pre-generate SQL fragments from Python constants
    agg_filter = _sql_is_bdc_aggregate()
    bad_issuer_filter = _sql_is_bad_issuer_name()
    bad_numeric_issuer_filter = (
        "(LENGTH(trim(CAST(issuer_name AS VARCHAR))) >= 1 "
        "AND NOT regexp_matches(trim(CAST(issuer_name AS VARCHAR)), '[a-zA-Z]'))"
    )
    # Entity signal check on raw identifier -- when issuer_name is bad but raw
    # has company signals (LLC, Inc, etc.), keep the row with raw as issuer_name
    _entity_sigs = [
        "inc.", "inc,", " inc ", " inc-",
        "llc", "l.l.c", "corp.", "corp,",
        "corporation",
        "ltd.", "ltd,", " ltd ",
        "limited",
        ", lp", " lp,", "l.p.",
        "holdings", "holding company",
        "group",
        "gmbh", "sarl", " co.", " plc",
    ]
    _sql_has_entity_in_raw = " OR ".join(
        f"contains(lower(_raw_id), '{s}')" for s in _entity_sigs
    )
    asset_case = _sql_classify_bdc_asset()
    coinvest_expr = _sql_is_named_coinvest()
    mm_check = _sql_money_market_check()
    # Cash-identity check: a row is a genuine cash position only when its own
    # issuer/instrument text names a cash equivalent (money-market fund, treasury,
    # cash deposit).  Rows that match the raw cash filter only via a trailing
    # aggregate phrase like "Total Cash and Cash Equivalents" (filer balance-sheet
    # reconciliation footers such as "Net Assets" / "Liabilities Less Other
    # Assets") are NOT cash positions and must keep being dropped, not retained.
    _cash_identity_keywords = sorted(set(_CASH_KEYWORDS) | set(_MONEY_MARKET_KEYWORDS) | {
        "cash equivalent", "cash equivalents",
        "government obligations", "treasury obligations",
        "liquidity fund", "government fund", "govt fund",
    })
    cash_identity_check = _sql_keyword_check(
        "(lower(trim(CAST(issuer_name AS VARCHAR))) || ' ' "
        "|| lower(trim(CAST(instrument_description AS VARCHAR))))",
        _cash_identity_keywords,
    )
    industry_in = _sql_industry_label_in()
    pipe_parts = "regexp_split_to_array(_raw_id, '\\s*\\|\\s*')"
    has_pipe = "regexp_matches(_raw_id, '\\|')"
    affil_in = _sql_exact_match(
        f"lower(trim({pipe_parts}[-1]))", _AFFILIATION_TAGS
    )
    # 3-pipe format detection helpers
    seg1_has_suffix = (
        f"regexp_matches(lower(trim({pipe_parts}[1])), "
        f"'{_LEGAL_SUFFIX_RE_SQL}')"
    )
    seg2_has_suffix = (
        f"regexp_matches(lower(trim({pipe_parts}[2])), "
        f"'{_LEGAL_SUFFIX_RE_SQL}')"
    )
    seg3_is_instrument = _sql_keyword_check(
        f"lower(trim({pipe_parts}[3]))", _PIPE_INSTRUMENT_KEYWORDS
    )
    seg2_is_industry = _sql_exact_match(
        f"lower(trim({pipe_parts}[2]))", _INDUSTRY_LABELS
    )
    slr_seg2_is_leaf_issuer = (
        f"len({pipe_parts}) >= 3 "
        "AND regexp_matches(lower(trim("
        f"{pipe_parts}[1])), '^equipment\\s+financing\\s*-\\s*-?\\d[\\d.]*%$') "
        "AND NOT starts_with(lower(trim("
        f"{pipe_parts}[2])), 'total ') "
        f"AND NOT {_sql_exact_match(f'lower(trim({pipe_parts}[2]))', _INDUSTRY_LABELS)} "
        "AND NOT regexp_matches(lower(trim("
        f"{pipe_parts}[2])), '^(?:sofr|libor|euribor|prime|s\\s*\\+|e\\s*\\+|\\d|maturity|interest|reference\\s+rate)')"
    )
    name_norm = _sql_normalize_name("issuer_name")

    # Normalised raw identifier: em-dash -> ' - ', en-dash -> '-'
    _norm_raw = (
        "regexp_replace("
        "replace(replace(_raw_id, '\u2014', ' - '), '\u2013', '-'), "
        "'\\s+-\\s*', ' - ', 'g')"
    )
    # Base industry prefix regex (standard labels only)
    _industry_prefix_re = "|".join(
        re.escape(label).replace(r"\ ", r"\s+")
        for label in sorted(_INDUSTRY_LABELS, key=len, reverse=True)
    )
    # Crescent industry label regex (moved earlier for placeholder registry).
    # Sort by length desc so longer, more-specific labels are tried first --
    # otherwise a shorter prefix (e.g. "Diversified") shadows a longer label
    # ("Diversified Financials") in regex alternation (first-match-wins).
    _crescent_industry_re = "|".join(
        re.escape(label).replace("\\ ", "\\s+")
        for label in sorted(_CRESCENT_HIERARCHY_INDUSTRIES, key=len, reverse=True)
    )

    # --- Load all staging configs once, expand placeholders, group by strategy ---
    _staging_configs = _load_staging_configs()
    # Collect per-CIK extra industry labels from staging configs (read before
    # placeholder expansion since these are plain JSON string lists).
    _all_extra_industry_labels: set[str] = set()
    for _cfg in _staging_configs.values():
        _all_extra_industry_labels.update(
            _cfg["staging"].get("extra_industry_labels", [])
        )
    # Expanded industry prefix regex: base labels + all declared extras
    _expanded_industry_prefix_re = "|".join(
        re.escape(label).replace(r"\ ", r"\s+")
        for label in sorted(
            _INDUSTRY_LABELS | _all_extra_industry_labels, key=len, reverse=True
        )
    )
    _placeholders = {
        "(?:INDUSTRY_LABELS)": f"(?:{_industry_prefix_re})",
        "(?:MSD_INDUSTRY_LABELS)": f"(?:{_expanded_industry_prefix_re})",
        "(?:CRESCENT_INDUSTRY_LABELS)": f"(?:{_crescent_industry_re})",
    }
    for _cfg in _staging_configs.values():
        _expand_staging_strings(_cfg["staging"], _placeholders)
    _prefix_strip_cfgs = {k: v for k, v in _staging_configs.items()
                          if v["staging"].get("strategy") == "prefix_strip"}
    _hierarchy_extract_cfgs = {k: v for k, v in _staging_configs.items()
                               if v["staging"].get("strategy") == "hierarchy_extract"}
    _leaf_guard_cfgs = {k: v for k, v in _staging_configs.items()
                        if v["staging"].get("strategy") == "hierarchy_leaf_guard"}

    # --- pipe_field_map: CIK-scoped overrides for pipe-delimited segment layout ---
    _pipe_field_map_cfgs: list[dict[str, Any]] = []
    for _pfm_norm, _pfm_cfg in _staging_configs.items():
        pfm = _pfm_cfg["staging"].get("pipe_field_map")
        if pfm is None:
            continue
        _pfm_cik = _pfm_cfg["cik"]
        _pfm_cik_sql = (
            "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), "
            f"10, '0') = '{_pfm_cik}'"
        )
        _pipe_field_map_cfgs.append({
            "cik": _pfm_cik,
            "cik_sql": _pfm_cik_sql,
            "issuer_segment": pfm["issuer_segment"],
            "instrument_segments": pfm.get("instrument_segments", []),
            "industry_segment": pfm.get("industry_segment"),
            "lien_segment": pfm.get("lien_segment"),
        })

    # Build CIK-scoped pipe_field_map WHEN branches for _pipe_issuer
    _pfm_issuer_parts: list[str] = []
    _pfm_format_parts: list[str] = []
    for _pfm in _pipe_field_map_cfgs:
        seg = _pfm["issuer_segment"]
        _pfm_issuer_parts.append(
            f"WHEN {has_pipe} AND len({pipe_parts}) >= {seg} "
            f"AND {_pfm['cik_sql']}\n"
            f"                THEN trim({pipe_parts}[{seg}])"
        )
        _pfm_format_parts.append(
            f"WHEN {has_pipe} AND len({pipe_parts}) >= {seg} "
            f"AND {_pfm['cik_sql']}\n"
            f"                THEN 'field_map'"
        )
    _pfm_issuer_sql = "\n                ".join(_pfm_issuer_parts) if _pfm_issuer_parts else ""
    _pfm_format_sql = "\n                ".join(_pfm_format_parts) if _pfm_format_parts else ""

    # Build CIK-scoped pipe_field_map WHEN branches for instrument_description
    _pfm_instrument_parts: list[str] = []
    for _pfm in _pipe_field_map_cfgs:
        inst_segs = _pfm.get("instrument_segments", [])
        if inst_segs:
            # Concatenate declared instrument segments with ', '
            concat_expr = " || ', ' || ".join(
                f"trim({pipe_parts}[{s}])" for s in inst_segs
            )
            min_seg = max(inst_segs)
            _pfm_instrument_parts.append(
                f"WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'field_map' "
                f"AND {_pfm['cik_sql']}\n"
                f"                THEN {concat_expr}"
            )
        else:
            # No instrument segments: use the issuer segment as-is
            seg = _pfm["issuer_segment"]
            _pfm_instrument_parts.append(
                f"WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'field_map' "
                f"AND {_pfm['cik_sql']}\n"
                f"                THEN trim({pipe_parts}[{seg}])"
            )
    _pfm_instrument_sql = "\n                ".join(_pfm_instrument_parts) if _pfm_instrument_parts else ""

    # Prefix-strip hierarchy: build per-CIK conditions and clean expressions
    # so each CIK's own hierarchy_prefix_re is applied correctly.
    _prefix_strip_per_cik: list[dict[str, str]] = []
    for _ps_cfg in _prefix_strip_cfgs.values():
        _ps_cik = _ps_cfg["cik"]
        _ps_re = _ps_cfg["staging"]["hierarchy_prefix_re"]
        _ps_cik_sql = (
            f"LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), "
            f"10, '0') = '{_ps_cik}'"
        )
        _prefix_strip_per_cik.append({"cik_sql": _ps_cik_sql, "re": _ps_re})
    # CIKs eligible for single-child rollup detection (comma-delimited format)
    _comma_delim_ciks = _get_comma_delimited_ciks()
    _single_child_rollup_cik_sql = (
        "LPAD(REGEXP_REPLACE(CAST(a.cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') "
        "IN (" + ", ".join(f"'{c}'" for c in _comma_delim_ciks) + ")"
    ) if _comma_delim_ciks else "FALSE"
    # Combined condition: any prefix_strip CIK matches its own regex
    _msd_hierarchy_condition = (
        " OR ".join(
            f"({d['cik_sql']} AND regexp_matches(_raw_id, '{d['re']}'))"
            for d in _prefix_strip_per_cik
        )
        if _prefix_strip_per_cik else "FALSE"
    )
    # Per-CIK clean expression: apply the matching CIK's regex
    _msd_clean_raw = (
        ("CASE " + " ".join(
            f"WHEN {d['cik_sql']} THEN regexp_replace("
            f"regexp_replace(_raw_id, '{d['re']}', ''), '{d['re']}', '')"
            for d in _prefix_strip_per_cik
        ) + " ELSE _raw_id END")
        if _prefix_strip_per_cik else "_raw_id"
    )
    # Prefix-rules aggregate bypass: CIKs with declared prefix_rules in
    # their wrapper JSON should not have real positions dropped by the
    # aggregate filter when the identifier starts with a declared prefix
    # AND the remainder contains entity signals or leaf detail.
    _prefix_rules_data = _get_prefix_rules_data()
    # Shared instrument-keyword regex for prefix_rules CIKs.  Used both
    # in the aggregate-filter bypass (rescue real positions) and in the
    # no_prefix_hierarchy CTE (remove subtotals).
    _pr_instrument_re = (
        r"(?:unitranche|first[-\s]+lien|second[-\s]+lien|term\s+loan|secured\s+loan"
        r"|delayed\s+draw|revolver|revolving|senior\s+secured|subordinated"
        r"|equipment\s+financing|notes?\b|bonds?\b|common\s+(?:stock|equity|units)"
        r"|preferred\s+(?:stock|equity|units|shares)"
        r"|warrants?\b|equity\s+(?:interest|co-invest|investment)"
        r"|partnership\s+interest|llc\s+interest|member(?:ship)?\s+interest"
        r"|class\s+[a-z][a-z0-9_-]*\s+(?:interest|units|shares|membership\s+units)"
        r"|type\s+of\s+investment|interest\s+rate|maturity\s+date|maturity\s+\d"
        r"|reference\s+rate|sofr|libor|euribor|prime\s+rate|corra)"
    )
    _prefix_rules_condition_parts: list[str] = []
    _prefix_rules_hierarchy_parts: list[str] = []
    _double_investments_cik_norms: list[str] = []
    _prefix_strip_cik_set = {v["cik"] for v in _prefix_strip_cfgs.values()}
    for _pr_cik, _pr_prefixes in _prefix_rules_data.items():
        _pr_cik_norm = _pr_cik.lstrip("0").zfill(10)
        _pr_cik_sql = (
            f"LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') "
            f"= '{_pr_cik_norm}'"
        )
        # Track CIKs that use "Investments Investments" as a declared prefix,
        # but skip CIKs with prefix_strip staging since they have their own
        # hierarchy_prefix_re that handles the full stripping correctly.
        if (any(p.lower() == "investments investments" for p in _pr_prefixes)
                and _pr_cik_norm not in _prefix_strip_cik_set):
            _double_investments_cik_norms.append(_pr_cik_norm)
        # Build regex to match any declared prefix (case-insensitive)
        _pr_prefix_alts = "|".join(
            re.escape(p) for p in sorted(_pr_prefixes, key=len, reverse=True)
        )
        # After the prefix, require an instrument-type keyword somewhere
        # in the remainder (prefix stripped). This rescues real positions
        # (which always name their instrument) while blocking issuer-level
        # and sector-level subtotals that contain company names but no
        # instrument detail.  We strip the prefix before checking because
        # prefixes like "Portfolio Company Warrant Investments" contain
        # instrument words ("warrant") that would incorrectly rescue all rows.
        _pr_remainder = (
            f"lower(regexp_replace(_raw_id, "
            f"'(?i)^(?:{_pr_prefix_alts})\\s*-?\\s*', ''))"
        )
        _pr_condition = (
            f"({_pr_cik_sql} "
            f"AND regexp_matches(_raw_id, '(?i)^(?:{_pr_prefix_alts})\\s') "
            f"AND regexp_matches({_pr_remainder}, '(?i){_pr_instrument_re}')"
            f")"
        )
        _prefix_rules_condition_parts.append(_pr_condition)

        # Build per-CIK subtotal filter for no_prefix_hierarchy CTE.
        # For prefix_rules CIKs, real positions always start with a
        # declared prefix AND have instrument keywords after the prefix.
        # Subtotals that survive the aggregate filter are caught by four
        # conditions:
        _pr_entity_check = " OR ".join(
            f"contains(lower(_raw_id), '{s}')" for s in _entity_sigs
        )
        # Prefix match that also handles dash separators ("Prefix- ...")
        # and bare prefix with no suffix ("Prefix" at end of string).
        _pr_prefix_match = (
            f"regexp_matches(_raw_id, '(?i)^(?:{_pr_prefix_alts})(?:\\s|-|$)')"
        )
        _pr_hier_conds = [
            # 2a: Prefix-starting rows without instrument detail after prefix
            (
                f"({_pr_prefix_match} "
                f"AND NOT regexp_matches({_pr_remainder}, '(?i){_pr_instrument_re}'))"
            ),
            # 2b: "Total X" rows without instrument keywords — catches both
            # starts_with("total ") and embedded "Total" after sector names
            # (e.g. "...United States Total Applied Digital Corporation")
            (
                f"(regexp_matches(_lower_id, '(?:^|\\s)total\\s') "
                f"AND NOT regexp_matches(lower(_raw_id), '(?i){_pr_instrument_re}'))"
            ),
            # 2c: Affiliation headers that lack a separator after "Investments"
            (
                "(regexp_matches(_lower_id, "
                "'^(?:control(?:led)?|affiliate[d]?|non-?control(?:led)?(?:[/,]\\s*non-?affiliate[d]?)?)"
                "\\s+(?:and\\s+(?:control(?:led)?|affiliate[d]?)\\s+)?investments\\s*$'))"
            ),
            # 2d: Bare entity names without prefix or instrument keywords
            # (e.g. "Bestow, Inc." from affiliation stripping)
            (
                f"(NOT {_pr_prefix_match} "
                f"AND NOT regexp_matches(_lower_id, '(?:^|\\s)total\\s') "
                "AND NOT regexp_matches(_lower_id, "
                "'^(?:control(?:led)?|affiliate[d]?|non-?control(?:led)?(?:[/,]\\s*non-?affiliate[d]?)?)"
                "\\s+(?:and\\s+(?:control(?:led)?|affiliate[d]?)\\s+)?investments') "
                f"AND ({_pr_entity_check}) "
                f"AND NOT regexp_matches(lower(_raw_id), '(?i){_pr_instrument_re}'))"
            ),
        ]
        _pr_hier_condition = (
            f"({_pr_cik_sql} AND ({' OR '.join(_pr_hier_conds)}))"
        )
        _prefix_rules_hierarchy_parts.append(_pr_hier_condition)

    _prefix_rules_hierarchy_condition = (
        " OR ".join(_prefix_rules_condition_parts)
        if _prefix_rules_condition_parts
        else "FALSE"
    )
    # Combined subtotal filter for prefix_rules CIKs (used by
    # no_prefix_hierarchy CTE below no_aggregates).
    _prefix_hierarchy_filter = (
        " OR ".join(_prefix_rules_hierarchy_parts)
        if _prefix_rules_hierarchy_parts
        else "FALSE"
    )

    # CIK-scoped stripping of "Investments Investments" double-prefix in
    # strip_affil.  These CIKs declare "Investments Investments" as a
    # prefix_rules prefix; without stripping, the dash-split in Phase B
    # produces issuer_name = "Investments Investments" which gets caught
    # by the aggregate header flags.  The regex mirrors
    # _INVESTMENTS_HIERARCHY_RE but anchored to the double form.
    _double_inv_cik_sql = (
        "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') "
        "IN (" + ", ".join(
            f"'{c}'" for c in _double_investments_cik_norms
        ) + ")"
    ) if _double_investments_cik_norms else "FALSE"
    _DOUBLE_INVESTMENTS_HIERARCHY_RE = (
        r"(?i)^Investments\s+Investments\s*(?:--|-|/)\s*"
        r"(?:non-?\s*control(?:led)?(?:\s*[/,]\s*non-?\s*affiliat(?:e|ed|d))?"
        r"|control(?:led)?(?:\s*[/,]\s*affiliat(?:e|ed|d))?"
        r"|affiliat(?:e|ed|d))"
        r"(?:\s+(?:equity|debt|first\s+lien|second\s+lien|senior\s+secured"
        r"|subordinated|unsecured|mezzanine|unitranche|preferred|common"
        r"|warrant|structured|other)(?:\s+(?:securities|investments|interests))?)?"
        r"\s+"
    )

    # Entity signal check on seg[1] (for pct-prefix category detection)
    _seg1_entity_sql = " OR ".join(
        f"contains(lower(trim(_segments[1])), '{s}')" for s in _entity_sigs
    )

    # Keyword boundary regex for extracting company name from pct-prefix segments
    _kw_boundary_re = (
        r"^(.+?)\s+(?:Industry|Interest Rate|Current Coupon|Maturity"
        r"|Reference Rate|Basis Point|Floor|PIK)(?:\s|$)"
    )

    # --- Hierarchical pct identifier parser (config-driven) -----------------
    _id_parsers = _load_identifier_parsers()
    _hier_pct_ciks = [
        cik for cik, cfg in _id_parsers.items()
        if cfg.get("type") == "hierarchical_pct"
    ]
    _hier_pct_cik_sql = (
        "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') "
        "IN (" + ", ".join(f"'{c}'" for c in _hier_pct_ciks) + ")"
    ) if _hier_pct_ciks else "FALSE"
    _hier_pct_leaf_prefix_re = "^-?\\d[\\d.]*%,?\\s+\\S"
    # Condition: CIK matches AND >= 2 segments AND last segment has pct prefix.
    # Some hierarchical-pct filers use comma-delimited category chains, leaving
    # the final dash segment as "1.06%, Issuer"; accept the comma as delimiter.
    # Issuer names can also contain dashes, e.g. "Foundation Software - Class B",
    # so also accept a percent-prefixed penultimate segment.
    _hier_pct_condition = (
        f"({_hier_pct_cik_sql} "
        "AND len(_segments) >= 2 "
        f"AND (regexp_matches(trim(_segments[-1]), '{_hier_pct_leaf_prefix_re}') "
        f"OR (len(_segments) >= 5 AND regexp_matches(trim(_segments[-2]), '{_hier_pct_leaf_prefix_re}'))))"
    )
    _hier_leaf_sql = (
        "CASE "
        f"WHEN regexp_matches(trim(_segments[-1]), '{_hier_pct_leaf_prefix_re}') "
        "THEN trim(_segments[-1]) "
        f"WHEN len(_segments) >= 5 AND regexp_matches(trim(_segments[-2]), '{_hier_pct_leaf_prefix_re}') "
        "THEN trim(_segments[-2] || ' - ' || _segments[-1]) "
        "ELSE trim(_segments[-1]) END"
    )
    _hier_instrument_segment_sql = (
        "CASE "
        f"WHEN len(_segments) >= 5 AND regexp_matches(trim(_segments[-2]), '{_hier_pct_leaf_prefix_re}') "
        "THEN trim(_segments[-3]) "
        "ELSE trim(_segments[-2]) END"
    )
    # Build boundary keyword regex from all hierarchical_pct configs (union)
    _hier_boundary_kws: set[str] = set()
    _hier_country_names: set[str] = set()
    for _hp_cfg in _id_parsers.values():
        if _hp_cfg.get("type") == "hierarchical_pct":
            _hier_boundary_kws.update(_hp_cfg.get("issuer_boundary_keywords", []))
            _hier_country_names.update(_hp_cfg.get("country_list", []))
    _hier_boundary_re = (
        "(?:" + "|".join(
            re.escape(kw).replace(r"\ ", r"\s+")
            for kw in sorted(_hier_boundary_kws, key=len, reverse=True)
        ) + ")"
    ) if _hier_boundary_kws else "ZZZZZ_NO_MATCH"
    _hier_country_re = (
        "(?:" + "|".join(
            re.escape(c) for c in sorted(_hier_country_names, key=len, reverse=True)
        ) + ")"
    ) if _hier_country_names else "ZZZZZ_NO_MATCH"
    # Industry label regex for trailing equity match (no "Industry" keyword)
    _hier_industry_label_re = (
        "(?:" + "|".join(
            re.escape(label).replace(r"\ ", r"\s+")
            for label in sorted(_INDUSTRY_LABELS, key=len, reverse=True)
        ) + ")"
    )
    # --- end hierarchical pct parser setup ------------------------------------

    # Industry label check on seg[3] (for geography-prefix detection in Blue Owl)
    _seg3_is_industry = _sql_exact_match(
        "lower(trim(_segments[3]))", _INDUSTRY_LABELS
    )
    # hierarchy_extract: per-CIK regexes from staging configs
    # Clean raw: collapse whitespace, replace NBSP, insert space before
    # Investment/Security Type when missing (Apollo filing data quality issue:
    # e.g. "Inc.Investment Type" -> "Inc. Investment Type").
    _he_clean_raw = (
        "replace(replace("
        "regexp_replace(replace(CAST(_raw_id AS VARCHAR), '\u00a0', ' '), "
        "'\\s+', ' ', 'g'), "
        "'Investment Type', ' Investment Type'), "
        "'Security Type', ' Security Type')"
    )
    # Build per-CIK hierarchy_extract components (parallel to _lg_per_cik)
    _he_per_cik: list[dict[str, str]] = []
    for _he_cfg in _hierarchy_extract_cfgs.values():
        _he_cik = _he_cfg["cik"]
        _he_stg = _he_cfg["staging"]
        _he_cik_sql = (
            "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), "
            f"10, '0') = '{_he_cik}'"
        )
        _cond = _he_stg.get("hierarchy_condition_extra", "FALSE")
        _cond = _cond.replace("_clean", _he_clean_raw)
        _he_per_cik.append({
            "cik": _he_cik,
            "cik_sql": _he_cik_sql,
            "condition": f"{_he_cik_sql} AND {_cond}",
            "issuer_re": _he_stg.get("hierarchy_issuer_re", ""),
            "instrument_re": _he_stg.get("hierarchy_instrument_re", ""),
            "trailing_re": _he_stg.get("hierarchy_trailing_re", ""),
        })
    # Per-CIK SQL WHEN branches for issuer extraction
    _he_issuer_parts: list[str] = []
    for _he in _he_per_cik:
        _he_issuer_parts.append(
            f"WHEN {_he['condition']}\n"
            f"                THEN trim(regexp_extract(\n"
            f"                    {_he_clean_raw},\n"
            f"                    '{_he['issuer_re']}',\n"
            f"                    1\n"
            f"                ))"
        )
    _he_issuer_sql = "\n                ".join(_he_issuer_parts) if _he_issuer_parts else (
        "WHEN FALSE THEN NULL"
    )
    # Per-CIK SQL WHEN branches for instrument extraction
    _he_instrument_parts: list[str] = []
    for _he in _he_per_cik:
        _instr = (
            f"WHEN {_he['condition']}\n"
            f"                THEN trim(regexp_extract(\n"
            f"                    {_he_clean_raw},\n"
            f"                    '{_he['instrument_re']}',\n"
            f"                    1\n"
            f"                ))"
        )
        if _he["trailing_re"]:
            _instr = (
                f"WHEN {_he['condition']}\n"
                f"                THEN trim(regexp_extract(\n"
                f"                    {_he_clean_raw},\n"
                f"                    '{_he['instrument_re']}',\n"
                f"                    1\n"
                f"                )) || COALESCE(\n"
                f"                    NULLIF(' - ' || trim(regexp_extract(\n"
                f"                        {_he_clean_raw},\n"
                f"                        '{_he['trailing_re']}',\n"
                f"                        1\n"
                f"                    )), ' - '),\n"
                f"                    ''\n"
                f"                )"
            )
        _he_instrument_parts.append(_instr)
    _he_instrument_sql = "\n                ".join(_he_instrument_parts) if _he_instrument_parts else (
        "WHEN FALSE THEN NULL"
    )
    _he_any_condition = (
        "(" + " OR ".join(f"({_he['condition']})" for _he in _he_per_cik) + ")"
    ) if _he_per_cik else "FALSE"
    # Hierarchy leaf guard: CIK list, prefix patterns, marker/evidence from JSON
    _hierarchy_leaf_ciks = [v["cik"] for v in _leaf_guard_cfgs.values()]
    _hierarchy_leaf_cik_sql = (
        "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') "
        "IN (" + ", ".join(f"'{c}'" for c in _hierarchy_leaf_ciks) + ")"
    ) if _hierarchy_leaf_ciks else "FALSE"
    # Build per-CIK leaf guard components
    _lg_per_cik: list[dict[str, str]] = []
    for _lg_cik_norm, _lg_cfg in _leaf_guard_cfgs.items():
        lg = _lg_cfg["staging"]["leaf_guard"]
        _lg_prefix_re = lg["type_industry_prefix_re"]
        _lg_per_cik.append({
            "cik_norm": _lg_cik_norm,
            "prefix_re": _lg_prefix_re,
            "clean_raw": f"regexp_replace(_raw_id, '{_lg_prefix_re}', '')",
            "marker_re": lg["marker_re"],
            "evidence_re": lg["evidence_re"],
        })
    # Chain per-CIK type_industry_prefix_re patterns via nested regexp_replace()
    # Since prefixes are anchored (^) and CIK-specific, non-matching patterns
    # are no-ops (same behavior as the former hardcoded chaining).
    _leaf_clean = "_raw_id"
    for _lg in _lg_per_cik:
        _leaf_clean = f"regexp_replace({_leaf_clean}, '{_lg['prefix_re']}', '')"
    _hierarchy_leaf_clean_raw = _leaf_clean

    # Per-CIK SQL branching for marker_re/evidence_re.
    # Shared-path optimization: if all CIKs have identical values, produce
    # compact SQL equivalent to the former single-marker approach.
    _lg_marker_set = {lg["marker_re"] for lg in _lg_per_cik}
    _lg_evidence_set = {lg["evidence_re"] for lg in _lg_per_cik}
    _all_same_marker_evidence = (len(_lg_marker_set) <= 1
                                 and len(_lg_evidence_set) <= 1)

    def _cik_check_sql(cik_norm: str) -> str:
        return (
            "LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), "
            f"'[^0-9]', '', 'g'), 10, '0') = '{cik_norm}'"
        )

    if _all_same_marker_evidence and _lg_per_cik:
        # Homogeneous path: single condition / issuer_re / instrument_re
        _marker = _lg_per_cik[0]["marker_re"]
        _evidence = _lg_per_cik[0]["evidence_re"]
        _hierarchy_leaf_condition = (
            f"{_hierarchy_leaf_cik_sql} "
            f"AND NOT contains({_norm_raw}, ' - ') "
            f"AND regexp_matches({_hierarchy_leaf_clean_raw}, "
            f"'(?i)\\s+{_marker}\\b') "
            f"AND regexp_matches(lower({_hierarchy_leaf_clean_raw}), "
            f"'{_evidence}')"
        )
        _issuer_re = rf"(?i)^(.+?)\s+{_marker}\b"
        _instrument_re = rf"(?i)^.+?\s+({_marker}\b.*)$"
        _hierarchy_leaf_issuer_sql = (
            f"WHEN {_hierarchy_leaf_condition}\n"
            f"                THEN trim(regexp_extract(\n"
            f"                    {_hierarchy_leaf_clean_raw},\n"
            f"                    '{_issuer_re}',\n"
            f"                    1\n"
            f"                ))"
        )
        _hierarchy_leaf_instrument_sql = (
            f"WHEN {_hierarchy_leaf_condition}\n"
            f"                THEN trim(regexp_extract(\n"
            f"                    {_hierarchy_leaf_clean_raw},\n"
            f"                    '{_instrument_re}',\n"
            f"                    1\n"
            f"                ))"
        )
    elif _lg_per_cik:
        # Per-CIK path: generate separate WHEN branches per CIK
        _lg_cond_parts = []
        _lg_issuer_parts = []
        _lg_instrument_parts = []
        for _lg in _lg_per_cik:
            _cik_cond = (
                f"({_cik_check_sql(_lg['cik_norm'])} "
                f"AND NOT contains({_norm_raw}, ' - ') "
                f"AND regexp_matches({_lg['clean_raw']}, "
                f"'(?i)\\s+{_lg['marker_re']}\\b') "
                f"AND regexp_matches(lower({_lg['clean_raw']}), "
                f"'{_lg['evidence_re']}'))"
            )
            _lg_cond_parts.append(_cik_cond)
            _i_re = rf"(?i)^(.+?)\s+{_lg['marker_re']}\b"
            _d_re = rf"(?i)^.+?\s+({_lg['marker_re']}\b.*)$"
            _lg_issuer_parts.append(
                f"WHEN {_cik_cond}\n"
                f"                THEN trim(regexp_extract(\n"
                f"                    {_lg['clean_raw']},\n"
                f"                    '{_i_re}',\n"
                f"                    1\n"
                f"                ))"
            )
            _lg_instrument_parts.append(
                f"WHEN {_cik_cond}\n"
                f"                THEN trim(regexp_extract(\n"
                f"                    {_lg['clean_raw']},\n"
                f"                    '{_d_re}',\n"
                f"                    1\n"
                f"                ))"
            )
        _hierarchy_leaf_condition = " OR ".join(_lg_cond_parts)
        _hierarchy_leaf_issuer_sql = "\n                ".join(
            _lg_issuer_parts
        )
        _hierarchy_leaf_instrument_sql = "\n                ".join(
            _lg_instrument_parts
        )
    else:
        # No leaf_guard CIKs configured
        _hierarchy_leaf_condition = "FALSE"
        _hierarchy_leaf_issuer_sql = "WHEN FALSE THEN NULL"
        _hierarchy_leaf_instrument_sql = "WHEN FALSE THEN NULL"

    # Fund vehicle/manager detection: equity-type positions with these name
    # signals get issuer_category = FUND (overrides the default CORPORATE).
    fund_vehicle_clauses = []
    for kw in _BDC_FUND_VEHICLE_KEYWORDS:
        kw_escaped = kw.replace("'", "''")
        if kw == "asset management":
            # Position guard: must appear within first N chars
            fund_vehicle_clauses.append(
                f"(strpos(lower(CAST(issuer_name AS VARCHAR)), '{kw_escaped}') > 0"
                f" AND strpos(lower(CAST(issuer_name AS VARCHAR)), '{kw_escaped}')"
                f" <= {_BDC_FUND_VEHICLE_POS_GUARD})"
            )
        else:
            fund_vehicle_clauses.append(
                f"contains(lower(CAST(issuer_name AS VARCHAR)), '{kw_escaped}')"
            )
    fund_vehicle_sql = " OR ".join(fund_vehicle_clauses)

    # Filter comparative-period rows if the 'period' column exists.
    # Also exclude pre-2022 BDC data (unreliable partial XBRL coverage).
    # Rows with NULL/empty report_date pass the cutoff (test compatibility).
    _bdc_raw_cols = {
        r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'bdc_raw'"
        ).fetchall()
    }
    has_period = "period" in _bdc_raw_cols

    # -- Pre-filter: DELETE comparative-period and pre-2022 rows from the
    # materialized table BEFORE any CTE processing.  This drops ~50% of rows
    # so every downstream CTE, regex, and join operates on half the data.
    pre_filter_count = con.execute("SELECT COUNT(*) FROM bdc_raw").fetchone()[0]
    if has_period:
        con.execute("""
            DELETE FROM bdc_raw
            WHERE NOT (
                TRY_CAST(period AS DATE) = TRY_CAST(report_date AS DATE)
                OR period IS NULL
                OR CAST(period AS VARCHAR) = ''
            )
            OR (TRY_CAST(report_date AS DATE) < '2022-01-01'
                AND TRY_CAST(report_date AS DATE) IS NOT NULL)
        """)
    else:
        con.execute("""
            DELETE FROM bdc_raw
            WHERE TRY_CAST(report_date AS DATE) < '2022-01-01'
              AND TRY_CAST(report_date AS DATE) IS NOT NULL
        """)
    post_filter_count = con.execute("SELECT COUNT(*) FROM bdc_raw").fetchone()[0]
    removed = pre_filter_count - post_filter_count
    if removed > 0:
        logger.info("  Pre-filtered: %d -> %d rows (%d comparative/pre-2022 removed)",
                    pre_filter_count, post_filter_count, removed)

    # Period/date filtering already applied via DELETE above
    period_filter = "WHERE TRUE"

    # =========================================================================
    # Wrapper disposition lookup table.
    # For wrapper-covered CIKs, call classify_identifier() on each raw
    # investment_identifier in bdc_raw to get wrapper_disposition.  This is
    # used in Phase A CTEs to rescue *_position_leaf rows from aggregate/
    # prefix-hierarchy heuristics and to drop *_rollup / aggregate rows.
    # =========================================================================
    _wrapper_ciks = supported_wrapper_ciks()
    if _wrapper_ciks:
        _wd_cik_filter = ", ".join(f"'{c}'" for c in _wrapper_ciks)
        _wd_candidates = con.execute(f"""
            SELECT DISTINCT
                LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik_norm,
                COALESCE(CAST(investment_identifier AS VARCHAR), '') AS raw_id
            FROM bdc_raw
            WHERE LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')
                  IN ({_wd_cik_filter})
        """).fetchdf()
        _disp_rows = []
        for _, _r in _wd_candidates.iterrows():
            result = classify_identifier(_r["cik_norm"], _r["raw_id"])
            disp = result.get("wrapper_disposition", "")
            if disp:
                _disp_rows.append({
                    "cik_norm": _r["cik_norm"],
                    "raw_id": _r["raw_id"],
                    "wrapper_disposition": disp,
                })
        if _disp_rows:
            _disp_df = pd.DataFrame(_disp_rows)
            con.register("_wd_view", _disp_df)
            con.execute("CREATE TEMP TABLE _wrapper_disp AS SELECT * FROM _wd_view")
            logger.info("  Wrapper disposition lookup: %d classified from %d candidates",
                         len(_disp_rows), len(_wd_candidates))
        else:
            con.execute(
                "CREATE TEMP TABLE _wrapper_disp "
                "(cik_norm VARCHAR, raw_id VARCHAR, wrapper_disposition VARCHAR)"
            )
    else:
        con.execute(
            "CREATE TEMP TABLE _wrapper_disp "
            "(cik_norm VARCHAR, raw_id VARCHAR, wrapper_disposition VARCHAR)"
        )

    # Conditional CTE for CC-reviewed aggregate header exclusion.
    # When the aggregate_header_flags.csv file has entries, inject a CTE
    # that LEFT JOINs against the flags and filters out matches.
    # Two-pass matching:
    #   1. Exact match on identifier_raw (backfilled raw investment_identifier)
    #      against _lower_id -- precise, no normalization loss.
    #   2. Fallback: normalized issuer_name against name_norm (original logic).
    # Safety guard: skip exclusion when the row has position-level detail
    # fields (interest_rate, maturity, principal, shares) to prevent
    # false positives from normalization collisions.
    _legal_suffix_sql = (
        r",?\s*\b(llc|l\.l\.c\.|inc\.?|incorporated|corp\.?|corporation"
        r"|ltd\.?|limited|l\.p\.?|lp|co\.?|company|holdings|holding"
        r"|group|enterprises?|plc|p\.l\.c\.|n\.v\.|s\.a\.|ag|gmbh"
        r"|international|intl\.?)\b\.?\s*$"
    )
    _detail_guard = (
        "n._ir IS NULL "
        "AND n._pa IS NULL AND n._sh IS NULL"
    )
    if _has_agg_flags:
        _cc_agg_header_cte = (
            "-- CTE 5c2: Exclude CC-reviewed aggregate headers.\n"
            "    -- Two-pass: (1) exact identifier_raw match on _lower_id,\n"
            "    -- (2) fallback normalized issuer_name match on name_norm.\n"
            "    -- Safety guard: rows with detail fields are never excluded.\n"
            "    no_cc_agg_headers AS (\n"
            "        SELECT n.* FROM no_bad_issuers n\n"
            "        LEFT JOIN cc_aggregate_header_flags f1\n"
            "            ON f1.identifier_raw != ''\n"
            "            AND lower(TRIM(CAST(n._lower_id AS VARCHAR))) = f1.identifier_raw\n"
            "        LEFT JOIN cc_aggregate_header_flags f2\n"
            "            ON f1.identifier_raw IS NULL\n"
            "            AND TRIM(REGEXP_REPLACE(\n"
            "                   REGEXP_REPLACE(\n"
            "                       lower(TRIM(CAST(n.issuer_name AS VARCHAR))),\n"
            f"                       '{_legal_suffix_sql}',\n"
            "                       '', 'i'),\n"
            "                   '\\s+', ' ', 'g')\n"
            "               ) = f2.name_norm\n"
            "        WHERE (f1.identifier_raw IS NULL AND f2.name_norm IS NULL)\n"
            f"           OR NOT ({_detail_guard})\n"
            "    ),"
        )
        _affil_dedup_source = "no_cc_agg_headers"
    else:
        _cc_agg_header_cte = "-- (no aggregate header flags loaded)"
        _affil_dedup_source = "no_bad_issuers"

    # =========================================================================
    # Phase A: Row-level normalization, scale correction, amendment dedup,
    # affiliation stripping, aggregate/artifact filtering, and prefix rollup.
    # Materializes into _bdc_phase_a temp table so downstream phases read a
    # clean columnar scan instead of re-deriving through the CTE chain.
    # =========================================================================
    _t_phase = time.time()
    sql_phase_a = f"""
    CREATE TEMP TABLE _bdc_phase_a AS
    WITH
    -- CTE 1: Normalise text columns, cast numerics, add row id
    -- Comparative-period and pre-2022 rows already removed by pre-filter DELETE.
    raw AS (
        SELECT
            *,
            ROW_NUMBER() OVER (
                ORDER BY
                    COALESCE(CAST(cik AS VARCHAR), ''),
                    COALESCE(CAST(report_date AS VARCHAR), ''),
                    COALESCE(CAST(accession_number AS VARCHAR), ''),
                    COALESCE(CAST(investment_identifier AS VARCHAR), ''),
                    COALESCE(CAST(dimensions_raw AS VARCHAR), ''),
                    COALESCE(CAST(fair_value AS VARCHAR), '')
            ) AS _row_id,
            COALESCE(CAST(investment_identifier AS VARCHAR), '') AS _raw_id,
            COALESCE(lower(trim(CAST(investment_identifier AS VARCHAR))), '') AS _lower_id,
            TRY_CAST(fair_value AS DOUBLE) AS _fv,
            TRY_CAST(interest_rate AS DOUBLE) AS _ir,
            TRY_CAST(principal_amount AS DOUBLE) AS _pa,
            TRY_CAST(shares_held AS DOUBLE) AS _sh,
            TRY_CAST(basis_spread AS DOUBLE) AS _bs,
            TRY_CAST(cost AS DOUBLE) AS _cost,
            TRY_CAST(pct_of_net_assets AS DOUBLE) AS _pct,
            TRY_CAST(pik_rate AS DOUBLE) AS _pik,
            TRY_CAST(unrealized_gain_loss AS DOUBLE) AS _ugl
        FROM bdc_raw
        {period_filter}
    ),

    -- CTE 1a-i: Detect 1000x scale errors by comparing each CIK-quarter's
    -- total FV against the CIK's median across all quarters.  Requires >= 3
    -- quarters so the median is robust.  Only fires when ratio > 100x, which
    -- catches clear filer errors (observed: CIK 1825265/2023-03-31 and
    -- CIK 1916608/2023-06-30) without risking false positives on genuine
    -- portfolio growth.
    _quarterly_fv AS (
        SELECT cik, CAST(report_date AS VARCHAR) AS report_date,
               SUM(_fv) AS total_fv
        FROM raw
        WHERE _fv IS NOT NULL AND _fv > 0
        GROUP BY cik, CAST(report_date AS VARCHAR)
    ),
    _cik_medians AS (
        SELECT cik, MEDIAN(total_fv) AS median_fv, COUNT(*) AS n_quarters
        FROM _quarterly_fv
        GROUP BY cik
    ),
    _scale_errors AS (
        SELECT q.cik, q.report_date
        FROM _quarterly_fv q
        JOIN _cik_medians m ON q.cik = m.cik
        WHERE m.n_quarters >= 3
          AND m.median_fv > 0
          AND q.total_fv / m.median_fv > 100
    ),
    scale_corrected AS (
        SELECT r.* EXCLUDE (_fv, _cost, _pa),
            CASE WHEN s.cik IS NOT NULL THEN r._fv / 1000 ELSE r._fv END AS _fv,
            CASE WHEN s.cik IS NOT NULL THEN r._cost / 1000 ELSE r._cost END AS _cost,
            CASE WHEN s.cik IS NOT NULL THEN r._pa / 1000 ELSE r._pa END AS _pa,
            -- Provenance flag: the /1000 must be declared in corrected_fields
            -- downstream or the re-verifier sees an unexplained mismatch
            -- (lec_live7 finding 2026-08-25).
            (s.cik IS NOT NULL) AS _scale_div1000
        FROM raw r
        LEFT JOIN _scale_errors s
          ON r.cik = s.cik
         AND CAST(r.report_date AS VARCHAR) = s.report_date
    ),

    -- CTE 1b: Amendment dedup -- when a CIK has both a 10-K and 10-K/A
    -- (or 10-Q and 10-Q/A) for the same report_date, keep only the rows
    -- from the latest-filed accession.  If the amendment's XBRL had no
    -- investment data (common: 21/27 amendments in our dataset), the
    -- original is the only accession with rows and is kept automatically.
    no_amendments AS (
        SELECT r.* FROM scale_corrected r
        INNER JOIN (
            SELECT cik, report_date, accession_number,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, CAST(report_date AS VARCHAR),
                        REGEXP_REPLACE(CAST(form_type AS VARCHAR), '/A$', '')
                    ORDER BY
                        CAST(filing_date AS VARCHAR) DESC,
                        COALESCE(CAST(accession_number AS VARCHAR), '') DESC
                ) AS _amd_rank
            FROM scale_corrected
            GROUP BY cik, report_date, accession_number, form_type, filing_date
        ) ranked
          ON r.cik = ranked.cik
         AND r.report_date = ranked.report_date
         AND r.accession_number = ranked.accession_number
        WHERE ranked._amd_rank = 1
    ),

    -- CTE 1c: Strip affiliation prefixes/suffixes from _raw_id
    -- Handles PhenixFIN-style identifiers where the XBRL identifier
    -- has the affiliation category as a prefix or suffix, e.g.:
    --   "Non-Controlled/Non-Affiliated Investments - Acme Corp - Term Loan"
    --   -> "Acme Corp - Term Loan"
    -- Must run BEFORE aggregate filter so cleaned _raw_id/_lower_id
    -- are used for aggregate detection.
    -- Compute stripped value once, derive _lower_id from it (3 regex
    -- calls instead of 6).
    strip_affil AS (
        SELECT * EXCLUDE (_raw_id, _lower_id, _stripped),
            _stripped AS _raw_id,
            lower(trim(_stripped)) AS _lower_id
        FROM (
            SELECT *,
                -- Apply double-Investments stripping for CIKs that declare
                -- "Investments Investments" in prefix_rules, then fall
                -- through to the standard affiliation/hierarchy stripping.
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            regexp_replace(
                                CASE WHEN {_double_inv_cik_sql}
                                    THEN regexp_replace(
                                        _raw_id,
                                        '{_DOUBLE_INVESTMENTS_HIERARCHY_RE}',
                                        ''
                                    )
                                    ELSE _raw_id
                                END,
                                '{_AFFILIATION_PREFIX_RE}',
                                ''
                            ),
                            '{_AFFILIATION_SUFFIX_RE}',
                            ''
                        ),
                        '{_AFFILIATION_PIPE_SUFFIX_RE}',
                        ''
                    ),
                    '{_INVESTMENTS_HIERARCHY_RE}',
                    ''
                ) AS _stripped
            FROM no_amendments
        )
    ),

    aggregate_override_matches AS (
        SELECT
            s._row_id,
            MAX(CASE WHEN o.action = 'include' THEN 1 ELSE 0 END) AS force_include,
            MAX(CASE WHEN o.action = 'exclude' THEN 1 ELSE 0 END) AS force_exclude
        FROM strip_affil s
        JOIN bdc_aggregate_overrides o
          ON LPAD(REGEXP_REPLACE(CAST(s.cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = o.cik
         AND (o.report_date = '' OR CAST(s.report_date AS VARCHAR) = o.report_date)
         AND (o.accession_number = '' OR CAST(s.accession_number AS VARCHAR) = o.accession_number)
         AND (
             (o.match_mode = 'exact' AND lower(trim(CAST(s._raw_id AS VARCHAR))) = o.match_text_lower)
             OR (o.match_mode = 'contains' AND contains(lower(CAST(s._raw_id AS VARCHAR)), o.match_text_lower))
         )
        GROUP BY s._row_id
    ),

    -- CTE 2: Filter aggregate/subtotal rows
    -- Wrapper-authoritative rescue: *_position_leaf bypasses agg_filter.
    -- Wrapper rollup/aggregate drop is NOT applied here because some
    -- wrappers misclassify equity co-investments as debt_issuer_rollup
    -- (e.g. Fidelity).  Rollup rows are already handled by the global
    -- agg_filter, prefix hierarchy filters, and the CC-reviewed aggregate
    -- header exclusions.
    no_aggregates AS (
        SELECT s.* FROM strip_affil s
        LEFT JOIN aggregate_override_matches o
          ON s._row_id = o._row_id
        LEFT JOIN _wrapper_disp wd
          ON LPAD(REGEXP_REPLACE(CAST(s.cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = wd.cik_norm
         AND COALESCE(CAST(s.investment_identifier AS VARCHAR), '') = wd.raw_id
        LEFT JOIN html_section_bridges hsb
          ON LPAD(REGEXP_REPLACE(CAST(s.cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = hsb.bridge_cik
         AND CAST(s.accession_number AS VARCHAR) = hsb.bridge_accession_number
         AND CAST(s.report_date AS VARCHAR) = hsb.bridge_report_date
         AND lower(trim(CAST(s.investment_identifier AS VARCHAR))) = hsb.bridge_raw_id_lower
        WHERE COALESCE(o.force_exclude, 0) = 0
          AND (
              COALESCE(o.force_include, 0) = 1
              OR COALESCE(wd.wrapper_disposition, '') LIKE '%_position_leaf'
              OR COALESCE(hsb.disposition, '') LIKE '%_position_leaf'
              OR ({_he_any_condition})
              OR ({_prefix_rules_hierarchy_condition})
              OR NOT ({agg_filter})
          )
    ),

    -- CTE 2b: Filter prefix_rules subtotals that leaked through the
    -- aggregate filter (they have entity signals like "Inc." that
    -- protect them from the no-entity guard).
    -- Wrapper-authoritative: *_position_leaf rescues from prefix filter.
    -- Category rollups, total rollups, and explicit aggregate dispositions
    -- are safe to drop here because they are issuerless hierarchy/subtotal patterns;
    -- issuer_rollup is still not authoritative due known false-positive risk
    -- in older wrappers.
    no_prefix_hierarchy AS (
        SELECT nag.* FROM no_aggregates nag
        LEFT JOIN _wrapper_disp wd
          ON LPAD(REGEXP_REPLACE(CAST(nag.cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = wd.cik_norm
         AND COALESCE(CAST(nag.investment_identifier AS VARCHAR), '') = wd.raw_id
        LEFT JOIN html_section_bridges hsb
          ON LPAD(REGEXP_REPLACE(CAST(nag.cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') = hsb.bridge_cik
         AND CAST(nag.accession_number AS VARCHAR) = hsb.bridge_accession_number
         AND CAST(nag.report_date AS VARCHAR) = hsb.bridge_report_date
         AND lower(trim(CAST(nag.investment_identifier AS VARCHAR))) = hsb.bridge_raw_id_lower
        WHERE COALESCE(wd.wrapper_disposition, '') LIKE '%_position_leaf'
           OR COALESCE(hsb.disposition, '') LIKE '%_position_leaf'
           OR (
               COALESCE(wd.wrapper_disposition, '') != 'aggregate'
               AND
               COALESCE(wd.wrapper_disposition, '') NOT LIKE '%_category_rollup'
               AND COALESCE(wd.wrapper_disposition, '') NOT LIKE '%_total_rollup'
               AND NOT ({_prefix_hierarchy_filter})
           )
    ),

    -- CTE 3: Filter XBRL artifacts (no financial data at all)
    no_artifacts AS (
        SELECT * FROM no_prefix_hierarchy
        WHERE _fv IS NOT NULL
           OR _ir IS NOT NULL
           OR _pa IS NOT NULL
           OR _sh IS NOT NULL
    ),

    -- CTE 3b: Require fair value (removes unfunded commitments,
    -- tranche detail duplicates, and equity stubs with no FV)
    has_fv AS (
        SELECT * FROM no_artifacts
        WHERE _fv IS NOT NULL
    ),

    -- CTE 4: Filter deterministic hierarchical prefix rollups.
    -- A shorter row is removed only when at least two FV-carrying child rows
    -- extend the identifier and their fair values tie exactly to the parent.
    -- This avoids dropping real same-borrower positions just because another
    -- position starts with the same text.
    prefix_rollup_parents AS (
        SELECT
            a._row_id,
            COUNT(b._row_id) AS child_count,
            SUM(b._fv) AS child_fv
        FROM has_fv a
        JOIN has_fv b
          ON a.cik = b.cik
         AND a.accession_number = b.accession_number
         AND b._raw_id LIKE a._raw_id || '%'
         AND LENGTH(b._raw_id) >= LENGTH(a._raw_id) + 10
         AND a._raw_id IS NOT NULL
         AND LENGTH(a._raw_id) >= 3
        GROUP BY a._row_id, a._fv
        HAVING COUNT(b._row_id) >= 2
           AND abs(a._fv - SUM(b._fv))
               <= greatest(1.0, 0.0001 * greatest(abs(a._fv), abs(SUM(b._fv))))
    ),

    -- CTE 4b: Entity-level FV-match rollup parents (CIK-scoped).
    -- Catches entity-level rollup rows whose FV matches ANY individual
    -- instrument-level child row.  This handles parents with multiple
    -- children at different FV levels (e.g. comparative-period variants)
    -- where the parent FV equals one child but not the sum.
    -- Only applies to CIKs with wrapper configs that use "issuer, instrument"
    -- delimiter format, where bare entity names are always rollups.
    -- Guards: parent lacks instrument keywords, child HAS instrument keywords,
    -- child is at least 5 chars longer (covers ", CLO" minimum suffix).
    single_child_rollup_parents AS (
        SELECT DISTINCT
            a._row_id
        FROM has_fv a
        JOIN has_fv b
          ON a.cik = b.cik
         AND a.accession_number = b.accession_number
         AND b._raw_id LIKE a._raw_id || '%'
         AND LENGTH(b._raw_id) >= LENGTH(a._raw_id) + 5
         AND a._raw_id IS NOT NULL
         AND LENGTH(a._raw_id) >= 3
         AND a._row_id != b._row_id
        WHERE {_single_child_rollup_cik_sql}
          AND NOT regexp_matches(
            lower(a._raw_id),
            '(first lien|second lien|senior secured|subordinated|unitranche'
            '|term loan|revolving|delayed draw|equipment financing'
            '|secured loan|common stock|common equity|common units'
            '|preferred stock|preferred equity|preferred shares|preferred units'
            '|senior preferred|partnership interest|llc interest|equity interest'
            '|equity co-invest|warrant|warrants|member interest'
            '|class [a-z]|series [a-z]|collateralized loan obligation|clo)'
        )
          AND regexp_matches(
            lower(b._raw_id),
            '(first lien|second lien|senior secured|subordinated|unitranche'
            '|term loan|revolving|delayed draw|equipment financing'
            '|secured loan|common stock|common equity|common units'
            '|preferred stock|preferred equity|preferred shares|preferred units'
            '|senior preferred|partnership interest|llc interest|equity interest'
            '|equity co-invest|warrant|warrants|member interest'
            '|class [a-z]|series [a-z]|collateralized loan obligation|clo'
            '|subordinated certificates|certificates)'
        )
          AND abs(a._fv - b._fv)
              <= greatest(1.0, 0.0001 * greatest(abs(a._fv), abs(b._fv)))
    ),

    no_subtotals AS (
        SELECT a.* FROM has_fv a
        LEFT JOIN prefix_rollup_parents p
          ON a._row_id = p._row_id
        LEFT JOIN single_child_rollup_parents sp
          ON a._row_id = sp._row_id
        WHERE p._row_id IS NULL
          AND sp._row_id IS NULL
    )

    SELECT * FROM no_subtotals
    """
    con.execute(sql_phase_a)

    # Log 1000x scale corrections (diagnostic, uses bdc_raw which is still alive)
    try:
        scale_log = con.execute("""
            WITH _qfv AS (
                SELECT cik, CAST(report_date AS VARCHAR) AS report_date,
                       SUM(TRY_CAST(fair_value AS DOUBLE)) AS total_fv
                FROM bdc_raw
                WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(fair_value AS DOUBLE) > 0
                GROUP BY cik, CAST(report_date AS VARCHAR)
            ),
            _cm AS (
                SELECT cik, MEDIAN(total_fv) AS median_fv, COUNT(*) AS n_quarters
                FROM _qfv GROUP BY cik
            )
            SELECT q.cik, q.report_date, q.total_fv, m.median_fv,
                   ROUND(q.total_fv / m.median_fv, 0) AS ratio
            FROM _qfv q
            JOIN _cm m ON q.cik = m.cik
            WHERE m.n_quarters >= 3 AND m.median_fv > 0
              AND q.total_fv / m.median_fv > 100
        """).fetchdf()
        for _, row in scale_log.iterrows():
            logger.info("  1000x scale correction: CIK %s %s "
                        "(total_fv=%.0f, median=%.0f, ratio=%.0fx)",
                        row["cik"], row["report_date"],
                        row["total_fv"], row["median_fv"], row["ratio"])
    except Exception:
        pass  # Diagnostic only

    _phase_a_count = con.execute(
        "SELECT COUNT(*) FROM _bdc_phase_a"
    ).fetchone()[0]
    logger.info("  Phase A (filter+dedup): %d rows in %.1f s",
                _phase_a_count, time.time() - _t_phase)
    if _phase_a_count == 0:
        logger.info("  Phase B/C skipped: no rows after Phase A filters")
        con.close()
        logger.info("  After all BDC filters: 0 rows (%d removed)", input_count)
        return pd.DataFrame(columns=UNIFIED_COLUMNS)

    # =========================================================================
    # Phase B: Identifier parsing, issuer/instrument extraction, bad-issuer
    # cleanup, CC aggregate header exclusion, and affiliation-axis dedup.
    # Reads from materialized _bdc_phase_a, writes to _bdc_phase_b.
    # =========================================================================
    _t_phase = time.time()
    sql_phase_b = f"""
    CREATE TEMP TABLE _bdc_phase_b AS
    WITH
    -- CTE 5a: Initial split + helper columns for re-parsing
    -- Normalise em-dash (U+2014) to ' - ' and en-dash (U+2013) to '-' before
    -- splitting so that PennantPark (em-dash) and Goldman Sachs (en-dash) BDCs
    -- are handled consistently.
    initial_split AS (
        SELECT *,
            string_split({_norm_raw}, ' - ') AS _segments,
            CASE
                WHEN NOT contains({_norm_raw}, ' - ')
                THEN trim(_raw_id)
                ELSE trim(string_split({_norm_raw}, ' - ')[1])
            END AS _issuer_raw,
            CASE
                WHEN NOT contains({_norm_raw}, ' - ')
                THEN lower(trim(_raw_id))
                ELSE lower(trim(string_split({_norm_raw}, ' - ')[1]))
            END AS _issuer_lower,
            -- Pipe-separator detection: four 3-pipe sub-formats
            --   affil_last:    "Company | Instrument | Affiliation"  -> issuer = seg1
            --   company_first: "Company | Industry | Instrument"     -> issuer = seg1
            --   company_seg2:  "Category | Company | Instrument"     -> issuer = seg2
            --   slr:           "Type | Industry | Company | ..."     -> issuer = seg3
            CASE
                -- 3+ pipes: last segment is affiliation tag
                WHEN {has_pipe} AND len({pipe_parts}) >= 3
                     AND {affil_in}
                THEN trim({pipe_parts}[1])
                -- 3 pipes: seg1 has legal suffix -> company-first
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg1_has_suffix}
                THEN trim({pipe_parts}[1])
                -- 3 pipes: seg3 is instrument AND seg2 has legal suffix -> company in seg2
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_has_suffix}
                THEN trim({pipe_parts}[2])
                -- 3 pipes: seg3 is instrument AND seg2 is known industry -> company in seg1
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_is_industry}
                THEN trim({pipe_parts}[1])
                -- SLR equipment-financing leaf: "Equipment Financing - 24.1% | Company | Industry | ..."
                WHEN {has_pipe} AND {slr_seg2_is_leaf_issuer}
                THEN trim({pipe_parts}[2])
                -- CIK-scoped pipe_field_map: issuer from declared segment index
                {_pfm_issuer_sql}
                -- 3+ pipes: default SLR -> issuer = seg3
                WHEN {has_pipe} AND len({pipe_parts}) >= 3
                THEN trim({pipe_parts}[3])
                -- 2 pipes
                WHEN {has_pipe} AND len({pipe_parts}) = 2
                THEN trim({pipe_parts}[1])
                ELSE NULL
            END AS _pipe_issuer,
            -- Track which pipe variant for instrument_description assembly
            CASE
                WHEN {has_pipe} AND len({pipe_parts}) >= 3
                     AND {affil_in}
                THEN 'affil_last'
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg1_has_suffix}
                THEN 'company_first'
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_has_suffix}
                THEN 'company_seg2'
                WHEN {has_pipe} AND len({pipe_parts}) = 3
                     AND {seg3_is_instrument}
                     AND {seg2_is_industry}
                THEN 'company_first'
                WHEN {has_pipe} AND {slr_seg2_is_leaf_issuer}
                THEN 'slr_seg2_leaf'
                -- CIK-scoped pipe_field_map format tag
                {_pfm_format_sql}
                WHEN {has_pipe} AND len({pipe_parts}) >= 3
                THEN 'slr'
                WHEN {has_pipe} AND len({pipe_parts}) = 2
                THEN 'two_pipe'
                ELSE NULL
            END AS _pipe_format,
        FROM _bdc_phase_a
    ),

    -- CTE 5b: Re-parse with industry-prefix detection and pipe-format override
    parsed AS (
        SELECT * EXCLUDE (_issuer_raw, _issuer_lower, _pipe_issuer, _pipe_format, _segments),
            CASE
                -- CIK-scoped hierarchy_extract wrappers override generic pipe
                -- parsing when their explicit condition matches. Some filers
                -- use pipes as hierarchy delimiters rather than issuer/instrument
                -- separators, so the generic pipe fallback would otherwise read
                -- category text as the issuer.
                {_he_issuer_sql}
                -- Pipe format takes priority
                WHEN _pipe_issuer IS NOT NULL THEN _pipe_issuer
                -- CIK-scoped no-dash hierarchy leaves. These filers encode
                -- category/industry/issuer/instrument terms in one
                -- typed dimension value, so the generic first-segment parser
                -- would otherwise treat the whole string as a bad issuer.
                {_hierarchy_leaf_issuer_sql}
                -- MSD Investment Corp. embeds the full SOI hierarchy in one
                -- typed-dimension value. Valid borrowers often lack LLC/Inc
                -- suffixes, so parse only this CIK's hierarchy instead of
                -- widening the generic bad-issuer guard.
                WHEN {_msd_hierarchy_condition}
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        {_msd_clean_raw},
                        '^(.+?)\\s+(?:-|Reference Rate|Rate and Spread|Interest Rate|Maturity Date|Equity Interest Rate)(?:\\s|$)',
                        1
                    ), ''),
                    {_msd_clean_raw}
                )
                -- Industry prefix with 3+ segments: take segment 2 as issuer
                WHEN {industry_in}
                     AND len(_segments) >= 3
                THEN trim(_segments[2])
                -- Pct-prefix category + geography prefix (Blue Owl CIK 1817825):
                -- seg[1] = "NNN.N% of Shareholder's Equity", seg[2] = "Investments made in <Country>",
                -- seg[3] = <Industry>, seg[4] = <Company>
                WHEN len(_segments) >= 5
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND lower(trim(_segments[2])) LIKE 'investments made in%'
                     AND {_seg3_is_industry}
                THEN trim(_segments[4])
                -- Pct-prefix category + geography prefix (non-industry seg[3]):
                -- seg[3] = <Company> (not a known industry label)
                WHEN len(_segments) >= 4
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND lower(trim(_segments[2])) LIKE 'investments made in%'
                THEN trim(_segments[3])
                -- Saratoga-style after affiliation-prefix stripping:
                -- seg[1] = "NNN.N%", seg[2] = issuer,
                -- seg[3+] = industry + instrument.
                -- Require 4+ segments so ambiguous category-only rows such
                -- as "10.6% - Education Services - Common Stock" are still
                -- filtered by the bad-issuer guard.
                WHEN len(_segments) >= 4
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%$')
                THEN trim(_segments[2])
                -- Pct-prefix category skip (PennantPark / Blue Owl):
                -- seg[1] = "NNN.N% Category", seg[2] = "NNN.N% Company ... Industry ..."
                WHEN len(_segments) >= 2
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND regexp_matches(trim(_segments[2]), '^\d[\d.]*%')
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace(
                            regexp_replace(trim(_segments[2]), '^\d[\d.]*%\s+', ''),
                            '^(?i)Issuer Name\s+', ''
                        ),
                        '{_kw_boundary_re}',
                        1
                    ), ''),
                    regexp_replace(
                        regexp_replace(trim(_segments[2]), '^\d[\d.]*%\s+', ''),
                        '^(?i)Issuer Name\s+', ''
                    )
                )
                -- No-dash "Issuer Name" label (PennantPark variant):
                -- "Category Issuer Name <Company> Industry ..."
                WHEN NOT contains({_norm_raw}, ' - ')
                     AND NOT _issuer_lower LIKE 'investment %'
                     AND regexp_matches(_raw_id, '(?i)\\bIssuer Name\\s+')
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace(_raw_id, '^.*?(?i)\\bIssuer Name\\s+', ''),
                        '{_kw_boundary_re}',
                        1
                    ), ''),
                    regexp_replace(_raw_id, '^.*?(?i)\\bIssuer Name\\s+', '')
                )
                -- Config-driven hierarchical pct format (GS Private Credit etc.):
                -- 2-4 dash-separated segments with pct prefixes.
                -- Issuer = last segment stripped of pct, text before boundary keyword.
                -- For equity rows (no keyword boundary), text before trailing industry label.
                WHEN {_hier_pct_condition}
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace({_hier_leaf_sql}, '^-?\\d[\\d.]*%,?\\s+', ''),
                        '(?i)^(.+?)\\s+{_hier_boundary_re}(?:\\s|$)',
                        1
                    ), ''),
                    -- Equity fallback: strip trailing industry label
                    NULLIF(regexp_extract(
                        regexp_replace({_hier_leaf_sql}, '^-?\\d[\\d.]*%,?\\s+', ''),
                        '(?i)^(.+?)\\s+{_hier_industry_label_re}$',
                        1
                    ), ''),
                    regexp_replace({_hier_leaf_sql}, '^-?\\d[\\d.]*%,?\\s+', '')
                )
                -- Goldman Sachs 1-segment (no dash separator):
                -- "Investment <type> <pct>% <company> Industry ..."
                WHEN NOT contains(_raw_id, ' - ')
                     AND {_hier_pct_cik_sql}
                     AND regexp_matches(_raw_id, '\\d[\\d.]*%\\s+\\S')
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace(_raw_id, '^.*?\\d[\\d.]*%\\s+', ''),
                        '(?i)^(.+?)\\s+{_hier_boundary_re}(?:\\s|$)',
                        1
                    ), ''),
                    regexp_replace(_raw_id, '^.*?\\d[\\d.]*%\\s+', '')
                )
                -- Default: first segment
                ELSE _issuer_raw
            END AS issuer_name,
            CASE
                -- CIK-scoped hierarchy_extract wrappers override generic pipe
                -- parsing when their explicit condition matches.
                {_he_instrument_sql}
                -- 2-pipe: instrument = segment 2
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'two_pipe'
                THEN trim({pipe_parts}[2])
                -- Affiliation-last (3+): instrument = segment 2
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'affil_last'
                THEN trim({pipe_parts}[2])
                -- Company-first (3): instrument = segment 3
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'company_first'
                THEN trim({pipe_parts}[3])
                -- Company in seg2 (3): instrument = segment 3
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'company_seg2'
                THEN trim({pipe_parts}[3])
                -- SLR equipment-financing leaf: issuer = seg2, instrument = seg1 + seg3+
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'slr_seg2_leaf'
                THEN trim({pipe_parts}[1])
                     || CASE
                         WHEN len({pipe_parts}) >= 3
                         THEN ', ' || trim(array_to_string({pipe_parts}[3:], ' | '))
                         ELSE ''
                     END
                -- SLR (3+): combine segments 1, 2, and 4+ as instrument
                WHEN _pipe_issuer IS NOT NULL AND _pipe_format = 'slr'
                THEN trim({pipe_parts}[1]) || ', ' || trim({pipe_parts}[2])
                     || CASE
                         WHEN len({pipe_parts}) >= 4
                         THEN ', ' || trim(array_to_string({pipe_parts}[4:], ' | '))
                         ELSE ''
                     END
                -- CIK-scoped pipe_field_map: instrument from declared segments
                {_pfm_instrument_sql}
                {_hierarchy_leaf_instrument_sql}
                WHEN {_msd_hierarchy_condition}
                THEN trim(COALESCE(
                    NULLIF(regexp_extract({_msd_clean_raw}, '^.+?\\s+-\\s+(.+)$', 1), ''),
                    NULLIF(regexp_extract(
                        {_msd_clean_raw},
                        '^.+?\\s+((?:Reference Rate|Rate and Spread|Interest Rate|Maturity Date|Equity Interest Rate).+)$',
                        1
                    ), ''),
                    ''
                ))
                -- Industry prefix with 3+ segments: segments 3+ as instrument
                WHEN {industry_in}
                     AND len(_segments) >= 3
                THEN regexp_replace(
                    trim(array_to_string(_segments[3:], ' - ')),
                    '^\\$?[\\d,.]+ ?', ''
                )
                -- Pct-prefix + geography + industry: instrument = category + segs 5+
                WHEN len(_segments) >= 5
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND lower(trim(_segments[2])) LIKE 'investments made in%'
                     AND {_seg3_is_industry}
                THEN regexp_replace(trim(_segments[1]), '^\d[\d.]*%\s+', '')
                     || CASE WHEN len(_segments) >= 6
                        THEN ' - ' || trim(array_to_string(_segments[5:], ' - '))
                        ELSE '' END
                -- Pct-prefix + geography (non-industry seg[3]): instrument = category + segs 4+
                WHEN len(_segments) >= 4
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND lower(trim(_segments[2])) LIKE 'investments made in%'
                THEN regexp_replace(trim(_segments[1]), '^\d[\d.]*%\s+', '')
                     || CASE WHEN len(_segments) >= 5
                        THEN ' - ' || trim(array_to_string(_segments[4:], ' - '))
                        ELSE '' END
                -- Saratoga-style pct-only first segment: instrument keeps
                -- industry + leaf detail after the recovered issuer.
                WHEN len(_segments) >= 4
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%$')
                THEN regexp_replace(
                    trim(array_to_string(_segments[3:], ' - ')),
                    '^\\$?[\\d,.]+ ?', ''
                )
                -- Pct-prefix category skip: instrument = category from seg[1]
                WHEN len(_segments) >= 2
                     AND regexp_matches(trim(_segments[1]), '^\d[\d.]*%\s+')
                     AND NOT ({_seg1_entity_sql})
                     AND regexp_matches(trim(_segments[2]), '^\d[\d.]*%')
                THEN regexp_replace(trim(_segments[1]), '^\d[\d.]*%\s+', '')
                -- No-dash "Issuer Name" label: instrument = text before "Issuer Name"
                WHEN NOT contains({_norm_raw}, ' - ')
                     AND NOT _issuer_lower LIKE 'investment %'
                     AND regexp_matches(_raw_id, '(?i)\\bIssuer Name\\s+')
                THEN regexp_replace(
                    regexp_replace(_raw_id, '(?i)\\bIssuer Name\\s+.*$', ''),
                    '^\d[\d.]*%\s+', ''
                )
                -- Config-driven hierarchical pct: instrument description
                -- 4+ segments: seg[-2] stripped of pct (lien type, e.g. "1st Lien/Senior Secured Debt")
                -- 3 segments: seg[1] minus "Investment " prefix (already correct)
                -- 2 segments: seg[1] minus "Investment " prefix
                WHEN {_hier_pct_condition} AND len(_segments) >= 4
                THEN regexp_replace({_hier_instrument_segment_sql}, '^-?\\d[\\d.]*%,?\\s+', '')
                WHEN {_hier_pct_condition}
                THEN regexp_replace(trim(_segments[1]), '^(?i)Investment\\s+', '')
                -- Hierarchical pct 1-segment (no dash separator)
                WHEN NOT contains(_raw_id, ' - ')
                     AND {_hier_pct_cik_sql}
                     AND regexp_matches(_raw_id, '\\d[\\d.]*%\\s+\\S')
                THEN COALESCE(
                    NULLIF(regexp_extract(
                        regexp_replace(_raw_id, '^(?i)Investment\\s+', ''),
                        '^(.+?)\\s+\\d[\\d.]*%',
                        1
                    ), ''),
                    ''
                )
                -- No dash: empty instrument
                WHEN NOT contains(_raw_id, ' - ') THEN ''
                -- Default: segments 2+ as instrument
                ELSE regexp_replace(
                    trim(array_to_string(_segments[2:], ' - ')),
                    '^\\$?[\\d,.]+ ?', ''
                )
            END AS instrument_description,
            -- Hierarchical pct: country from seg[2] stripped of pct (>= 3 segments)
            CASE WHEN {_hier_pct_condition} AND len(_segments) >= 3
                 THEN regexp_extract(
                     regexp_replace(trim(_segments[2]), '^-?\\d[\\d.]*%,?\\s+', ''),
                     '(?i)^({_hier_country_re})$', 1
                 )
                 ELSE NULL
            END AS _hier_country,
            -- Hierarchical pct: industry from leaf segment
            -- Debt: text after "Industry" keyword, before next boundary keyword
            -- Equity: trailing industry label match (no "Industry" keyword)
            CASE WHEN {_hier_pct_condition}
                 AND regexp_matches({_hier_leaf_sql}, '(?i)\\bIndustry\\s+')
                 THEN trim(regexp_extract(
                     regexp_replace({_hier_leaf_sql}, '^-?\\d[\\d.]*%,?\\s+', ''),
                     '(?i)(?:^.*?)\\bIndustry\\s+(.+?)(?:\\s+(?:{_hier_boundary_re})(?:\\s|$)|$)',
                     1
                 ))
                 WHEN {_hier_pct_condition}
                 THEN regexp_extract(
                     regexp_replace({_hier_leaf_sql}, '^-?\\d[\\d.]*%,?\\s+', ''),
                     '(?i)\\s+({_hier_industry_label_re})$',
                     1
                 )
                 ELSE NULL
            END AS _hier_industry
        FROM initial_split
    ),

    parsed_with_manual_bridge AS (
        SELECT p.* EXCLUDE (issuer_name, instrument_description),
            COALESCE(b.issuer_name, p.issuer_name) AS issuer_name,
            COALESCE(
                b.instrument_description,
                p.instrument_description
            ) AS instrument_description
        FROM parsed p
        LEFT JOIN saratoga_issuer_bridges b
          ON LPAD(
                 regexp_replace(CAST(p.cik AS VARCHAR), '[^0-9]', '', 'g'),
                 10,
                 '0'
             ) = b.cik
         AND CAST(p.report_date AS VARCHAR) = b.report_date
         AND lower(trim(CAST(p._raw_id AS VARCHAR))) = b.raw_id_lower
    ),

    parsed_with_saratoga_bridge AS (
        SELECT p.* EXCLUDE (issuer_name, instrument_description),
            CASE
                WHEN hsb.bridge_raw_id_lower IS NOT NULL
                     AND (
                         COALESCE(hsb.permit_overwrite, false)
                         OR COALESCE(trim(CAST(p.instrument_description AS VARCHAR)), '') = ''
                     )
                THEN COALESCE(NULLIF(hsb.issuer_name, ''), p.issuer_name)
                ELSE p.issuer_name
            END AS issuer_name,
            CASE
                WHEN hsb.bridge_raw_id_lower IS NOT NULL
                     AND (
                         COALESCE(hsb.permit_overwrite, false)
                         OR COALESCE(trim(CAST(p.instrument_description AS VARCHAR)), '') = ''
                     )
                THEN COALESCE(NULLIF(hsb.instrument_description, ''), p.instrument_description)
                ELSE p.instrument_description
            END AS instrument_description
        FROM parsed_with_manual_bridge p
        LEFT JOIN html_section_bridges hsb
          ON LPAD(
                 regexp_replace(CAST(p.cik AS VARCHAR), '[^0-9]', '', 'g'),
                 10,
                 '0'
             ) = hsb.bridge_cik
         AND CAST(p.accession_number AS VARCHAR) = hsb.bridge_accession_number
         AND CAST(p.report_date AS VARCHAR) = hsb.bridge_report_date
         AND lower(trim(CAST(p._raw_id AS VARCHAR))) = hsb.bridge_raw_id_lower
    ),

    -- CTE 5c: Fix bad issuer names (extraction artifacts from dimension paths)
    -- When issuer_name is a generic label (e.g., "Investments") but the raw
    -- identifier contains entity signals (LLC, Inc, etc.), replace issuer_name
    -- with the full raw identifier to preserve the position data.
    -- Only filter rows where both issuer_name AND raw identifier are generic.
    no_bad_issuers AS (
        SELECT * EXCLUDE (issuer_name),
            CASE
                WHEN ({bad_numeric_issuer_filter})
                     AND ({_he_any_condition})
                THEN issuer_name
                WHEN ({bad_issuer_filter})
                     AND ({_sql_has_entity_in_raw})
                THEN _raw_id
                ELSE issuer_name
            END AS issuer_name
        FROM parsed_with_saratoga_bridge
        WHERE NOT (
            ({bad_issuer_filter})
            AND NOT (({bad_numeric_issuer_filter}) AND ({_he_any_condition}))
            AND NOT ({_sql_has_entity_in_raw})
        )
    ),

    {_cc_agg_header_cte}

    -- CTE 5d: Affiliation-axis dedup -- same position tagged under multiple
    -- affiliation dimension members (e.g. Non-Controlled vs Affiliated) in
    -- the same filing.  This must stay position-level: distinct instruments
    -- for the same issuer and FV are separate holdings.
    no_affil_dupes AS (
        SELECT * FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, accession_number, report_date,
                                 regexp_replace(
                                     lower(trim(CAST(issuer_name AS VARCHAR))),
                                     '[^a-z0-9]+', ' ', 'g'
                                 ),
                                 regexp_replace(
                                     lower(trim(CAST(instrument_description AS VARCHAR))),
                                     '[^a-z0-9]+', ' ', 'g'
                                 ),
                                 ROUND(COALESCE(_fv, 0), 0),
                                 ROUND(COALESCE(_cost, 0), 0),
                                 ROUND(COALESCE(_pa, 0), 0),
                                 ROUND(COALESCE(_sh, 0), 0)
                    ORDER BY
                        CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'non-controlled') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'non-control') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'non-affiliated') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'non-affiliate') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'affiliated') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'affiliate') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'controlled') THEN 1 ELSE 0 END
                      + CASE WHEN contains(COALESCE(lower(CAST(_raw_id AS VARCHAR)), ''), 'control') THEN 1 ELSE 0 END,
                        LENGTH(COALESCE(CAST(_raw_id AS VARCHAR), '')),
                        COALESCE(CAST(_raw_id AS VARCHAR), ''),
                        COALESCE(CAST(dimensions_raw AS VARCHAR), ''),
                        COALESCE(CAST(affiliation AS VARCHAR), ''),
                        COALESCE(CAST(src_context_id AS VARCHAR), ''),
                        _row_id
                ) AS _affil_rank
            FROM {_affil_dedup_source}
        ) sub
        WHERE _affil_rank = 1
    )

    SELECT * FROM no_affil_dupes
    """
    con.execute(sql_phase_b)

    _phase_b_count = con.execute(
        "SELECT COUNT(*) FROM _bdc_phase_b"
    ).fetchone()[0]
    logger.info("  Phase B (parse+dedup): %d rows in %.1f s",
                _phase_b_count, time.time() - _t_phase)

    # =========================================================================
    # Prefix-identifier dedup: remove subtotal/rollup rows where one
    # identifier is a strict prefix of another (with " - " separator)
    # and both carry the same fair value within $1 tolerance.  This catches
    # XBRL filings that report each position under multiple dimension paths:
    # a short sector-level subtotal and a longer position-level detail row.
    # Both carry identical FV, inflating position counts and FV totals.
    # Affects ~7 CIKs as of 2026-06 (Muzinich, PhenixFIN, Capital
    # Southwest, Rand Capital, Oxford Square, Steele Creek).
    # =========================================================================
    _prefix_dedup_sql = """
        DELETE FROM _bdc_phase_b
        WHERE _row_id IN (
            SELECT p1._row_id
            FROM _bdc_phase_b p1
            WHERE p1._fv IS NOT NULL AND p1._fv > 0
              AND EXISTS (
                SELECT 1 FROM _bdc_phase_b p2
                WHERE p2.cik = p1.cik
                  AND CAST(p2.report_date AS VARCHAR) = CAST(p1.report_date AS VARCHAR)
                  AND CAST(p2._raw_id AS VARCHAR) <> CAST(p1._raw_id AS VARCHAR)
                  AND starts_with(
                      CAST(p2._raw_id AS VARCHAR),
                      CAST(p1._raw_id AS VARCHAR) || ' - '
                  )
                  AND p2._fv IS NOT NULL AND p2._fv > 0
                  AND ABS(p2._fv - p1._fv) < 1.0
              )
        )
    """
    con.execute(_prefix_dedup_sql)
    _post_prefix = con.execute("SELECT COUNT(*) FROM _bdc_phase_b").fetchone()[0]
    _prefix_removed = _phase_b_count - _post_prefix
    if _prefix_removed > 0:
        logger.info("  Prefix-identifier dedup: removed %d subtotal/rollup rows",
                    _prefix_removed)

    # =========================================================================
    # Wrapper non-private-market exclusion lookup table.
    # For wrapper-covered CIKs, call is_non_private_market_identifier() on each
    # row to catch cash, treasury, money-market rows that the global keyword
    # filter misses.  Register matching _row_id values as _wrapper_non_private
    # so CTE 9 can join-exclude them alongside the global money-market check.
    # =========================================================================
    _wrapper_ciks = supported_wrapper_ciks()
    if _wrapper_ciks:
        _wrapper_cik_filter = ", ".join(f"'{c}'" for c in _wrapper_ciks)
        _wnp_candidates = con.execute(f"""
            SELECT _row_id, cik, _raw_id
            FROM _bdc_phase_b
            WHERE LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')
                  IN ({_wrapper_cik_filter})
        """).fetchdf()
        _wnp_row_ids: list[int] = []
        for _, _r in _wnp_candidates.iterrows():
            _cik_norm = str(_r["cik"]).lstrip("0").zfill(10)
            _spec = get_wrapper_spec(_cik_norm)
            _markers = _spec.non_private_markers if _spec else None
            if is_non_private_market_identifier(_r["_raw_id"], _markers):
                _wnp_row_ids.append(int(_r["_row_id"]))
        if _wnp_row_ids:
            _wnp_df = pd.DataFrame({"_row_id": _wnp_row_ids})
            con.register("_wnp_view", _wnp_df)
            con.execute(
                "CREATE TEMP TABLE _wrapper_non_private AS "
                "SELECT _row_id FROM _wnp_view"
            )
            logger.info("  Wrapper non-private-market exclusion: %d rows from %d candidates",
                        len(_wnp_row_ids), len(_wnp_candidates))
        else:
            con.execute(
                "CREATE TEMP TABLE _wrapper_non_private (_row_id BIGINT)"
            )
    else:
        con.execute(
            "CREATE TEMP TABLE _wrapper_non_private (_row_id BIGINT)"
        )

    # =========================================================================
    # Phase C: Classification, schema mapping, enrichment, casing normalization.
    # Reads from materialized _bdc_phase_b, produces the final result.
    # =========================================================================
    _t_phase = time.time()
    sql_phase_c = f"""
    WITH
    -- CTE 6: Classify asset category
    classified AS (
        SELECT *,
            -- Precompute lowercase fields for classification
            COALESCE(lower(trim(CAST(instrument_description AS VARCHAR))), '') AS _lower_instr,
            COALESCE(lower(trim(CAST(investment_type AS VARCHAR))), '') AS _lower_type,
            COALESCE(lower(trim(CAST(_raw_id AS VARCHAR))), '') AS _lower_full,
            (_ir IS NOT NULL AND _ir != 0) AS _has_interest_rate,
            (_sh IS NOT NULL AND _sh != 0) AS _has_shares,
            (_bs IS NOT NULL AND _bs != 0) AS _has_basis_spread,
            (_pa IS NOT NULL AND _pa != 0) AS _has_principal_amount
        FROM _bdc_phase_b
    ),

    with_asset AS (
        SELECT *,
            {asset_case} AS asset_category
        FROM classified
    ),

    -- CTE 7: Classify issuer
    with_issuer AS (
        SELECT *,
            CASE
                WHEN asset_category = 'FUND' THEN 'FUND'
                -- Equity stakes in fund managers / lending vehicles
                WHEN asset_category IN ('EQUITY_COMMON', 'EQUITY_PREFERRED', 'OTHER')
                     AND ({fund_vehicle_sql})
                THEN 'FUND'
                ELSE 'CORPORATE'
            END AS issuer_category
        FROM with_asset
    ),

    -- CTE 8: Named co-invest reclassification
    reclassified AS (
        SELECT *,
            -- Precompute fields for coinvest detection
            COALESCE(lower(trim(CAST(issuer_name AS VARCHAR))), '') AS _lower_issuer,
            COALESCE(lower(trim(CAST(issuer_name AS VARCHAR))), '') || ' ' ||
                COALESCE(lower(trim(CAST(instrument_description AS VARCHAR))), '') || ' ' ||
                COALESCE(lower(trim(CAST(_raw_id AS VARCHAR))), '') AS _combined_coinvest,
            COALESCE(lower(trim(CAST(_raw_id AS VARCHAR))), '') AS _lower_bdc_id
        FROM with_issuer
    ),

    with_reclass AS (
        SELECT *,
            CASE
                WHEN {coinvest_expr} AND contains(
                    COALESCE(lower(CAST(issuer_name AS VARCHAR)), '') || ' ' || COALESCE(lower(CAST(instrument_description AS VARCHAR)), ''),
                    'preferred'
                ) THEN 'EQUITY_PREFERRED'
                WHEN {coinvest_expr} THEN 'EQUITY_COMMON'
                ELSE asset_category
            END AS asset_category_final,
            CASE
                WHEN {coinvest_expr} THEN 'CORPORATE'
                ELSE issuer_category
            END AS issuer_category_final
        FROM reclassified
    ),

    -- CTE 9: Retain genuine cash equivalents as a Cash bucket (analytics-only),
    -- drop non-cash leaks.  Money-market-keyword rows and wrapper
    -- non-private-market rows are candidate cash equivalents.  A candidate is
    -- retained and stamped asset_category='CASH' ONLY when its own issuer /
    -- instrument text names a cash equivalent (money market, treasury, cash
    -- deposit).  Candidates that match only via a trailing aggregate phrase
    -- (e.g. "... | Total Cash and Cash Equivalents | Net Assets") are filer
    -- balance-sheet reconciliation footers, not positions -- they keep being
    -- dropped, exactly as before.  Retained cash rows classify as
    -- index_classification='CASH' / asset_class='CASH' and are NOT index
    -- constituents (position matching excludes asset_class='CASH'), so the
    -- position-level indices are unchanged.
    no_mm AS (
        SELECT * EXCLUDE (asset_category_final, _cash_filter_match, _cash_identity),
            CASE
                WHEN _cash_filter_match AND _cash_identity THEN 'CASH'
                ELSE asset_category_final
            END AS asset_category_final
        FROM (
            SELECT wr.*,
                (({mm_check}) OR wnp._row_id IS NOT NULL) AS _cash_filter_match,
                ({cash_identity_check}) AS _cash_identity
            FROM with_reclass wr
            LEFT JOIN _wrapper_non_private wnp ON wr._row_id = wnp._row_id
        )
        WHERE NOT (_cash_filter_match AND NOT _cash_identity)
    ),

    -- CTE 10: Infer coupon type
    with_coupon AS (
        SELECT *,
            CASE
                WHEN _bs IS NOT NULL AND _bs != 0 THEN 'Floating'
                WHEN _ir IS NOT NULL AND _ir != 0 THEN 'Fixed'
                ELSE ''
            END AS coupon_type
        FROM no_mm
    ),

    -- CTE 10b: Text enrichment from investment_identifier
    with_enrichment AS (
        SELECT *,
            -- Reference rate type: SOFR/LIBOR/PRIME from identifier text
            -- Also detects "S + N" / "L + N" / "E + N" shorthand
            CASE
                WHEN regexp_matches(lower(_raw_id), '\\bsofr\\b') THEN 'SOFR'
                WHEN regexp_matches(lower(_raw_id), '\\blibor\\b') THEN 'LIBOR'
                WHEN regexp_matches(lower(_raw_id), '\\bprime\\b') THEN 'PRIME'
                WHEN regexp_matches(_raw_id, '\\bS\\s*\\+\\s*\\d') THEN 'SOFR'
                WHEN regexp_matches(_raw_id, '\\bL\\s*\\+\\s*\\d') THEN 'LIBOR'
                WHEN regexp_matches(_raw_id, '\\bE\\s*\\+\\s*\\d') THEN 'EURIBOR'
                ELSE NULL
            END AS _text_ref_rate,
            -- Maturity date: extract from "M/D/YYYY Maturity", "Due M/D/YY",
            -- "Maturity Date MM/DD/YYYY", "Maturity M/D/YYYY" patterns
            -- Scan both the identifier AND instrument_description: filers like
            -- Blackstone leave the identifier bare ("Issuer | Non-Affiliated")
            -- but put "... due 2/2032" in instrument_description.
            COALESCE(
                NULLIF(regexp_extract(_raw_id,
                    '(\\d{{1,2}}/\\d{{1,2}}/\\d{{2,4}})\\s+[Mm]aturity', 1), ''),
                NULLIF(regexp_extract(_raw_id,
                    '(?:[Mm]aturity|[Dd]ue)\\s+(?:[Dd]ate\\s+)?(\\d{{1,2}}/\\d{{1,2}}/\\d{{2,4}})', 1), ''),
                NULLIF(regexp_extract(CAST(instrument_description AS VARCHAR),
                    '(?:[Mm]aturity|[Dd]ue)\\s+(?:[Dd]ate\\s+)?(\\d{{1,2}}/\\d{{1,2}}/\\d{{2,4}})', 1), '')
            ) AS _text_maturity_raw,
            COALESCE(
                NULLIF(regexp_extract(
                    replace(CAST(_raw_id AS VARCHAR), '\u00a0', ' '),
                    '(?:[Mm]aturity\\s*/\\s*[Dd]issolution\\s+[Dd]ate|[Mm]aturity/\\s*[Dd]issolution\\s+[Dd]ate)\\s+(\\d{{1,2}}/\\d{{4}})',
                    1
                ), ''),
                NULLIF(regexp_extract(_raw_id,
                    '(?i)\\bdue\\s+(\\d{{1,2}}/\\d{{4}})', 1), ''),
                NULLIF(regexp_extract(CAST(instrument_description AS VARCHAR),
                    '(?i)\\b(?:due|maturity(?:\\s+date)?)\\s+(\\d{{1,2}}/\\d{{4}})', 1), '')
            ) AS _text_maturity_month_raw,
            -- Basis spread: "SOFR + 5.25%", "Prime + 6.0%", "S + 5.25%", "E + 5.75%"
            TRY_CAST(COALESCE(
                NULLIF(regexp_extract(_raw_id,
                    '(?i)(?:SOFR|LIBOR|PRIME|EURIBOR|SONIA|CORRA)\\s*\\+\\s*(\\d+\\.?\\d*)', 1), ''),
                NULLIF(regexp_extract(_raw_id,
                    '\\b[SLE]\\s*\\+\\s*(\\d+\\.?\\d*)', 1), '')
            ) AS DOUBLE) AS _text_basis_spread,
            -- Interest rate: "Fixed interest rate 12.9%", "Floor rate 11.0%",
            -- "Interest Rate 9.04%" (only when not a PIK sub-rate)
            TRY_CAST(COALESCE(
                NULLIF(regexp_extract(_raw_id,
                    '(?i)\\bFixed\\s+interest\\s+rate\\s+(\\d+\\.?\\d*)%', 1), ''),
                NULLIF(regexp_extract(_raw_id,
                    '(?i)\\bFloor\\s+rate\\s+(\\d+\\.?\\d*)%', 1), ''),
                CASE WHEN NOT regexp_matches(_raw_id, '(?i)\\+PIK\\s+(?:Fixed\\s+)?Interest\\s+Rate')
                     THEN NULLIF(regexp_extract(_raw_id,
                         '(?i)\\bInterest\\s+Rate\\s+(\\d+\\.?\\d*)%', 1), '')
                     ELSE NULL END
            ) AS DOUBLE) AS _text_interest_rate,
            -- PIK rate: "15.00% PIK", "(7.25% PIK)", "+PIK Interest Rate 1.0%"
            TRY_CAST(COALESCE(
                NULLIF(regexp_extract(_raw_id,
                    '(\\d+\\.?\\d*)%\\s*PIK', 1), ''),
                NULLIF(regexp_extract(_raw_id,
                    '(?i)\\+PIK\\s+(?:Fixed\\s+)?Interest\\s+Rate\\s+(\\d+\\.?\\d*)%', 1), '')
            ) AS DOUBLE) AS _text_pik_rate
        FROM with_coupon
    ),

    -- CTE 11: Map to unified schema
    unified AS (
        SELECT
            'bdc' AS source,
            LPAD(CAST(cik AS VARCHAR), 10, '0') AS cik,
            entity_name,
            accession_number,
            filing_date,
            report_date,
            {name_norm} AS issuer_name,
            instrument_description,
            '' AS cusip,
            '' AS isin,
            '' AS lei,
            '' AS ticker,
            _fv AS fair_value,
            _cost AS cost,
            upper(trim(regexp_replace(COALESCE(CAST(fair_value_unit AS VARCHAR), ''), '^.*:', ''))) AS fair_value_currency,
            upper(trim(regexp_replace(COALESCE(CAST(cost_unit AS VARCHAR), ''), '^.*:', ''))) AS cost_currency,
            CASE WHEN _pct IS NOT NULL AND _pct <= 0.50 THEN _pct * 100
                 WHEN _pct IS NOT NULL AND _pct > 50 THEN _pct / 100
                 ELSE _pct END AS pct_of_net_assets,
            asset_category_final AS asset_category,
            issuer_category_final AS issuer_category,
            '' AS index_classification,
            '' AS exposure_type,
            '' AS asset_class,
            '' AS fair_value_level,
            CASE WHEN _ir IS NOT NULL AND _ir < 0 THEN NULL
                 WHEN _ir IS NOT NULL AND _ir <= 0.50 THEN _ir * 100
                 WHEN _ir IS NOT NULL AND _ir >= 50 THEN _ir / 100
                 WHEN _ir IS NOT NULL THEN _ir
                 WHEN _text_interest_rate IS NOT NULL THEN _text_interest_rate
                 ELSE NULL END AS interest_rate,
            -- provenance: did the value come from the structured XBRL tag (drift-immune)
            -- or the identifier text fallback? (structured-first; mirrors reference_rate_source)
            CASE WHEN _ir IS NOT NULL AND _ir >= 0 THEN 'xbrl_field'
                 WHEN _ir IS NULL AND _text_interest_rate IS NOT NULL THEN 'identifier_text'
                 ELSE '' END AS interest_rate_source,
            CASE WHEN _bs IS NOT NULL AND _bs < 0 THEN NULL
                 WHEN _bs IS NOT NULL AND _bs <= 0.50 THEN _bs * 100
                 WHEN _bs IS NOT NULL AND _bs >= 50 THEN _bs / 100
                 WHEN _bs IS NOT NULL THEN _bs
                 WHEN _text_basis_spread IS NOT NULL THEN _text_basis_spread
                 ELSE NULL END AS basis_spread,
            CASE WHEN _bs IS NOT NULL AND _bs >= 0 THEN 'xbrl_field'
                 WHEN _bs IS NULL AND _text_basis_spread IS NOT NULL THEN 'identifier_text'
                 ELSE '' END AS basis_spread_source,
            -- reference_rate_type: XBRL field -> identifier text -> evidence-based
            -- inference.  Filers like Blackstone/Nuveen Churchill/KKR FS tag the
            -- variable-rate SPREAD per position but not the reference-rate NAME.
            -- A present basis_spread means the coupon floats over a reference
            -- rate; for USD that is SOFR post-LIBOR-cessation (30 Jun 2023) and
            -- LIBOR before.  Inferred values are flagged in reference_rate_source.
            COALESCE(
                NULLIF(CAST(reference_rate_type AS VARCHAR), ''),
                _text_ref_rate,
                CASE WHEN _bs IS NOT NULL AND _bs <> 0
                          AND NOT regexp_matches(lower(_raw_id),
                              'euribor|sonia|\\beur\\b|\\bgbp\\b|sterling')
                     THEN CASE WHEN CAST(report_date AS VARCHAR) >= '2023-07-01'
                               THEN 'SOFR' ELSE 'LIBOR' END
                     ELSE NULL END,
                '')
                AS reference_rate_type,
            CASE
                WHEN NULLIF(CAST(reference_rate_type AS VARCHAR), '') IS NOT NULL
                    THEN 'xbrl_field'
                WHEN _text_ref_rate IS NOT NULL THEN 'identifier_text'
                WHEN _bs IS NOT NULL AND _bs <> 0
                     AND NOT regexp_matches(lower(_raw_id),
                         'euribor|sonia|\\beur\\b|\\bgbp\\b|sterling')
                    THEN CASE WHEN CAST(report_date AS VARCHAR) >= '2023-07-01'
                              THEN 'inferred_post_libor' ELSE 'inferred_pre_libor' END
                ELSE ''
            END AS reference_rate_source,
            CASE
                WHEN coupon_type != '' THEN coupon_type
                WHEN _text_basis_spread IS NOT NULL THEN 'Floating'
                WHEN _text_interest_rate IS NOT NULL
                     AND regexp_matches(lower(_raw_id), '\\b(?:variable|floating|sofr|libor|prime)\\b')
                     THEN 'Floating'
                WHEN _text_interest_rate IS NOT NULL THEN 'Fixed'
                ELSE ''
            END AS coupon_type,
            CASE WHEN _pik IS NOT NULL AND _pik < 0 THEN NULL
                 WHEN _pik IS NOT NULL AND _pik <= 0.50 THEN _pik * 100
                 WHEN _pik IS NOT NULL AND _pik >= 50 THEN _pik / 100
                 WHEN _pik IS NOT NULL THEN _pik
                 WHEN _text_pik_rate IS NOT NULL THEN _text_pik_rate
                 ELSE NULL END AS pik_rate,
            -- Maturity date with guard: reject dates before 1950
            -- and sentinel year 2099 (BDC convention for perpetual instruments)
            CASE
                WHEN maturity_date IS NOT NULL AND CAST(maturity_date AS VARCHAR) != ''
                     AND TRY_CAST(maturity_date AS DATE) >= DATE '1950-01-01'
                     AND YEAR(TRY_CAST(maturity_date AS DATE)) < 2099
                    THEN CAST(maturity_date AS VARCHAR)
                WHEN maturity_date IS NOT NULL AND CAST(maturity_date AS VARCHAR) != ''
                    THEN ''
                WHEN _text_maturity_raw IS NOT NULL THEN
                    CASE WHEN (
                        CASE WHEN LENGTH(regexp_extract(
                                 _text_maturity_raw, '/(\\d+)$', 1)) <= 2
                             THEN TRY_STRPTIME(_text_maturity_raw, '%m/%d/%y')
                             ELSE TRY_STRPTIME(_text_maturity_raw, '%m/%d/%Y')
                        END) >= DATE '1950-01-01'
                    AND YEAR(
                        CASE WHEN LENGTH(regexp_extract(
                                 _text_maturity_raw, '/(\\d+)$', 1)) <= 2
                             THEN TRY_STRPTIME(_text_maturity_raw, '%m/%d/%y')
                             ELSE TRY_STRPTIME(_text_maturity_raw, '%m/%d/%Y')
                        END) < 2099
                    THEN strftime(
                        CASE WHEN LENGTH(regexp_extract(
                                 _text_maturity_raw, '/(\\d+)$', 1)) <= 2
                             THEN TRY_STRPTIME(_text_maturity_raw, '%m/%d/%y')
                             ELSE TRY_STRPTIME(_text_maturity_raw, '%m/%d/%Y')
                        END,
                        '%Y-%m-%d')
                    ELSE '' END
                WHEN _text_maturity_month_raw IS NOT NULL THEN
                    CASE WHEN last_day(TRY_STRPTIME(_text_maturity_month_raw, '%m/%Y')) >= DATE '1950-01-01'
                          AND YEAR(last_day(TRY_STRPTIME(_text_maturity_month_raw, '%m/%Y'))) < 2099
                    THEN strftime(last_day(TRY_STRPTIME(_text_maturity_month_raw, '%m/%Y')), '%Y-%m-%d')
                    ELSE '' END
                ELSE ''
            END AS maturity_date,
            -- provenance: structured XBRL maturity tag wins (when valid); identifier text
            -- only fills when the structured tag is absent (structured-first).
            CASE WHEN maturity_date IS NOT NULL AND CAST(maturity_date AS VARCHAR) != ''
                      AND TRY_CAST(maturity_date AS DATE) >= DATE '1950-01-01'
                      AND YEAR(TRY_CAST(maturity_date AS DATE)) < 2099
                     THEN 'xbrl_field'
                 WHEN (maturity_date IS NULL OR CAST(maturity_date AS VARCHAR) = '')
                      AND (_text_maturity_raw IS NOT NULL OR _text_maturity_month_raw IS NOT NULL)
                     THEN 'identifier_text'
                 ELSE '' END AS maturity_date_source,
            _sh AS shares_held,
            _pa AS principal_amount,
            upper(trim(regexp_replace(COALESCE(CAST(principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) AS principal_amount_currency,
            CASE
                WHEN _pa IS NULL THEN NULL
                WHEN upper(trim(regexp_replace(COALESCE(CAST(principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) IN ('', 'USD')
                THEN _pa
                WHEN fx.usd_per_currency IS NOT NULL THEN _pa * fx.usd_per_currency
                ELSE NULL
            END AS principal_amount_usd,
            CASE
                WHEN _pa IS NULL THEN NULL
                WHEN upper(trim(regexp_replace(COALESCE(CAST(principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) IN ('', 'USD')
                THEN 1.0
                ELSE fx.usd_per_currency
            END AS principal_fx_rate_to_usd,
            CASE
                WHEN _pa IS NULL THEN ''
                WHEN upper(trim(regexp_replace(COALESCE(CAST(principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) IN ('', 'USD')
                THEN 'source_usd'
                WHEN fx.usd_per_currency IS NOT NULL THEN 'reference_fx'
                ELSE 'missing_reference_fx'
            END AS principal_fx_status,
            _raw_id AS bdc_investment_identifier,
            form_type AS bdc_form_type,
            dimensions_raw AS bdc_dimensions_raw,
            _ugl AS bdc_unrealized_gain_loss,
            COALESCE(_hier_country, '') AS bdc_investment_country,
            COALESCE(CAST(src_context_id AS VARCHAR), '') AS src_context_id,
            COALESCE(CAST(dedupe_context_count AS VARCHAR), '') AS src_context_count,
            COALESCE(CAST(dedupe_conflict_fields AS VARCHAR), '') AS src_conflict_fields,
            COALESCE(concat_ws(';',
                CASE WHEN _ir IS NOT NULL AND _ir < 0 THEN 'interest_rate:neg_null'
                     WHEN _ir IS NOT NULL AND _ir <= 0.50 THEN 'interest_rate:rate_x100'
                     WHEN _ir IS NOT NULL AND _ir >= 50 THEN 'interest_rate:rate_div100'
                     ELSE NULL END,
                CASE WHEN _bs IS NOT NULL AND _bs < 0 THEN 'basis_spread:neg_null'
                     WHEN _bs IS NOT NULL AND _bs <= 0.50 THEN 'basis_spread:rate_x100'
                     WHEN _bs IS NOT NULL AND _bs >= 50 THEN 'basis_spread:rate_div100'
                     ELSE NULL END,
                CASE WHEN _pik IS NOT NULL AND _pik < 0 THEN 'pik_rate:neg_null'
                     WHEN _pik IS NOT NULL AND _pik <= 0.50 THEN 'pik_rate:rate_x100'
                     WHEN _pik IS NOT NULL AND _pik >= 50 THEN 'pik_rate:rate_div100'
                     ELSE NULL END,
                CASE WHEN _pct IS NOT NULL AND _pct <= 0.50 THEN 'pct_of_net_assets:rate_x100'
                     WHEN _pct IS NOT NULL AND _pct > 50 THEN 'pct_of_net_assets:rate_div100'
                     ELSE NULL END
            ), '') AS src_transforms,
            '' AS src_field_overrides,
            '' AS cost_source,
            '' AS shares_held_source,
            -- ELSE '' is dead: has_fv CTE (Phase C input gate) requires _fv IS NOT NULL.
            CASE WHEN _fv IS NOT NULL THEN 'xbrl_field' ELSE '' END AS fair_value_source,
            CASE WHEN _pa IS NOT NULL THEN 'xbrl_field' ELSE '' END AS principal_amount_source,
            CASE WHEN _pct IS NOT NULL THEN 'xbrl_field' ELSE '' END AS pct_of_net_assets_source,
            CASE WHEN _pik IS NOT NULL AND _pik >= 0 THEN 'xbrl_field'
                 WHEN _pik IS NULL AND _text_pik_rate IS NOT NULL THEN 'identifier_text'
                 ELSE '' END AS pik_rate_source,
            CASE WHEN _ugl IS NOT NULL THEN 'xbrl_field' ELSE '' END AS bdc_unrealized_gain_loss_source,
            COALESCE(CAST(src_facts AS VARCHAR), '') AS src_facts,
            COALESCE(CAST(dedupe_filled_fields AS VARCHAR), '') AS src_filled_fields,
            concat_ws(';',
                CASE WHEN _scale_div1000 AND _fv IS NOT NULL THEN 'fair_value' END,
                CASE WHEN _scale_div1000 AND _cost IS NOT NULL THEN 'cost' END,
                CASE WHEN _scale_div1000 AND _pa IS NOT NULL THEN 'principal_amount' END
            ) AS corrected_fields,
            '' AS nport_holding_id,
            '' AS nport_series_name,
            '' AS nport_series_id,
            '' AS nport_asset_cat,
            '' AS nport_issuer_type,
            '' AS nport_payoff_profile,
            '' AS nport_investment_country,
            '' AS nport_is_restricted,
            '' AS nport_quarter,
            '' AS nport_is_default,
            '' AS nport_are_interest_payments_in_arrears,
            '' AS nport_is_paid_in_kind,
            '' AS nport_currency_code,
            '' AS nport_liquidity_classification,
            COALESCE(TRY_CAST(nonaccrual_footnote AS BOOLEAN), FALSE) AS nonaccrual_footnote,
            COALESCE(TRY_CAST(nonaccrual_dimension AS BOOLEAN), FALSE) AS nonaccrual_dimension,
            CASE WHEN lower(COALESCE(CAST(dimensions_raw AS VARCHAR), ''))
                          LIKE '%nonconsolidatedsubsidiar%'
                      OR lower(COALESCE(CAST(dimensions_raw AS VARCHAR), ''))
                          LIKE '%subsidiar%'
                      -- Equity-method investee (JV) look-through facts: same
                      -- retain-and-flag treatment as the subsidiary axes
                      -- (adjudicated 2026-07-21/22, data_investigation_results
                      -- parts 5-8: JV note portfolios are not fund holdings).
                      OR lower(COALESCE(CAST(dimensions_raw AS VARCHAR), ''))
                          LIKE '%equitymethodinvestmentequitymethodinvesteenameaxis%'
                 THEN 1 ELSE 0 END AS is_subsidiary,
            -- Row provenance (spec 2026-08-30): the row's normalized presentation
            -- profile. Lowercase, '='-attached member values stripped, segments
            -- trimmed and SORTED for order stability. Plain (no '=') member-label
            -- segments are KEPT deliberately -- they discriminate bare-axis rows
            -- from affiliation-labeled presentations (the 1812554/1838126 layer
            -- forensics). Derived-only; appliers never write it.
            CASE WHEN COALESCE(TRIM(CAST(dimensions_raw AS VARCHAR)), '') = '' THEN ''
                 ELSE array_to_string(list_sort(list_filter(
                        list_transform(
                            string_split(
                                regexp_replace(lower(CAST(dimensions_raw AS VARCHAR)),
                                               '=[^|]*', '', 'g'), '|'),
                            x -> trim(x)),
                        x -> x <> '')), '|')
            END AS axis_profile,
            '' AS jv_subsidiary,
            '' AS entity_id,
            '' AS canonical_name,
            COALESCE(_hier_industry, '') AS extracted_industry,
            '' AS gics_sub_industry,
            '' AS lien_position,
            '' AS instrument_type,
            -- Position key: normalized issuer+instrument identity, volatile parts stripped
            CASE
                WHEN LPAD(REGEXP_REPLACE(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0')
                     IN ({', '.join(f"'{c}'" for c in _comma_delim_ciks) if _comma_delim_ciks else "'__NONE__'"})
                THEN TRIM(REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        LOWER(CAST(_raw_id AS VARCHAR)),
                        '[^a-z0-9 ]', ' ', 'g'),
                    '\\s+', ' ', 'g'))
                ELSE TRIM(REGEXP_REPLACE(
                    REGEXP_REPLACE(
                        LOWER(
                        REGEXP_REPLACE(
                        REGEXP_REPLACE(
                        REGEXP_REPLACE(
                        REGEXP_REPLACE(
                            CAST({name_norm} AS VARCHAR)
                            || ' '
                            || COALESCE(CAST(instrument_description AS VARCHAR), ''),
                            '\\(\\$[\\d,.]+\\s*par\\b[^)]*\\)', '', 'gi'),
                            '(?:interest rate |rate )\\d+\\.?\\d*%', '', 'gi'),
                            '(?:sofr|libor|prime)\\s*\\+\\s*\\d+\\.?\\d*%?', '', 'gi'),
                            '^\\d+\\.\\d+%\\s+', '', 'g')),
                        '[^a-z0-9 ]', ' ', 'g'),
                    '\\s+', ' ', 'g'))
            END AS position_key,
            '' AS position_id,
            _row_id
        FROM with_enrichment w
        LEFT JOIN fx_rates fx
          ON upper(trim(regexp_replace(COALESCE(CAST(w.principal_amount_unit AS VARCHAR), ''), '^.*:', ''))) = fx.currency
         AND CAST(w.report_date AS VARCHAR) = fx.rate_date
    ),

    -- CTE 12a: Fix PIK rate boundary errors.
    -- Raw XBRL pik_rate at 0.20-0.50 (20-50 bps) gets wrongly *100'd to 20-50%.
    -- If normalized pik_rate >= 20 and exceeds interest_rate, it was bps: /100.
    unified_pik_fixed AS (
        SELECT * EXCLUDE (pik_rate, src_transforms),
            CASE WHEN pik_rate >= 20
                  AND interest_rate IS NOT NULL
                  AND pik_rate > interest_rate
                 THEN pik_rate / 100
                 ELSE pik_rate END AS pik_rate,
            CASE WHEN pik_rate >= 20
                  AND interest_rate IS NOT NULL
                  AND pik_rate > interest_rate
                 THEN concat_ws(';', NULLIF(src_transforms, ''),
                                'pik_rate:pik_boundary_div100')
                 ELSE src_transforms END AS src_transforms
        FROM unified
    ),

    -- CTE 12: Normalize issuer_name casing within each CIK.
    -- When the same issuer appears with different casing across XBRL
    -- dimension paths, pick the most frequent variant per CIK.
    -- Tiebreak: prefer mixed-case over ALL-CAPS, then alphabetical.
    _casing_vote AS (
        SELECT cik, issuer_name, COUNT(*) AS _cnt
        FROM unified_pik_fixed
        WHERE issuer_name IS NOT NULL AND issuer_name != ''
        GROUP BY cik, issuer_name
    ),
    _canonical_casing AS (
        SELECT cik,
            LOWER(issuer_name) AS _name_lower,
            issuer_name AS _canonical
        FROM _casing_vote
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY cik, LOWER(issuer_name)
            ORDER BY _cnt DESC,
                CASE WHEN issuer_name = UPPER(issuer_name) THEN 1 ELSE 0 END,
                issuer_name
        ) = 1
    ),
    with_casing AS (
        SELECT u.* EXCLUDE (issuer_name),
            COALESCE(cc._canonical, u.issuer_name) AS issuer_name
        FROM unified_pik_fixed u
        LEFT JOIN _canonical_casing cc
            ON u.cik = cc.cik
            AND LOWER(u.issuer_name) = cc._name_lower
    )

    SELECT * FROM with_casing ORDER BY _row_id
    """

    result = con.execute(sql_phase_c).fetchdf()
    result = _repair_weak_position_keys(result)
    logger.info("  Phase C (classify+map): %d rows in %.1f s",
                len(result), time.time() - _t_phase)

    con.close()

    # Drop internal row id column
    result.drop(columns=["_row_id"], inplace=True)

    # Log filtering stats (input_count set during data source selection above)
    output_count = len(result)
    logger.info("  After all BDC filters: %d rows (%d removed)",
                output_count, input_count - output_count)

    logger.info("  BDC asset breakdown:")
    for cat, count in result["asset_category"].value_counts().items():
        logger.info("    %s: %d (%.1f%%)", cat, count, 100 * count / len(result))

    # HTML-section bridge: overlay maturity_date / reference_rate_type from
    # audited cached-HTML bridges for filers that leave these untagged in XBRL
    # (Blackstone et al.).  Exact-keyed, blank-only, evidence-reconciled.
    result = apply_html_section_bridge_field_overlays(
        result, identifier_col="bdc_investment_identifier"
    )

    # iXBRL field-status overlay: apply only status=value maturity/lien/
    # reference_rate from the per-position field-status artifact (blank-only;
    # lien status already reflects the subtotal-reconciliation gate). No-op if
    # the artifact has not been produced yet.
    from pipeline.config import BDC_IXBRL_FIELD_STATUS_FILE
    if BDC_IXBRL_FIELD_STATUS_FILE.exists():
        from pipeline.bdc_xbrl_html_bridge import apply_ixbrl_field_status_overlay
        # Read only the columns the overlay needs and keep only rows with an
        # applicable status=value (the only rows that can be applied).  This is the
        # difference between a full ~1M-row CSV->dicts->DataFrame round-trip and a
        # narrow, pre-filtered DataFrame passed straight through.
        _cols = ["cik", "accession_number", "report_date", "raw_id_lower",
                 "maturity_date", "maturity_status", "reference_rate_type",
                 "reference_rate_status", "lien_position", "lien_status"]
        _sdf = pd.read_csv(BDC_IXBRL_FIELD_STATUS_FILE, dtype=str,
                           usecols=lambda c: c in _cols)
        _sdf = _sdf[(_sdf["maturity_status"] == "value")
                    | (_sdf["lien_status"] == "value")
                    | (_sdf["reference_rate_status"] == "value")]
        result = apply_ixbrl_field_status_overlay(result, _sdf)

    # Agent A basis_spread corrections: audited, keyed OVERRIDE (NOT blank-only) of the
    # per-position spreads where the freeform-identifier spread reconciles with all-in+SOFR
    # and the XBRL tag does not. Reversible (override records old_value_xbrl). No-op if the
    # override file is absent.
    from pipeline.identifier_spread_corrections import (
        apply_spread_corrections,
        spread_changed_index,
    )
    _spread_before = result["basis_spread"].copy() if "basis_spread" in result.columns else None
    result, _n_spread = apply_spread_corrections(
        result, identifier_col="bdc_investment_identifier"
    )
    if _n_spread and _spread_before is not None and "corrected_fields" in result.columns:
        from pipeline.agent_promoted import append_corrected_fields
        _spread_changed = spread_changed_index(_spread_before, result["basis_spread"])
        if len(_spread_changed):
            append_corrected_fields(result, _spread_changed, ["basis_spread"])

    # Log text enrichment stats
    n = len(result)
    ref_filled = (result["reference_rate_type"] != "").sum()
    mat_filled = (result["maturity_date"] != "").sum()
    logger.info("  Text enrichment: reference_rate_type %d (%.1f%%), "
                "maturity_date %d (%.1f%%)",
                ref_filled, 100 * ref_filled / n if n else 0,
                mat_filled, 100 * mat_filled / n if n else 0)

    return result


# ---------------------------------------------------------------------------
# N-PORT preparation
# ---------------------------------------------------------------------------
