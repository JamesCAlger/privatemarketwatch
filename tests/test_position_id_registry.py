"""Tests for the stable position_id registry layer.

Proves the properties that motivate the registry (see
docs/position_id_stable_identifier_design.md): replay determinism, closed-quarter
label stability under row reordering, merge->retirement, the within-quarter
uniqueness invariant, and rawid-drift carry-forward.
"""

from __future__ import annotations

import pandas as pd

from pipeline.position_id_registry import (
    compute_natural_keys,
    resolve_position_ids,
    load_registry,
    REGISTRY_COLUMNS,
)


def _row(cik, source, rd, rawid="", nport="", principal="", shares="",
         issuer="", fv="", instr="", pk="", dims=""):
    return {
        "cik": cik, "source": source, "report_date": rd,
        "bdc_investment_identifier": rawid, "nport_holding_id": nport,
        "principal_amount": principal, "shares_held": shares,
        "issuer_name": issuer, "fair_value": fv,
        "instrument_description": instr, "position_key": pk,
        "bdc_dimensions_raw": dims,
    }


def _df(rows):
    return pd.DataFrame(rows).reset_index(drop=True)


def _components_from_chains(chains):
    """chains: list of lists of uids -> dict(root->set) like uf.components()."""
    return {min(c): set(c) for c in chains}


# ---------------------------------------------------------------------------
# Natural key
# ---------------------------------------------------------------------------

def test_natural_key_excludes_issuer_and_fv():
    # Two rows identical on the key fields but different issuer/fv get the SAME
    # base key (issuer/fv are not identity) -- so they collide and are lot-split.
    df = _df([
        _row("1", "bdc", "2023-03-31", rawid="ACME TL", principal="100",
             shares="", issuer="Acme A", fv="90"),
        _row("1", "bdc", "2023-03-31", rawid="ACME TL", principal="100",
             shares="", issuer="Acme B", fv="95"),
    ])
    keys = compute_natural_keys(df)
    assert keys.iloc[0] != keys.iloc[1]      # disambiguated
    assert keys.iloc[0].startswith("1|bdc|2023-03-31|ACME TL|100|")
    assert "#" in keys.iloc[0] and "#" in keys.iloc[1]


def test_natural_key_dimensions_disambiguate_without_ordinal():
    # Two unfunded tranches sharing rawid/principal/shares but distinct XBRL
    # dimension contexts -> disambiguated by #dim:, no @ordinal needed.
    df = _df([
        _row("1", "bdc", "2023-03-31", rawid="ACME", principal="0", shares="0",
             fv="0", dims="ACME|Term Loan A|NonAffiliated"),
        _row("1", "bdc", "2023-03-31", rawid="ACME", principal="0", shares="0",
             fv="0", dims="ACME|Term Loan B|NonAffiliated"),
    ])
    keys = compute_natural_keys(df)
    assert keys.iloc[0] != keys.iloc[1]
    assert "#dim:" in keys.iloc[0] and "@" not in keys.iloc[0]


def test_natural_key_identical_context_falls_back_to_ordinal():
    # Identical XBRL context (and everything) -> interchangeable; the ordinal
    # is the only separator and it is deterministic.
    df = _df([
        _row("1", "bdc", "2023-03-31", rawid="X", principal="1", dims="D"),
        _row("1", "bdc", "2023-03-31", rawid="X", principal="1", dims="D"),
    ])
    keys = compute_natural_keys(df)
    assert keys.iloc[0] != keys.iloc[1]
    assert "@" in keys.iloc[0] and "@" in keys.iloc[1]
    assert sorted([keys.iloc[0], keys.iloc[1]]) == list(compute_natural_keys(
        _df([
            _row("1", "bdc", "2023-03-31", rawid="X", principal="1", dims="D"),
            _row("1", "bdc", "2023-03-31", rawid="X", principal="1", dims="D"),
        ])
    ).sort_values())  # deterministic across recompute


def test_natural_key_uses_nport_id_fallback():
    df = _df([_row("9", "nport", "2023-03-31", nport="H123", principal="5")])
    keys = compute_natural_keys(df)
    assert keys.iloc[0] == "9|nport|2023-03-31|H123|5|"


