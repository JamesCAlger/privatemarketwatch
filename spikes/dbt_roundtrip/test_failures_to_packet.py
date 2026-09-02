"""Converter tests. Fixture fakes the dbt stored-failure table; never
touches the real spike.duckdb or data/output/."""
from pathlib import Path

import duckdb
import pytest

import failures_to_packet as f2p

ROWS = [
    # (cik, entity, accession, report_date, source_row_id, issuer, instr, fv, key_sig, group_size)
    ("0000000001", "Fund A", "acc-1", "2025-12-31", "src:acc-1:ctxA", "Acme", "TL", 100.0, "k1", 3),
    ("0000000001", "Fund A", "acc-1", "2025-12-31", "src:acc-1:ctxB", "ACME", "TL", 100.0, "k1", 3),
    ("0000000001", "Fund A", "acc-1", "2025-12-31", "src:acc-1:ctxC", "Acme.", "TL", 100.0, "k1", 3),
    ("0000000002", "Fund B", "acc-2", "2025-09-30", "src:acc-2:ctxZ", "Beta", "EQ", 50.0, "k2", 2),
    ("0000000002", "Fund B", "acc-2", "2025-09-30", "src:acc-2:ctxY", "Beta", "EQ", 50.0, "k2", 2),
]


@pytest.fixture
def fake_db(tmp_path: Path) -> Path:
    db = tmp_path / "fake.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA main_dbt_test__audit")
    con.execute("""
        CREATE TABLE main_dbt_test__audit.duplicate_dimension_paths (
            cik VARCHAR, entity_name VARCHAR, accession_number VARCHAR,
            report_date VARCHAR, source_row_id VARCHAR, issuer_name VARCHAR,
            instrument_description VARCHAR, fair_value DOUBLE,
            key_sig VARCHAR, group_size BIGINT)
    """)
    con.executemany(
        "INSERT INTO main_dbt_test__audit.duplicate_dimension_paths VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", ROWS)
    con.close()
    return db


def test_one_packet_per_group(fake_db):
    packets = f2p.build_packets(fake_db)
    assert len(packets) == 2


def test_packet_contents_and_provenance(fake_db):
    packets = {p["key_sig"]: p for p in f2p.build_packets(fake_db)}
    p = packets["k1"]
    assert p["schema_version"] == "dbt-spike-packet.v0"
    assert p["mechanism"] == "boundary_duplicate_dimension_path"
    assert p["boundary_model"] == "stg_bdc_holdings"
    assert p["downstream_fix_model"] == "bdc_dim_deduped"
    assert p["cik"] == "0000000001"
    assert p["report_date"] == "2025-12-31"
    assert p["group_size"] == 3
    assert p["source_row_ids"] == ["src:acc-1:ctxA", "src:acc-1:ctxB", "src:acc-1:ctxC"]
    assert len(p["fair_values"]) == 3
    assert p["is_blocking"] is True


def test_deterministic_order(fake_db):
    a = f2p.build_packets(fake_db)
    b = f2p.build_packets(fake_db)
    assert a == b
    assert [p["key_sig"] for p in a] == sorted(p["key_sig"] for p in a)


def test_missing_table_raises(tmp_path):
    db = tmp_path / "empty.duckdb"
    duckdb.connect(str(db)).close()
    with pytest.raises(f2p.NoFailuresTable):
        f2p.build_packets(db)
