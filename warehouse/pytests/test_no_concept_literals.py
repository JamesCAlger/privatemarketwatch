"""Slice 3 Task 1: the standard XBRL concepts are defined once, in seeds/concept_map.csv.

No SQL file under models/, macros/ or tests/ may write a standard concept's local name (in code or in a comment):
a model reads the seed instead. Unit-test rows in the .yml files are invented input data and are not checked.
"""
import csv
import re
from pathlib import Path

WAREHOUSE = Path(__file__).resolve().parent.parent
SEED = WAREHOUSE / "seeds" / "concept_map.csv"
CHECKED = ["models", "macros", "tests"]


def standard_concepts():
    with open(SEED, encoding="utf-8", newline="") as fh:
        return sorted({row["concept_local"] for row in csv.DictReader(fh)})


def literals_in(text, concepts):
    """The standard concept local names written in text, as whole words."""
    return sorted(c for c in concepts if re.search(r"(?<![A-Za-z0-9_])" + re.escape(c) + r"(?![A-Za-z0-9_])", text))


def test_seed_lists_the_concepts_slice_2_read():
    concepts = standard_concepts()
    assert len(concepts) == 11
    assert all(re.fullmatch(r"[A-Za-z]+", c) for c in concepts)


def test_no_sql_file_writes_a_standard_concept():
    concepts = standard_concepts()
    found = {}
    for folder in CHECKED:
        for path in sorted((WAREHOUSE / folder).rglob("*.sql")):
            hits = literals_in(path.read_text(encoding="utf-8"), concepts)
            if hits:
                found[path.relative_to(WAREHOUSE).as_posix()] = hits
    assert found == {}


def test_the_check_finds_a_literal_and_ignores_a_longer_name():
    concepts = ["InvestmentOwnedAtFairValue", "InvestmentInterestRate"]
    assert literals_in("where concept_local = 'InvestmentOwnedAtFairValue'", concepts) == ["InvestmentOwnedAtFairValue"]
    # a longer local name that starts with a standard one is not that concept
    assert literals_in("concept_local = 'InvestmentInterestRatePaidInKind'", concepts) == []
    assert literals_in("field = 'fair_value'", concepts) == []
