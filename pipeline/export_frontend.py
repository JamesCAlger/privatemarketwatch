"""Export pre-computed JSON for the static Next.js frontend.

Reads pipeline output CSVs with DuckDB, writes aggregated JSON files to
``frontend/public/data/``. The public BDC cohort includes complete position
history, source status and portfolio summaries.

Usage:
    python -m pipeline.main --export-frontend
"""

import logging

import duckdb

from pipeline.export.analytics_exports import (
    _export_concentration_curve,
    _export_credit_risk,
    _export_data_quality,
    _export_distribution_histogram,
    _export_gics_sector_breakdown,
    _export_investee_concentration,
    _export_leverage_histogram,
    _export_manager_concentration,
    _export_pik_eligibility,
    _export_position_concentration,
    _export_spread_by_fund_size,
    _export_spread_by_lien,
    _export_spread_time_series,
    _export_vehicle_concentration,
)
from pipeline.export.fund_exports import (
    _export_fund_details,
    _export_fund_list,
    _export_fund_summary,
)
from pipeline.export.helpers import FRONTEND_DATA_DIR
from pipeline.export.index_exports import (
    _export_metadata,
    _export_portfolio_characteristics,
    _export_sector_breakdown,
    _export_top_constituents,
    _export_vehicle_contribution,
)
from pipeline.export.timeseries_exports import (
    _export_aum_time_series,
    _export_industry_breakdown,
)

logger = logging.getLogger(__name__)


def export_all() -> None:
    """Run all exports.  Called by ``pipeline.main --export-frontend``."""
    from pipeline.holdings_finalizer import require_exportable_identity
    require_exportable_identity()
    from pipeline.export import helpers
    from pipeline.public_partitions import public_snapshot, write_public_contributors
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXPORTING FRONTEND JSON")
    logger.info("=" * 60)

    FRONTEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    snapshot = public_snapshot(con, helpers.UNIFIED_HOLDINGS_CSV,
        cutoff=helpers._quarter_to_date(helpers.INDEX_DISPLAY_END_QUARTER)
        if helpers.INDEX_DISPLAY_END_QUARTER else "9999-12-31")
    write_public_contributors(con,FRONTEND_DATA_DIR/"public_partition_contributors.json",snapshot["asOf"])
    from pipeline.cohort_guard import load_cohort_ciks
    from pipeline.holdings_history import export_history
    from pipeline import config
    export_history(con,helpers.UNIFIED_HOLDINGS_CSV,FRONTEND_DATA_DIR/"holdings_history",
        cohort=load_cohort_ciks(),end=snapshot["asOf"],source_cache=config.BDC_HTML_CACHE_DIR,
        sector_bundle=config.GICS_ENRICHMENT_DECISIONS_FILE,taxonomy=config.GICS_REFERENCE_FILE,
        sector_audit=config.OUTPUT_DIR/'sector_enrichment_audit.csv',cost_donors=config.OUTPUT_DIR/'cost_donor_audit.csv')

    # Index surfaces (index_returns, index_summary, fund_index_returns) are out
    # of v1 scope and are no longer exported. Position-level analytics remain.
    _export_top_constituents(con, snapshot=snapshot)
    _export_sector_breakdown(con)
    _export_vehicle_contribution(con)
    _export_manager_concentration(con)
    _export_vehicle_concentration(con)
    _export_investee_concentration(con)
    _export_position_concentration(con)
    _export_concentration_curve(con)
    _export_portfolio_characteristics(con, snapshot=snapshot)
    _export_metadata(con, [], snapshot=snapshot)
    _export_fund_list(con)
    _export_fund_details(con)
    _export_fund_summary(con)
    _export_industry_breakdown(con)
    _export_data_quality(con)

    # Landing page visualizations
    _export_aum_time_series(con)
    _export_gics_sector_breakdown(con, snapshot=snapshot)
    _export_credit_risk(con)
    _export_pik_eligibility(con)
    _export_distribution_histogram(con)
    _export_leverage_histogram(con)
    _export_spread_time_series(con)
    _export_spread_by_fund_size(con)
    _export_spread_by_lien(con)

    con.close()
    logger.info("Frontend export complete -- %d JSON files in %s",
                len(list(FRONTEND_DATA_DIR.glob("*.json"))),
                FRONTEND_DATA_DIR)
