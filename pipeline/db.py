"""Postgres loader -- bulk-loads pipeline CSVs into a Postgres database.

Usage:
    python -m pipeline.main --load-db

Requires DATABASE_URL env var (default: postgresql://localhost:5432/private_markets).
"""

import logging
from pathlib import Path

import psycopg2
import psycopg2.extensions

from pipeline.config import (
    DATABASE_URL,
    COMBINED_UNIVERSE_FILE,
    UNIFIED_HOLDINGS_FILE,
    POSITION_MATCHES_FILE,
    POSITION_RETURNS_FILE,
    INDEX_RETURNS_FILE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_ENTITIES_DDL = """\
CREATE TABLE pmi_entities (
    entity_id       TEXT PRIMARY KEY,
    cik             TEXT NOT NULL,
    entity_name     TEXT,
    series_id       TEXT,
    fund_name       TEXT,
    file_number     TEXT,
    vehicle_type    TEXT,
    status          TEXT,
    activity_status TEXT,
    election_date   DATE,
    withdrawal_date DATE,
    first_filing_date   DATE,
    last_filing_date    DATE,
    latest_periodic_filing_date DATE,
    latest_periodic_filing_type TEXT,
    discovery_methods   TEXT,
    data_sources        TEXT,
    in_third_party_lists TEXT,
    adviser_name        TEXT,
    total_net_assets    DOUBLE PRECISION
);
CREATE INDEX idx_entities_cik ON pmi_entities (cik);
CREATE INDEX idx_entities_vehicle_type ON pmi_entities (vehicle_type);
"""

_HOLDINGS_DDL = """\
CREATE TABLE pmi_holdings (
    source              TEXT,
    cik                 TEXT,
    entity_name         TEXT,
    accession_number    TEXT,
    filing_date         DATE,
    report_date         DATE,
    issuer_name         TEXT,
    instrument_description TEXT,
    cusip               TEXT,
    isin                TEXT,
    lei                 TEXT,
    ticker              TEXT,
    fair_value          DOUBLE PRECISION,
    cost                DOUBLE PRECISION,
    pct_of_net_assets   DOUBLE PRECISION,
    shares_held         DOUBLE PRECISION,
    principal_amount    DOUBLE PRECISION,
    asset_category      TEXT,
    issuer_category     TEXT,
    index_classification TEXT,
    fair_value_level    TEXT,
    interest_rate       DOUBLE PRECISION,
    basis_spread        DOUBLE PRECISION,
    reference_rate_type TEXT,
    coupon_type         TEXT,
    pik_rate            DOUBLE PRECISION,
    maturity_date       TEXT,
    bdc_investment_identifier TEXT,
    bdc_form_type       TEXT,
    bdc_dimensions_raw  TEXT,
    bdc_unrealized_gain_loss DOUBLE PRECISION,
    nport_holding_id    TEXT,
    nport_series_name   TEXT,
    nport_series_id     TEXT,
    nport_asset_cat     TEXT,
    nport_issuer_type   TEXT,
    nport_payoff_profile TEXT,
    nport_investment_country TEXT,
    nport_is_restricted TEXT,
    nport_quarter       TEXT,
    entity_id           TEXT,
    canonical_name      TEXT,
    extracted_industry  TEXT,
    position_id         TEXT
);
CREATE INDEX idx_holdings_cik ON pmi_holdings (cik);
CREATE INDEX idx_holdings_index_class ON pmi_holdings (index_classification);
CREATE INDEX idx_holdings_report_date ON pmi_holdings (report_date);
CREATE INDEX idx_holdings_index_date ON pmi_holdings (index_classification, report_date);
CREATE INDEX idx_holdings_position_id ON pmi_holdings (position_id);
CREATE INDEX idx_holdings_entity_id ON pmi_holdings (entity_id);
"""

_POSITION_MATCHES_DDL = """\
CREATE TABLE pmi_position_matches (
    cik                     TEXT,
    entity_name             TEXT,
    source                  TEXT,
    index_classification    TEXT,
    begin_quarter           TEXT,
    begin_report_date       DATE,
    begin_issuer_name       TEXT,
    begin_fair_value        DOUBLE PRECISION,
    begin_cost              DOUBLE PRECISION,
    begin_principal_amount  DOUBLE PRECISION,
    begin_interest_rate     DOUBLE PRECISION,
    begin_basis_spread      DOUBLE PRECISION,
    begin_shares_held       DOUBLE PRECISION,
    end_quarter             TEXT,
    end_report_date         DATE,
    end_issuer_name         TEXT,
    end_fair_value          DOUBLE PRECISION,
    end_cost                DOUBLE PRECISION,
    end_principal_amount    DOUBLE PRECISION,
    end_interest_rate       DOUBLE PRECISION,
    end_basis_spread        DOUBLE PRECISION,
    end_shares_held         DOUBLE PRECISION,
    match_method            TEXT,
    match_key               TEXT,
    match_score             DOUBLE PRECISION,
    span_months             INTEGER,
    asset_category          TEXT,
    issuer_category         TEXT,
    maturity_date           TEXT,
    coupon_type             TEXT,
    position_id             TEXT
);
CREATE INDEX idx_matches_cik ON pmi_position_matches (cik);
CREATE INDEX idx_matches_index_class ON pmi_position_matches (index_classification);
CREATE INDEX idx_matches_end_quarter ON pmi_position_matches (end_quarter);
CREATE INDEX idx_matches_position_id ON pmi_position_matches (position_id);
"""

_POSITION_RETURNS_DDL = """\
CREATE TABLE pmi_position_returns (
    cik                     TEXT,
    entity_name             TEXT,
    source                  TEXT,
    begin_quarter           TEXT,
    end_quarter             TEXT,
    issuer_name             TEXT,
    index_classification    TEXT,
    asset_category          TEXT,
    begin_fair_value        DOUBLE PRECISION,
    end_fair_value          DOUBLE PRECISION,
    begin_cost              DOUBLE PRECISION,
    end_cost                DOUBLE PRECISION,
    begin_principal_amount  DOUBLE PRECISION,
    end_principal_amount    DOUBLE PRECISION,
    begin_shares_held       DOUBLE PRECISION,
    end_shares_held         DOUBLE PRECISION,
    begin_interest_rate     DOUBLE PRECISION,
    begin_basis_spread      DOUBLE PRECISION,
    income_rate             DOUBLE PRECISION,
    capital_return          DOUBLE PRECISION,
    income_return           DOUBLE PRECISION,
    total_return            DOUBLE PRECISION,
    quarterly_total_return  DOUBLE PRECISION,
    match_method            TEXT,
    match_score             DOUBLE PRECISION,
    span_months             INTEGER,
    span_adjusted           TEXT,
    position_id             TEXT
);
CREATE INDEX idx_returns_cik ON pmi_position_returns (cik);
CREATE INDEX idx_returns_index_class ON pmi_position_returns (index_classification);
CREATE INDEX idx_returns_end_quarter ON pmi_position_returns (end_quarter);
CREATE INDEX idx_returns_index_quarter ON pmi_position_returns (index_classification, end_quarter);
CREATE INDEX idx_returns_position_id ON pmi_position_returns (position_id);
"""

_INDEX_RETURNS_DDL = """\
CREATE TABLE pmi_index_returns (
    index_classification    TEXT NOT NULL,
    quarter                 TEXT NOT NULL,
    fv_weighted_return      DOUBLE PRECISION,
    equal_weighted_return   DOUBLE PRECISION,
    cost_weighted_return    DOUBLE PRECISION,
    constituent_count       INTEGER,
    total_begin_fv          DOUBLE PRECISION,
    total_end_fv            DOUBLE PRECISION,
    index_level_fv          DOUBLE PRECISION,
    index_level_equal       DOUBLE PRECISION,
    index_level_cost        DOUBLE PRECISION,
    PRIMARY KEY (index_classification, quarter)
);
"""

# Ordered list of (table_name, ddl_string)
_ALL_TABLES = [
    ("pmi_entities", _ENTITIES_DDL),
    ("pmi_holdings", _HOLDINGS_DDL),
    ("pmi_position_matches", _POSITION_MATCHES_DDL),
    ("pmi_position_returns", _POSITION_RETURNS_DDL),
    ("pmi_index_returns", _INDEX_RETURNS_DDL),
]

# ---------------------------------------------------------------------------
# Materialized Views
# ---------------------------------------------------------------------------

_MV_LATEST_QUARTER = """\
CREATE MATERIALIZED VIEW pmi_mv_latest_quarter AS
SELECT ir.*
FROM pmi_index_returns ir
INNER JOIN (
    SELECT index_classification, MAX(quarter) AS max_q
    FROM pmi_index_returns
    GROUP BY index_classification
) latest ON ir.index_classification = latest.index_classification
        AND ir.quarter = latest.max_q;
"""

_MV_TOP_CONSTITUENTS = """\
CREATE MATERIALIZED VIEW pmi_mv_top_constituents AS
SELECT *
FROM (
    SELECT pr.*,
           ROW_NUMBER() OVER (
               PARTITION BY pr.index_classification, pr.end_quarter
               ORDER BY pr.end_fair_value DESC NULLS LAST
           ) AS rn
    FROM pmi_position_returns pr
) ranked
WHERE rn <= 20;
"""

_MV_SECTOR_BREAKDOWN = """\
CREATE MATERIALIZED VIEW pmi_mv_sector_breakdown AS
SELECT
    pr.index_classification,
    pr.end_quarter,
    pr.asset_category,
    COUNT(*) AS position_count,
    SUM(pr.end_fair_value) AS total_fv,
    SUM(pr.end_fair_value * pr.quarterly_total_return)
        / NULLIF(SUM(pr.end_fair_value), 0) AS fv_weighted_return
FROM pmi_position_returns pr
WHERE pr.end_fair_value IS NOT NULL
  AND pr.quarterly_total_return IS NOT NULL
GROUP BY pr.index_classification, pr.end_quarter, pr.asset_category;
"""

_MV_VEHICLE_CONTRIBUTION = """\
CREATE MATERIALIZED VIEW pmi_mv_vehicle_contribution AS
SELECT
    pr.index_classification,
    pr.end_quarter,
    e.vehicle_type,
    COUNT(*) AS position_count,
    SUM(pr.end_fair_value) AS total_fv
FROM pmi_position_returns pr
LEFT JOIN pmi_entities e ON pr.cik = e.cik
GROUP BY pr.index_classification, pr.end_quarter, e.vehicle_type;
"""

_MV_LATEST_HOLDINGS = """\
CREATE MATERIALIZED VIEW pmi_mv_latest_holdings AS
SELECT h.*
FROM pmi_holdings h
INNER JOIN (
    SELECT cik, MAX(report_date) AS max_rd
    FROM pmi_holdings
    GROUP BY cik
) latest ON h.cik = latest.cik AND h.report_date = latest.max_rd;
"""

_ALL_MATERIALIZED_VIEWS = [
    ("pmi_mv_latest_quarter", _MV_LATEST_QUARTER),
    ("pmi_mv_top_constituents", _MV_TOP_CONSTITUENTS),
    ("pmi_mv_sector_breakdown", _MV_SECTOR_BREAKDOWN),
    ("pmi_mv_vehicle_contribution", _MV_VEHICLE_CONTRIBUTION),
    ("pmi_mv_latest_holdings", _MV_LATEST_HOLDINGS),
]

# ---------------------------------------------------------------------------
# Column lists (must match CSV headers exactly)
# ---------------------------------------------------------------------------

_ENTITIES_COLS = [
    "entity_id", "cik", "entity_name", "series_id", "fund_name",
    "file_number", "vehicle_type", "status", "activity_status",
    "election_date", "withdrawal_date", "first_filing_date",
    "last_filing_date", "latest_periodic_filing_date",
    "latest_periodic_filing_type", "discovery_methods", "data_sources",
    "in_third_party_lists", "adviser_name", "total_net_assets",
]

_HOLDINGS_COLS = [
    "source", "cik", "entity_name", "accession_number", "filing_date",
    "report_date", "issuer_name", "instrument_description", "cusip", "isin",
    "lei", "ticker", "fair_value", "cost", "pct_of_net_assets", "shares_held",
    "principal_amount", "asset_category", "issuer_category",
    "index_classification", "fair_value_level", "interest_rate",
    "basis_spread", "reference_rate_type", "coupon_type", "pik_rate",
    "maturity_date", "bdc_investment_identifier", "bdc_form_type",
    "bdc_dimensions_raw", "bdc_unrealized_gain_loss", "nport_holding_id",
    "nport_series_name", "nport_series_id", "nport_asset_cat",
    "nport_issuer_type", "nport_payoff_profile", "nport_investment_country",
    "nport_is_restricted", "nport_quarter", "entity_id", "canonical_name",
    "extracted_industry", "position_id",
]

_POSITION_MATCHES_COLS = [
    "cik", "entity_name", "source", "index_classification", "begin_quarter",
    "begin_report_date", "begin_issuer_name", "begin_fair_value",
    "begin_cost", "begin_principal_amount", "begin_interest_rate",
    "begin_basis_spread", "begin_shares_held", "end_quarter",
    "end_report_date", "end_issuer_name", "end_fair_value", "end_cost",
    "end_principal_amount", "end_interest_rate", "end_basis_spread",
    "end_shares_held", "match_method", "match_key", "match_score",
    "span_months", "asset_category", "issuer_category", "maturity_date",
    "coupon_type", "position_id",
]

_POSITION_RETURNS_COLS = [
    "cik", "entity_name", "source", "begin_quarter", "end_quarter",
    "issuer_name", "index_classification", "asset_category",
    "begin_fair_value", "end_fair_value", "begin_cost", "end_cost",
    "begin_principal_amount", "end_principal_amount", "begin_shares_held",
    "end_shares_held", "begin_interest_rate", "begin_basis_spread",
    "income_rate", "capital_return", "income_return", "total_return",
    "quarterly_total_return", "match_method", "match_score", "span_months",
    "span_adjusted", "position_id",
]

_INDEX_RETURNS_COLS = [
    "index_classification", "quarter", "fv_weighted_return",
    "equal_weighted_return", "cost_weighted_return", "constituent_count",
    "total_begin_fv", "total_end_fv", "index_level_fv", "index_level_equal",
    "index_level_cost",
]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_connection(dsn: str | None = None) -> psycopg2.extensions.connection:
    """Return a new psycopg2 connection using *dsn* or DATABASE_URL."""
    return psycopg2.connect(dsn or DATABASE_URL)


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def create_schema(conn: psycopg2.extensions.connection) -> None:
    """Drop and recreate all pmi_ tables."""
    cur = conn.cursor()
    # Drop in reverse order to avoid FK issues (none currently, but safe habit)
    for table_name, _ in reversed(_ALL_TABLES):
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
    for table_name, ddl in _ALL_TABLES:
        cur.execute(ddl)
        logger.info("Created table %s", table_name)
    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# CSV bulk loading
# ---------------------------------------------------------------------------

def _load_csv_copy(
    conn: psycopg2.extensions.connection,
    table_name: str,
    csv_path: Path,
    columns: list[str],
) -> int:
    """Bulk-load a CSV file into *table_name* using COPY FROM STDIN.

    Returns the number of rows loaded, or 0 if the file is missing.
    """
    if not csv_path.exists():
        logger.warning("CSV not found, skipping: %s", csv_path)
        return 0

    cols_sql = ", ".join(columns)
    copy_sql = (
        f"COPY {table_name} ({cols_sql}) "
        f"FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"
    )
    cur = conn.cursor()
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        cur.copy_expert(copy_sql, f)
    conn.commit()

    cur.execute(f"SELECT COUNT(*) FROM {table_name};")
    count = cur.fetchone()[0]
    cur.close()
    logger.info("Loaded %s rows into %s", f"{count:,}", table_name)
    return count


def load_entities(conn: psycopg2.extensions.connection) -> int:
    return _load_csv_copy(conn, "pmi_entities", COMBINED_UNIVERSE_FILE, _ENTITIES_COLS)


def load_holdings(conn: psycopg2.extensions.connection) -> int:
    """Load holdings via TEXT staging table to handle dirty numeric values."""
    if not UNIFIED_HOLDINGS_FILE.exists():
        logger.warning("CSV not found, skipping: %s", UNIFIED_HOLDINGS_FILE)
        return 0

    cur = conn.cursor()

    # Create all-TEXT staging table
    staging_cols = ", ".join(f"{c} TEXT" for c in _HOLDINGS_COLS)
    cur.execute(f"CREATE TEMP TABLE _stg_holdings ({staging_cols});")

    # COPY into staging
    cols_sql = ", ".join(_HOLDINGS_COLS)
    copy_sql = (
        f"COPY _stg_holdings ({cols_sql}) "
        f"FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"
    )
    with open(UNIFIED_HOLDINGS_FILE, "r", encoding="utf-8", errors="replace") as f:
        cur.copy_expert(copy_sql, f)

    # INSERT into real table with safe numeric casts
    _NUMERIC_COLS = {
        "fair_value", "cost", "pct_of_net_assets", "shares_held",
        "principal_amount", "interest_rate", "basis_spread", "pik_rate",
        "bdc_unrealized_gain_loss",
    }
    cast_exprs = []
    for c in _HOLDINGS_COLS:
        if c == "filing_date" or c == "report_date":
            cast_exprs.append(f"CASE WHEN {c} ~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}' "
                              f"THEN {c}::DATE ELSE NULL END")
        elif c in _NUMERIC_COLS:
            cast_exprs.append(
                f"CASE WHEN {c} ~ '^-?[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?$' "
                f"THEN {c}::DOUBLE PRECISION ELSE NULL END"
            )
        else:
            cast_exprs.append(f"NULLIF({c}, '')")
    insert_sql = (
        f"INSERT INTO pmi_holdings ({cols_sql}) "
        f"SELECT {', '.join(cast_exprs)} FROM _stg_holdings;"
    )
    cur.execute(insert_sql)
    cur.execute("DROP TABLE _stg_holdings;")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM pmi_holdings;")
    count = cur.fetchone()[0]
    cur.close()
    logger.info("Loaded %s rows into pmi_holdings", f"{count:,}")
    return count


def load_position_matches(conn: psycopg2.extensions.connection) -> int:
    return _load_csv_copy(
        conn, "pmi_position_matches", POSITION_MATCHES_FILE, _POSITION_MATCHES_COLS,
    )


def load_position_returns(conn: psycopg2.extensions.connection) -> int:
    count = _load_csv_copy(
        conn, "pmi_position_returns", POSITION_RETURNS_FILE, _POSITION_RETURNS_COLS,
    )
    if count > 0:
        # Convert span_adjusted from text ('True'/'False') to boolean
        cur = conn.cursor()
        cur.execute(
            "ALTER TABLE pmi_position_returns "
            "ALTER COLUMN span_adjusted TYPE BOOLEAN "
            "USING (span_adjusted = 'True');"
        )
        conn.commit()
        cur.close()
        logger.info("Converted span_adjusted to BOOLEAN")
    return count


def load_index_returns(conn: psycopg2.extensions.connection) -> int:
    return _load_csv_copy(
        conn, "pmi_index_returns", INDEX_RETURNS_FILE, _INDEX_RETURNS_COLS,
    )


# ---------------------------------------------------------------------------
# Materialized views
# ---------------------------------------------------------------------------

def create_materialized_views(conn: psycopg2.extensions.connection) -> None:
    """Drop and recreate all pmi_mv_ materialized views."""
    cur = conn.cursor()
    for mv_name, _ in reversed(_ALL_MATERIALIZED_VIEWS):
        cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {mv_name} CASCADE;")
    for mv_name, mv_sql in _ALL_MATERIALIZED_VIEWS:
        cur.execute(mv_sql)
        logger.info("Created materialized view %s", mv_name)
    conn.commit()
    cur.close()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def load_all(dsn: str | None = None) -> None:
    """Full load: create schema, bulk-load CSVs, build materialized views."""
    conn = get_connection(dsn)
    try:
        logger.info("Creating schema ...")
        create_schema(conn)

        logger.info("Loading CSVs ...")
        load_entities(conn)
        load_holdings(conn)
        load_position_matches(conn)
        load_position_returns(conn)
        load_index_returns(conn)

        logger.info("Creating materialized views ...")
        create_materialized_views(conn)

        logger.info("Database load complete")
    finally:
        conn.close()
