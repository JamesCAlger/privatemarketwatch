"""Tests for the anchor-based row_id (unified_holdings._assign_row_ids).

row_id = 'ROW-' + md5[:16] of the row's source anchor:
    bdc:   source|accession_number|src_context_id
    nport: source|accession_number|nport_holding_id
Rows lacking an anchor part fall back to the legacy natural-key hash.
row_id_basis records which regime produced each id. Anchored ids are
invariant to value corrections (principal/shares) -- the anchor names the
filing fact context, not the published content.
"""

import hashlib
import re

import pandas as pd

from pipeline.unified_holdings import _assign_row_ids

_ROW_ID_RE = re.compile(r"^ROW-[0-9a-f]{16}$")


def _expected(anchor: str) -> str:
    return "ROW-" + hashlib.md5(anchor.encode()).hexdigest()[:16]


def _base_df() -> pd.DataFrame:
    return pd.DataFrame({
        "cik": ["0000000001", "0000000001", "0000000002", "0000000003"],
        "source": ["bdc", "bdc", "nport", "bdc"],
        "report_date": ["2025-12-31"] * 4,
        "accession_number": [
            "0000000001-26-000001",
            "0000000001-26-000001",
            "0000000002-26-000009",
            "",  # no accession -> natural-key fallback
        ],
        "src_context_id": ["ctx_acme", "ctx_beta", "", ""],
        "bdc_investment_identifier": [
            "Acme Corp | First Lien Term Loan | SOFR+5.00%",
            "Beta LLC | Second Lien Term Loan | SOFR+8.50%",
            "",
            "Gamma Co | Equity",
        ],
        "nport_holding_id": ["", "", "HOLDING-123", ""],
        "principal_amount": [1000000.0, 2000000.0, None, None],
        "shares_held": [None, None, 500.0, 100.0],
        "issuer_name": ["Acme Corp", "Beta LLC", "Gamma Fund", "Gamma Co"],
        "fair_value": [990000.0, 1980000.0, 51000.0, 5000.0],
        "cost": [1000000.0, 2000000.0, 50000.0, 5000.0],
        "bdc_dimensions_raw": ["", "", "", ""],
    })


def test_format_uniqueness_and_basis_column():
    out = _assign_row_ids(_base_df())
    assert "row_id" in out.columns and "row_id_basis" in out.columns
    assert out["row_id"].map(lambda v: bool(_ROW_ID_RE.match(v))).all()
    assert out["row_id"].nunique() == len(out)
    assert list(out["row_id_basis"]) == [
        "src_anchor", "src_anchor", "src_anchor", "natural_key"]


def test_bdc_anchor_id_is_md5_of_source_accession_context():
    out = _assign_row_ids(_base_df())
    assert out.loc[0, "row_id"] == _expected(
        "bdc|0000000001-26-000001|ctx_acme")
    assert out.loc[1, "row_id"] == _expected(
        "bdc|0000000001-26-000001|ctx_beta")


def test_nport_anchor_id_uses_holding_id():
    out = _assign_row_ids(_base_df())
    assert out.loc[2, "row_id"] == _expected(
        "nport|0000000002-26-000009|HOLDING-123")


def test_anchored_id_survives_principal_correction():
    # THE point of the migration: a value correction must not rename the row.
    a = _assign_row_ids(_base_df())
    changed = _base_df()
    changed.loc[0, "principal_amount"] = 999999.0
    b = _assign_row_ids(changed)
    assert a.loc[0, "row_id"] == b.loc[0, "row_id"]
    assert b.loc[0, "row_id_basis"] == "src_anchor"


def test_anchored_id_survives_issuer_name_drift():
    a = _assign_row_ids(_base_df())
    drifted = _base_df()
    drifted.loc[0, "issuer_name"] = "ACME Corporation, Inc."
    b = _assign_row_ids(drifted)
    assert a.loc[0, "row_id"] == b.loc[0, "row_id"]


