"""Engine-agnostic regression gates for identifier-drift mis-matches.

These encode the *behavioral contract* surfaced by spot-checking the J06
fuzzy-match oracle flags (see docs/position_match_identifier_drift_findings.md),
NOT a specific wrapper rule.  They are deliberately written against the matching
identity contract so they survive the planned wrapper-system overhaul/split: any
new normalization/extraction implementation must satisfy them.

Both gates currently FAIL (marked strict xfail).  When the fix lands they will
XPASS -> the strict marker turns that into a failure, forcing removal of the
marker and confirming the contract is met.

Evidence (CIK 1930087, LeadsOnline, 2024-06-30 -> 2024-09-30):
  begin: "LeadsOnline, LLC, LLC, One stop 2"  (FV 2,259k)
  end:   "LeadsOnline, LLC, One stop 2"        (FV 2,253k)   <- correct partner
  but J06 flagged the produced match  One stop 2 -> One stop 3 (780k)  [WRONG].
Root cause, both confirmed via _normalize_name_sql:
  1. trailing tranche ordinal is stripped: "...One stop 2" and "...One stop 3"
     both normalize to "...one stop" -> tranches indistinguishable in fuzzy tier.
  2. doubled "LLC, LLC" is not collapsed -> exact-name tier misses, forcing the
     fuzzy tier that then mis-pairs by FV/order.
"""

from __future__ import annotations

import duckdb
import pytest

from pipeline.position_matching import _normalize_name_sql


def _norm(s: str) -> str:
    con = duckdb.connect()
    lit = "'" + s.replace("'", "''") + "'"
    try:
        return con.execute(f"SELECT {_normalize_name_sql(lit)}").fetchone()[0]
    finally:
        con.close()


@pytest.mark.xfail(
    strict=True,
    reason="Matching normalizer strips trailing tranche ordinals, collapsing "
           "distinct tranches (One stop 2 vs 3). Remove xfail when matching "
           "identity becomes tranche-aware. See identifier_drift_findings.",
)
def test_distinct_tranche_ordinals_are_not_collapsed():
    # A first-lien tranche 2 and tranche 3 of the same borrower are distinct
    # index constituents and must keep distinct matching identities.
    n2 = _norm("LeadsOnline, LLC, One stop 2")
    n3 = _norm("LeadsOnline, LLC, One stop 3")
    assert n2 != n3, (
        f"tranche ordinal stripped: both normalized to {n2!r}"
    )


@pytest.mark.xfail(
    strict=True,
    reason="Doubled 'LLC, LLC' extraction artifact is not collapsed, so the "
           "same position fails exact-name matching across quarters. Remove "
           "xfail when identifier normalization/extraction de-duplicates "
           "repeated entity suffixes. See identifier_drift_findings.",
)
def test_doubled_entity_suffix_collapses_to_single():
    # "Foo, LLC, LLC" (an extraction doubling) is the same borrower as
    # "Foo, LLC" and must share a matching identity.
    doubled = _norm("LeadsOnline, LLC, LLC, One stop 2")
    single = _norm("LeadsOnline, LLC, One stop 2")
    assert doubled == single, (
        f"doubled suffix not collapsed: {doubled!r} != {single!r}"
    )


def test_normalizer_is_callable_contract_anchor():
    # Non-xfail anchor: documents the function the gates depend on. If the
    # overhaul renames/moves the matching normalizer, this fails loudly and
    # points maintainers at the two contract gates above.
    out = _norm("Acme Corp.")
    assert isinstance(out, str) and out
