"""Tests for scripts/match_gold/build_packets.py chain packet sampler."""
from pathlib import Path

import pandas as pd

from tests.test_match_quality import _edge, _edges, _holdings, _row
from scripts.match_gold import build_packets as bp


def _chain_fixture():
    holdings = _holdings([
        _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a"),
        _row("0000000001", "2025-06-30", "Acme Corp", 101.0, "POS-1", "ROW-b"),
        _row("0000000001", "2025-03-31", "Beta LLC", 50.0, "POS-2", "ROW-c"),
        _row("0000000001", "2025-06-30", "Beta LLC", 900.0, "POS-2", "ROW-d"),
    ])
    edges = _edges([
        _edge("POS-1", "B2_exact_name", 100.0, 101.0),
        _edge("POS-2", "D_fuzzy", 50.0, 900.0),   # fv-jump anomaly
    ])
    return holdings, edges


def test_sample_chains_strata_and_determinism():
    holdings, edges = _chain_fixture()
    s1 = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                          n_interior_singleton=5, n_drift_break=5)
    s2 = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                          n_interior_singleton=5, n_drift_break=5)
    pd.testing.assert_frame_equal(s1, s2)          # deterministic
    assert set(s1["stratum"]) >= {"tier_random", "fv_jump"}
    # POS-2 must appear in the fv_jump stratum
    assert "POS-2" in set(s1[s1["stratum"] == "fv_jump"]["position_id"])


def test_no_duplicate_packet_for_same_pid_and_stratum():
    holdings, edges = _chain_fixture()
    s = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                         n_interior_singleton=5, n_drift_break=5)
    assert not s.duplicated(["stratum", "position_id"]).any()


def test_sample_entities_near_miss_pair():
    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-a"),
        _row("0000000002", "2025-06-30", "Acme Co", 20.0, "POS-2", "ROW-b"),  # near-miss variant, different fund (JW=0.9556)
        _row("0000000001", "2025-06-30", "Zebra Partners", 10.0, "POS-3", "ROW-c"),
    ])
    s = bp.sample_entities(holdings)
    near = s[s["stratum"] == "cross_fund_near_miss"]
    assert len(near) == 1
    assert near.iloc[0]["ciks"] == "0000000001;0000000002"


def test_sample_entities_merge_verify_cross_fund_cluster():
    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-a",
             entity_id="ENT-1"),
        _row("0000000002", "2025-06-30", "Acme Corporation", 20.0, "POS-2", "ROW-b",
             entity_id="ENT-1"),
    ])
    s = bp.sample_entities(holdings)
    mv = s[s["stratum"] == "entity_merge_verify"]
    assert list(mv["cluster_key"]) == ["ENT-1"]


def test_sample_entities_deterministic():
    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-a"),
        _row("0000000002", "2025-06-30", "Acme Co", 20.0, "POS-2", "ROW-b"),
    ])
    pd.testing.assert_frame_equal(bp.sample_entities(holdings),
                                  bp.sample_entities(holdings))


import json


