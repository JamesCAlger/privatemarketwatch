"""pipeline.holdings_compare: which funds' published rows moved between two builds."""
import duckdb
import pytest

from pipeline import holdings_compare as hc

A, B, C = "0000000001", "0000000002", "0000000003"


def write(path, rows, columns=("row_id", "cik", "issuer_name", "fair_value", "lien_position")):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (%s)" % ", ".join("%s %s" % (c, "DOUBLE" if c == "fair_value" else "VARCHAR")
                                                 for c in columns))
    con.executemany("INSERT INTO t VALUES (%s)" % ", ".join("?" for _ in columns), rows)
    con.execute("COPY t TO '%s' (FORMAT PARQUET)" % path.as_posix())
    con.close()
    return path


BEFORE = [("r1", "1", "Acme", 100.0, "First Lien"), ("r2", "1", "Bolt", 50.0, "First Lien"),
          ("r3", "2", "Cork", 70.0, "Second Lien"), ("r4", "2", "Dune", 30.0, None),
          ("r5", "3", "Echo", 10.0, "First Lien")]


def by_cik(rows):
    return {r["cik"]: r for r in rows}


def test_unchanged_build_moves_nothing(tmp_path):
    old = write(tmp_path / "old.parquet", BEFORE)
    new = write(tmp_path / "new.parquet", BEFORE)
    rows = hc.compare(new, old)
    assert [r["cik"] for r in rows] == [A, B, C]
    assert not any(r["moved"] for r in rows)
    assert hc.summarize(rows) == {"funds": 3, "funds_moved": 0, "funds_moved_unexplained": 0,
                                  "unexplained_ciks": [], "fair_value_change": 0.0}


def test_changed_field_added_and_removed_rows(tmp_path):
    old = write(tmp_path / "old.parquet", BEFORE)
    after = [("r1", "1", "Acme Corp", 100.0, "First Lien"),      # name fixed
             ("r2", "1", "Bolt", 55.0, "First Lien"),            # value changed
             ("r3", "2", "Cork", 70.0, None),                    # a lien lost: no rule flags this
             ("r4", "2", "Dune", 30.0, None),
             ("r6", "3", "Fern", 5.0, "First Lien")]             # r5 removed, r6 added
    new = write(tmp_path / "new.parquet", after)
    got = by_cik(hc.compare(new, old, named_ciks=[A]))
    assert got[A]["rows_changed"] == 2 and got[A]["changed_fields"] == "fair_value:1;issuer_name:1"
    assert got[A]["fair_value_change"] == 5.0 and got[A]["named_by_fix"] and got[A]["moved"]
    assert got[B]["rows_changed"] == 1 and got[B]["changed_fields"] == "lien_position:1"
    assert got[B]["moved"] and not got[B]["named_by_fix"] and got[B]["fair_value_change"] == 0.0
    assert (got[C]["rows_added"], got[C]["rows_removed"], got[C]["rows_changed"]) == (1, 1, 0)
    summary = hc.summarize(list(got.values()))
    assert summary["funds_moved"] == 3 and summary["unexplained_ciks"] == [B, C]


def test_star_names_every_fund_and_ignore_drops_a_column(tmp_path):
    old = write(tmp_path / "old.parquet", BEFORE)
    new = write(tmp_path / "new.parquet", [("r1", "1", "Acme", 100.0, "Unitranche")] + BEFORE[1:])
    assert all(r["named_by_fix"] for r in hc.compare(new, old, named_ciks=["*"]))
    assert by_cik(hc.compare(new, old))[A]["rows_changed"] == 1
    assert not by_cik(hc.compare(new, old, ignore=("lien_position",)))[A]["moved"]


def test_a_fund_only_in_one_build_and_new_columns(tmp_path):
    old = write(tmp_path / "old.parquet", BEFORE[:2])
    new = write(tmp_path / "new.parquet", [r + ("x",) for r in BEFORE],
                columns=("row_id", "cik", "issuer_name", "fair_value", "lien_position", "new_column"))
    got = by_cik(hc.compare(new, old))
    assert not got[A]["moved"]  # a column only one build has is not a difference
    assert got[B]["rows_before"] == 0 and got[B]["rows_added"] == 2 and got[B]["moved"]


def test_missing_key_column_is_an_error(tmp_path):
    old = write(tmp_path / "old.parquet", [("1", "Acme", 1.0)], columns=("cik", "issuer_name", "fair_value"))
    new = write(tmp_path / "new.parquet", BEFORE)
    with pytest.raises(ValueError, match="row_id"):
        hc.compare(new, old)
