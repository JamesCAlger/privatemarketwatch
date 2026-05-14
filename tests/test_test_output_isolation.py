from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import PROJECT_ROOT


OUTPUT_ROOT = PROJECT_ROOT / "data" / "output"
FRONTEND_DATA_ROOT = PROJECT_ROOT / "frontend" / "public" / "data"


def _existing_output_file() -> Path:
    for path in OUTPUT_ROOT.rglob("*"):
        if path.is_file():
            return path
    pytest.skip("No production output artifact is available to read")


def test_open_blocks_production_output_write():
    path = OUTPUT_ROOT / "_pytest_guard_open.txt"

    with pytest.raises(AssertionError, match="pytest attempted to write protected output path"):
        with open(path, "w", encoding="utf-8"):
            pass


def test_path_open_blocks_production_output_write():
    path = OUTPUT_ROOT / "_pytest_guard_path_open.txt"

    with pytest.raises(AssertionError, match="mode='w'"):
        with path.open("w", encoding="utf-8"):
            pass


def test_path_write_text_blocks_frontend_data_write():
    path = FRONTEND_DATA_ROOT / "_pytest_guard_write_text.json"

    with pytest.raises(AssertionError, match="frontend"):
        path.write_text("{}", encoding="utf-8")


def test_append_mode_blocks_production_output_write():
    path = OUTPUT_ROOT / "_pytest_guard_append.txt"

    with pytest.raises(AssertionError, match="mode='a'"):
        with open(path, "a", encoding="utf-8"):
            pass


def test_subdirectory_write_blocks_production_output_write():
    path = OUTPUT_ROOT / "_pytest_guard_subdir" / "artifact.csv"

    with pytest.raises(AssertionError, match="artifact.csv"):
        with open(path, "w", encoding="utf-8"):
            pass


def test_pandas_to_csv_blocks_production_output_write():
    path = OUTPUT_ROOT / "_pytest_guard_pandas.csv"

    with pytest.raises(AssertionError, match="_pytest_guard_pandas.csv"):
        pd.DataFrame([{"value": 1}]).to_csv(path, index=False)


def test_production_output_reads_are_allowed():
    path = _existing_output_file()

    with open(path, "rb") as handle:
        handle.read(1)


def test_tmp_path_writes_are_allowed(tmp_path):
    path = tmp_path / "allowed.csv"

    path.write_text("value\n1\n", encoding="utf-8")

    assert path.read_text(encoding="utf-8") == "value\n1\n"
