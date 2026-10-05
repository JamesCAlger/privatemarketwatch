"""PM_OUTPUT_DIR redirects every derived output path (fund sandbox runs); unset, nothing changes."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ("from pipeline import config; "
         "print(config.OUTPUT_DIR); print(config.UNIFIED_HOLDINGS_FILE); "
         "print(config.ORACLE_OUTPUT_DIR); print(config.OVERRIDES_DIR); print(config.RAW_DIR)")


def _probe(env_value):
    env = {k: v for k, v in os.environ.items() if k != "PM_OUTPUT_DIR"}
    if env_value is not None:
        env["PM_OUTPUT_DIR"] = str(env_value)
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return [Path(line) for line in out.stdout.strip().splitlines()]


def test_default_output_root_is_data_output():
    output, holdings, oracle, overrides, raw = _probe(None)
    assert output == ROOT / "data" / "output"
    assert holdings == ROOT / "data" / "output" / "private_markets_holdings.csv"


def test_override_moves_outputs_but_not_inputs(tmp_path):
    sandbox = tmp_path / "sandbox_output"
    output, holdings, oracle, overrides, raw = _probe(sandbox)
    assert output == sandbox.resolve()
    assert holdings == sandbox.resolve() / "private_markets_holdings.csv"
    assert oracle == sandbox.resolve() / "oracle"
    assert overrides == ROOT / "data" / "overrides"
    assert raw == ROOT / "data" / "raw"
