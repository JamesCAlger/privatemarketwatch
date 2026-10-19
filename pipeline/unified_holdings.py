"""Unified private markets holdings -- combines BDC and N-PORT data.

Produces a single private_markets_holdings.csv with standardised schema,
asset/issuer/index classification, and parsed identifiers suitable for
index construction and dashboard analytics.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Union

import duckdb
import pandas as pd

from pipeline import (
    classification,
    instrument_classification,
    lien_classification,
    staging_bdc,
    staging_nport,
)
from pipeline.config import (
    BDC_HOLDINGS_FILE,
    BDC_HOLDINGS_PARQUET_FILE,
    COMBINED_UNIVERSE_FILE,
    # Not read by the build since 2026-10-04 (it is a previous run's output).
    # Kept as a module attribute because tests and the programme-rules audit
    # patch it; patching it must have no effect on the build.
    ENTITY_LOOKUP_FILE,  # noqa: F401
    FUND_FINANCIALS_FILE,
    FUND_STRATEGY_CORRECTION_CANDIDATES_FILE,
    FUND_STRATEGY_CORRECTION_CANDIDATES_PINNED_FILE,
    FUND_STRATEGY_REFERENCE_FILE,
    IDENTIFIER_EXTRACTION_LOOKUP_FILE,
    NPORT_HOLDINGS_FILE,
    NPORT_HOLDINGS_PARQUET_FILE,
    ROW_CORRECTIONS_BY_CONTEXT_FILE,
    ROW_CORRECTIONS_FILE,
    UNCLASSIFIED_REVIEW_CACHE_FILE,
    UNIFIED_HOLDINGS_FILE,
    UNIFIED_HOLDINGS_PARQUET_FILE,
    UNIVERSE_ORPHAN_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WRAPPER_DUPLICATE_LOT_KEY_CIKS = frozenset({
    "0001772704",
    "0001784700",
})

# Unified output column order
UNIFIED_COLUMNS = [
    # Identity
    "source", "cik", "entity_name", "accession_number",
    "filing_date", "report_date",
    # Holding identification
    "issuer_name", "instrument_description",
    # Identifiers (N-PORT only)
    "cusip", "isin", "lei", "ticker",
    # Valuation
    "fair_value", "cost", "pct_of_net_assets",
    "shares_held", "principal_amount",
    "fair_value_currency", "cost_currency",
    "principal_amount_currency", "principal_amount_usd",
    "principal_fx_rate_to_usd", "principal_fx_status",
    # Classification
    "asset_category", "issuer_category", "index_classification",
    "exposure_type", "asset_class",
    "fair_value_level",
    # Rate/spread
    "interest_rate", "interest_rate_source",
    "basis_spread", "basis_spread_source",
    "reference_rate_type",
    "reference_rate_source",
    "coupon_type", "pik_rate",
    # Debt details
    "maturity_date", "maturity_date_source",
    # Source-specific (BDC)
    "bdc_investment_identifier", "bdc_form_type", "bdc_dimensions_raw",
    "bdc_unrealized_gain_loss",
    "bdc_investment_country",
    # The filer's tagged acquisition date (us-gaap:InvestmentAcquisitionDate), BDC only. Many filers tag
    # it on a twin context of the position; the extractor merges the twins (owner, 2026-10-13).
    "bdc_acquisition_date",
    "src_context_id",
    "src_context_count",
    "src_conflict_fields",
    "src_transforms",
    "src_field_overrides",
    "cost_source",
    "shares_held_source",
    "fair_value_source",
    "principal_amount_source",
    "pct_of_net_assets_source",
    "pik_rate_source",
    "bdc_unrealized_gain_loss_source",
    "src_facts",
    "src_filled_fields",
    "corrected_fields",
    # Non-accrual signals (BDC only -- extracted from XBRL footnotes/dimensions)
    "nonaccrual_footnote", "nonaccrual_dimension",
    # Source-specific (N-PORT)
    "nport_holding_id", "nport_series_name", "nport_series_id",
    "nport_asset_cat", "nport_issuer_type", "nport_payoff_profile",
    "nport_investment_country", "nport_is_restricted", "nport_quarter",
    "nport_is_default", "nport_are_interest_payments_in_arrears",
    "nport_is_paid_in_kind", "nport_currency_code",
    "nport_liquidity_classification",
    # Subsidiary flag (BDC only -- nonconsolidated JV/subsidiary positions)
    "is_subsidiary",
    # Row provenance: normalized presentation profile of bdc_dimensions_raw
    # (BDC only; '' for N-PORT). Derived at staging, never corrected.
    "axis_profile",
    # JV/subsidiary flag from agent review of unclassified positions
    "jv_subsidiary",
    # Entity resolution (populated by --entities step)
    "entity_id", "canonical_name",
    # LLM-extracted fields (populated by --extract step)
    "extracted_industry",
    # GICS classification (populated by --classify-gics step)
    "gics_sub_industry",
    # Lien position (First Lien / Second Lien / Unsecured; DIRECT_LENDING only)
    "lien_position",
    # Instrument type (Revolver / Delayed Draw Term Loan / Term Loan / Unitranche)
    "instrument_type",
    # Normalized position key for multi-tranche disambiguation
    "position_key",
    # Position tracking (populated by --returns step)
    "position_id",
]
from pipeline.financial_conventions import ADDITIONS as FINANCIAL_ADDITIONS
UNIFIED_COLUMNS += list(FINANCIAL_ADDITIONS)
# NOTE: the saved artifact carries provenance columns beyond UNIFIED_COLUMNS: row_id,
# appended by _assign_row_ids as the last step of build_unified_holdings.
# It is deliberately NOT in UNIFIED_COLUMNS -- that list doubles as the
# in-flight SQL schema (union/stabilization passes) where row_id does not
# exist yet.

ORPHAN_HOLDINGS_COLUMNS = [
    "cik", "entity_name", "source", "first_report_date", "last_report_date",
    "row_count", "fair_value", "reason",
]


def _normalize_cik_series(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace(r"[^0-9]", "", regex=True)
        .str.zfill(10)
    )


def _write_empty_orphan_report(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=ORPHAN_HOLDINGS_COLUMNS).to_csv(path, index=False)


def _apply_universe_gate(
    df: pd.DataFrame,
    universe_path: Optional[Path] = None,
    orphan_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Remove holdings for CIKs outside combined_universe and write review residuals."""
    path = universe_path or (UNIFIED_HOLDINGS_FILE.parent / COMBINED_UNIVERSE_FILE.name)
    out_path = orphan_path or (UNIFIED_HOLDINGS_FILE.parent / UNIVERSE_ORPHAN_HOLDINGS_FILE.name)
    if df.empty:
        _write_empty_orphan_report(out_path)
        return df
    if not path.exists():
        logger.warning("Combined universe file not found; skipping universe gate: %s", path)
        _write_empty_orphan_report(out_path)
        return df

    universe = pd.read_csv(path, dtype=str)
    if "cik" not in universe.columns:
        logger.warning("Combined universe file missing cik column; skipping universe gate: %s", path)
        _write_empty_orphan_report(out_path)
        return df

    allowed = set(_normalize_cik_series(universe["cik"]))
    gated = df.copy()
    gated["_norm_cik"] = _normalize_cik_series(gated["cik"])
    gated["cik"] = gated["_norm_cik"]
    orphan_mask = ~gated["_norm_cik"].isin(allowed)
    orphan_rows = gated[orphan_mask].copy()

    if orphan_rows.empty:
        _write_empty_orphan_report(out_path)
        return gated.drop(columns=["_norm_cik"])

    orphan_rows["fair_value"] = pd.to_numeric(orphan_rows["fair_value"], errors="coerce")
    orphan_summary = (
        orphan_rows.groupby(["_norm_cik", "entity_name", "source"], dropna=False)
        .agg(
            first_report_date=("report_date", "min"),
            last_report_date=("report_date", "max"),
            row_count=("source", "size"),
            fair_value=("fair_value", "sum"),
        )
        .reset_index()
        .rename(columns={"_norm_cik": "cik"})
    )
    orphan_summary["reason"] = "cik_absent_from_combined_universe"
    orphan_summary = orphan_summary[ORPHAN_HOLDINGS_COLUMNS]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    orphan_summary.to_csv(out_path, index=False)

    logger.warning(
        "Universe gate removed %d holdings across %d CIK/source groups; review %s",
        len(orphan_rows), len(orphan_summary), out_path.name,
    )
    return gated[~orphan_mask].drop(columns=["_norm_cik"]).reset_index(drop=True)

def _stabilize_classification(df: pd.DataFrame) -> pd.DataFrame:
    """Stabilize QoQ classification flips using 2x majority rule.

    For each position-level group that has multiple distinct values for
    index_classification (or exposure_type / asset_class), if the most frequent
    value has >= 2x the quarter-count of the second most frequent, override all
    minority rows to the majority value.

    This prevents spurious flips caused by BDC identifier format changes between
    filings (e.g., pipe vs comma delimiters, 10-K vs 10-Q naming differences).
    Stabilization is intentionally keyed below borrower level so a loan,
    common equity stake, and preferred equity stake in the same borrower do not
    overwrite each other's classifications.
    """
    if df.empty:
        return df

    con = duckdb.connect()
    con.register("src", df)

    # Build stabilization CTEs for all three classification columns
    cte_parts = []
    select_overrides = []
    join_clauses = []

    for i, col in enumerate(("index_classification", "exposure_type", "asset_class")):
        alias = f"_stab{i}"
        cte_parts.append(f"""
        {alias}_base AS (
            SELECT *,
                regexp_replace(
                    lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                    '[^a-z0-9]+', ' ', 'g'
                ) AS _stab_issuer,
                regexp_replace(
                    lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                    '[^a-z0-9]+', ' ', 'g'
                ) AS _stab_instrument,
                COALESCE(CAST(source AS VARCHAR), '') AS _stab_source,
                COALESCE(CAST(asset_category AS VARCHAR), '') AS _stab_asset,
                COALESCE(CAST(issuer_category AS VARCHAR), '') AS _stab_issuer_cat
            FROM src
        ),
        {alias}_counts AS (
            SELECT cik, _stab_source, _stab_issuer, _stab_instrument,
                   _stab_asset, _stab_issuer_cat,
                   CAST({col} AS VARCHAR) AS cls, COUNT(*) AS n_q
            FROM {alias}_base
            WHERE {col} IS NOT NULL
              AND CAST({col} AS VARCHAR) != ''
            GROUP BY 1, 2, 3, 4, 5, 6, 7
        ),
        {alias}_ranked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, _stab_source, _stab_issuer,
                        _stab_instrument, _stab_asset, _stab_issuer_cat
                    ORDER BY n_q DESC, cls
                ) AS rn
            FROM {alias}_counts
        ),
        {alias}_stable AS (
            SELECT r1.cik, r1._stab_source, r1._stab_issuer,
                   r1._stab_instrument, r1._stab_asset,
                   r1._stab_issuer_cat, r1.cls AS stable_val
            FROM {alias}_ranked r1
            JOIN {alias}_ranked r2
              ON r1.cik = r2.cik
             AND r1._stab_source = r2._stab_source
             AND r1._stab_issuer = r2._stab_issuer
             AND r1._stab_instrument = r2._stab_instrument
             AND r1._stab_asset = r2._stab_asset
             AND r1._stab_issuer_cat = r2._stab_issuer_cat
             AND r2.rn = 2
            WHERE r1.rn = 1
              AND r1.n_q >= 2 * r2.n_q
        )""")
        select_overrides.append(
            f"COALESCE({alias}.stable_val, CAST(s.{col} AS VARCHAR)) AS {col}"
        )
        join_clauses.append(
            f"LEFT JOIN {alias}_stable {alias}"
            f" ON s.cik = {alias}.cik"
            f" AND COALESCE(CAST(s.source AS VARCHAR), '') = {alias}._stab_source"
            f" AND regexp_replace(lower(trim(COALESCE(CAST(s.issuer_name AS VARCHAR), ''))), '[^a-z0-9]+', ' ', 'g') = {alias}._stab_issuer"
            f" AND regexp_replace(lower(trim(COALESCE(CAST(s.instrument_description AS VARCHAR), ''))), '[^a-z0-9]+', ' ', 'g') = {alias}._stab_instrument"
            f" AND COALESCE(CAST(s.asset_category AS VARCHAR), '') = {alias}._stab_asset"
            f" AND COALESCE(CAST(s.issuer_category AS VARCHAR), '') = {alias}._stab_issuer_cat"
        )

    # Build list of columns to pass through (everything except the 3 we override)
    override_set = {"index_classification", "exposure_type", "asset_class"}
    pass_cols = [f"s.{c}" for c in UNIFIED_COLUMNS if c not in override_set]

    sql = "WITH " + ",".join(cte_parts) + f"""
    SELECT {', '.join(pass_cols)},
           {', '.join(select_overrides)}
    FROM src s
    {chr(10).join(join_clauses)}
    """

    result = con.execute(sql).fetchdf()

    # Log stabilization impact
    for col in ("index_classification", "exposure_type", "asset_class"):
        changed = (df[col].astype(str) != result[col].astype(str)).sum()
        if changed > 0:
            logger.info("  Classification stabilization: %d rows changed for %s",
                        changed, col)

    con.close()

    # Restore column order
    result = result[UNIFIED_COLUMNS]
    return result


