"""Task 5 pre-check: do production's wrapper readers and the wrapper JSON schema accept a new top-level key?

Reads the named wrappers from data/overrides/bdc_xbrl_wrappers (read only), adds a top-level `reading_rules` list in
memory, writes the copies to a temporary folder OUTSIDE the repository, then:
  1. loads that folder through pipeline.source_encodings.load_encodings
  2. loads it through pipeline.bdc_xbrl_wrapper._load_specs_from_json
  3. validates each copy against schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json (as tests/test_source_encodings.py
     test_the_v05_wrappers_fit_the_wrapper_schema does)
Nothing under the repository is written. Run from the repository root with the machine Python (pandas, jsonschema):
    C:\\Users\\alger\\miniconda3\\python.exe warehouse/scripts/slice2/check_wrapper_extra_key.py <tmp_dir>
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

CIKS = ["0001287750", "0001812554", "0001837532"]
PROBE = [{"target": "role", "action": "probe_only", "concept_namespace": "http://example.invalid/*",
          "concept_local": "Probe", "evidence": "probe"}]


def main(tmp_dir):
    import jsonschema
    from pipeline import bdc_xbrl_wrapper, source_encodings

    out = Path(tmp_dir)
    out.mkdir(parents=True, exist_ok=True)
    if ROOT in out.resolve().parents or out.resolve() == ROOT:
        raise SystemExit("temporary folder must be outside the repository")
    schema = json.loads((ROOT / "schemas/bdc_xbrl_wrapper/wrapper_v3.schema.json").read_text(encoding="utf-8"))
    for cik in CIKS:
        wrapper = json.loads((ROOT / "data/overrides/bdc_xbrl_wrappers" / f"{cik}.json").read_text(encoding="utf-8"))
        before = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(wrapper)]
        wrapper["reading_rules"] = PROBE
        (out / f"{cik}.json").write_text(json.dumps(wrapper, indent=2), encoding="utf-8")
        after = [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(wrapper)]
        print(f"{cik} schema errors without the key: {len(before)}; with it: {len(after)} {after}")
    enc = source_encodings.load_encodings(out)
    print(f"source_encodings.load_encodings: {len(enc)} wrappers loaded: {sorted(enc)}")
    specs = bdc_xbrl_wrapper._load_specs_from_json(out)
    print(f"bdc_xbrl_wrapper._load_specs_from_json: {len(specs)} specs loaded: {sorted(specs)}")


if __name__ == "__main__":
    main(sys.argv[1])
