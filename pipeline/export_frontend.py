"""Export pre-computed JSON for the static Next.js frontend.

Reads pipeline output CSVs with DuckDB, writes aggregated JSON files to
``frontend/public/data/``.  No position-level data is exposed -- only
index-level time-series and aggregated summaries.

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
    _export_index_returns,
    _export_index_summary,
    _export_metadata,
    _export_portfolio_characteristics,
    _export_sector_breakdown,
    _export_top_constituents,
    _export_vehicle_contribution,
)
from pipeline.export.timeseries_exports import (
    _export_aum_time_series,
    _export_fund_index_returns,
    _export_industry_breakdown,
)

logger = logging.getLogger(__name__)


def export_all() -> None:
    """Run all exports.  Called by ``pipeline.main --export-frontend``."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXPORTING FRONTEND JSON")
    logger.info("=" * 60)

    FRONTEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()

    ir = _export_index_returns(con)
    _export_index_summary(ir, con)
    _export_top_constituents(con)
    _export_sector_breakdown(con)
    _export_vehicle_contribution(con)
    _export_manager_concentration(con)
    _export_vehicle_concentration(con)
    _export_investee_concentration(con)
    _export_position_concentration(con)
    _export_concentration_curve(con)
    _export_portfolio_characteristics(con)
    _export_metadata(con, ir)
    _export_fund_list(con)
    _export_fund_details(con)
    _export_fund_summary(con)
    _export_industry_breakdown(con)
    _export_data_quality(con)

    # Landing page visualizations
    _export_fund_index_returns(con)
    _export_aum_time_series(con)
    _export_gics_sector_breakdown(con)
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