def _restore_deterministic_classification_rules(df: pd.DataFrame) -> pd.DataFrame:
    """Reapply high-confidence deterministic rules after QoQ stabilization.

    Stabilization is useful for noisy issuer/instrument parsing, but it should
    not erase explicit current-row signals such as structured-credit keywords
    or BDC fund-vehicle names.
    """
    if df.empty:
        return df

    con = duckdb.connect()
    con.register("src", df)

    idx_case = classification._sql_classify_index()
    asset_class_case = classification._sql_classify_asset_class()
    sc_kw = classification._sql_keyword_check(
        "_combined_fund_text",
        classification._STRUCTURED_CREDIT_KEYWORDS,
    )
    bdc_vehicle_fund = classification._sql_is_bdc_vehicle_fund()
    restore_predicate = f"({sc_kw} OR {bdc_vehicle_fund})"

    lien_case = lien_classification._sql_classify_lien()

    override_set = {"index_classification", "asset_class", "lien_position"}
    pass_cols = [f"s.{c}" for c in UNIFIED_COLUMNS if c not in override_set]
    sql = f"""
    WITH keyed AS (
        SELECT *,
            COALESCE(lower(trim(issuer_name)), '') || ' ' ||
            COALESCE(lower(trim(instrument_description)), '') AS _combined_fund_text
        FROM src
    ),
    reclassified AS (
        SELECT *,
            {idx_case} AS _rule_index_classification,
            {asset_class_case} AS _rule_asset_class,
            {lien_case} AS _rule_lien,
            {restore_predicate} AS _restore_classification
        FROM keyed
    )
    SELECT {', '.join(pass_cols)},
           CASE WHEN _restore_classification
                THEN _rule_index_classification
                ELSE CAST(s.index_classification AS VARCHAR)
           END AS index_classification,
           CASE WHEN _restore_classification
                THEN _rule_asset_class
                ELSE CAST(s.asset_class AS VARCHAR)
           END AS asset_class,
           CASE WHEN _restore_classification
                THEN CASE WHEN _rule_index_classification = 'DIRECT_LENDING'
                          THEN CAST(_rule_lien AS VARCHAR) ELSE NULL END
                ELSE CAST(s.lien_position AS VARCHAR)
           END AS lien_position
    FROM reclassified s
    """

    result = con.execute(sql).fetchdf()
    con.close()

    for col in ("index_classification", "asset_class"):
        changed = (df[col].astype(str) != result[col].astype(str)).sum()
        if changed > 0:
            logger.info("  Deterministic classification restore: %d rows changed for %s",
                        changed, col)

    result = result[UNIFIED_COLUMNS]
    return result


# ---------------------------------------------------------------------------
# pct_of_net_assets correction for multi-entity BDCs
# ---------------------------------------------------------------------------


def _correct_pct_of_net_assets(df: pd.DataFrame) -> pd.DataFrame:
    """Compatibility entry point: reported percentages are never recomputed.

    Financial finalization writes the independently supported NAV ratio to
    pct_of_net_assets_calculated. Keeping this no-op prevents old callers from
    overwriting the disclosure while they migrate to that explicit field.
    """
    return df



# ---------------------------------------------------------------------------
# In-build entity resolution (input-determined entity_id / canonical_name)
# ---------------------------------------------------------------------------

# The only columns entity resolution reads from holdings.
_ENTITY_INPUT_COLUMNS = [
    "issuer_name", "source", "cusip", "lei", "bdc_investment_identifier",
]


def _resolve_entities_in_build(combined: pd.DataFrame) -> pd.DataFrame:
    """Fill entity_id / canonical_name from a lookup built from THIS frame.

    The lookup is a function of the frame's issuer names plus the entity
    resolver's own reference inputs (identifier extraction cache, entity
    overrides). Nothing is read from ENTITY_LOOKUP_FILE, which is an output of
    the previous run: reading it back made the GICS canonical-name fallback,
    and so the published sector mix, depend on rebuild order.

    The final entity_lookup.csv is still written by the holdings finalizer
    from the finished holdings. Both passes run the same resolver over the
    same five columns, serialized the same way, so they agree.

    Row order and row count are preserved (the caller has already sorted).
    """
    if combined.empty:
        return combined

    import tempfile

    from pipeline import entity_resolution

    with tempfile.TemporaryDirectory(prefix="unified-entities-") as directory:
        staged = Path(directory) / "entity_inputs.csv"
        # Same serializer as the final holdings CSV the finalizer resolves from.
        combined[_ENTITY_INPUT_COLUMNS].to_csv(staged, index=False)
        # build_entity_lookup cannot handle a frame with no resolvable issuer
        # name (opaque ids, subtotal labels, blanks only). Ask the resolver's
        # own variant filter rather than re-implementing it here.
        if entity_resolution._build_variant_table(staged).empty:
            logger.info("Entity enrichment (in-build): no resolvable issuer names")
            result = combined.copy()
            result["entity_id"] = ""
            result["canonical_name"] = ""
            return result
        variants = entity_resolution.build_entity_lookup(
            staged, enrich=False,
            lookup_path=Path(directory) / "entity_lookup.csv",
            stats_path=Path(directory) / "entity_resolution_stats.csv")

    lookup = pd.DataFrame({
        "_entity_issuer": variants["issuer_name"].astype(str),
        "_entity_source": variants["source"].astype(str),
        "entity_id": variants["entity_num"].map(entity_resolution._format_entity_id),
        "canonical_name": variants["canonical_name"],
    })

    columns = list(combined.columns)
    keyed = combined.drop(columns=["entity_id", "canonical_name"])
    # String keys mirror the CAST(... AS VARCHAR) of the CSV the resolver read.
    for key, column in (("_entity_issuer", "issuer_name"), ("_entity_source", "source")):
        values = keyed[column].astype(object)
        keyed[key] = values.where(values.isna(), values.astype(str))
    # A duplicated (issuer, source) variant would multiply holdings rows; fail loudly.
    merged = keyed.merge(lookup, how="left", on=["_entity_issuer", "_entity_source"],
                         validate="many_to_one")
    if len(merged) != len(combined):
        raise ValueError("In-build entity enrichment changed the holdings row count")
    merged.index = combined.index
    for column in ("entity_id", "canonical_name"):
        merged[column] = merged[column].astype(object).where(merged[column].notna(), "")
    merged = merged[columns]

    with_entity = int((merged["entity_id"] != "").sum())
    logger.info("Entity enrichment (in-build): %d/%d rows (%.1f%%) with entity_id",
                with_entity, len(merged), 100 * with_entity / len(merged))
    return merged


# ---------------------------------------------------------------------------
# GICS cache application (zero-cost, no LLM)
# ---------------------------------------------------------------------------


def _apply_gics_cache(combined: pd.DataFrame) -> pd.DataFrame:
    """Apply cached GICS classifications from company_gics_cache.csv.

    This runs automatically during --unified so that GICS data survives
    rebuilds without requiring a separate --classify-gics step.  No LLM
    calls are made -- only the on-disk cache is read.
    """
    from pipeline.config import COMPANY_GICS_CACHE_FILE

    if not COMPANY_GICS_CACHE_FILE.exists():
        return combined

    from pipeline.gics_classification import (
        _apply_gics_to_holdings,
        _load_cache,
    )

    cache = _load_cache()
    if not cache:
        return combined

    logger.info("Applying GICS cache (%d entries) to unified holdings...", len(cache))
    combined = _apply_gics_to_holdings(combined, cache)
    classified = (combined["gics_sub_industry"] != "").sum()
    logger.info("  GICS: %d/%d rows (%.1f%%) classified from cache",
                classified, len(combined),
                100 * classified / len(combined) if len(combined) else 0)
    return combined


def printed_industry_gics(labels) -> dict[str, tuple[str, str]]:
    """{filer industry label: (GICS sub-industry, how)} for the labels that map without a model call.

    'alias' and 'exact' come from the reviewed table and the GICS names in pipeline.gics_mapping;
    'label_cache' is an earlier mapping of the same label kept in that module's cache. A label that
    maps to nothing, or to 'Other', is left out.
    """
    import re
    from pipeline import gics_mapping
    names = gics_mapping._load_gics_names()
    exact = {gics_mapping._gics_lookup_key(name): name for name in names}
    try:
        cached = gics_mapping._load_cache()
    except Exception:  # an unreadable cache is no mapping, not a failed build
        cached = {}
    result: dict[str, tuple[str, str]] = {}
    for label in labels:
        text = str(label or "").strip()
        if not text:
            continue
        found = gics_mapping._try_remap_stale(text, exact, names)
        if found is None:
            # the reviewed table is keyed without punctuation ('beverage food and tobacco')
            # ... and a filer can number the rows of one industry in the member ('Capital Goods 2')
            plain = " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", re.sub(r"\s+\d{1,2}$", "", text).replace("&", " and ")).split())
            found = gics_mapping._try_remap_stale(plain, exact, names)
        if found is None and text in cached:
            found = (cached[text][0], "label_cache")
        if found is not None and found[0] and found[0] != "Other" and found[1] != "aggregate":
            result[text] = found
    return result


def _apply_printed_industry(combined: pd.DataFrame) -> pd.DataFrame:
    """Set gics_sub_industry from the industry the filer prints for the row (extracted_industry).

    Owner ruling 2026-10-11: the industry is read from the filer's heading, not guessed from the
    company name. Where a BDC row carries the filer's industry and that label maps to a GICS
    sub-industry without a model call, the mapping replaces the name-keyed label. A row whose
    label does not map keeps what it had; the log counts those rows so the table can be extended.
    """
    if "extracted_industry" not in combined.columns or "gics_sub_industry" not in combined.columns:
        return combined
    # A member that writes its column words with a non-breaking space ('Interest\xa0Rate 10.93%')
    # passes the staging split and leaves the rate behind the industry. No industry holds these words.
    if "source" in combined.columns:
        text = combined["extracted_industry"].astype("string")
        tailed = (combined["source"] == "bdc") & text.str.contains(r"(?i)\s(?:Interest|Reference)\s+Rate\b", regex=True).fillna(False)
        if tailed.any():
            combined.loc[tailed, "extracted_industry"] = text[tailed].str.replace(
                r"(?i)\s+(?:Interest|Reference)\s+Rate\b.*$", "", regex=True).str.strip()
    # A filer that carries the industry inside the member text (dispatch.industry_from_identifier_re):
    # read it where the row has none yet.
    from pipeline.staging_bdc import industry_from_identifier_patterns, industry_label_gics_maps
    member_patterns = industry_from_identifier_patterns() if {"cik", "bdc_investment_identifier"} <= set(combined.columns) else {}
    # A filer's own label map (dispatch.industry_label_gics), for that filer's rows only.
    fund_maps = industry_label_gics_maps() if "cik" in combined.columns else {}

    def map_labels(label: pd.Series, rows: pd.Series) -> pd.Series:
        mapping = printed_industry_gics(label[rows].unique().tolist())
        out = label.map({key: value[0] for key, value in mapping.items()}).astype(object)
        for fund, table in fund_maps.items():
            mine = rows & (_normalize_cik_series(combined["cik"]) == fund)
            if mine.any():
                own = label[mine].map(lambda text: table.get(" ".join(str(text).lower().split())))
                own = own[own.notna()]
                out.loc[own.index] = own
        return out

    def fill_from_member() -> None:
        for cik, pattern in member_patterns.items():
            mine = (combined["source"] == "bdc") & (_normalize_cik_series(combined["cik"]) == cik)
            mine &= combined["extracted_industry"].astype("string").fillna("").str.strip() == ""
            if mine.any():
                found = combined.loc[mine, "bdc_investment_identifier"].astype("string").str.extract(pattern, expand=True)[0]
                found = found.fillna("").str.strip()
                # Where the member's segments are out of order the pattern catches another field ('Term
                # Loan', an issuer). Such a catch is rare for the fund and maps to nothing; a real industry
                # the table does not know yet is frequent. Rare and unmapped is not taken.
                counts = found[found != ""].value_counts()
                known = set(printed_industry_gics(counts.index.tolist()))
                own = fund_maps.get(cik, {})
                known |= {text for text in counts.index if " ".join(str(text).lower().split()) in own}
                rare = {text for text, n in counts.items() if n < 20 and text not in known}
                found = found.where(~found.isin(rare), "")
                combined.loc[found[found != ""].index, "extracted_industry"] = found[found != ""]

    fill_from_member()
    label = combined["extracted_industry"].astype("string").fillna("").str.strip()
    rows = (combined["source"] == "bdc") & (label != "")
    if "index_classification" in combined.columns:
        rows &= combined["index_classification"].astype("string").fillna("") != "CASH"
    if not rows.any():
        return combined
    mapped = map_labels(label, rows)
    # Where most of a filing's labels map to nothing, the labels are not industries: in the Apollo
    # layout the heading above a row is the company group ('Paladone', 'FingerPaint Marketing'), the
    # industry sits one heading higher. Such a filing's unmapped labels are withdrawn, not published.
    if {"cik", "accession_number"} <= set(combined.columns):
        filing = combined["cik"].astype("string").fillna("") + "|" + combined["accession_number"].astype("string").fillna("")
        counted = pd.DataFrame({"filing": filing[rows], "mapped": mapped[rows].notna()})
        share = counted.groupby("filing")["mapped"].agg(["size", "mean"])
        weak = set(share[(share["size"] >= 20) & (share["mean"] < 0.5)].index)
        if weak:
            withdraw = rows & filing.isin(weak) & mapped.isna()
            combined.loc[withdraw, "extracted_industry"] = ""
            logger.info("  Printed industry: %d labels withdrawn in %d filings where under half map (not industry headings)",
                        int(withdraw.sum()), len(weak))
            # A row whose heading was withdrawn can still carry the industry in its member text.
            fill_from_member()
            label = combined["extracted_industry"].astype("string").fillna("").str.strip()
            rows = (combined["source"] == "bdc") & (label != "")
            if "index_classification" in combined.columns:
                rows &= combined["index_classification"].astype("string").fillna("") != "CASH"
            mapped = map_labels(label, rows)
    take = rows & mapped.notna()
    changed = take & (combined["gics_sub_industry"].astype("string").fillna("") != mapped.fillna(""))
    combined.loc[take, "gics_sub_industry"] = mapped[take]
    logger.info("  Printed industry: %d BDC rows carry the filer's industry; %d mapped to GICS (%d changed); "
                "%d rows in %d labels not mapped", int(rows.sum()), int(take.sum()), int(changed.sum()),
                int((rows & ~take).sum()), int(label[rows & ~take].nunique()))
    return combined


def _apply_lien_cache(combined: pd.DataFrame) -> pd.DataFrame:
    """Apply cached lien position classifications from lien_cache.csv.

    Runs automatically during --unified so that agent-reviewed lien data
    survives rebuilds.  No LLM calls -- only the on-disk cache is read.
    """
    from pipeline.config import LIEN_CACHE_FILE

    if not LIEN_CACHE_FILE.exists():
        return combined

    result = lien_classification._apply_lien_cache(combined)
    return result


