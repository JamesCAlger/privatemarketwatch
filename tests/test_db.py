"""Tests for pipeline.db -- Postgres schema creation, CSV loading, and MVs.

Requires a running Postgres instance.  Set TEST_DATABASE_URL env var to point
at a *test* database (default: postgresql://localhost:5432/private_markets_test).
All tests are skipped gracefully if Postgres is unavailable.
"""

import csv
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# Skip entire module if psycopg2 cannot connect
_TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://localhost:5432/private_markets_test"
)

try:
    import psycopg2

    _conn_check = psycopg2.connect(_TEST_DSN)
    _conn_check.close()
    _PG_AVAILABLE = True
except Exception:
    _PG_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _PG_AVAILABLE,
    reason=f"Postgres not available at {_TEST_DSN}",
)

from pipeline.db import (
    _ALL_MATERIALIZED_VIEWS,
    _ALL_TABLES,
    _ENTITIES_COLS,
    _HOLDINGS_COLS,
    _INDEX_RETURNS_COLS,
    _POSITION_MATCHES_COLS,
    _POSITION_RETURNS_COLS,
    create_materialized_views,
    create_schema,
    get_connection,
    load_all,
    load_entities,
    load_holdings,
    load_index_returns,
    load_position_matches,
    load_position_returns,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def conn():
    """Provide a connection that rolls back all changes after each test."""
    c = get_connection(_TEST_DSN)
    yield c
    c.rollback()
    c.close()


@pytest.fixture()
def clean_conn():
    """Provide a connection with schema created, cleaned up after test."""
    c = get_connection(_TEST_DSN)
    create_schema(c)
    yield c
    # Cleanup: drop all tables/MVs
    cur = c.cursor()
    for mv_name, _ in reversed(_ALL_MATERIALIZED_VIEWS):
        cur.execute(f"DROP MATERIALIZED VIEW IF EXISTS {mv_name} CASCADE;")
    for table_name, _ in reversed(_ALL_TABLES):
        cur.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
    c.commit()
    cur.close()
    c.close()


def _write_csv(path: Path, columns: list[str], rows: list[list]) -> None:
    """Write a CSV file with the given columns and rows."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Test: Schema creation
# ---------------------------------------------------------------------------

class TestSchemaCreation:
    def test_tables_created(self, conn):
        create_schema(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename LIKE 'pmi_%' ORDER BY tablename;"
        )
        tables = [row[0] for row in cur.fetchall()]
        cur.close()
        expected = sorted(t for t, _ in _ALL_TABLES)
        assert tables == expected

    def test_idempotent(self, conn):
        """Running create_schema twice should not error."""
        create_schema(conn)
        create_schema(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename LIKE 'pmi_%';"
        )
        assert cur.fetchone()[0] == len(_ALL_TABLES)
        cur.close()


# ---------------------------------------------------------------------------
# Test: CSV loading
# ---------------------------------------------------------------------------

class TestCsvLoading:
    def test_load_entities(self, clean_conn):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "combined_universe.csv"
            _write_csv(csv_path, _ENTITIES_COLS, [
                ["ENT-1", "0001234567", "Test BDC", "", "", "814-00001",
                 "bdc", "active", "active", "", "", "2020-01-01",
                 "2025-01-01", "2025-01-01", "10-K", "bdc_dataset",
                 "bdc_dataset", "", "Test Adviser", "1000000"],
                ["ENT-2", "0009876543", "Test Fund", "S000012345",
                 "Test Interval", "", "interval_fund", "active", "active",
                 "", "", "2019-06-01", "2024-12-01", "2024-12-01", "N-PORT",
                 "ncen", "ncen", "ift", "Fund Adviser", "500000"],
            ])
            with mock.patch("pipeline.db.COMBINED_UNIVERSE_FILE", csv_path):
                count = load_entities(clean_conn)
            assert count == 2

            cur = clean_conn.cursor()
            cur.execute("SELECT entity_name FROM pmi_entities WHERE cik = '0001234567';")
            assert cur.fetchone()[0] == "Test BDC"
            cur.close()

    def test_load_index_returns(self, clean_conn):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "index_returns.csv"
            _write_csv(csv_path, _INDEX_RETURNS_COLS, [
                ["DIRECT_LENDING", "2025q1", "0.025", "0.018", "0.022",
                 "8500", "50000000", "51250000", "142.6", "140.1", "138.5"],
                ["COMMON_EQUITY", "2025q1", "0.031", "0.028", "0.030",
                 "1200", "10000000", "10310000", "121.6", "118.2", "115.0"],
            ])
            with mock.patch("pipeline.db.INDEX_RETURNS_FILE", csv_path):
                count = load_index_returns(clean_conn)
            assert count == 2

            cur = clean_conn.cursor()
            cur.execute(
                "SELECT constituent_count FROM pmi_index_returns "
                "WHERE index_classification = 'DIRECT_LENDING';"
            )
            assert cur.fetchone()[0] == 8500
            cur.close()

    def test_load_position_returns_boolean_conversion(self, clean_conn):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "position_returns.csv"
            _write_csv(csv_path, _POSITION_RETURNS_COLS, [
                ["0001234567", "Test BDC", "bdc", "2024q4", "2025q1",
                 "Acme Corp", "DIRECT_LENDING", "LOAN", "1000000", "1010000",
                 "1000000", "1000000", "1000000", "1000000", "", "",
                 "10.5", "5.0", "10.5", "0.01", "0.026", "0.036",
                 "0.036", "B2", "1.0", "3", "True", "POS-1"],
                ["0001234567", "Test BDC", "bdc", "2024q4", "2025q1",
                 "Beta Inc", "DIRECT_LENDING", "LOAN", "500000", "505000",
                 "500000", "500000", "500000", "500000", "", "",
                 "9.0", "4.0", "9.0", "0.01", "0.0225", "0.0325",
                 "0.0325", "B2", "1.0", "3", "False", "POS-2"],
            ])
            with mock.patch("pipeline.db.POSITION_RETURNS_FILE", csv_path):
                count = load_position_returns(clean_conn)
            assert count == 2

            cur = clean_conn.cursor()
            cur.execute(
                "SELECT span_adjusted FROM pmi_position_returns "
                "WHERE position_id = 'POS-1';"
            )
            assert cur.fetchone()[0] is True
            cur.execute(
                "SELECT span_adjusted FROM pmi_position_returns "
                "WHERE position_id = 'POS-2';"
            )
            assert cur.fetchone()[0] is False
            cur.close()


# ---------------------------------------------------------------------------
# Test: Missing CSV
# ---------------------------------------------------------------------------

class TestMissingCsv:
    def test_missing_csv_returns_zero(self, clean_conn):
        fake_path = Path("/nonexistent/path/to/file.csv")
        with mock.patch("pipeline.db.COMBINED_UNIVERSE_FILE", fake_path):
            count = load_entities(clean_conn)
        assert count == 0

    def test_missing_csv_no_crash(self, clean_conn):
        """All loaders should handle missing files gracefully."""
        fake = Path("/nonexistent/path.csv")
        with mock.patch("pipeline.db.COMBINED_UNIVERSE_FILE", fake), \
             mock.patch("pipeline.db.UNIFIED_HOLDINGS_FILE", fake), \
             mock.patch("pipeline.db.POSITION_MATCHES_FILE", fake), \
             mock.patch("pipeline.db.POSITION_RETURNS_FILE", fake), \
             mock.patch("pipeline.db.INDEX_RETURNS_FILE", fake):
            load_entities(clean_conn)
            load_holdings(clean_conn)
            load_position_matches(clean_conn)
            load_position_returns(clean_conn)
            load_index_returns(clean_conn)


# ---------------------------------------------------------------------------
# Test: Materialized views
# ---------------------------------------------------------------------------

class TestMaterializedViews:
    def test_mvs_created(self, clean_conn):
        # Load some data first so MVs have something to query
        with tempfile.TemporaryDirectory() as tmpdir:
            ir_path = Path(tmpdir) / "index_returns.csv"
            _write_csv(ir_path, _INDEX_RETURNS_COLS, [
                ["DIRECT_LENDING", "2025q1", "0.025", "0.018", "0.022",
                 "8500", "50000000", "51250000", "142.6", "140.1", "138.5"],
            ])
            with mock.patch("pipeline.db.INDEX_RETURNS_FILE", ir_path):
                load_index_returns(clean_conn)

        create_materialized_views(clean_conn)

        cur = clean_conn.cursor()
        cur.execute(
            "SELECT matviewname FROM pg_matviews "
            "WHERE schemaname = 'public' AND matviewname LIKE 'pmi_mv_%' "
            "ORDER BY matviewname;"
        )
        mvs = [row[0] for row in cur.fetchall()]
        expected = sorted(name for name, _ in _ALL_MATERIALIZED_VIEWS)
        assert mvs == expected

    def test_latest_quarter_queryable(self, clean_conn):
        with tempfile.TemporaryDirectory() as tmpdir:
            ir_path = Path(tmpdir) / "index_returns.csv"
            _write_csv(ir_path, _INDEX_RETURNS_COLS, [
                ["DIRECT_LENDING", "2024q4", "0.020", "0.015", "0.018",
                 "8000", "48000000", "48960000", "139.0", "137.0", "135.0"],
                ["DIRECT_LENDING", "2025q1", "0.025", "0.018", "0.022",
                 "8500", "50000000", "51250000", "142.6", "140.1", "138.5"],
            ])
            with mock.patch("pipeline.db.INDEX_RETURNS_FILE", ir_path):
                load_index_returns(clean_conn)

        create_materialized_views(clean_conn)

        cur = clean_conn.cursor()
        cur.execute("SELECT quarter FROM pmi_mv_latest_quarter;")
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "2025q1"
        cur.close()


# ---------------------------------------------------------------------------
# Test: load_all end-to-end
# ---------------------------------------------------------------------------

class TestLoadAll:
    def test_load_all_with_synthetic_csvs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create minimal CSVs for each table
            _write_csv(tmpdir / "entities.csv", _ENTITIES_COLS, [
                ["ENT-1", "0001234567", "Test BDC", "", "", "",
                 "bdc", "active", "active", "", "", "", "", "", "",
                 "bdc_dataset", "bdc_dataset", "", "", ""],
            ])
            _write_csv(tmpdir / "holdings.csv", _HOLDINGS_COLS, [
                ["bdc", "0001234567", "Test BDC", "0001234567-25-000001",
                 "2025-01-15", "2025-01-01", "Acme Corp", "Term Loan",
                 "", "", "", "", "1000000", "1000000", "5.0", "", "1000000",
                 "LOAN", "CORPORATE", "DIRECT_LENDING", "", "10.5", "5.0",
                 "SOFR", "FLOATING", "", "2027-01-01", "Acme Corp | Loan",
                 "10-K", "", "", "", "", "", "", "", "", "", "", "",
                 "ENT-1", "", "", "POS-1"],
            ])
            _write_csv(tmpdir / "matches.csv", _POSITION_MATCHES_COLS, [
                ["0001234567", "Test BDC", "bdc", "DIRECT_LENDING",
                 "2024q4", "2024-12-31", "Acme Corp", "990000", "1000000",
                 "1000000", "10.5", "5.0", "",
                 "2025q1", "2025-03-31", "Acme Corp", "1010000", "1000000",
                 "1000000", "10.5", "5.0", "",
                 "B2", "Acme Corp", "1.0", "3", "LOAN", "CORPORATE",
                 "2027-01-01", "FLOATING", "POS-1"],
            ])
            _write_csv(tmpdir / "returns.csv", _POSITION_RETURNS_COLS, [
                ["0001234567", "Test BDC", "bdc", "2024q4", "2025q1",
                 "Acme Corp", "DIRECT_LENDING", "LOAN", "990000", "1010000",
                 "1000000", "1000000", "1000000", "1000000", "", "",
                 "10.5", "5.0", "10.5", "0.0202", "0.02625", "0.04645",
                 "0.04645", "B2", "1.0", "3", "True", "POS-1"],
            ])
            _write_csv(tmpdir / "index.csv", _INDEX_RETURNS_COLS, [
                ["DIRECT_LENDING", "2025q1", "0.025", "0.018", "0.022",
                 "8500", "50000000", "51250000", "142.6", "140.1", "138.5"],
            ])

            with mock.patch("pipeline.db.COMBINED_UNIVERSE_FILE", tmpdir / "entities.csv"), \
                 mock.patch("pipeline.db.UNIFIED_HOLDINGS_FILE", tmpdir / "holdings.csv"), \
                 mock.patch("pipeline.db.POSITION_MATCHES_FILE", tmpdir / "matches.csv"), \
                 mock.patch("pipeline.db.POSITION_RETURNS_FILE", tmpdir / "returns.csv"), \
                 mock.patch("pipeline.db.INDEX_RETURNS_FILE", tmpdir / "index.csv"):
                load_all(dsn=_TEST_DSN)

            # Verify all tables + MVs populated
            c = get_connection(_TEST_DSN)
            cur = c.cursor()
            for table_name, _ in _ALL_TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table_name};")
                assert cur.fetchone()[0] >= 1, f"{table_name} should have rows"

            # MVs should exist and be queryable
            for mv_name, _ in _ALL_MATERIALIZED_VIEWS:
                cur.execute(f"SELECT COUNT(*) FROM {mv_name};")
                # At least 0 rows (some MVs may be empty with minimal data)

            # Verify specific values
            cur.execute(
                "SELECT entity_name FROM pmi_entities WHERE cik = '0001234567';"
            )
            assert cur.fetchone()[0] == "Test BDC"

            cur.execute(
                "SELECT span_adjusted FROM pmi_position_returns WHERE position_id = 'POS-1';"
            )
            assert cur.fetchone()[0] is True

            cur.close()

            # Cleanup
            cur2 = c.cursor()
            for mv_name, _ in reversed(_ALL_MATERIALIZED_VIEWS):
                cur2.execute(f"DROP MATERIALIZED VIEW IF EXISTS {mv_name} CASCADE;")
            for table_name, _ in reversed(_ALL_TABLES):
                cur2.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
            c.commit()
            cur2.close()
            c.close()
