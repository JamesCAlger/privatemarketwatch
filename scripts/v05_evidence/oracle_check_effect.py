"""Read-only: what a change to oracle checks A01 and A04 does on the published outputs.

    python scripts/v05_evidence/oracle_check_effect.py <path to the previous oracle_checks.py>

Runs both versions of A01 (subtotal arithmetic) and A04 (holdings against filed investments) in
memory on the published source-reconciliation detail, holdings and fund financials, for the
wrapper funds, and prints status counts and every fund-quarter whose status differs (at most 60).
Writes nothing. Get the previous file with: git show <commit>:pipeline/oracle_checks.py > <file>
"""
import importlib.util
import sys
from collections import Counter
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline import config  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


con = duckdb.connect()
con.execute("SET memory_limit='4GB'")
out = config.OUTPUT_DIR.as_posix()
wrapped = ", ".join("'%s'" % p.stem for p in (config.OVERRIDES_DIR / "bdc_xbrl_wrappers").glob("*.json"))
detail = con.execute(f"""SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS report_date,
        CAST(accession_number AS VARCHAR) AS accession_number, CAST(period AS VARCHAR)[:10] AS period,
        CAST(source_wrapper_disposition AS VARCHAR) AS source_wrapper_disposition,
        CAST(source_wrapper_parent_key AS VARCHAR) AS source_wrapper_parent_key,
        CAST(source_wrapper_family AS VARCHAR) AS source_wrapper_family, source_fair_value
    FROM read_parquet('{out}/source_reconciliation_detail.parquet')
    WHERE lpad(CAST(cik AS VARCHAR),10,'0') IN ({wrapped})
      AND (CAST(source_wrapper_disposition AS VARCHAR) LIKE '%_rollup' OR CAST(source_wrapper_disposition AS VARCHAR) LIKE '%_position_leaf')""").df()
holdings = con.execute(f"""SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS report_date,
        fair_value, source, accounting_record_class
    FROM read_parquet('{out}/private_markets_holdings.parquet')
    WHERE source = 'bdc' AND lpad(CAST(cik AS VARCHAR),10,'0') IN ({wrapped})""").df()
financials = con.execute(f"""SELECT lpad(CAST(cik AS VARCHAR),10,'0') AS cik, CAST(report_date AS VARCHAR)[:10] AS report_date,
        investments_at_fair_value, total_assets
    FROM read_csv('{out}/fund_financials.csv', header=true, all_varchar=true, sample_size=-1) WHERE source = 'companyfacts'""").df()
print("rows: detail %d, holdings %d, fund financials %d" % (len(detail), len(holdings), len(financials)))
before, after = load(sys.argv[1], "oracle_before"), load(REPO / "pipeline/oracle_checks.py", "oracle_after")
for name, args in (("A01", (detail,)), ("A04", (holdings, financials))):
    function = "check_A01_subtotal_arithmetic" if name == "A01" else "check_A04_gav_reconciliation"
    old = {(r.cik, r.report_date): r for r in getattr(before, function)(*args) if r.cik}
    new = {(r.cik, r.report_date): r for r in getattr(after, function)(*args) if r.cik}
    print("%s fund-quarters %d | before %s | after %s" % (name, len(new), dict(Counter(r.status for r in old.values())),
                                                           dict(Counter(r.status for r in new.values()))))
    changed = sorted(k for k in new if k in old and old[k].status != new[k].status)
    moves = Counter((old[k].status, new[k].status) for k in changed)
    print("   changed %d: %s" % (len(changed), {"%s -> %s" % m: n for m, n in moves.items()}))
    for key in changed[:60]:
        print("   %s | %s | %s -> %s | %s" % (key[0], key[1], old[key].status, new[key].status, str(old[key].message)[:110]))