# Mapping from agent asset_class + new_index_classification to unified schema
_AGENT_EXPOSURE_MAP = {
    "FUND": "FUND",
    "LOAN": "DIRECT",
    "EQUITY_COMMON": "DIRECT",
    "EQUITY_PREFERRED": "DIRECT",
    "CASH": "LIQUID",
}

_AGENT_ASSET_CLASS_MAP: dict[tuple[str, str], str] = {
    ("FUND", "HEDGE_FUND"): "HEDGE_FUND",
    ("FUND", "PRIVATE_EQUITY_FUND"): "PRIVATE_EQUITY",
    ("FUND", "PRIVATE_CREDIT_FUND"): "PRIVATE_CREDIT",
    ("FUND", "REAL_ESTATE_FUND"): "REAL_ESTATE",
    ("LOAN", "DIRECT_LENDING"): "PRIVATE_CREDIT",
    ("LOAN", "STRUCTURED_CREDIT"): "STRUCTURED_CREDIT",
    ("EQUITY_COMMON", "COMMON_EQUITY"): "PRIVATE_EQUITY",
    ("EQUITY_PREFERRED", "PREFERRED_EQUITY"): "PRIVATE_EQUITY",
    ("CASH", "CASH"): "CASH",
}


def _apply_unclassified_cache(combined: pd.DataFrame) -> pd.DataFrame:
    """Apply agent-reviewed classifications to UNCLASSIFIED holdings.

    Loads ``unclassified_review_cache.csv`` and applies:
    - CLASSIFIED/AUTO_CLASSIFIED verdicts: reclassify UNCLASSIFIED rows
    - JV_SUBSIDIARY verdicts: flag rows with ``jv_subsidiary='Y'``

    Only updates rows where ``index_classification='UNCLASSIFIED'``.
    Existing classifications are never changed.
    """
    if not UNCLASSIFIED_REVIEW_CACHE_FILE.exists():
        if "jv_subsidiary" not in combined.columns:
            combined["jv_subsidiary"] = ""
        return combined

    from pipeline.gics_classification import _normalize_company_name

    cache = pd.read_csv(UNCLASSIFIED_REVIEW_CACHE_FILE, dtype=str).fillna("")

    # Split into classification and JV lookups
    classify_mask = (
        cache["verdict"].isin(["CLASSIFIED", "AUTO_CLASSIFIED"])
        & cache["confidence"].isin(["high", "medium"])
        & (cache["new_index_classification"] != "")
    )
    jv_mask = cache["verdict"] == "JV_SUBSIDIARY"

    classify_cache = cache.loc[classify_mask, ["name_norm", "new_index_classification", "asset_class"]].copy()
    jv_cache = cache.loc[jv_mask, ["name_norm"]].copy()

    if classify_cache.empty and jv_cache.empty:
        if "jv_subsidiary" not in combined.columns:
            combined["jv_subsidiary"] = ""
        return combined

    # Build classification lookup with derived exposure_type and unified asset_class.
    classify_df = classify_cache.rename(
        columns={
            "new_index_classification": "new_idx",
            "asset_class": "agent_asset_class",
        }
    ).copy()
    classify_df["name_norm"] = classify_df["name_norm"].str.strip()
    classify_df["new_idx"] = classify_df["new_idx"].str.strip()
    classify_df["agent_asset_class"] = classify_df["agent_asset_class"].str.strip()
    classify_df["new_exp"] = (
        classify_df["agent_asset_class"].map(_AGENT_EXPOSURE_MAP).fillna("DIRECT")
    )
    classify_df["new_ac"] = [
        _AGENT_ASSET_CLASS_MAP.get((asset_class, index_classification), "OTHER")
        for asset_class, index_classification in zip(
            classify_df["agent_asset_class"],
            classify_df["new_idx"],
        )
    ]
    classify_df = classify_df[["name_norm", "new_idx", "new_exp", "new_ac"]]
    # S14 tie-break: the cache CSV row order must not decide which entry survives
    # when the same name_norm appears twice. Stable-sort on ALL columns so the
    # kept ('first') survivor is deterministic, and warn once if the collapsed
    # duplicates DISAGREE on the classification we are about to apply.
    classify_df = classify_df.sort_values(
        list(classify_df.columns), kind="mergesort"
    )
    _dup_mask = classify_df.duplicated(subset=["name_norm"], keep=False)
    if _dup_mask.any():
        _disagree = (
            classify_df.loc[_dup_mask]
            .groupby("name_norm")[["new_idx", "new_exp", "new_ac"]]
            .nunique()
            .gt(1)
            .any(axis=1)
        )
        _disagree_names = sorted(_disagree[_disagree].index.astype(str))
        if _disagree_names:
            logger.warning(
                "Unclassified cache: %d name_norm(s) have DISAGREEING duplicate "
                "classifications; keeping deterministic first after stable sort: %s",
                len(_disagree_names),
                ", ".join(_disagree_names[:20]),
            )
    classify_df = classify_df.drop_duplicates(subset=["name_norm"], keep="first")

    jv_names = set(jv_cache["name_norm"].str.strip().values)

    # Pre-compute normalized issuer_name for matching
    combined = combined.copy()
    combined["_row_idx"] = range(len(combined))
    issuer_col = combined["issuer_name"].fillna("").astype(str)
    combined["_name_norm"] = issuer_col.map(_normalize_company_name)

    # Build JV flag column
    combined["jv_subsidiary"] = ""
    combined.loc[combined["_name_norm"].isin(jv_names), "jv_subsidiary"] = "Y"

    if classify_df.empty:
        combined = combined.drop(columns=["_row_idx", "_name_norm"])
        logger.info("Unclassified cache: 0 classify entries, %d JV flags applied",
                    (combined["jv_subsidiary"] == "Y").sum())
        return combined

    # Use DuckDB for efficient LEFT JOIN reclassification
    con = duckdb.connect()
    con.register("holdings", combined)
    con.register("unclass_lookup", classify_df)

    result = con.execute("""
        SELECT h.* EXCLUDE (index_classification, exposure_type, asset_class,
                            _row_idx, _name_norm),
               CASE WHEN CAST(h.index_classification AS VARCHAR) = 'UNCLASSIFIED'
                         AND ul.new_idx IS NOT NULL
                    THEN ul.new_idx
                    ELSE CAST(h.index_classification AS VARCHAR)
               END AS index_classification,
               CASE WHEN CAST(h.index_classification AS VARCHAR) = 'UNCLASSIFIED'
                         AND ul.new_exp IS NOT NULL
                    THEN ul.new_exp
                    ELSE CAST(h.exposure_type AS VARCHAR)
               END AS exposure_type,
               CASE WHEN CAST(h.index_classification AS VARCHAR) = 'UNCLASSIFIED'
                         AND ul.new_ac IS NOT NULL
                    THEN ul.new_ac
                    ELSE CAST(h.asset_class AS VARCHAR)
               END AS asset_class
        FROM holdings h
        LEFT JOIN unclass_lookup ul ON h._name_norm = ul.name_norm
        ORDER BY h._row_idx
    """).fetchdf()
    con.close()

    # Restore column order (EXCLUDE moves overridden columns to end)
    result = result[[c for c in UNIFIED_COLUMNS if c in result.columns]]

    # Count reclassifications
    before_unclass = (combined["index_classification"].astype(str) == "UNCLASSIFIED").sum()
    after_unclass = (result["index_classification"].astype(str) == "UNCLASSIFIED").sum()
    reclassified = before_unclass - after_unclass
    jv_count = (result["jv_subsidiary"] == "Y").sum()

    logger.info(
        "Unclassified cache: %d classify entries, reclassified %d rows "
        "(UNCLASSIFIED %d -> %d), %d JV flags",
        len(classify_df), reclassified, before_unclass, after_unclass, jv_count,
    )

    return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

from pipeline.rule_admission import capture_inputs