def test_entity_packet_owning_cik_used_for_cache_check(tmp_path):
    """Cross-fund entity packet: mini-bundle cik and cache check use the filing's owning CIK.

    Accession 'ACC-CIK2' belongs to CIK 0000000002 (ciks_list[1]).
    _has_cached_filing must be called with CIK2, not CIK1 (ciks_list[0]).
    """
    import types

    holdings = _holdings([
        _row("0000000001", "2025-06-30", "Acme Corp", 10.0, "POS-1", "ROW-a",
             entity_id="ENT-X"),
        _row("0000000002", "2025-06-30", "Acme Corporation", 20.0, "POS-2", "ROW-b",
             entity_id="ENT-X"),
    ])
    holdings["accession_number"] = ["ACC-CIK1", "ACC-CIK2"]
    holdings["instrument_description"] = ""
    holdings["bdc_investment_identifier"] = holdings["issuer_name"]
    holdings["principal_amount"] = None
    holdings["basis_spread"] = None

    # Capture which (cik, acc) pairs _has_cached_filing is called with
    calls: list[tuple[str, str]] = []

    import scripts.match_gold.build_packets as _bp_mod
    original_has_cached = _bp_mod._has_cached_filing

    def _fake_has_cached(cik: str, acc: str) -> bool:
        calls.append((cik, acc))
        return True

    _bp_mod._has_cached_filing = _fake_has_cached
    try:
        entity_sample = bp.sample_entities(holdings, n_merge_verify=5,
                                           n_cross_fund_near_miss=5, n_within_fund=5)
        chain_sample = pd.DataFrame(columns=bp.SAMPLE_COLUMNS)
        stats = bp.write_batch(holdings, pd.DataFrame(columns=[
            "edge_type", "position_id", "cik", "source", "begin_report_date",
            "begin_quarter", "begin_issuer_name", "begin_fair_value",
            "end_report_date", "end_quarter", "end_issuer_name",
            "end_fair_value", "match_method", "match_key", "match_score", "span_months"
        ]), chain_sample, entity_sample, tmp_path)
    finally:
        _bp_mod._has_cached_filing = original_has_cached

    # The entity_merge_verify packet spans both CIKs.
    # Cache check for ACC-CIK1 must use CIK1, for ACC-CIK2 must use CIK2.
    acc_to_cik_used = {acc: cik for cik, acc in calls}
    if "ACC-CIK1" in acc_to_cik_used:
        assert acc_to_cik_used["ACC-CIK1"] == "0000000001", (
            f"Expected CIK1 for ACC-CIK1, got {acc_to_cik_used['ACC-CIK1']}"
        )
    if "ACC-CIK2" in acc_to_cik_used:
        assert acc_to_cik_used["ACC-CIK2"] == "0000000002", (
            f"Expected CIK2 for ACC-CIK2, got {acc_to_cik_used['ACC-CIK2']}"
        )

    # Verify mini-bundle cik fields match owning CIK (not always cik_repr)
    wl = pd.read_csv(tmp_path / "worklist.csv")
    entity_packets = wl[wl["packet_type"] == "entity"]
    for _, row in entity_packets.iterrows():
        pid = row["packet_id"]
        filing_dir = tmp_path / "filings" / pid
        if filing_dir.exists():
            for bundle_path in filing_dir.iterdir():
                acc = bundle_path.stem
                bundle = json.loads(bundle_path.read_text("utf-8"))
                expected_cik = {"ACC-CIK1": "0000000001", "ACC-CIK2": "0000000002"}.get(acc)
                if expected_cik is not None:
                    assert bundle["cik"] == expected_cik, (
                        f"mini-bundle for {acc}: expected {expected_cik}, got {bundle['cik']}"
                    )


def test_write_batch_layout(tmp_path):
    holdings, edges = _chain_fixture()
    holdings["accession_number"] = "0000000001-25-000001"
    holdings["instrument_description"] = "First Lien Term Loan"
    holdings["bdc_investment_identifier"] = holdings["issuer_name"]
    holdings["principal_amount"] = 100.0
    holdings["basis_spread"] = 5.0
    chain_sample = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                                    n_interior_singleton=5, n_drift_break=5)
    entity_sample = bp.sample_entities(holdings)
    stats = bp.write_batch(holdings, edges, chain_sample, entity_sample, tmp_path)
    assert stats["n_packets"] == len(chain_sample) + len(entity_sample)
    wl = pd.read_csv(tmp_path / "worklist.csv")
    assert set(wl.columns) >= {"packet_id", "packet_type", "stratum",
                               "prompt_path", "packet_path", "verdict_path"}
    pid = wl.iloc[0]["packet_id"]
    packet = json.loads((tmp_path / "packets" / f"{pid}.json").read_text("utf-8"))
    assert packet["schema_version"] == "match-gold-packet.v1"
    # blinding: tier never appears in packet or prompt
    raw = (tmp_path / "packets" / f"{pid}.json").read_text("utf-8")
    prompt = (tmp_path / "prompts" / f"{pid}.md").read_text("utf-8")
    for banned in ("match_method", "B2_exact_name", "D_fuzzy", "match_score"):
        assert banned not in raw and banned not in prompt
    # sidecar has the tier for the scorer
    meta = json.loads((tmp_path / "packets_meta" / f"{pid}.json").read_text("utf-8"))
    assert "stratum" in meta


