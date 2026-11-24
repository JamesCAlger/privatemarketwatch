"""The CI fixture build: parse the fixture filings, load the fixture readings, build and test with dbt. See README.md.

Usage (from anywhere; the same command locally and in CI):
  <python> warehouse/ci/run_fixture_build.py [--work DIR]

<python> is the interpreter that has dbt installed beside it (warehouse/.venv locally, the job's Python in CI).
Everything is written under the work folder (default: a new temporary folder): the filed layer, the readings, the
schema-only stand-ins for data/output, the DuckDB file, dbt's target and log folders. Nothing in the repository is
written, and nothing under data/ or warehouse/data/ is read. Exit code 0 only when every step passes.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
WAREHOUSE = HERE.parent
REPO = WAREHOUSE.parent
FIXTURE = HERE / "fixture"
STEP_TIMEOUT = 900  # seconds per step; the whole build takes well under a minute
FORBIDDEN = [REPO / "data", WAREHOUSE / "data", WAREHOUSE / "target"]

# What dbt runs, in three steps (README.md, "What it covers"). The selection lives here only.
# 1. dbt run: the views the unit tests of cmp_row_set and cmp_excluded_quarter read their column types from, built over
#    empty stand-ins of the pipeline's files. Nothing else reads them.
UNIT_TEST_INPUTS = ["stg_v05_scope", "stg_holdings", "stg_fund_financials"]
# 2. dbt build: everything that builds from the filed layer, the readings and the seeds alone, with every data test
#    whose parents are all in that set (--indirect-selection cautious; a test that also reads a model left out, such
#    as stg_holdings, is left out) and four hand-written tests that read no model. Baseline tests are left out: their
#    ceilings are measured on real data. The hand-written tests named singly read no model (filed_one_filing_row_per_
#    folder reads the filed folder itself), so no model selection brings them in. Left out by not being selected: every model that reads data/output (the step
#    1 staging views other than the unit-test inputs, the marts, cmp_row_set, cmp_excluded_quarter).
BUILD_SELECT = [
    "path:models/staging/filed", "path:models/staging/readings", "path:models/staging/stg_v05_scope.sql",
    "resource_type:seed", "path:models/staging/stg_fx_rate.sql", "path:models/intermediate/int_*.sql",
    "path:tests/int_source_row_text_patterns.sql", "path:tests/concept_release_unmatched_fixture.sql",
    "path:tests/concept_rule_namespace_gaps_fixture.sql", "path:tests/filed_one_filing_row_per_folder.sql",
]
BUILD_EXCLUDE = ["path:tests/baseline_*.sql"]
# 2b. dbt run --empty: the two comparison models the cmp_amount and cmp_rate unit tests read (slice 3 Task 4 fix round
#     1; cmp_rate since slice 4 Task 4), built with no rows over the stand-ins, only so the unit tests can read their
#     column types. No test of theirs runs here; cmp_amount and cmp_rate themselves are not built in CI.
EMPTY_UNIT_TEST_INPUTS = ["cmp_row_set", "cmp_excluded_quarter"]
# 3. dbt test: every unit test (dbt build runs a unit test only when its model is built, so those of the two cmp
#    models need this step; the int_* ones run again, which costs seconds) and the one baseline whose ceiling is a
#    rule, not a measurement: production_wrapper_changed (0), here on the fixture's wrapper copy and its stand-in, and
#    wrapper_copy_changed_since_load (0), the fixture's copy against the hash the loader recorded in step (b), and
#    row_store_changed_since_load (0), the fixture's two row stores against the hashes recorded in step (b), and
#    agent_store_changed_since_load (0), the fixture's two agent store folders likewise (slice 5 Task 2).
TEST_SELECT = ["test_type:unit", "path:tests/baseline_production_wrapper_changed.sql",
               "path:tests/baseline_wrapper_copy_changed_since_load.sql",
               "path:tests/baseline_row_store_changed_since_load.sql",
               "path:tests/baseline_agent_store_changed_since_load.sql"]


def _inside(path, folder):
    try:
        path.relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _run(name, cmd, cwd, env):
    print(f"== {name}: {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, timeout=STEP_TIMEOUT)
    if result.returncode != 0:
        print(f"== {name} FAILED (exit {result.returncode})", flush=True)
        sys.exit(result.returncode)


def _dbt():
    folder = Path(sys.executable).parent
    for name in ("dbt.exe", "dbt"):
        if (folder / name).exists():
            return folder / name
    found = shutil.which("dbt")
    if not found:
        sys.exit("dbt is not installed beside this Python or on PATH")
    return Path(found)


def _empty_holdings(columns_csv, out_path):
    """An empty Parquet file with the column names and types listed in columns_csv (no rows)."""
    with open(columns_csv, encoding="utf-8", newline="") as fh:
        cols = [(r["column_name"], r["column_type"]) for r in csv.DictReader(fh)]
    select = ", ".join(f'cast(null as {t}) as "{n}"' for n, t in cols)
    target = out_path.as_posix().replace("'", "''")
    con = duckdb.connect()
    try:
        con.execute(f"copy (select {select} limit 0) to '{target}' (format parquet)")
    finally:
        con.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--work", help="empty or new folder for every output (default: a new temporary folder)")
    args = p.parse_args(argv)

    work = Path(args.work).resolve() if args.work else Path(tempfile.mkdtemp(prefix="warehouse_ci_"))
    if any(_inside(work, f) for f in FORBIDDEN + [FIXTURE]):
        sys.exit(f"work folder {work} is inside the repository's data, target or fixture folder")
    work.mkdir(parents=True, exist_ok=True)
    if any(work.iterdir()):
        sys.exit(f"work folder {work} is not empty")
    print(f"work folder: {work}", flush=True)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(WAREHOUSE)
    env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
    env["WAREHOUSE_CI_DUCKDB"] = (work / "ci.duckdb").as_posix()
    scope = FIXTURE / "scope.json"

    # (a) the fixture filings into a filed layer
    _run("parse", [sys.executable, "-m", "filed_parser", "--raw", FIXTURE / "raw", "--out", work / "filed",
                   "--scope-file", scope], WAREHOUSE, env)
    # (b) the fixture wrapper copy, its production stand-in and row stores into readings
    _run("load readings", [sys.executable, "-m", "readings_loader", "--out", work / "readings", "--scope-file", scope,
                           "--wrappers", FIXTURE / "wrappers", "--production-wrappers", FIXTURE / "production_wrappers",
                           "--row-corrections", FIXTURE / "row_corrections.csv",
                           "--row-corrections-by-context", FIXTURE / "row_corrections_by_context.csv",
                           "--agent-b2-corrections", FIXTURE / "agent_b2_corrections",
                           "--agent-investigate-rules", FIXTURE / "agent_investigate_rules"], WAREHOUSE, env)
    # Schema-only stand-ins for data/output: read only to give the unit tests' input views their column types.
    output = work / "output"
    output.mkdir()
    _empty_holdings(FIXTURE / "output" / "private_markets_holdings.columns.csv", output / "private_markets_holdings.parquet")
    shutil.copyfile(FIXTURE / "output" / "fund_financials.csv", output / "fund_financials.csv")

    # (c) dbt, on its own target and database file, with every path from --vars
    dbt_vars = json.dumps({
        "filed_dir": (work / "filed").as_posix(),
        "readings_dir": (work / "readings").as_posix(),
        "thresholds_file": scope.as_posix(),
        "output_dir": output.as_posix(),
        # the wrapper drift view hashes these files at build time (stg_wrapper_drift)
        "wrappers_dir": (FIXTURE / "wrappers").as_posix(),
        "production_wrappers_dir": (FIXTURE / "production_wrappers").as_posix(),
        # the row-store drift view hashes these files at build time (stg_row_store_drift); the same files step (b) loads
        "row_store_files": {"row_corrections": (FIXTURE / "row_corrections.csv").as_posix(),
                            "row_corrections_by_context": (FIXTURE / "row_corrections_by_context.csv").as_posix()},
        # the agent-store drift view hashes these folders' files at build time (stg_agent_store_drift); the same folders
        # step (b) loads
        "agent_store_dirs": {"agent_b2_corrections": (FIXTURE / "agent_b2_corrections").as_posix(),
                             "agent_investigate_rules": (FIXTURE / "agent_investigate_rules").as_posix()},
        # stg_fx_rate reads this small committed rate file (same columns as the FRED H.10 file production uses)
        "fx_rate_file": (FIXTURE / "fx_rates.csv").as_posix(),
        # switches on tests/ci_fixture_expected_roles.sql (the role each fixture context must get),
        # tests/ci_fixture_expected_amounts.sql (the amount each fixture position field must get) and
        # tests/ci_fixture_expected_rates.sql (the rate fields and maturity date, slice 4 Task 5)
        "ci_fixture": True,
    })
    common = ["--profiles-dir", ".", "--target", "ci", "--target-path", work / "target", "--log-path", work / "logs",
              "--vars", dbt_vars, "--no-version-check"]
    dbt = _dbt()
    _run("dbt run (unit-test input views)", [dbt, "run", "--select", *UNIT_TEST_INPUTS, *common], WAREHOUSE, env)
    _run("dbt build (fixture selection)", [dbt, "build", "--select", *BUILD_SELECT, "--exclude", *BUILD_EXCLUDE,
                                           "--indirect-selection", "cautious", *common], WAREHOUSE, env)
    _run("dbt run --empty (inputs of the cmp_amount unit test)", [dbt, "run", "--empty", "--select",
                                                                   *EMPTY_UNIT_TEST_INPUTS, *common], WAREHOUSE, env)
    _run("dbt test (unit tests, wrapper drift)", [dbt, "test", "--select", *TEST_SELECT, *common], WAREHOUSE, env)
    print("== fixture build passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