@capture_inputs(lambda: UNIFIED_HOLDINGS_FILE.parent, output_parameter='output_file')
def build_unified_holdings(
    bdc_df: Optional[pd.DataFrame] = None,
    nport_df: Optional[pd.DataFrame] = None,
    *,
    output_file: Optional[Path] = None,
    orphan_file: Optional[Path] = None,
    agent_rules_dir: Optional[Path] = None,
    b2_corrections_dir: Optional[Path] = None,
) -> pd.DataFrame:
    """Build unified private markets holdings from BDC + N-PORT data.

    If DataFrames are not provided, reads from disk (BDC_HOLDINGS_FILE,
    NPORT_HOLDINGS_FILE).

    Parameters
    ----------
    output_file : Path, optional
        Write the unified CSV (and parquet companion) to this path instead
        of the default ``UNIFIED_HOLDINGS_FILE``.
    orphan_file : Path, optional
        Write orphan holdings to this path instead of beside the selected
        holdings output using ``UNIVERSE_ORPHAN_HOLDINGS_FILE.name``.
    agent_rules_dir, b2_corrections_dir : Path, optional
        Promoted agent-fix stores (gap 1). Default to the config stores
        (``AGENT_INVESTIGATE_RULES_DIR`` / ``AGENT_B2_CORRECTIONS_DIR``);
        fixture-based tests pass an empty directory so promoted production
        fixes never leak into fixtures that use real CIKs. Every application
        is audited to ``agent_fix_application_audit.csv`` next to the output.

    Returns the combined DataFrame and saves to *output_file* (or the
    default production path).
    """
    t0 = time.time()

    # Promoted agent fixes (gap 1): Layer B (raw-staging comparative filters) applies
    # inside BDC staging while the frame still carries XBRL `period`; Layer C
    # (investigator rules) applies at the tail. One code path for production, trial,
    # and rebuild_outputs -- parity by construction.
    from pipeline import agent_promoted
    _agent_fix_audits: list[dict] = []
    _raw_exclusions = agent_promoted.raw_staging_exclusions(
        agent_promoted.load_promoted_corrections(b2_corrections_dir))

    # Prepare BDC: prefer Parquet > CSV file path (DuckDB direct read)
    # over pandas DataFrame.  This bypasses the slow pandas CSV parse +
    # DuckDB registration path that was the main staging bottleneck.
    if bdc_df is None:
        bdc_file = (
            BDC_HOLDINGS_PARQUET_FILE
            if BDC_HOLDINGS_PARQUET_FILE.exists()
            else BDC_HOLDINGS_FILE
        )
        logger.info("Loading BDC holdings from %s (via DuckDB)", bdc_file.name)
        bdc_unified = staging_bdc._prepare_bdc(
            bdc_file=bdc_file, raw_exclusions=_raw_exclusions,
            raw_exclusion_audits=_agent_fix_audits)
    else:
        bdc_unified = staging_bdc._prepare_bdc(
            bdc_df=bdc_df, raw_exclusions=_raw_exclusions,
            raw_exclusion_audits=_agent_fix_audits)

    # Prepare N-PORT: same pattern -- file path for DuckDB direct read.
    nport_input: Union[pd.DataFrame, Path]
    if nport_df is None:
        nport_file = (
            NPORT_HOLDINGS_PARQUET_FILE
            if NPORT_HOLDINGS_PARQUET_FILE.exists()
            else NPORT_HOLDINGS_FILE
        )
        logger.info("Loading N-PORT holdings from %s (via DuckDB)", nport_file.name)
        nport_input = nport_file
    else:
        nport_input = nport_df
    nport_unified = staging_nport._prepare_nport(nport_input)
    for staged in (bdc_unified,nport_unified):
        for field,kind in FINANCIAL_ADDITIONS.items():
            if field not in staged:
                staged[field]=None if kind=='DOUBLE' else ''
    _out_file = output_file or UNIFIED_HOLDINGS_FILE
    _orphan_file = orphan_file or (_out_file.parent / UNIVERSE_ORPHAN_HOLDINGS_FILE.name)
    if bdc_unified.empty and nport_unified.empty:
        combined = _assign_row_ids(pd.DataFrame(columns=UNIFIED_COLUMNS))
        from pipeline.financial_finalization import prepare_artifact
        combined,_ = prepare_artifact(combined,_out_file.parent,source_frame=True)
        validate_final_holdings_schema(combined)
        _write_empty_orphan_report(_orphan_file)
        _out_file.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(_out_file, index=False)
        from pipeline.utils import write_parquet_companion
        write_parquet_companion(_out_file)
        logger.info("Unified holdings built with no eligible rows")
        return combined

    # Combine via DuckDB UNION ALL + index classification
    con = duckdb.connect()
    con.register("bdc_part", bdc_unified)
    con.register("nport_part", nport_unified)

    idx_case = classification._sql_classify_index()
    exposure_case = classification._sql_classify_exposure_type()
    asset_class_case = classification._sql_classify_asset_class()
    lien_case = lien_classification._sql_classify_lien()
    instr_case = instrument_classification._sql_classify_instrument_type()
    _special_cols = {
        "index_classification", "exposure_type", "asset_class", "lien_position",
        "instrument_type",
        "principal_amount", "principal_amount_usd", "principal_fx_status", "cusip",
    }
    col_list = ", ".join(c for c in UNIFIED_COLUMNS if c not in _special_cols)
    # Use explicit column list for UNION ALL to avoid positional mismatch
    union_cols = ", ".join(UNIFIED_COLUMNS)
    from pipeline.accounting_scope import scope_expression
    dedup_scope = scope_expression(
        'cik', 'bdc_dimensions_raw', 'is_subsidiary',
        "coalesce(nullif(CAST(src_context_id AS VARCHAR),''),"
        "nullif(CAST(nport_holding_id AS VARCHAR),''),'row:'||CAST(row_number() OVER () AS VARCHAR))",
    )

    from pipeline.staging_bdc import distinct_member_suffix_sql, shares_pow10_normalise_off_ciks
    member_suffix_key = distinct_member_suffix_sql(None, 'bdc_investment_identifier')
    # Funds whose wrapper keeps tagged unit counts as filed (dispatch.shares_pow10_normalise: false).
    pow10_off_sql = ", ".join("'%s'" % c for c in sorted(shares_pow10_normalise_off_ciks())) or "''"

    sql = f"""
    WITH nport_deduped AS (
        -- N-PORT within-source dedup: the same monthly filing can appear in
        -- adjacent quarterly bulk datasets (e.g. Nov-2021 in both 2021q4 and
        -- 2022q1 TSVs), and the same position can appear multiple times
        -- within a single filing.  Collapse these duplicates before
        -- cross-source dedup so the _source_count guard below only protects
        -- genuinely distinct positions (different CUSIPs/maturities/types).
        SELECT * EXCLUDE (_nport_rank) FROM (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, report_date,
                        regexp_replace(
                            lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        regexp_replace(
                            lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                        ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                        ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0),
                        COALESCE(CAST(maturity_date AS VARCHAR), ''),
                        COALESCE(CAST(nport_asset_cat AS VARCHAR), ''),
                        COALESCE(
                            NULLIF(NULLIF(NULLIF(CAST(cusip AS VARCHAR), ''),
                                         '000000000'), '999999999'),
                            ''
                        )
                ORDER BY
                    COALESCE(CAST(nport_quarter AS VARCHAR), '') DESC,
                    COALESCE(CAST(accession_number AS VARCHAR), '') DESC,
                    COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                    COALESCE(CAST(cusip AS VARCHAR), ''),
                    COALESCE(CAST(fair_value AS VARCHAR), ''),
                    COALESCE(CAST(cost AS VARCHAR), ''),
                    COALESCE(CAST(shares_held AS VARCHAR), ''),
                    COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                    COALESCE(CAST(accession_number AS VARCHAR), '')
                ) AS _nport_rank
            FROM nport_part
        ) sub
        WHERE _nport_rank = 1
    ),
    combined AS (
        SELECT {union_cols} FROM bdc_part
        UNION ALL
        SELECT {union_cols} FROM nport_deduped
    ),
    scoped_combined AS (
        SELECT *, {dedup_scope} AS _dedup_scope FROM combined
    ),
    -- Cross-source dedup: if the same holding appears in both BDC and N-PORT
    -- (same CIK + period + similar issuer name + similar fair_value),
    -- keep the BDC source row.  The _source_count guard preserves
    -- same-source groups (genuinely distinct positions that share the
    -- narrower cross-source key, e.g. different CUSIPs / maturities).
    deduped AS (
        SELECT *,
            COUNT(DISTINCT source) OVER (
                PARTITION BY cik, report_date, _dedup_scope,
                    regexp_replace(
                        lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    regexp_replace(
                        lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                    ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                    ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)
            ) AS _source_count,
            ROW_NUMBER() OVER (
                PARTITION BY cik, report_date, _dedup_scope,
                    regexp_replace(
                        lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    regexp_replace(
                        lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                    ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                    ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)
                ORDER BY
                    CASE WHEN source = 'bdc' THEN 0 ELSE 1 END,
                    COALESCE(CAST(accession_number AS VARCHAR), '') DESC,
                    COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                    COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                    COALESCE(CAST(cusip AS VARCHAR), ''),
                    COALESCE(CAST(fair_value AS VARCHAR), ''),
                    COALESCE(CAST(cost AS VARCHAR), ''),
                    COALESCE(CAST(shares_held AS VARCHAR), ''),
                    COALESCE(CAST(src_context_id AS VARCHAR), ''),
                    COALESCE(CAST(nport_holding_id AS VARCHAR), '')
            ) AS _dedup_rank
        FROM scoped_combined
    ),
    no_dupes AS (
        SELECT * FROM deduped WHERE _source_count = 1 OR _dedup_rank = 1
    ),
    -- D08: equal economics in a parent and an underlying schedule do not
    -- establish duplicate observations. Only deduplicate within a scope.
    -- BDC-only dimension-path dedup: same XBRL position can appear under
    -- multiple dimension paths with case/punctuation issuer variants and
    -- occasionally different cost values. Keep cost out of this key so the
    -- duplicate residue collapses without collapsing real tranches.
    bdc_dim_ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY cik, accession_number, report_date, _dedup_scope,
                    regexp_replace(
                        lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    regexp_replace(
                        lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                        '[^a-z0-9]+', ' ', 'g'
                    ),
                    ROUND(COALESCE(TRY_CAST(fair_value AS DOUBLE), 0), 0),
                    ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                    ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0),
                    {member_suffix_key}
                ORDER BY
                    LENGTH(COALESCE(CAST(issuer_name AS VARCHAR), '')),
                    COALESCE(CAST(issuer_name AS VARCHAR), ''),
                    COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                    COALESCE(CAST(accession_number AS VARCHAR), ''),
                    COALESCE(CAST(src_context_id AS VARCHAR), '')
            ) AS _dim_rank
        FROM no_dupes
        WHERE source = 'bdc'
    ),
    no_dim_dupes AS (
        SELECT * EXCLUDE (_dim_rank)
        FROM bdc_dim_ranked
        WHERE _dim_rank = 1
        UNION ALL
        SELECT *
        FROM no_dupes
        WHERE source != 'bdc'
    ),
    with_fund_text AS (
        SELECT *,
            COALESCE(lower(trim(issuer_name)), '') || ' ' ||
            COALESCE(lower(trim(instrument_description)), '') AS _combined_fund_text
        FROM no_dim_dupes
    ),
    classified AS (
        SELECT *,
            {idx_case} AS _index_class,
            {exposure_case} AS _exposure_type,
            {asset_class_case} AS _asset_class,
            -- Keyword classifier first; fall back to the iXBRL section-header lien
            -- (staging lien_position is populated ONLY by the reconciled iXBRL
            -- field-status overlay, so this is additive: it fills lien where the
            -- keyword rule is blank without overriding existing classifications).
            COALESCE(NULLIF(TRIM({lien_case}), ''), NULLIF(TRIM(lien_position), '')) AS _lien_raw,
            -- Instrument type from row text (keyword), falling back to any staged
            -- value. Applies to all rows; the keywords only fire on debt products.
            COALESCE(NULLIF(TRIM({instr_case}), ''), NULLIF(TRIM(instrument_type), '')) AS _instr_raw
        FROM with_fund_text
    ),
    -- Cost remains reported through matching. The finalizer computes labelled
    -- proxies only after the durable position registry establishes continuity.
    with_cost AS (SELECT * FROM classified),
    -- Shares normalization: detect power-of-10 unit mismatches within
    -- the same position (cik + issuer_name) by comparing each row's
    -- per-unit price (fair_value / shares_held) against the group median.
    -- Outliers are replaced with the nearest non-outlier shares value.
    -- The window ORDER BY terminates with anchor keys src_context_id /
    -- nport_holding_id for deterministic donor selection on ties.
    -- (Amended per tiebreak-hardening plan; prior byte-identical contract
    -- from the provenance migration is hereby superseded.)
    --
    -- Provenance: when the outlier flag fires, shares_held_source is set
    -- to 'derived_proxy' and 'shares_held:pow10_shares' is appended to
    -- src_transforms.  Non-outlier rows keep both columns unchanged.
    with_shares_fix AS (
        SELECT * EXCLUDE (shares_held, shares_held_source, src_transforms),
            CASE
                WHEN _is_outlier THEN COALESCE(
                    -- Nearest previous non-outlier shares
                    LAST_VALUE(CASE WHEN NOT _is_outlier THEN _sh_val END
                        IGNORE NULLS) OVER (
                        PARTITION BY cik, issuer_name
                        ORDER BY
                            report_date,
                            COALESCE(CAST(accession_number AS VARCHAR), ''),
                            COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                            COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                            COALESCE(CAST(_sh_val AS VARCHAR), ''),
                            COALESCE(CAST(src_context_id AS VARCHAR), ''),
                            COALESCE(CAST(nport_holding_id AS VARCHAR), '')
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
                    -- Nearest following non-outlier shares
                    FIRST_VALUE(CASE WHEN NOT _is_outlier THEN _sh_val END
                        IGNORE NULLS) OVER (
                        PARTITION BY cik, issuer_name
                        ORDER BY
                            report_date,
                            COALESCE(CAST(accession_number AS VARCHAR), ''),
                            COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                            COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                            COALESCE(CAST(_sh_val AS VARCHAR), ''),
                            COALESCE(CAST(src_context_id AS VARCHAR), ''),
                            COALESCE(CAST(nport_holding_id AS VARCHAR), '')
                        ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING)
                )
                ELSE _sh_val
            END AS shares_held,
            CASE WHEN _is_outlier THEN 'derived_proxy'
                 ELSE shares_held_source
            END AS shares_held_source,
            CASE WHEN _is_outlier
                 THEN concat_ws(';', NULLIF(src_transforms, ''), 'shares_held:pow10_shares')
                 ELSE src_transforms
            END AS src_transforms
        FROM (
            SELECT *,
                TRY_CAST(shares_held AS DOUBLE) AS _sh_val,
                TRY_CAST(fair_value AS DOUBLE) AS _fv_val,
                -- Median per-unit price across the group
                MEDIAN(
                    ABS(TRY_CAST(fair_value AS DOUBLE)
                        / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0))
                ) OVER (PARTITION BY cik, issuer_name)
                    AS _med_upx,
                -- Group size (only rows with valid shares)
                COUNT(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(shares_held AS DOUBLE) != 0
                           AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(fair_value AS DOUBLE) != 0
                      THEN 1 END
                ) OVER (PARTITION BY cik, issuer_name)
                    AS _sh_group_size,
                -- Outlier flag
                (TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                 AND TRY_CAST(shares_held AS DOUBLE) != 0
                 AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                 AND TRY_CAST(fair_value AS DOUBLE) != 0
                 AND lpad(CAST(cik AS VARCHAR), 10, '0') NOT IN ({pow10_off_sql})
                 AND COUNT(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                                AND TRY_CAST(shares_held AS DOUBLE) != 0
                                AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                                AND TRY_CAST(fair_value AS DOUBLE) != 0
                           THEN 1 END
                     ) OVER (PARTITION BY cik, issuer_name) >= 2
                 AND ABS(LOG10(NULLIF(
                     ABS(TRY_CAST(fair_value AS DOUBLE)
                         / TRY_CAST(shares_held AS DOUBLE))
                     / NULLIF(MEDIAN(
                         ABS(TRY_CAST(fair_value AS DOUBLE)
                             / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0))
                       ) OVER (PARTITION BY cik, issuer_name), 0)
                 , 0))) > 1.5
                ) AS _is_outlier
            FROM with_cost
        ) _sh_sub
    )
    SELECT
        {col_list},
        CASE WHEN COALESCE(CAST(cusip AS VARCHAR), '') IN ('999999999', '000000000', '00000000')
             THEN NULL ELSE cusip END AS cusip,
        CASE WHEN _index_class IN (
                 'COMMON_EQUITY', 'PREFERRED_EQUITY',
                 'PRIVATE_EQUITY_FUND', 'PRIVATE_CREDIT_FUND',
                 'REAL_ESTATE_FUND', 'HEDGE_FUND'
             ) THEN NULL ELSE principal_amount END AS principal_amount,
        CASE WHEN _index_class IN (
                 'COMMON_EQUITY', 'PREFERRED_EQUITY',
                 'PRIVATE_EQUITY_FUND', 'PRIVATE_CREDIT_FUND',
                 'REAL_ESTATE_FUND', 'HEDGE_FUND'
             ) THEN NULL ELSE principal_amount_usd END AS principal_amount_usd,
        CASE WHEN _index_class IN (
                 'COMMON_EQUITY', 'PREFERRED_EQUITY',
                 'PRIVATE_EQUITY_FUND', 'PRIVATE_CREDIT_FUND',
                 'REAL_ESTATE_FUND', 'HEDGE_FUND'
             ) THEN '' ELSE principal_fx_status END AS principal_fx_status,
        _index_class AS index_classification,
        _exposure_type AS exposure_type,
        _asset_class AS asset_class,
        CASE WHEN _index_class = 'DIRECT_LENDING' THEN _lien_raw
             ELSE NULL END AS lien_position,
        _instr_raw AS instrument_type
    FROM with_shares_fix
    """

    combined = con.execute(sql).fetchdf()

    # Diagnostic: count shares corrections
    try:
        shares_diag = con.execute(f"""
        WITH combined AS (
            SELECT * FROM bdc_part
            UNION ALL
            SELECT * FROM nport_part
        ),
        scoped_combined AS (
            SELECT *, {dedup_scope} AS _dedup_scope FROM combined
        ),
        deduped AS (
            SELECT *,
                COUNT(DISTINCT source) OVER (
                    PARTITION BY cik, report_date, _dedup_scope,
                        regexp_replace(
                            lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        regexp_replace(
                            lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                        ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                        ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)
                ) AS _source_count,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, report_date, _dedup_scope,
                        regexp_replace(
                            lower(trim(COALESCE(CAST(issuer_name AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        regexp_replace(
                            lower(trim(COALESCE(CAST(instrument_description AS VARCHAR), ''))),
                            '[^a-z0-9]+', ' ', 'g'
                        ),
                        ROUND(TRY_CAST(fair_value AS DOUBLE), -2),
                        ROUND(COALESCE(TRY_CAST(principal_amount AS DOUBLE), 0), 0),
                        ROUND(COALESCE(TRY_CAST(shares_held AS DOUBLE), 0), 0)
                    ORDER BY
                        CASE WHEN source = 'bdc' THEN 0 ELSE 1 END,
                        COALESCE(CAST(accession_number AS VARCHAR), '') DESC,
                        COALESCE(CAST(bdc_investment_identifier AS VARCHAR), ''),
                        COALESCE(CAST(nport_holding_id AS VARCHAR), ''),
                        COALESCE(CAST(cusip AS VARCHAR), ''),
                        COALESCE(CAST(fair_value AS VARCHAR), ''),
                        COALESCE(CAST(cost AS VARCHAR), ''),
                        COALESCE(CAST(shares_held AS VARCHAR), '')
                ) AS _dedup_rank
            FROM scoped_combined
        ),
        no_dupes AS (
            SELECT * FROM deduped WHERE _source_count = 1 OR _dedup_rank = 1
        ),
        _sh_check AS (
            SELECT
                TRY_CAST(shares_held AS DOUBLE) AS orig_sh,
                TRY_CAST(fair_value AS DOUBLE) AS fv,
                ABS(TRY_CAST(fair_value AS DOUBLE)
                    / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0)) AS _upx,
                MEDIAN(ABS(TRY_CAST(fair_value AS DOUBLE)
                    / NULLIF(TRY_CAST(shares_held AS DOUBLE), 0)))
                    OVER (PARTITION BY cik, issuer_name) AS _med_upx,
                COUNT(CASE WHEN TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(shares_held AS DOUBLE) != 0
                           AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                           AND TRY_CAST(fair_value AS DOUBLE) != 0
                      THEN 1 END) OVER (PARTITION BY cik, issuer_name) AS _grp
            FROM no_dupes
            WHERE TRY_CAST(shares_held AS DOUBLE) IS NOT NULL
              AND TRY_CAST(shares_held AS DOUBLE) != 0
              AND TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
              AND TRY_CAST(fair_value AS DOUBLE) != 0
              AND lpad(CAST(cik AS VARCHAR), 10, '0') NOT IN ({pow10_off_sql})
        )
        SELECT COUNT(*) AS n_corrected,
               COUNT(DISTINCT orig_sh) AS n_distinct
        FROM _sh_check
        WHERE _grp >= 2
          AND ABS(LOG10(_upx / NULLIF(_med_upx, 0))) > 1.5
        """).fetchone()
        if shares_diag and shares_diag[0] > 0:
            logger.info("  Shares normalization: corrected %d rows (%d distinct original values)",
                        shares_diag[0], shares_diag[1])
    except Exception:
        pass  # Diagnostic only, don't fail the pipeline

    con.close()

    # Ensure column order
    combined = combined[[c for c in UNIFIED_COLUMNS if c in combined.columns]]
    for col in UNIFIED_COLUMNS:
        if col not in combined.columns:
            combined[col] = ""
    combined = combined[UNIFIED_COLUMNS]

    pre_dedup = len(bdc_unified) + len(nport_unified)
    dedup_removed = pre_dedup - len(combined)
    logger.info("Combined: %d total rows (BDC %d + N-PORT %d, %d cross-source dupes removed)",
                len(combined), len(bdc_unified), len(nport_unified), dedup_removed)

    combined = _apply_universe_gate(combined, orphan_path=_orphan_file)

    # Log subsidiary stats
    if "is_subsidiary" in combined.columns:
        sub_count = (combined["is_subsidiary"].astype(str) == "1").sum()
        if sub_count > 0:
            logger.info("  Subsidiary positions: %d rows flagged (is_subsidiary=1)", sub_count)

    # Entity enrichment no longer happens here. This block used to LEFT JOIN
    # data/output/entity_lookup.csv -- an OUTPUT of the previous run -- so the
    # GICS canonical-name fallback made build N depend on build N-1
    # (2026-10-01 defect). See _resolve_entities_in_build, called just before
    # the GICS cache is applied.

    # Industry enrichment: join against identifier_extraction_lookup if available
    if IDENTIFIER_EXTRACTION_LOOKUP_FILE.exists() and not combined.empty:
        con3 = duckdb.connect()
        con3.register("holdings", combined)
        ilookup_str = str(IDENTIFIER_EXTRACTION_LOOKUP_FILE).replace("\\", "/")
        combined = con3.execute(f"""
            SELECT h.* EXCLUDE (extracted_industry),
                   CASE
                       WHEN (h.extracted_industry IS NULL
                             OR CAST(h.extracted_industry AS VARCHAR) = '')
                            AND e.extracted_industry IS NOT NULL
                            AND e.extracted_industry != ''
                            AND e.extracted_industry != 'None'
                       THEN e.extracted_industry
                       ELSE COALESCE(h.extracted_industry, '')
                   END AS extracted_industry
            FROM holdings h
            LEFT JOIN read_csv_auto('{ilookup_str}',
                          header=true, all_varchar=true) e
              ON CAST(h.bdc_investment_identifier AS VARCHAR)
               = CAST(e.bdc_investment_identifier AS VARCHAR)
        """).fetchdf()
        con3.close()
        combined = combined[UNIFIED_COLUMNS]
        ind_count = (combined["extracted_industry"] != "").sum()
        logger.info("Industry enrichment: %d/%d rows (%.1f%%) with extracted_industry",
                     ind_count, len(combined),
                     100 * ind_count / len(combined) if len(combined) else 0)

    # Classification stabilization: override QoQ flips where one class
    # has >= 2x the quarters of the second-most-frequent for same position.
    combined = _stabilize_classification(combined)
    combined = _restore_deterministic_classification_rules(combined)

    # Keep the reported NAV percentage unchanged. The financial contract adds
    # an independently supported calculated percentage in a separate field.

    # Class by printed schedule section, for the funds whose wrapper opts in
    # (dispatch.structured_credit_sections; pipeline/printed_sections.py). Before the row
    # corrections, so a correction still wins.
    from pipeline.printed_sections import apply_structured_sections
    combined = apply_structured_sections(combined)

    # Apply manual row corrections
    combined = _apply_row_corrections(combined)

    # Apply fund strategy correction candidates (if file exists on disk)
    combined = _apply_fund_strategy_corrections(combined)

    # Fund-level asset_class override for RE-strategy funds (runs last so it
    # catches everything the row-level correction system missed)
    combined = _apply_fund_strategy_asset_class_override(combined)

    # Promoted B2 stage-2 corrections (2026-08-13, gap-1 Layer B post-staging): the
    # non-comparative correction classes apply to the unified frame here, per CIK,
    # BDC rows only -- BEFORE Layer C rules so rules see corrected values. The
    # comparative_period_filter family already applied at raw staging above.
    _promoted_corrections = agent_promoted.load_promoted_corrections(b2_corrections_dir)

    # Promoted investigator rules (gap 1 Layer C): gate-PASS rules from the audited
    # override store, applied per CIK to BDC-source rows only. Runs after
    # classification (rule predicates reference unified-frame columns) and before the
    # write, so validation, position matching, and frontend export all see corrected
    # data -- no forked views.
    _promoted_rules = agent_promoted.load_promoted_rules(agent_rules_dir)
    if _promoted_rules or _promoted_corrections:
        combined, _plan_audits = agent_promoted.apply_promoted_plan(
            combined, _promoted_corrections, _promoted_rules)
        _agent_fix_audits.extend(_plan_audits)

    # A filer whose member puts the issuer in a moving segment (dispatch.issuer_from_identifier):
    # where the name as built is a label, a rate or a heading, read the issuer from the member text.
    from pipeline.staging_bdc import issuer_from_identifier_settings
    combined = _issuer_from_identifier(combined, issuer_from_identifier_settings())

    # The name as filed, kept for the GICS cache below: its entries were made from these names, and
    # a name the strips shorten would otherwise lose its label (dropped after the cache is applied).
    combined["_issuer_name_filed"] = combined["issuer_name"]
    # A filer's own trailing text on the issuer name (a row number), removed last so that the
    # duplicate filters, rules and corrections above still see the name as filed.
    from pipeline.staging_bdc import issuer_name_strip_patterns, issuer_name_strip_to_instrument_ciks
    combined = _strip_issuer_names(combined, issuer_name_strip_patterns(), issuer_name_strip_to_instrument_ciks())
    from pipeline.staging_bdc import instrument_description_strip_may_empty_ciks, instrument_description_strip_patterns
    combined = _strip_instrument_text(combined, instrument_description_strip_patterns(),
                                      instrument_description_strip_may_empty_ciks())
    # The shared default for every other filer ('Issuer, Instrument n'), after the per-fund settings
    # above; off until data/reference/issuer_instrument_split.json switches it on.
    from pipeline import issuer_instrument_split
    if issuer_instrument_split.enabled():
        combined = issuer_instrument_split.split_issuer_instrument(combined, issuer_instrument_split.opted_out_ciks())
        logger.info("Global issuer/instrument split applied")

    # Log cost proxy stats
    cost_filled = combined["cost"].notna() & (combined["cost"] != 0)
    logger.info("  Cost coverage: %d rows (%.1f%%)",
                cost_filled.sum(), 100 * cost_filled.sum() / len(combined) if len(combined) else 0)

    # Keep downstream position IDs stable across DuckDB/pandas incidental
    # ordering changes.  These columns identify source row identity before
    # returns populate position_id.
    sort_cols = [
        "source", "cik", "report_date", "filing_date", "accession_number",
        "bdc_investment_identifier", "nport_holding_id", "issuer_name",
        "instrument_description", "fair_value", "cost", "principal_amount",
        "shares_held",
    ]
    combined = combined.sort_values(
        [c for c in sort_cols if c in combined.columns],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)

    # Entity identity for THIS build, resolved from this frame's own issuer
    # names (never from a previous run's entity_lookup.csv). Must precede the
    # GICS cache, whose fallback keys on canonical_name.
    combined = _resolve_entities_in_build(combined)

    # Apply cached GICS classifications (if cache exists on disk)
    combined = _apply_gics_cache(combined)
    combined = combined.drop(columns=["_issuer_name_filed"], errors="ignore")
    # The filer's own industry for the row, where it maps to GICS, takes the place of the
    # name-keyed label above.
    combined = _apply_printed_industry(combined)

    # Apply cached lien position classifications (if cache exists on disk)
    combined = _apply_lien_cache(combined)
    # A filer that abbreviates the lien in its member ('NCNA Debt Inv. | FLSS | ...', Stepstone
    # 2026-06-30): dispatch.lien_from_identifier fills a blank lien from the member text.
    from pipeline.staging_bdc import lien_from_identifier_patterns
    combined = _lien_from_identifier(combined, lien_from_identifier_patterns())

    # Apply agent-reviewed unclassified reclassifications + JV flags
    combined = _apply_unclassified_cache(combined)

    # Override position_key with wrapper-generated keys for wrapped BDC CIKs
    combined = _apply_wrapper_position_keys(combined)

    # Remap GICS sub-industry for RE-strategy fund holdings (runs after
    # _apply_gics_cache so that the LLM-assigned codes are already in place)
    combined = _apply_re_fund_gics_overrides(combined)

    # Rebuild-time agent-fix audit: per-rule matched rows + FV deltas vs the rule's
    # authoring-time measured_impact. Written whenever any promoted store is non-empty
    # (drift there is the re-validation trigger; nothing promoted -> no artifact).
    if _raw_exclusions or _promoted_rules or _promoted_corrections:
        agent_promoted.write_application_audit(
            _agent_fix_audits, _out_file.parent / "agent_fix_application_audit.csv")

    # Rebuild-stable per-row identifier, computed on the FINAL frame (after all
    # correction/cache layers) so the id reflects the row as published.
    combined = _assign_row_ids(combined)
    from pipeline.financial_finalization import prepare_artifact
    combined,_ = prepare_artifact(combined,_out_file.parent,source_frame=True)
    from pipeline.accounting_scope import OUTPUT_COLUMNS as SCOPE_COLUMNS
    combined=combined[UNIFIED_COLUMNS+['row_id','row_id_basis']+list(SCOPE_COLUMNS)]

    validate_final_holdings_schema(combined)

    # Save CSV + Parquet companion
    _out_file.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(_out_file, index=False)
    logger.info("Saved to %s (%.1f MB)",
                _out_file.name,
                _out_file.stat().st_size / (1024 * 1024))
    from pipeline.utils import write_parquet_companion
    write_parquet_companion(_out_file)

    # Log summary statistics
    _log_summary(combined)

    elapsed = time.time() - t0
    logger.info("Unified holdings built in %.1f s", elapsed)

    return combined