def test_fallback_rows_use_natural_key_and_stay_content_sensitive():
    a = _assign_row_ids(_base_df())
    changed = _base_df()
    changed.loc[3, "shares_held"] = 200.0  # natural-key field on fallback row
    b = _assign_row_ids(changed)
    assert a.loc[3, "row_id_basis"] == "natural_key"
    assert a.loc[3, "row_id"] != b.loc[3, "row_id"]


def test_bdc_row_missing_context_falls_back():
    df = _base_df()
    df.loc[0, "src_context_id"] = ""
    out = _assign_row_ids(df)
    assert out.loc[0, "row_id_basis"] == "natural_key"
    assert _ROW_ID_RE.match(out.loc[0, "row_id"])


def test_missing_anchor_columns_entirely_falls_back():
    # frames built without staging (e.g. some test fixtures) must not crash
    df = _base_df().drop(columns=["src_context_id", "accession_number"])
    out = _assign_row_ids(df)
    assert (out["row_id_basis"] == "natural_key").all()
    assert out["row_id"].nunique() == len(out)


def test_row_order_invariance():
    a = _assign_row_ids(_base_df())
    shuffled = _base_df().sample(frac=1, random_state=7).reset_index(drop=True)
    b = _assign_row_ids(shuffled)
    map_a = dict(zip(a["issuer_name"], a["row_id"]))
    map_b = dict(zip(b["issuer_name"], b["row_id"]))
    assert map_a == map_b


def test_duplicate_anchor_assigns_unique_ids(caplog):
    """Duplicate anchor keys get distinct ids via collision suffix; no warning."""
    import logging
    df = _base_df()
    twin = df.iloc[[0]].copy()
    both = pd.concat([df, twin], ignore_index=True)  # same ctx twice
    with caplog.at_level(logging.WARNING):
        out = _assign_row_ids(both)
    assert len(out) == 5
    # collision suffix resolves duplicates -- all ids must be unique
    assert out["row_id"].nunique() == 5
    # no warning expected: suffix prevents any post-assignment duplicates
    assert "uniqueness violated" not in caplog.text.lower()


def test_empty_frame():
    out = _assign_row_ids(pd.DataFrame())
    assert "row_id" in out.columns and "row_id_basis" in out.columns
    assert len(out) == 0


# ---------------------------------------------------------------------------
# Collision-suffix tests (Task 2: row_id uniqueness invariant)
# ---------------------------------------------------------------------------

def _frame(rows: list) -> pd.DataFrame:
    """Build a minimal DataFrame suitable for _assign_row_ids from row dicts.

    Provides all columns required by _assign_row_ids / compute_natural_keys;
    callers only need to supply the fields that matter for their test.
    """
    defaults = {
        "cik": "0000000001",
        "source": "bdc",
        "report_date": "2025-12-31",
        "accession_number": "0000000001-26-000001",
        "src_context_id": "ctx1",
        "bdc_investment_identifier": "",
        "nport_holding_id": "",
        "principal_amount": None,
        "shares_held": None,
        "issuer_name": "Test Corp",
        "fair_value": 1.0,
        "cost": 1.0,
        "bdc_dimensions_raw": "",
    }
    merged = [{**defaults, **r} for r in rows]
    return pd.DataFrame(merged)


def test_unique_anchor_ids_unchanged():
    """Pin: non-colliding anchor id must equal the pre-change formula exactly."""
    df = _frame([{"source": "bdc", "accession_number": "A1",
                  "src_context_id": "ctxZ", "fair_value": 5.0}])
    expected = "ROW-" + hashlib.md5(b"bdc|A1|ctxZ").hexdigest()[:16]
    assert _assign_row_ids(df).iloc[0]["row_id"] == expected


