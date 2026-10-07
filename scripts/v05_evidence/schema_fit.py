"""Read-only: do a sandbox's output files fit their schema contracts?

    python scripts/v05_evidence/schema_fit.py <label>

For every artifact with a contract in pipeline/output_schemas.py that exists in the sandbox:
columns must be the contract's, in order; every non-empty value must cast to its contract type.
Also checks that each wrapper of the sandbox's funds validates against the wrapper JSON schema.
Exit 1 if anything does not fit.
"""
import json
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from pipeline.output_schemas import OUTPUT_SCHEMAS  # noqa: E402

sandbox = REPO / "scratch/fund_sandbox" / sys.argv[1]
out = sandbox / "output"
con = duckdb.connect()
bad = 0
print("artifact | rows | columns | cast failures")
for name, contract in sorted(OUTPUT_SCHEMAS.items()):
    path = out / name
    if not path.exists():
        print("   %s | (not in sandbox)" % name)
        continue
    reader = "read_csv('%s', header=true, all_varchar=true, sample_size=-1)" % path.as_posix()
    columns = [r[0] for r in con.execute("DESCRIBE SELECT * FROM " + reader).fetchall()]
    wanted = list(contract)
    if columns != wanted:
        missing = [c for c in wanted if c not in columns]
        extra = [c for c in columns if c not in wanted]
        note = "missing %s, extra %s" % (missing, extra) if missing or extra else "same columns, different order"
        print("   %s | COLUMNS DO NOT FIT: %s" % (name, note))
        bad += 1
        continue
    checks = ", ".join(
        "count(*) FILTER (WHERE nullif(trim(\"%s\"), '') IS NOT NULL AND TRY_CAST(\"%s\" AS %s) IS NULL)" % (c, c, t)
        for c, t in contract.items() if t != "VARCHAR")
    row = con.execute("SELECT count(*)%s FROM %s" % (", " + checks if checks else "", reader)).fetchone()
    typed = [c for c, t in contract.items() if t != "VARCHAR"]
    failures = {c: n for c, n in zip(typed, row[1:]) if n}
    bad += bool(failures)
    print("   %s | %d | %d | %s" % (name, row[0], len(columns), failures or "none"))

import jsonschema  # noqa: E402

schema = json.loads((REPO / "schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json").read_text(encoding="utf-8"))
ciks = json.loads((sandbox / "run.json").read_text(encoding="utf-8"))["ciks"]
print("wrapper | fits the wrapper schema")
for cik in ciks:
    wrapper = json.loads((REPO / "data/overrides/bdc_xbrl_wrappers" / (cik + ".json")).read_text(encoding="utf-8"))
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(wrapper), key=lambda e: list(e.path))
    bad += bool(errors)
    print("   %s | %s" % (cik, "yes" if not errors else "NO: " + "; ".join(e.message[:80] for e in errors[:3])))
print("fits" if not bad else "DOES NOT FIT: %d problem(s)" % bad)
raise SystemExit(1 if bad else 0)