def _assign_row_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Populate ``row_id`` and ``row_id_basis`` (appended, not in UNIFIED_COLUMNS).

    ``row_id`` = ``ROW-`` + first 16 hex chars of md5 over the row's source
    anchor when one exists (``row_id_basis='src_anchor'``):

        bdc:   source|accession_number|src_context_id
        nport: source|accession_number|nport_holding_id

    The anchor names the filing fact context (accessions are immutable), so
    the id survives rebuilds, staging reorders, value corrections, and parser
    fixes. It is an as-filed claim: an amendment (new accession) is a new id.
    Rows missing accession or the per-source anchor part fall back to the
    legacy drift-resistant natural key from
    ``position_id_registry.compute_natural_keys``
    (``row_id_basis='natural_key'``; content-sensitive by design).

    NOT a cross-quarter identity -- ``position_id`` owns that layer.
    """
    if df.empty:
        df["row_id"] = pd.Series(dtype=str)
        df["row_id_basis"] = pd.Series(dtype=str)
        return df
    from pipeline.position_id_registry import compute_natural_keys

    def _col(name: str) -> pd.Series:
        if name in df.columns:
            # astype(object) + where (not fillna): fillna("") on a masked integer
            # column (Int32/Int64 from DuckDB inference, NAs from appended
            # correction rows) raises TypeError -- '' is not a valid integer
            # (2026-08-30 mpa trial crash); object-fillna trips the pandas
            # downcasting FutureWarning.
            s = df[name].astype(object)
            return s.where(s.notna(), "").astype(str).str.strip()
        return pd.Series("", index=df.index, dtype=str)

    source = _col("source").str.lower()
    accession = _col("accession_number")
    anchor_part = _col("src_context_id").where(
        source.ne("nport"), _col("nport_holding_id"))
    has_anchor = accession.ne("") & anchor_part.ne("")

    keys = (source + "|" + accession + "|" + anchor_part).where(
        has_anchor, compute_natural_keys(df))
    # Reset to RangeIndex so rank_frame construction aligns by position, not
    # by the caller frame's (potentially non-contiguous) index labels.
    keys = keys.reset_index(drop=True)

    def _col_r(name: str) -> pd.Series:
        """Like _col but always RangeIndex-aligned (safe inside rank_frame)."""
        s = _col(name)
        return s.reset_index(drop=True)

    # Collision suffix: rows sharing an anchor key get content-ranked |dup<k>
    # suffixes (k>=1); rank 0 keeps the bare key so existing ids never change.
    # Content rank (not frame order) keeps the ids rebuild-stable.
    #
    # For each content column we add a null-indicator (0=value present,
    # 1=null/empty) sorted BEFORE the stringified value so that null rows
    # always rank LAST within a collision group.
    def _null_ind(series: pd.Series) -> pd.Series:
        """Return 0 where series has a non-empty value, 1 where null/empty."""
        return series.eq("").astype("int8")

    fv = _col_r("fair_value")
    cost = _col_r("cost")
    pa = _col_r("principal_amount")
    sh = _col_r("shares_held")
    bid = _col_r("bdc_investment_identifier")
    rank_frame = pd.DataFrame({
        "k": keys,
        "_fv_null": _null_ind(fv),   "_fv": fv,
        "_co_null": _null_ind(cost),  "_cost": cost,
        "_pa_null": _null_ind(pa),    "_pa": pa,
        "_sh_null": _null_ind(sh),    "_sh": sh,
        "_bi_null": _null_ind(bid),   "_bid": bid,
    })
    dup_rank = (
        rank_frame
        .sort_values(
            ["k", "_fv_null", "_fv",
             "_co_null", "_cost",
             "_pa_null", "_pa",
             "_sh_null", "_sh",
             "_bi_null", "_bid"],
            kind="mergesort",
        )
        .groupby("k")          # sort=True (default) -- stable re-sort on key only
        .cumcount()
        .reindex(rank_frame.index)
    )
    keys = keys.where(dup_rank == 0, keys + "|dup" + dup_rank.astype(str))

    con = duckdb.connect()
    con.register("nk", pd.DataFrame({"i": range(len(keys)), "k": keys}))
    hashed = con.execute(
        "SELECT 'ROW-' || substr(md5(k), 1, 16) AS row_id FROM nk ORDER BY i"
    ).fetchdf()["row_id"]
    df["row_id"] = hashed.values
    df["row_id_basis"] = has_anchor.map(
        {True: "src_anchor", False: "natural_key"}).values
    n_anchor = int(has_anchor.sum())
    n_dup = int(df["row_id"].duplicated().sum())
    if n_dup:
        logger.warning(
            "row_id uniqueness violated on %d rows after "
            "collision suffixing -- investigate", n_dup)
    logger.info("row_id: %d assigned (%d src_anchor, %d natural_key)",
                len(df), n_anchor, len(df) - n_anchor)
    return df


def _apply_fund_strategy_corrections(
    df: pd.DataFrame,
    candidates_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Apply fund strategy correction candidates from disk (if file exists).

    Loads the correction candidates CSV, delegates to
    ``fund_strategy_validation.apply_fund_strategy_correction_candidates``
    which handles APPLY filtering, excluded-transition guards, and DuckDB join.

    When a per-pass PINNED copy exists (written by the run_quarter_pass pin stage),
    it takes precedence over the live file: the validate stage regenerates the live
    candidates from CURRENT holdings, so consuming them directly feeds validation
    output back into the next rebuild and oscillates marginal classifications
    (~20 non-corrected CIKs, 2026-08-13 known residual). The pin freezes the
    inputs for the whole pass round.
    """
    path = candidates_path
    if path is None:
        path = (FUND_STRATEGY_CORRECTION_CANDIDATES_PINNED_FILE
                if FUND_STRATEGY_CORRECTION_CANDIDATES_PINNED_FILE.exists()
                else FUND_STRATEGY_CORRECTION_CANDIDATES_FILE)
    if not path.exists():
        return df

    from pipeline.fund_strategy_validation import (
        apply_fund_strategy_correction_candidates,
    )

    candidates = pd.read_csv(path, dtype=str).fillna("")
    if candidates.empty:
        return df

    logger.info(
        "Applying fund strategy corrections from %s (%d candidate rows)",
        path.name,
        len(candidates),
    )
    return apply_fund_strategy_correction_candidates(df, candidates)


