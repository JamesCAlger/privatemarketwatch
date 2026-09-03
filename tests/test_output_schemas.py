"""Phase-1 Parquet schema contracts + typed companion writer."""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from pipeline.output_schemas import ALLOWED_TYPES, OUTPUT_SCHEMAS, OutputSchemaError
from pipeline.utils import write_parquet_companion


# ---------------------------------------------------------------------------
# Contract structure
# ---------------------------------------------------------------------------

class TestContractStructure:
    def test_eleven_artifacts(self):
        assert len(OUTPUT_SCHEMAS) == 11

    def test_all_types_allowed(self):
        for name, schema in OUTPUT_SCHEMAS.items():
            bad = {c: t for c, t in schema.items() if t not in ALLOWED_TYPES}
            assert not bad, f"{name}: disallowed types {bad}"

    def test_cik_is_varchar_everywhere(self):
        for name, schema in OUTPUT_SCHEMAS.items():
            if "cik" in schema:
                assert schema["cik"] == "VARCHAR", name

    def test_fair_value_is_double_where_present(self):
        for name, schema in OUTPUT_SCHEMAS.items():
            if "fair_value" in schema:
                assert schema["fair_value"] == "DOUBLE", name

    def test_report_date_is_date_where_present(self):
        for name, schema in OUTPUT_SCHEMAS.items():
            if "report_date" in schema:
                assert schema["report_date"] == "DATE", name

    def test_no_empty_schemas(self):
        for name, schema in OUTPUT_SCHEMAS.items():
            assert len(schema) >= 10, f"{name}: implausibly small contract"


# ---------------------------------------------------------------------------
# Typed companion writer (uses the smallest contract: position_id_edges, 16 cols)
# ---------------------------------------------------------------------------

EDGE_COLS = list(OUTPUT_SCHEMAS["position_id_edges.csv"].keys())


def _edge_df() -> pd.DataFrame:
    row1 = {c: None for c in EDGE_COLS}
    row1.update({
        "edge_type": "tier_a",
        "position_id": "POS-1",
        "cik": "0001418076",
        "source": "BDC",
        "begin_report_date": "2025-09-30",
        "begin_quarter": "2025q3",
        "begin_issuer_name": "Acme Corp",
        "begin_fair_value": 1000.5,
        "end_report_date": "2025-12-31",
        "end_quarter": "2025q4",
        "end_issuer_name": "Acme Corp",
        "end_fair_value": 990.0,
        "match_method": "A",
        "match_key": "k1",
        "match_score": 1.0,
        "span_months": 3,
    })
    row2 = {c: None for c in EDGE_COLS}  # all-NULL row: the INT32 bug class
    return pd.DataFrame([row1, row2], columns=EDGE_COLS)


class TestTypedCompanion:
    def test_types_and_values_round_trip(self, tmp_path):
        csv = tmp_path / "position_id_edges.csv"
        _edge_df().to_csv(csv, index=False)
        pq = write_parquet_companion(csv, strict=True)
        assert pq is not None and pq.exists()

        con = duckdb.connect()
        schema = {
            r[0]: r[1]
            for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{str(pq).replace(chr(92), '/')}')"
            ).fetchall()
        }
        contract = OUTPUT_SCHEMAS["position_id_edges.csv"]
        assert list(schema.keys()) == list(contract.keys())
        assert schema["cik"] == "VARCHAR"
        assert schema["begin_report_date"] == "DATE"
        assert schema["begin_fair_value"] == "DOUBLE"
        assert schema["span_months"] == "BIGINT"

        rows = con.execute(
            f"SELECT cik, begin_fair_value, span_months FROM "
            f"read_parquet('{str(pq).replace(chr(92), '/')}') ORDER BY cik NULLS LAST"
        ).fetchall()
        con.close()
        # Leading zeros survive (the padding-loss bug class), NULL row intact.
        assert rows[0] == ("0001418076", 1000.5, 3)
        assert rows[1] == (None, None, None)

    def test_bigint_cast_handles_pandas_float_ints(self, tmp_path):
        # pandas emits "3.0" for nullable-int columns; contract must land BIGINT.
        csv = tmp_path / "position_id_edges.csv"
        df = _edge_df()
        df["span_months"] = df["span_months"].astype("float64")  # 3.0 / NaN
        df.to_csv(csv, index=False)
        pq = write_parquet_companion(csv, strict=True)
        con = duckdb.connect()
        val, dtype = con.execute(
            f"SELECT span_months, typeof(span_months) FROM "
            f"read_parquet('{str(pq).replace(chr(92), '/')}') "
            f"WHERE span_months IS NOT NULL"
        ).fetchone()
        con.close()
        assert (val, dtype) == (3, "BIGINT")

    def test_missing_column_raises(self, tmp_path):
        csv = tmp_path / "position_id_edges.csv"
        _edge_df().drop(columns=["match_key"]).to_csv(csv, index=False)
        with pytest.raises(OutputSchemaError, match="match_key"):
            write_parquet_companion(csv, strict=True)

    def test_extra_column_raises(self, tmp_path):
        csv = tmp_path / "position_id_edges.csv"
        df = _edge_df()
        df["surprise"] = "x"
        df.to_csv(csv, index=False)
        with pytest.raises(OutputSchemaError, match="surprise"):
            write_parquet_companion(csv, strict=True)

    def test_reordered_columns_raise(self, tmp_path):
        csv = tmp_path / "position_id_edges.csv"
        df = _edge_df()[list(reversed(EDGE_COLS))]
        df.to_csv(csv, index=False)
        with pytest.raises(OutputSchemaError, match="order_changed"):
            write_parquet_companion(csv, strict=True)

    def test_garbage_in_typed_column_raises_not_nulls(self, tmp_path):
        # CAST (not TRY_CAST): corrupt values must hard-error, never silently null.
        csv = tmp_path / "position_id_edges.csv"
        df = _edge_df()
        df.loc[0, "begin_fair_value"] = "not-a-number"
        df.to_csv(csv, index=False)
        with pytest.raises(OutputSchemaError, match="cast failed"):
            write_parquet_companion(csv, strict=True)
        # No truncated partial file left behind (would crash read_parquet).
        assert not csv.with_suffix(".parquet").exists()

    def test_contract_name_outside_output_dir_defaults_nonstrict(self, tmp_path):
        # Auto mode: tmp-dir fixtures with contract names must not trip the
        # contract (legacy untyped companion instead of OutputSchemaError).
        csv = tmp_path / "position_id_edges.csv"
        _edge_df().drop(columns=["match_key"]).to_csv(csv, index=False)
        pq = write_parquet_companion(csv)  # strict=None -> auto
        assert pq is not None and pq.exists()

    def test_non_contract_file_uses_legacy_path(self, tmp_path):
        csv = tmp_path / "some_random_summary.csv"
        pd.DataFrame({"a": [1], "b": ["x"]}).to_csv(csv, index=False)
        pq = write_parquet_companion(csv)
        assert pq is not None and pq.exists()