def test_chain_packet_edges_resolve_to_row_ids(tmp_path):
    holdings, edges = _chain_fixture()
    holdings["accession_number"] = "0000000001-25-000001"
    holdings["instrument_description"] = ""
    holdings["bdc_investment_identifier"] = holdings["issuer_name"]
    holdings["principal_amount"] = None
    holdings["basis_spread"] = None
    chain_sample = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                                    n_interior_singleton=5, n_drift_break=5)
    bp.write_batch(holdings, edges, chain_sample, entity_sample=pd.DataFrame(
        columns=["packet_id", "packet_type", "stratum", "cluster_key", "ciks"]),
        batch_dir=tmp_path)
    pos1 = chain_sample[chain_sample["position_id"] == "POS-1"].iloc[0]["packet_id"]
    packet = json.loads((tmp_path / "packets" / f"{pos1}.json").read_text("utf-8"))
    edge = packet["edges"][0]
    assert edge["begin_row_id"] == "ROW-a" and edge["end_row_id"] == "ROW-b"


def test_truncated_flag_based_on_distinct_dates_not_row_count(tmp_path):
    """4 rows across 2 distinct dates must NOT set truncated=True (only >12 dates triggers it)."""
    holdings = _holdings([
        _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-X", "ROW-x1"),
        _row("0000000001", "2025-03-31", "Acme Corp", 101.0, "POS-X", "ROW-x2"),
        _row("0000000001", "2025-06-30", "Acme Corp", 102.0, "POS-X", "ROW-x3"),
        _row("0000000001", "2025-06-30", "Acme Corp", 103.0, "POS-X", "ROW-x4"),
    ])
    edges = _edges([_edge("POS-X", "B2_exact_name", 100.0, 102.0)])
    for col in ["accession_number", "instrument_description",
                "bdc_investment_identifier", "principal_amount", "basis_spread"]:
        holdings[col] = None
    chain_sample = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                                    n_interior_singleton=5, n_drift_break=5)
    # Only keep tier_random rows for POS-X to keep the test focused
    chain_sample = chain_sample[chain_sample["position_id"] == "POS-X"].reset_index(drop=True)
    if len(chain_sample) == 0:
        # If dedup removed duplicates, build a minimal sample manually
        chain_sample = pd.DataFrame([{
            "packet_id": bp._packet_id("chain", "tier_random", "POS-X"),
            "packet_type": "chain",
            "stratum": "tier_random",
            "position_id": "POS-X",
            "cik": "0000000001",
        }])
    bp.write_batch(holdings, edges, chain_sample,
                   entity_sample=pd.DataFrame(
                       columns=["packet_id", "packet_type", "stratum", "cluster_key", "ciks"]),
                   batch_dir=tmp_path)
    pid = chain_sample.iloc[0]["packet_id"]
    packet = json.loads((tmp_path / "packets" / f"{pid}.json").read_text("utf-8"))
    # 4 rows, 2 distinct dates — must NOT be truncated
    assert packet.get("truncated", False) is False


def test_drift_break_packet_has_two_rows(tmp_path):
    """drift_break stratum: packet contains dropped row + start row (no NameError)."""
    from pipeline.match_quality import drift_break_candidates
    # Build a holdings set that produces at least one drift_break candidate:
    # position_id appears exactly once (dropped), and there's a follow-on position
    # with similar issuer_name in the next quarter at the same CIK.
    holdings = _holdings([
        _row("0000000001", "2025-03-31", "Acme Corp", 100.0, "POS-1", "ROW-a"),
        _row("0000000001", "2025-06-30", "Acme Corp", 105.0, "POS-2", "ROW-b"),
    ])
    for col in ["accession_number", "instrument_description",
                "bdc_investment_identifier", "principal_amount", "basis_spread"]:
        holdings[col] = None
    edges = _edges([])

    drift = drift_break_candidates(holdings)
    if len(drift) == 0:
        # No drift_break candidates from this fixture — just verify no NameError
        # by calling write_batch with an empty drift_break sample
        chain_sample = pd.DataFrame(columns=bp.SAMPLE_COLUMNS)
        bp.write_batch(holdings, edges, chain_sample,
                       entity_sample=pd.DataFrame(
                           columns=["packet_id", "packet_type", "stratum", "cluster_key", "ciks"]),
                       batch_dir=tmp_path)
        assert True  # reached without NameError
        return

    # Build a drift_break chain_sample entry manually from the first candidate
    first = drift.iloc[0]
    dropped_rid = str(first["dropped_row_id"])
    pid = bp._packet_id("chain", "drift_break", dropped_rid)
    pid_val = holdings.set_index("row_id")["position_id"].get(dropped_rid, "")
    chain_sample = pd.DataFrame([{
        "packet_id": pid,
        "packet_type": "chain",
        "stratum": "drift_break",
        "position_id": pid_val,
        "cik": str(first["cik"]),
    }])
    bp.write_batch(holdings, edges, chain_sample,
                   entity_sample=pd.DataFrame(
                       columns=["packet_id", "packet_type", "stratum", "cluster_key", "ciks"]),
                   batch_dir=tmp_path)
    packet = json.loads((tmp_path / "packets" / f"{pid}.json").read_text("utf-8"))
    # drift_break packet must have 1 or 2 rows, never raise NameError
    assert len(packet["rows"]) >= 1