# Asset classes that should NOT be overridden by the fund-level RE strategy.
_RE_OVERRIDE_BLOCKED_ASSET_CLASSES = frozenset({"CASH", "STRUCTURED_CREDIT", "HEDGE_FUND"})


def _apply_fund_strategy_asset_class_override(
    df: pd.DataFrame,
    reference_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Override asset_class to REAL_ESTATE for all holdings in RE-strategy funds.

    The row-level classification system assigns asset_class based on instrument
    type (loans -> PRIVATE_CREDIT, equity -> PRIVATE_EQUITY) without considering
    the underlying collateral.  Real estate mortgage loans, mezzanine loans, and
    property SPV equity are indistinguishable from corporate credit/equity at the
    row level.

    This fund-level override sets asset_class='REAL_ESTATE' for all positions in
    funds whose strategy is REAL_ESTATE, except positions with asset_class in
    {CASH, STRUCTURED_CREDIT, HEDGE_FUND} which are explicitly blocked.

    index_classification and exposure_type are left unchanged -- the instrument
    type is correct, only the asset_class dimension needs the fund-level signal.
    """
    path = reference_path or FUND_STRATEGY_REFERENCE_FILE
    if not path.exists():
        logger.info("Fund strategy asset_class override: no reference file, skipping")
        return df

    if df.empty:
        return df

    ref = pd.read_csv(path, dtype=str).fillna("")
    if ref.empty or "strategy" not in ref.columns or "cik" not in ref.columns:
        return df

    re_ciks = set(
        ref.loc[ref["strategy"] == "REAL_ESTATE", "cik"]
        .str.strip()
        .str.zfill(10)
    )
    if not re_ciks:
        return df

    blocked = _RE_OVERRIDE_BLOCKED_ASSET_CLASSES
    norm_cik = df["cik"].astype(str).str.strip().str.zfill(10)
    mask = norm_cik.isin(re_ciks) & ~df["asset_class"].isin(blocked)

    n_affected = mask.sum()
    if n_affected == 0:
        logger.info("Fund strategy asset_class override: 0 rows matched RE-strategy CIKs")
        return df

    # Log breakdown by previous asset_class
    prev_classes = df.loc[mask, "asset_class"].value_counts()
    fv_affected = pd.to_numeric(df.loc[mask, "fair_value"], errors="coerce").sum()
    logger.info(
        "Fund strategy asset_class override: %d rows (FV $%.1fB) across %d RE-strategy CIKs",
        n_affected,
        fv_affected / 1e9 if pd.notna(fv_affected) else 0,
        norm_cik[mask].nunique(),
    )
    for cls, count in prev_classes.items():
        if cls != "REAL_ESTATE":
            logger.info("  %s -> REAL_ESTATE: %d rows", cls, count)

    df.loc[mask, "asset_class"] = "REAL_ESTATE"

    return df


# GICS sub-industry remapping for holdings in RE-strategy funds.
# The LLM classifier assigns GICS based on issuer name without fund context,
# so e.g. "BX Trust 2022-GPA" (a CMBS trust) gets "Asset Management & Custody
# Banks" instead of a mortgage-finance code.  These 11 rules correct the most
# common misclassifications (693 rows, $33.6B FV).
_RE_FUND_GICS_REMAP = {
    "Diversified Financial Services": "Diversified Real Estate Activities",
    "Publishing": "Diversified Real Estate Activities",
    "Industrial Conglomerates": "Industrial REITs",
    "Diversified Support Services": "Industrial REITs",
    "Asset Management & Custody Banks": "Commercial & Residential Mortgage Finance",
    "Health Care Facilities": "Health Care REITs",
    "Health Care Equipment": "Health Care REITs",
    "Agricultural Products & Services": "Diversified Real Estate Activities",
    "Air Freight & Logistics": "Industrial REITs",
    "Health Care Services": "Health Care REITs",
    "Data Processing & Outsourced Services": "Data Center REITs",
}


def _apply_wrapper_position_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Override position_key with wrapper-generated keys for wrapped BDC CIKs.

    For BDC rows where the wrapper classifies the identifier as a position
    leaf and produces a non-empty ``wrapper_position_key``, replace the
    generic staging ``position_key`` with the wrapper's per-CIK curated key.
    The wrapper applies CIK-specific rules (``canonical_strip_re``,
    ``identifier_format``, etc.) that the one-size-fits-all staging SQL
    cannot.  Non-wrapped CIKs and N-PORT rows are unaffected.
    """
    from pipeline.bdc_xbrl_wrapper import add_bdc_xbrl_wrapper_columns

    if df.empty or "source" not in df.columns:
        return df

    bdc_mask = df["source"].eq("bdc")
    if not bdc_mask.any() or "bdc_investment_identifier" not in df.columns:
        return df

    bdc_rows = df.loc[bdc_mask].copy()
    wrapped = add_bdc_xbrl_wrapper_columns(
        bdc_rows,
        identifier_col="bdc_investment_identifier",
        cik_col="cik",
    )

    # Only override where wrapper produced a position leaf with a key
    has_key = (
        wrapped["wrapper_position_key"].ne("")
        & wrapped["wrapper_disposition"].str.endswith("_position_leaf", na=False)
    )
    override_count = has_key.sum()
    if override_count > 0:
        df.loc[has_key[has_key].index, "position_key"] = (
            wrapped.loc[has_key, "wrapper_position_key"]
        )
        df = _append_duplicate_wrapper_lot_keys(df, has_key[has_key].index)
        logger.info(
            "  Wrapper position_key override: %d rows across %d CIKs",
            override_count,
            df.loc[has_key[has_key].index, "cik"].nunique(),
        )
    return df


def _append_duplicate_wrapper_lot_keys(
    df: pd.DataFrame,
    candidate_index: pd.Index,
) -> pd.DataFrame:
    """Append deterministic lot suffixes for repeated wrapper keys.

    Some BDC XBRL schedules disclose multiple separate rows with the same
    issuer, spread, and maturity. For configured CIKs, keep those rows as
    separate position-level constituents by ranking repeated wrapper keys
    within a CIK/source/report-date group. The suffix is applied only to keys
    that would otherwise repeat in that quarter.
    """
    required = {
        "cik", "source", "report_date", "position_key",
        "principal_amount", "fair_value", "cost",
    }
    if df.empty or not required.issubset(df.columns):
        return df

    cik_norm = (
        df["cik"].astype(str)
        .str.replace(r"[^0-9]", "", regex=True)
        .str.zfill(10)
    )
    candidate_mask = df.index.isin(candidate_index)
    scoped = (
        candidate_mask
        & cik_norm.isin(WRAPPER_DUPLICATE_LOT_KEY_CIKS)
        & df["position_key"].astype(str).ne("")
    )
    if not scoped.any():
        return df

    key_cols = ["cik", "source", "report_date", "position_key"]
    group_sizes = df.loc[scoped].groupby(key_cols, dropna=False)["position_key"].transform("size")
    duplicate_index = group_sizes[group_sizes.gt(1)].index
    if len(duplicate_index) == 0:
        return df

    anchor_cols = [c for c in ("src_context_id", "nport_holding_id") if c in df.columns]
    work = df.loc[
        duplicate_index,
        key_cols + ["principal_amount", "fair_value", "cost"] + anchor_cols,
    ].copy()
    work["_principal_abs"] = pd.to_numeric(work["principal_amount"], errors="coerce").abs().fillna(-1)
    work["_fair_value_abs"] = pd.to_numeric(work["fair_value"], errors="coerce").abs().fillna(-1)
    work["_cost_abs"] = pd.to_numeric(work["cost"], errors="coerce").abs().fillna(-1)
    # S19 tie-break: when principal/fv/cost are all tied, break by a stable
    # source anchor (src_context_id, then nport_holding_id) BEFORE falling back
    # to physical frame order. _source_index stays as the true last resort so
    # rows with no anchor at all remain deterministically ranked.
    if "src_context_id" in work.columns:
        _anchor = work["src_context_id"].fillna("").astype(str)
    else:
        _anchor = pd.Series("", index=work.index, dtype=object)
    if "nport_holding_id" in work.columns:
        _anchor = _anchor.where(_anchor != "", work["nport_holding_id"].fillna("").astype(str))
    work["_anchor"] = _anchor
    work["_source_index"] = range(len(work))
    work = work.sort_values(
        key_cols + ["_principal_abs", "_fair_value_abs", "_cost_abs", "_anchor", "_source_index"],
        ascending=[True, True, True, True, False, False, False, True, True],
        kind="mergesort",
    )
    work["_lot_rank"] = work.groupby(key_cols, dropna=False).cumcount() + 1
    suffix = " lot " + work["_lot_rank"].astype(str)
    df.loc[work.index, "position_key"] = df.loc[work.index, "position_key"].astype(str) + suffix
    return df


def _apply_re_fund_gics_overrides(
    df: pd.DataFrame,
    reference_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Override GICS sub-industry for holdings in RE-strategy funds.

    The LLM GICS classifier assigns codes based on issuer name without fund
    context.  For RE-strategy funds, many holdings have misleading names
    (e.g. "Industrial - Lambert Farms" -> "Industrial Conglomerates" when it
    is actually a warehouse property).  This remaps the 11 most common
    misclassified GICS sub-industries to their correct RE-sector equivalents.

    Only applies to holdings where:
    - The fund CIK is in the RE-strategy set (from fund_strategy_reference.csv)
    - The current gics_sub_industry matches one of the 11 remapping rules
    """
    path = reference_path or FUND_STRATEGY_REFERENCE_FILE
    if not path.exists():
        logger.info("RE fund GICS override: no reference file, skipping")
        return df

    if df.empty:
        return df

    ref = pd.read_csv(path, dtype=str).fillna("")
    if ref.empty or "strategy" not in ref.columns or "cik" not in ref.columns:
        return df

    re_ciks = set(
        ref.loc[ref["strategy"] == "REAL_ESTATE", "cik"]
        .str.strip()
        .str.zfill(10)
    )
    if not re_ciks:
        return df

    norm_cik = df["cik"].astype(str).str.strip().str.zfill(10)
    gics_col = df.get("gics_sub_industry")
    if gics_col is None:
        return df

    mask = norm_cik.isin(re_ciks) & gics_col.isin(_RE_FUND_GICS_REMAP)

    n_affected = mask.sum()
    if n_affected == 0:
        logger.info("RE fund GICS override: 0 rows matched")
        return df

    # Log breakdown by old -> new GICS
    old_gics = df.loc[mask, "gics_sub_industry"].value_counts()
    fv_affected = pd.to_numeric(df.loc[mask, "fair_value"], errors="coerce").sum()
    logger.info(
        "RE fund GICS override: %d rows (FV $%.1fB) remapped",
        n_affected,
        fv_affected / 1e9 if pd.notna(fv_affected) else 0,
    )
    for old_val, count in old_gics.items():
        new_val = _RE_FUND_GICS_REMAP[old_val]
        logger.info("  %s -> %s: %d rows", old_val, new_val, count)

    df.loc[mask, "gics_sub_industry"] = df.loc[mask, "gics_sub_industry"].map(
        _RE_FUND_GICS_REMAP
    )

    return df


def _lien_from_identifier(combined: pd.DataFrame, patterns: dict[str, dict[str, str]]) -> pd.DataFrame:
    """Fill a blank lien_position from the member text for one filer (dispatch.lien_from_identifier:
    {lien value: regex}). Loan rows only; a lien already set is never changed. One fund's rows only."""
    if not patterns or not {"lien_position", "bdc_investment_identifier", "cik"} <= set(combined.columns):
        return combined
    for cik, by_lien in patterns.items():
        rows = (combined["source"] == "bdc") & (_normalize_cik_series(combined["cik"]) == cik)
        rows &= combined["lien_position"].astype("string").fillna("").str.strip() == ""
        if "asset_category" in combined.columns:
            rows &= combined["asset_category"].astype("string").fillna("") == "LOAN"
        if not rows.any():
            continue
        member = combined.loc[rows, "bdc_investment_identifier"].astype("string").fillna("")
        filled = pd.Series(False, index=member.index)
        for lien, pattern in by_lien.items():
            hit = member.str.contains(pattern, regex=True).fillna(False) & ~filled
            if hit.any():
                combined.loc[hit[hit].index, "lien_position"] = lien
                filled |= hit
        if filled.any():
            logger.info("  Lien read from the member text: %d rows for %s", int(filled.sum()), cik)
    return combined


def _issuer_from_identifier(combined: pd.DataFrame, settings: dict[str, dict]) -> pd.DataFrame:
    """Re-read issuer_name from the member text for one filer's rows whose name is not an issuer
    (dispatch.issuer_from_identifier). Only rows whose issuer_name matches ``when_issuer_re`` are
    touched; the first pattern that matches the identifier with a lettered group 1 wins. A row no
    pattern reads keeps its name. One fund's rows only.
    """
    if not settings or not {"issuer_name", "bdc_investment_identifier", "cik"} <= set(combined.columns):
        return combined
    for cik, setting in settings.items():
        rows = (combined["source"] == "bdc") & (_normalize_cik_series(combined["cik"]) == cik)
        if not rows.any():
            continue
        names = combined.loc[rows, "issuer_name"].astype("string").fillna("")
        hit = names.str.contains(setting["when_issuer_re"], regex=True).fillna(False)
        if not hit.any():
            continue
        member = combined.loc[hit[hit].index, "bdc_investment_identifier"].astype("string").fillna("")
        found = pd.Series(pd.NA, index=member.index, dtype="string")
        for pattern in setting["patterns"]:
            todo = found.isna()
            if not todo.any():
                break
            got = member[todo].str.extract(pattern, expand=True)[0].astype("string").str.strip()
            # a catch that is itself a label (another moving segment) is not taken
            got = got.where(got.str.contains("[A-Za-z]", regex=True).fillna(False)
                            & ~got.str.contains(setting["when_issuer_re"], regex=True).fillna(False))
            found.loc[got.dropna().index] = got.dropna()
        found = found.dropna()
        if len(found):
            combined.loc[found.index, "issuer_name"] = found.values
            logger.info("  Issuer read from the member text: %d of %d label-named rows for %s", len(found), int(hit.sum()), cik)
    return combined


def _strip_issuer_names(combined: pd.DataFrame, patterns: dict[str, str],
                        to_instrument: set[str] | frozenset[str] = frozenset()) -> pd.DataFrame:
    """Remove a filer's own trailing text from issuer_name (dispatch.issuer_name_strip_re), per CIK.

    A name the pattern would empty is left as filed. For a CIK in ``to_instrument``
    (dispatch.issuer_name_strip_to_instrument) the removed text becomes the row's
    instrument_description where that is blank and the text holds a letter: Monroe's member is
    'issuer, Senior Secured Loans (Delayed Draw) 1' with no separate instrument, and two undrawn
    lines of one issuer are otherwise told apart only by the identifier. One fund's rows only.
    """
    for cik, pattern in patterns.items():
        rows = (combined["source"] == "bdc") & (_normalize_cik_series(combined["cik"]) == cik)
        if not rows.any():
            continue
        filed = combined.loc[rows, "issuer_name"].astype("string")
        stripped = filed.str.replace(pattern, "", regex=True)
        stripped = stripped.where(stripped.str.strip().fillna("") != "", filed)
        combined.loc[rows, "issuer_name"] = stripped
        if cik in to_instrument and "instrument_description" in combined.columns:
            removed = pd.Series(
                [f[len(s):] if isinstance(f, str) and isinstance(s, str) and f.startswith(s) else "" for f, s in zip(filed, stripped)],
                index=filed.index, dtype="string").str.replace("^[\\s,|.\\-\\u2013\\u2014]+|\\s+$", "", regex=True)
            current = combined.loc[rows, "instrument_description"].astype("string").fillna("").str.strip()
            lettered = removed.str.contains("[A-Za-z]", regex=True).fillna(False)
            fill = (current == "") & lettered
            if fill.any():
                combined.loc[fill[fill].index, "instrument_description"] = removed[fill]
            # Where the member already gave an instrument (its rate and maturity text), the tranche
            # words taken off the name are put in front of it, unless it already holds them.
            holds = pd.Series([r.lower() in c.lower() for r, c in zip(removed.fillna(""), current)], index=current.index)
            front = (current != "") & lettered & ~holds
            if front.any():
                combined.loc[front[front].index, "instrument_description"] = (removed[front] + " " + current[front]).values
    return combined


def _strip_instrument_text(combined: pd.DataFrame, patterns: dict[str, str],
                           may_empty: set[str] | frozenset[str] = frozenset()) -> pd.DataFrame:
    """Remove a filer's own header words from instrument_description (dispatch.instrument_description_strip_re).

    Every match is removed and the ends trimmed. Text the pattern would empty is left as filed,
    unless the fund is in ``may_empty`` (dispatch.instrument_description_strip_may_empty), where
    the text is not an instrument at all and becomes blank. One fund's rows only.
    """
    if "instrument_description" not in combined.columns:
        return combined
    for cik, pattern in patterns.items():
        rows = (combined["source"] == "bdc") & (_normalize_cik_series(combined["cik"]) == cik)
        if not rows.any():
            continue
        filed = combined.loc[rows, "instrument_description"].astype("string")
        stripped = filed.str.replace(pattern, "", regex=True).str.strip()
        if cik in may_empty:
            stripped = stripped.where(stripped.fillna("") != "", pd.NA)
        else:
            stripped = stripped.where(stripped.fillna("") != "", filed)
        combined.loc[rows, "instrument_description"] = stripped
    return combined


# Fields that row_corrections.csv is allowed to override.
_CORRECTABLE_FIELDS = frozenset({
    "fair_value", "cost", "principal_amount", "principal_amount_usd",
    "principal_amount_currency", "principal_fx_rate_to_usd", "principal_fx_status",
    "interest_rate", "basis_spread", "pik_rate", "shares_held",
    "index_classification", "exposure_type", "asset_class",
    # A class correction has to move the category with the index class (2026-10-06, decision D-021).
    "asset_category", "issuer_category",
    "issuer_name", "instrument_description",
    # An exact-key correction may restore the printed industry when a filer attaches
    # another company's member to the row. The existing downstream GICS mapping
    # consumes this source label; no derived GICS label is directly overridden.
    "extracted_industry",
    # A cost corrected from the printed page needs its unit corrected with it: a cost whose
    # unit is not the dollar is withheld downstream (2026-10-08, Blue Owl KWOR, decision D-046).
    "cost_currency",
    # A reference rate guessed for a row whose printed line carries no rate is withdrawn with the
    # rate (2026-10-08, Ares UP Intermediate revolver, decision D-053).
    "reference_rate_type", "reference_rate_source", "coupon_type",
    # A maturity the page reading or the filer's member has wrong, where the other one and the
    # printed row agree (2026-10-09, Goldman Sachs 123Dentist and Sixth Street Price Fx, D-074).
    "maturity_date",
    # What a filed rate holds, where the row's own printed line settles it and the tag does not:
    # 'cash' (the cash leg, PIK on top) or 'all_in' (the whole coupon). The financial step reads
    # an explicit kind before any tag or fund-level reading (2026-10-14, Monroe Bandas Law Firm:
    # printed '4.00 % Cash/ 13.75 % PIK', tagged with the plain rate concept and a PIK rate).
    "interest_rate_kind",
    # A position the printed schedule marks with the filer's non-accrual footnote where the XBRL
    # footnote link is missing or points at the comparative date's note (2026-10-17, Crescent
    # Seko/TriStrux/Action Signature: printed '(9)' = 'on non-accrual status as of <date>').
    # Only 'true' or 'false'; the financial step derives nonaccrual_status from it.
    "nonaccrual_footnote",
    # The precision of a maturity a correction sets from the printed line ('8/31/2029' is a day). The
    # financial step reads an explicit precision first; without it a corrected date with no source
    # tag published maturity_status 'unresolved' (2026-10-18, BCRED 2022-09-30 shifted members).
    # Only 'day', 'month' or 'year'.
    "maturity_precision",
})

_CORRECTABLE_PRECISIONS = frozenset({"day", "month", "year"})

# The only kinds a row correction may state; anything else is skipped with a warning.
_CORRECTABLE_RATE_KINDS = frozenset({"cash", "all_in"})
_CORRECTABLE_BOOLEANS = {"true": True, "false": False}


def _same_kind_as_column(column: pd.Series, flag: bool):
    """A corrected flag in the representation the column already uses (bool, 0/1 number or text)."""
    import numpy as np
    present = column.dropna()
    present = present[present.astype(str).str.strip() != ""]
    if present.empty:
        return flag
    sample = present.iloc[0]
    if isinstance(sample, (bool, np.bool_)):
        return flag
    if isinstance(sample, (int, np.integer)):
        return int(flag)
    if isinstance(sample, (float, np.floating)):
        return float(flag)
    text = str(sample)
    return ("TRUE" if flag else "FALSE") if text.isupper() else ("true" if flag else "false") if text.islower() else str(flag)

# Required columns in row_corrections.csv.
_CORRECTIONS_REQUIRED_COLS = {
    "cik", "report_date", "accession_number",
    "bdc_investment_identifier", "field", "value",
    "reason", "source_evidence", "author", "date_added",
}


def _apply_row_corrections(
    df: pd.DataFrame,
    corrections_path: Optional[Path] = None,
    context_corrections_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Apply manual row-level corrections from an override CSV.

    Each row in the corrections file identifies one (row, field) to patch.
    Match key: (cik, report_date, accession_number, bdc_investment_identifier).

    A second file (``row_corrections_by_context.csv``, same columns plus ``src_context_id``)
    narrows the key to one XBRL context: a filer can repeat an identifier in one filing, for its
    own line and for a joint venture's line (BCRED 2022-09-30 'Smile Doctors, LLC', 41.7M on
    the fund's schedule, 120.5M on the JV's), and only one of them is wrong. The default file is
    read only when ``corrections_path`` is not given (tests pass their own).

    Returns the dataframe with corrections applied.  Logs every correction
    applied and warns on unmatched correction rows.
    """
    path = corrections_path or ROW_CORRECTIONS_FILE
    ctx_path = context_corrections_path or (ROW_CORRECTIONS_BY_CONTEXT_FILE if corrections_path is None else None)
    has_ctx = ctx_path is not None and ctx_path.exists()
    if not path.exists() and not has_ctx:
        return df

    corrections = pd.read_csv(path, dtype=str).fillna("") if path.exists() else pd.DataFrame(
        columns=sorted(_CORRECTIONS_REQUIRED_COLS))
    if has_ctx:
        by_context = pd.read_csv(ctx_path, dtype=str).fillna("")
        if "src_context_id" not in by_context.columns:
            logger.warning("%s has no src_context_id column -- skipping", ctx_path.name)
        else:
            by_context = by_context[by_context["src_context_id"].str.strip() != ""]
            corrections = pd.concat([corrections, by_context], ignore_index=True).fillna("")
    if "src_context_id" not in corrections.columns:
        corrections["src_context_id"] = ""

    # --- Schema validation ---------------------------------------------------
    missing_cols = _CORRECTIONS_REQUIRED_COLS - set(corrections.columns)
    if missing_cols:
        logger.warning(
            "row_corrections.csv missing required columns: %s -- skipping",
            ", ".join(sorted(missing_cols)),
        )
        return df

    if corrections.empty:
        return df

    bad_fields = set(corrections["field"].unique()) - _CORRECTABLE_FIELDS
    if bad_fields:
        logger.warning(
            "row_corrections.csv contains uncorrectable field(s): %s -- "
            "these rows will be skipped",
            ", ".join(sorted(bad_fields)),
        )
        corrections = corrections[corrections["field"].isin(_CORRECTABLE_FIELDS)]

    if corrections.empty:
        return df

    # --- Normalize match keys ------------------------------------------------
    # Pad CIK to 10 digits to match unified holdings format.
    corrections["cik"] = corrections["cik"].str.strip().str.zfill(10)

    # Build a match key in the unified dataframe.
    key_cols = ["cik", "report_date", "accession_number",
                "bdc_investment_identifier"]
    df["_corr_key"] = (
        df["cik"].astype(str).str.strip().str.zfill(10) + "|"
        + df["report_date"].astype(str).str.strip() + "|"
        + df["accession_number"].astype(str).str.strip() + "|"
        + df["bdc_investment_identifier"].astype(str).str.strip()
    )

    corrections["_corr_key"] = (
        corrections["cik"] + "|"
        + corrections["report_date"].str.strip() + "|"
        + corrections["accession_number"].str.strip() + "|"
        + corrections["bdc_investment_identifier"].str.strip()
    )

    # --- Apply corrections ---------------------------------------------------
    n_applied = 0
    n_unmatched = 0

    # Group corrections by key for efficient lookup.
    corr_by_key: dict[str, list[tuple[str, str, str, str]]] = {}
    for _, row in corrections.iterrows():
        corr_by_key.setdefault(row["_corr_key"], []).append(
            (row["field"], row["value"], row["reason"], str(row["src_context_id"]).strip())
        )

    # Build a set of keys present in the dataframe for fast membership test.
    df_keys = set(df["_corr_key"])

    for key, patches in corr_by_key.items():
        if key not in df_keys:
            for field, value, reason, _ctx in patches:
                logger.warning(
                    "Row correction unmatched: field=%s reason=%r key=%s",
                    field, reason, key,
                )
            n_unmatched += len(patches)
            continue

        key_mask = df["_corr_key"] == key
        if not all(ctx for *_rest, ctx in patches) and key_mask.sum() > 1:
            logger.warning(
                "Row correction matches %d rows (expected 1): key=%s -- "
                "applying to all matches",
                key_mask.sum(), key,
            )

        for field, value, reason, ctx in patches:
            mask = key_mask
            if ctx:
                mask = key_mask & (df["src_context_id"].astype(str).str.strip() == ctx)
                if not mask.any():
                    logger.warning(
                        "Row correction unmatched: field=%s reason=%r key=%s context=%s",
                        field, reason, key, ctx,
                    )
                    n_unmatched += 1
                    continue
            # An empty value withdraws the field. It is stored as a missing value, not as empty
            # text: later steps cast these columns to numbers.
            if pd.isna(value) or str(value).strip() == "":
                value = None
            if field == "interest_rate_kind" and value is not None and str(value).strip() not in _CORRECTABLE_RATE_KINDS:
                logger.warning(
                    "Row correction skipped: interest_rate_kind must be cash or all_in, got %r key=%s",
                    value, key,
                )
                continue
            if field == "maturity_precision" and value is not None and str(value).strip() not in _CORRECTABLE_PRECISIONS:
                logger.warning(
                    "Row correction skipped: maturity_precision must be day, month or year, got %r key=%s",
                    value, key,
                )
                continue
            if field == "nonaccrual_footnote":
                flag =_CORRECTABLE_BOOLEANS.get(str(value).strip().lower()) if value is not None else None
                if flag is None:
                    logger.warning(
                        "Row correction skipped: nonaccrual_footnote must be true or false, got %r key=%s",
                        value, key,
                    )
                    continue
                # Keep the column's own representation: the combined frame can carry the flag as
                # 0/1 integers or as text, and a mixed object column breaks later DuckDB scans
                # (2026-10-17 sandbox ccza: 'Type BOOLEAN does not match with INTEGER').
                value = _same_kind_as_column(df[field], flag)
            df.loc[mask, field] = value
            if "corrected_fields" in df.columns:
                from pipeline.agent_promoted import append_corrected_fields
                append_corrected_fields(df, df.index[mask], [field])
            n_applied += 1
            logger.info(
                "Row correction applied: field=%s value=%s reason=%r key=%s%s",
                field, value, reason, key, (" context=" + ctx) if ctx else "",
            )

    df.drop(columns=["_corr_key"], inplace=True)

    logger.info(
        "Row corrections: %d applied, %d unmatched (from %s)",
        n_applied, n_unmatched, path.name,
    )
    return df


def validate_final_holdings_schema(df: pd.DataFrame) -> list[tuple[str, int]]:
    """Block structural violations after all value writers; retain domain flags."""
    missing = sorted(set(UNIFIED_COLUMNS) - set(df.columns))
    if missing:
        raise ValueError("Final holdings schema missing columns: " + ", ".join(missing))
    violations = _enforce_schema(df)
    from pipeline.financial_validation import violations as financial_violations
    violations += financial_violations(df)
    structural = [(name, count) for name, count in violations
                  if name.endswith("_enum") or name.startswith('financial_')
                  or name in {"cik_format", "report_date_parseable", "cash_classification_consistency"}]
    if structural:
        raise ValueError("Final holdings schema violations: " + repr(structural))
    for name, count in violations:
        logger.warning("Final holdings domain flag %s: %d rows", name, count)
    return violations


def _enforce_schema(df: pd.DataFrame) -> list[tuple[str, int]]:
    """Run schema assertions on the unified output.

    Returns [(check_name, fail_count), ...] for any check with violations > 0.
    Checks are non-fatal -- callers decide how to handle violations.
    """
    if df.empty:
        return []

    missing_columns = [col for col in UNIFIED_COLUMNS if col not in df.columns]
    if missing_columns:
        df = df.copy()
        for col in missing_columns:
            df[col] = ""

    con = duckdb.connect()
    con.register("unified", df)

    # --- Layer 1: Type and format (should never fail) ---
    checks: list[tuple[str, str]] = [
        ("cik_format",
         "SELECT COUNT(*) FROM unified"
         " WHERE LENGTH(CAST(cik AS VARCHAR)) != 10"
         "    OR regexp_matches(CAST(cik AS VARCHAR), '[^0-9]')"),
        ("source_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(source AS VARCHAR) NOT IN ('bdc', 'nport')"),
        ("asset_category_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(asset_category AS VARCHAR) NOT IN"
         " ('LOAN','DEBT','EQUITY_COMMON','EQUITY_PREFERRED','FUND','OTHER','CASH')"),
        ("cash_classification_consistency",
         "SELECT COUNT(*) FROM unified WHERE asset_category='CASH' AND ("
         " index_classification IS DISTINCT FROM 'CASH' OR asset_class IS DISTINCT FROM 'CASH'"
         " OR exposure_type IS DISTINCT FROM 'LIQUID')"),
        ("issuer_category_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(issuer_category AS VARCHAR) NOT IN"
         " ('CORPORATE','FUND','GOVERNMENT','OTHER')"),
        ("index_classification_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(index_classification AS VARCHAR) NOT IN"
         " ('DIRECT_LENDING','COMMON_EQUITY','PREFERRED_EQUITY',"
         "  'PRIVATE_CREDIT_FUND','PRIVATE_EQUITY_FUND',"
         "  'REAL_ESTATE_FUND','DIRECT_REAL_ESTATE',"
         "  'STRUCTURED_CREDIT','HEDGE_FUND','CASH','UNCLASSIFIED')"),
        ("exposure_type_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(exposure_type AS VARCHAR) NOT IN"
         " ('DIRECT','FUND','LIQUID')"),
        ("asset_class_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(asset_class AS VARCHAR) NOT IN"
         " ('PRIVATE_CREDIT','PRIVATE_EQUITY','REAL_ESTATE',"
         "  'STRUCTURED_CREDIT','HEDGE_FUND','CASH','OTHER')"),
        ("report_date_parseable",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(report_date AS VARCHAR) IS NOT NULL"
         "   AND CAST(report_date AS VARCHAR) != ''"
         "   AND TRY_CAST(report_date AS DATE) IS NULL"),
        ("fair_value_is_null",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(fair_value AS DOUBLE) IS NULL"),
        ("coupon_type_enum",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(coupon_type AS VARCHAR) NOT IN ('Fixed', 'Floating', '')"
         " AND NOT (coalesce(CAST(source AS VARCHAR),'')='nport' AND CAST(coupon_type AS VARCHAR)='Variable')"),

        # --- Layer 2: Domain range (catches transform errors) ---
        ("interest_rate_range",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(interest_rate AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(interest_rate AS DOUBLE) < 0"
         "        OR TRY_CAST(interest_rate AS DOUBLE) > 50)"),
        ("basis_spread_range",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(basis_spread AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(basis_spread AS DOUBLE) < 0"
         "        OR TRY_CAST(basis_spread AS DOUBLE) > 30)"),
        ("pik_rate_range",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(pik_rate AS DOUBLE) IS NOT NULL"
         "   AND (TRY_CAST(pik_rate AS DOUBLE) < 0"
         "        OR TRY_CAST(pik_rate AS DOUBLE) > 25)"),
        ("pct_net_assets_range",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(pct_of_net_assets AS DOUBLE) IS NOT NULL"
         "   AND ABS(TRY_CAST(pct_of_net_assets AS DOUBLE)) > 150"),
        ("shares_not_negative",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(shares_held AS DOUBLE) IS NOT NULL"
         "   AND TRY_CAST(shares_held AS DOUBLE) < 0"),
        ("principal_not_negative",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(principal_amount AS DOUBLE) IS NOT NULL"
         "   AND TRY_CAST(principal_amount AS DOUBLE) < 0"),
        ("principal_usd_not_negative",
         "SELECT COUNT(*) FROM unified"
         " WHERE TRY_CAST(principal_amount_usd AS DOUBLE) IS NOT NULL"
         "   AND TRY_CAST(principal_amount_usd AS DOUBLE) < 0"),

        # --- Layer 3: Relational / logical (catches transform logic bugs) ---
        ("bdc_has_identifier",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(source AS VARCHAR) = 'bdc'"
         "   AND (bdc_investment_identifier IS NULL"
         "        OR CAST(bdc_investment_identifier AS VARCHAR) = '')"),
        ("dl_implies_loan_or_debt_corporate",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(index_classification AS VARCHAR) = 'DIRECT_LENDING'"
         "   AND (CAST(asset_category AS VARCHAR) NOT IN ('LOAN', 'DEBT')"
         "        OR CAST(issuer_category AS VARCHAR) != 'CORPORATE')"),
        ("fund_index_implies_fund_issuer",
         "SELECT COUNT(*) FROM unified"
         " WHERE CAST(index_classification AS VARCHAR)"
         "       IN ('PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND', 'REAL_ESTATE_FUND', 'HEDGE_FUND')"
         "   AND CAST(issuer_category AS VARCHAR) != 'FUND'"),
    ]

    violations: list[tuple[str, int]] = []
    for name, sql in checks:
        try:
            count = con.execute(sql).fetchone()[0]
            if count > 0:
                violations.append((name, count))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Schema check '%s' failed to execute: %s", name, exc)
            violations.append((name, -1))

    con.close()
    return violations


def _log_summary(df: pd.DataFrame) -> None:
    """Log summary statistics about the unified dataset."""
    total = len(df)
    bdc_count = (df["source"] == "bdc").sum()
    nport_count = (df["source"] == "nport").sum()

    logger.info("")
    logger.info("Unified holdings: %d total", total)
    logger.info("  BDC:    %d (%.1f%%)", bdc_count, 100 * bdc_count / total if total else 0)
    logger.info("  N-PORT: %d (%.1f%%)", nport_count, 100 * nport_count / total if total else 0)

    logger.info("")
    logger.info("By index:")
    for idx_name, count in df["index_classification"].value_counts().items():
        logger.info("  %-25s %d (%.1f%%)", idx_name + ":", count, 100 * count / total)

    logger.info("")
    logger.info("Analytics coverage:")
    for col, label in [
        ("interest_rate", "interest_rate filled"),
        ("basis_spread", "basis_spread filled (BDC only)"),
        ("reference_rate_type", "reference_rate_type filled"),
        ("cost", "cost filled (BDC real + N-PORT proxy)"),
        ("maturity_date", "maturity_date filled"),
        ("principal_amount", "principal_amount filled"),
        ("shares_held", "shares_held filled"),
        ("pct_of_net_assets", "pct_of_net_assets"),
    ]:
        if col in df.columns:
            filled = df[col].notna() & (df[col] != "") & (df[col] != 0)
            pct = 100 * filled.sum() / total if total else 0
            logger.info("  %-30s %.1f%%", label + ":", pct)

    _log_fx_coverage(df)

    # Quarter range
    quarters = set()
    # From N-PORT quarter column
    nport_q = df.loc[df["nport_quarter"] != "", "nport_quarter"].dropna().unique()
    quarters.update(nport_q)
    # From BDC report_date -> approximate quarter
    bdc_dates = df.loc[df["source"] == "bdc", "report_date"].dropna()
    for d in bdc_dates.unique():
        try:
            dt = pd.to_datetime(d)
            q = f"{dt.year}q{(dt.month - 1) // 3 + 1}"
            quarters.add(q)
        except (ValueError, TypeError):
            pass

    if quarters:
        sorted_q = sorted(quarters)
        logger.info("  Quarters covered: %s - %s", sorted_q[0], sorted_q[-1])


def _log_fx_coverage(df: pd.DataFrame) -> None:
    """Log USD-normalized principal coverage for rows with source-native par."""
    if df.empty or "principal_amount" not in df.columns:
        return

    principal = pd.to_numeric(df.get("principal_amount"), errors="coerce")
    principal_usd = pd.to_numeric(df.get("principal_amount_usd"), errors="coerce")
    fair_value = pd.to_numeric(df.get("fair_value"), errors="coerce").fillna(0)
    currency = df.get("principal_amount_currency", pd.Series("", index=df.index))
    currency = currency.fillna("").astype(str).str.upper().str.strip()

    has_principal = principal.notna()
    non_usd = has_principal & ~currency.isin(["", "USD"])
    converted = has_principal & principal_usd.notna()
    missing = has_principal & principal_usd.isna()
    affected_fv = float(fair_value[non_usd].sum())
    total_fv = float(fair_value.sum())
    affected_share = affected_fv / total_fv if total_fv else 0

    logger.info(
        "  Principal FX coverage: %d rows with principal, %d non-USD, "
        "%d converted, %d missing USD principal, %.2f%% FV non-USD affected",
        int(has_principal.sum()),
        int(non_usd.sum()),
        int((non_usd & converted).sum()),
        int((non_usd & missing).sum()),
        affected_share * 100,
    )