def test_natural_key_order_independent():
    rows = [
        _row("1", "bdc", "2023-03-31", rawid="A", principal="1"),
        _row("2", "bdc", "2023-03-31", rawid="B", principal="2"),
    ]
    k1 = compute_natural_keys(_df(rows))
    k2 = compute_natural_keys(_df(list(reversed(rows)))).iloc[::-1].reset_index(drop=True)
    assert list(k1) == list(k2)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def test_cold_start_mints_sequentially():
    df = _df([
        _row("1", "bdc", "2023-03-31", rawid="A", principal="1"),
        _row("1", "bdc", "2023-06-30", rawid="A", principal="1"),
        _row("2", "bdc", "2023-03-31", rawid="B", principal="2"),
    ])
    nk = compute_natural_keys(df)
    comps = _components_from_chains([[0, 1]])  # rows 0,1 chain; row 2 singleton
    res = resolve_position_ids([list(v) for v in comps.values()], df, nk, None)
    assert res.uid_to_pid[0] == res.uid_to_pid[1]   # same chain, same id
    assert res.uid_to_pid[2] != res.uid_to_pid[0]   # singleton distinct
    assert res.n_minted == 2 and res.n_inherited == 0
    assert set(res.registry_df.columns) == set(REGISTRY_COLUMNS)


def test_replay_determinism_identical():
    df = _df([
        _row("1", "bdc", "2023-03-31", rawid="A", principal="1"),
        _row("1", "bdc", "2023-06-30", rawid="A", principal="1"),
        _row("2", "bdc", "2023-03-31", rawid="B", principal="2"),
    ])
    nk = compute_natural_keys(df)
    comps = [list(v) for v in _components_from_chains([[0, 1]]).values()]
    first = resolve_position_ids(comps, df, nk, None)
    second = resolve_position_ids(comps, df, nk, first.registry_df)
    assert first.uid_to_pid == second.uid_to_pid
    assert second.n_minted == 0           # all inherited on replay
    assert second.n_inherited >= 1


def test_closed_quarter_stable_under_reorder_and_new_quarter():
    # Build 1: two CIKs, Q1+Q2.
    rows_b1 = [
        _row("1", "bdc", "2023-03-31", rawid="A", principal="1"),
        _row("1", "bdc", "2023-06-30", rawid="A", principal="1"),
        _row("2", "bdc", "2023-03-31", rawid="B", principal="2"),
        _row("2", "bdc", "2023-06-30", rawid="B", principal="2"),
    ]
    df1 = _df(rows_b1)
    nk1 = compute_natural_keys(df1)
    comps1 = [[0, 1], [2, 3]]
    r1 = resolve_position_ids(comps1, df1, nk1, None)
    pid_cik1 = r1.uid_to_pid[0]
    pid_cik2 = r1.uid_to_pid[2]

    # Build 2: a NEW cik sorts first (would shift all ordinals in old scheme),
    # rows reordered, and a new Q3 appended to cik 1.
    rows_b2 = [
        _row("0", "bdc", "2023-03-31", rawid="Z", principal="9"),   # brand new, earliest
        _row("1", "bdc", "2023-09-30", rawid="A", principal="1"),   # new quarter
        _row("2", "bdc", "2023-06-30", rawid="B", principal="2"),
        _row("1", "bdc", "2023-03-31", rawid="A", principal="1"),
        _row("2", "bdc", "2023-03-31", rawid="B", principal="2"),
        _row("1", "bdc", "2023-06-30", rawid="A", principal="1"),
    ]
    df2 = _df(rows_b2)
    nk2 = compute_natural_keys(df2)
    # cik1 chain = uids 1,3,5 ; cik2 chain = uids 2,4 ; new cik0 = singleton 0
    comps2 = [[1, 3, 5], [2, 4]]
    r2 = resolve_position_ids(comps2, df2, nk2, r1.registry_df)

    # Closed-quarter ids unchanged despite reorder + new earliest cik.
    assert r2.uid_to_pid[3] == pid_cik1   # cik1 Q1
    assert r2.uid_to_pid[5] == pid_cik1   # cik1 Q2
    assert r2.uid_to_pid[1] == pid_cik1   # cik1 Q3 inherits chain id
    assert r2.uid_to_pid[2] == pid_cik2
    assert r2.uid_to_pid[4] == pid_cik2
    assert r2.uid_to_pid[0] not in (pid_cik1, pid_cik2)  # genuinely new id