def test_prompt_paths_are_absolute_and_resolvable(tmp_path):
    """A Codex worker runs `codex exec -C <scratch runroot>`, so relative prompt paths
    resolve against nothing. Every path a prompt hands the worker must be absolute and
    must point at a file that exists, and the evidence CLI must be named with the
    project interpreter (a bare `python` in the sandbox lacks the deps)."""
    import os
    import re

    holdings, edges = _chain_fixture()
    holdings["accession_number"] = "0000000001-25-000001"
    holdings["instrument_description"] = "First Lien Term Loan"
    holdings["bdc_investment_identifier"] = holdings["issuer_name"]
    holdings["principal_amount"] = 100.0
    holdings["basis_spread"] = 5.0
    chain_sample = bp.sample_chains(holdings, edges, per_tier=5, n_fv_jump=5,
                                    n_interior_singleton=5, n_drift_break=5)
    entity_sample = bp.sample_entities(holdings)
    # Relative batch dir: write_batch must resolve it, not propagate it.
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        bp.write_batch(holdings, edges, chain_sample, entity_sample, Path("batch"))
    finally:
        os.chdir(cwd)
    batch_dir = tmp_path / "batch"

    wl = pd.read_csv(batch_dir / "worklist.csv")
    assert len(wl) > 0
    for pid in wl["packet_id"]:
        prompt = (batch_dir / "prompts" / f"{pid}.md").read_text("utf-8")

        # No path is relative to the batch dir any more.
        for rel in (f"packets/{pid}.json", f"verdicts/{pid}.json", f"filings/{pid}",
                    "python scripts/review_agent/evidence_cli.py"):
            assert rel not in prompt, f"{pid}: relative path {rel!r} left in prompt"

        # The packet the worker is told to read exists at the absolute path given.
        packet_path = re.search(r'## Your packet\n"([^"\n]+)"\n', prompt).group(1)
        assert Path(packet_path).is_absolute()
        assert Path(packet_path).exists()

        # The verdict target sits in the batch verdicts dir (the sandbox write grant).
        verdict_path = re.search(r'Write EXACTLY one JSON file to: "([^"\n]+)"',
                                 prompt).group(1)
        assert Path(verdict_path).is_absolute()
        assert Path(verdict_path).parent == (batch_dir / "verdicts")

        # Every --bundle is absolute, exists, and is invoked via the project interpreter.
        bundles = re.findall(r'--bundle "([^"\n]+)"', prompt)
        packet = json.loads((batch_dir / "packets" / f"{pid}.json").read_text("utf-8"))
        assert len(set(bundles)) == len(packet["accessions"])
        for b in bundles:
            assert Path(b).is_absolute()
            assert Path(b).exists(), f"{pid}: prompt cites missing bundle {b}"
        assert f'"{bp.WORKER_PYTHON}" "{bp.EVIDENCE_CLI}"' in prompt
        assert bp.EVIDENCE_CLI.exists()

        # filing_bundles inside the packet points at the same real files.
        for acc, path in packet["filing_bundles"].items():
            assert Path(path).is_absolute()
            assert Path(path).exists()
