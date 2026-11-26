"""Slice 5 Task 1, item d: every per-detail ceiling has a test that counts it.

dbt_project.yml vars cmp_amount_detail_max and cmp_rate_detail_max give a ceiling per basis, field and 'cause|detail'.
The generic tests baseline_cmp_amount_cause / baseline_cmp_rate_cause (tests/generic) leave such a detail out of its
cause's count and count it only in a test entry of its own in models/intermediate/_intermediate.yml, with the same
basis, field, cause and detail. A key with no such entry is counted nowhere: its rows could grow without any test
seeing them. This check fails on such a key. (A test entry with no key fails in dbt itself: the generic test reads its
ceiling from the var.)
"""
from pathlib import Path

import yaml

WAREHOUSE = Path(__file__).resolve().parent.parent
PROJECT = WAREHOUSE / "dbt_project.yml"
MODELS_YML = WAREHOUSE / "models" / "intermediate" / "_intermediate.yml"
# ceiling var -> the generic test that counts one of its details
PAIRS = {"cmp_amount_detail_max": "baseline_cmp_amount_cause", "cmp_rate_detail_max": "baseline_cmp_rate_cause"}


def ceiling_keys(project, var):
    """(basis, field, cause, detail) of every key of one detail ceiling var."""
    keys = set()
    for basis, fields in (project["vars"].get(var) or {}).items():
        for field, details in (fields or {}).items():
            for key in details or {}:
                cause, detail = key.split("|", 1)
                keys.add((basis, field, cause, detail))
    return keys


def entries_of(node, test_name):
    """(basis, field, cause, detail) of every entry of a generic test anywhere in a parsed yml, with a detail."""
    found = set()
    if isinstance(node, dict):
        entry = node.get(test_name)
        if isinstance(entry, dict):
            args = entry.get("arguments") or {}
            if args.get("detail") is not None:
                found.add((args.get("basis"), args.get("field"), args.get("cause"), args.get("detail")))
        for value in node.values():
            found |= entries_of(value, test_name)
    elif isinstance(node, list):
        for value in node:
            found |= entries_of(value, test_name)
    return found


def missing(project, models_yml):
    """The ceiling keys with no test entry, as 'var basis field cause|detail'."""
    out = []
    for var, test_name in PAIRS.items():
        tested = entries_of(models_yml, test_name)
        for basis, field, cause, detail in sorted(ceiling_keys(project, var) - tested):
            out.append(f"{var} {basis} {field} {cause}|{detail}")
    return out


def load(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_every_detail_ceiling_has_a_test():
    project, models_yml = load(PROJECT), load(MODELS_YML)
    assert missing(project, models_yml) == []


def test_the_project_has_detail_ceilings_to_check():
    project = load(PROJECT)
    assert all(ceiling_keys(project, var) for var in PAIRS)


def test_the_check_finds_a_key_without_a_test():
    project = {"vars": {"cmp_amount_detail_max": {"published": {"cost": {"owner_review|made_up": 1}}},
                        "cmp_rate_detail_max": {"published": {"spread": {"convention|tested": 2}}}}}
    models_yml = {"models": [{"name": "cmp_rate", "data_tests": [
        {"baseline_cmp_rate_cause": {"arguments": {"basis": "published", "field": "spread", "cause": "convention",
                                                   "detail": "tested"}}},
        # the same detail under the other generic test does not count for the amount var
        {"baseline_cmp_rate_cause": {"arguments": {"basis": "published", "field": "cost", "cause": "owner_review",
                                                   "detail": "made_up"}}}]}]}
    assert missing(project, models_yml) == ["cmp_amount_detail_max published cost owner_review|made_up"]