def test_merge_retires_younger_id():
    # Build 1: two separate single-quarter positions -> two ids.
    df1 = _df([
        _row("1", "bdc", "2023-03-31", rawid="A", principal="1"),
        _row("1", "bdc", "2023-03-31", rawid="B", principal="2"),
    ])
    nk1 = compute_natural_keys(df1)
    r1 = resolve_position_ids([[0], [1]], df1, nk1, None)
    id_a = r1.uid_to_pid[0]
    id_b = r1.uid_to_pid[1]
    survivor = min(id_a, id_b)
    retired = max(id_a, id_b)

    # Build 2: same two rows now chained into one component (a merge).
    df2 = _df([
        _row("1", "bdc", "2023-03-31", rawid="A", principal="1"),
        _row("1", "bdc", "2023-03-31", rawid="B", principal="2"),
    ])
    nk2 = compute_natural_keys(df2)
    r2 = resolve_position_ids([[0, 1]], df2, nk2, r1.registry_df)
    assert r2.uid_to_pid[0] == r2.uid_to_pid[1] == survivor
    assert r2.n_merged == 1
    assert not r2.retirements_df.empty
    rec = r2.retirements_df.iloc[0]
    assert rec["retired_position_id"] == retired
    assert rec["surviving_position_id"] == survivor
    assert rec["reason"] == "chain_merge"


def test_split_preserves_uniqueness():
    # Build 1: one chain spanning two rows in the SAME quarter is impossible
    # (guarded), so model a split as: build1 one id over two quarters; build2
    # the two quarters no longer chain -> each keeps/var the id without
    # violating per-quarter uniqueness.
    df1 = _df([
        _row("1", "bdc", "2023-03-31", rawid="A", principal="1"),
        _row("1", "bdc", "2023-06-30", rawid="A", principal="1"),
    ])
    nk1 = compute_natural_keys(df1)
    r1 = resolve_position_ids([[0, 1]], df1, nk1, None)
    shared = r1.uid_to_pid[0]

    df2 = _df([
        _row("1", "bdc", "2023-03-31", rawid="A", principal="1"),
        _row("1", "bdc", "2023-06-30", rawid="A", principal="1"),
    ])
    nk2 = compute_natural_keys(df2)
    # Now they do NOT chain -> two singleton components both reference `shared`.
    r2 = resolve_position_ids([[0], [1]], df2, nk2, r1.registry_df)
    # Exactly one component keeps `shared`; the other is evicted and re-minted.
    ids = [r2.uid_to_pid[0], r2.uid_to_pid[1]]
    assert shared in ids
    assert ids[0] != ids[1]                      # split -> distinct ids
    assert r2.n_split_reassigned == 1

    # The eviction is AUDITED as a chain_split (source id still alive).
    split = r2.retirements_df[r2.retirements_df["reason"] == "chain_split"]
    assert len(split) == 1
    rec = split.iloc[0]
    assert rec["retired_position_id"] == shared        # the id it left
    evicted_new = ids[0] if ids[1] == shared else ids[1]
    assert rec["surviving_position_id"] == evicted_new  # the id it now carries


def test_rawid_drift_carry_forward_via_chain():
    # Build 1: position with rawid 'A | Non-Affiliated Issuer'.
    df1 = _df([
        _row("1", "bdc", "2023-03-31", rawid="A | Non-Affiliated Issuer",
             principal="1", fv="90"),
    ])
    nk1 = compute_natural_keys(df1)
    r1 = resolve_position_ids([[0]], df1, nk1, None)
    orig = r1.uid_to_pid[0]

    # Build 2: extraction fix changed rawid to 'A' (stripped). The Q1 row's
    # natural key changed -> registry would mint NEW unless the chain carries
    # it.  Add Q2 with the new rawid and chain Q1<->Q2; the chain inherits the
    # Q1 id from the prior registry entry.
    df2 = _df([
        _row("1", "bdc", "2023-03-31", rawid="A | Non-Affiliated Issuer",
             principal="1", fv="90"),
        _row("1", "bdc", "2023-06-30", rawid="A", principal="1", fv="92"),
    ])
    nk2 = compute_natural_keys(df2)
    r2 = resolve_position_ids([[0, 1]], df2, nk2, r1.registry_df)
    assert r2.uid_to_pid[0] == orig          # closed Q1 still resolvable
    assert r2.uid_to_pid[1] == orig          # new rawid carried forward


def test_load_registry_roundtrip(tmp_path):
    df = _df([_row("1", "bdc", "2023-03-31", rawid="A", principal="1")])
    nk = compute_natural_keys(df)
    r = resolve_position_ids([[0]], df, nk, None)
    p = tmp_path / "reg.csv"
    r.registry_df.to_csv(p, index=False)
    loaded = load_registry(p)
    assert loaded is not None
    assert list(loaded.columns) == REGISTRY_COLUMNS
    assert load_registry(tmp_path / "missing.csv") is None