def test_colliding_anchors_get_distinct_ids_content_ranked():
    """Two rows sharing the same anchor key must get distinct row_ids.

    The row with the lower fair_value (100.0) is rank-0 and keeps the bare
    unsuffixed id; the row with fair_value=200.0 gets a |dup1 suffix.
    """
    df = _frame([
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 200.0, "cost": 90.0},
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 100.0, "cost": 90.0},
    ])
    out = _assign_row_ids(df)
    assert out["row_id"].nunique() == 2
    # rank-0 row (lowest fair_value=100.0) keeps the unsuffixed id
    base = hashlib.md5(b"bdc|A1|ctx1").hexdigest()[:16]
    low_fv_id = out.loc[out["fair_value"] == 100.0, "row_id"].iloc[0]
    assert low_fv_id == f"ROW-{base}"


def test_collision_ids_independent_of_frame_order():
    """The id assigned to each logical row must not depend on frame order."""
    rows = [
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 200.0, "cost": 90.0},
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 100.0, "cost": 90.0},
    ]
    out_fwd = _assign_row_ids(_frame(rows))
    out_rev = _assign_row_ids(_frame(list(reversed(rows))))
    fwd = dict(zip(out_fwd["fair_value"].astype(str), out_fwd["row_id"]))
    rev = dict(zip(out_rev["fair_value"].astype(str), out_rev["row_id"]))
    assert fwd == rev


def test_non_default_index_collision_distinct_ids():
    """Collision suffix must work correctly when df carries a non-default index.

    Realistic case: a concat-assembled frame retains the original integer labels
    (e.g. index=[5, 9]) rather than 0..N-1.  The two rows share the same anchor
    key, so both receive rank-0/rank-1 treatment, and the resulting row_ids
    must be DISTINCT.  The rank-0 row (lower fair_value=100.0) must keep the
    bare unsuffixed id.
    """
    df = _frame([
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 200.0, "cost": 90.0},
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 100.0, "cost": 90.0},
    ])
    # Simulate a concat-assembled frame with non-contiguous labels
    df.index = [5, 9]
    out = _assign_row_ids(df)
    assert out["row_id"].nunique() == 2, "non-default index must still yield distinct ids"
    base = hashlib.md5(b"bdc|A1|ctx1").hexdigest()[:16]
    # row with index label 9 has fair_value=100.0 and should be rank-0 (bare key)
    low_fv_id = out.loc[out["fair_value"] == 100.0, "row_id"].iloc[0]
    assert low_fv_id == f"ROW-{base}", "rank-0 row must keep the bare unsuffixed id"


def test_null_fv_ranks_after_non_null_fv():
    """A collision where one row has fair_value=NaN: the NON-null row must keep
    the bare key (rank 0).  With the naive fillna('') approach, '' < '100.0' so
    the null row wins rank 0 incorrectly.  Nulls must sort LAST.
    """
    df = _frame([
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": float("nan"), "cost": 90.0},
        {"source": "bdc", "accession_number": "A1", "src_context_id": "ctx1",
         "fair_value": 100.0, "cost": 90.0},
    ])
    out = _assign_row_ids(df)
    assert out["row_id"].nunique() == 2, "null fv collision must still yield distinct ids"
    base = hashlib.md5(b"bdc|A1|ctx1").hexdigest()[:16]
    # The NON-null row (fair_value=100.0) must keep the bare unsuffixed id
    non_null_id = out.loc[out["fair_value"] == 100.0, "row_id"].iloc[0]
    assert non_null_id == f"ROW-{base}", "non-null fair_value row must be rank-0 (bare key)"


def test_masked_integer_columns_with_na_do_not_crash():
    # 2026-08-30 mpa trial crash: a masked Int64/Int32 content column (DuckDB
    # integer inference; missing_position_add appends None rows) made
    # _col's fillna("") raise TypeError ("Invalid value '' for dtype Int32").
    # _assign_row_ids must stringify masked integer columns dtype-safely.
    df = _base_df()
    df["shares_held"] = pd.array([100, None, 500, None], dtype="Int64")
    out = _assign_row_ids(df)
    assert out["row_id"].nunique() == len(out)
    assert _ROW_ID_RE.match(out["row_id"].iloc[0])
