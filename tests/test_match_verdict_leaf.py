from pipeline.match_verdict_leaf import validate_match_verdict


def _base(**kw):
    d = {
        "packet_id": "MGP-abc123", "packet_type": "chain",
        "verdict": "CONFIRMED", "confidence": 0.9,
        "edge_verdicts": [{"edge_index": 0, "verdict": "CONFIRMED", "evidence": []}],
        "proposed_links": [], "rationale": "matches across filings", "escalate": False,
    }
    d.update(kw)
    return d


def test_valid_confirmed_chain():
    assert validate_match_verdict(_base(), expected_edges=[0]) == []


def test_missing_required_key():
    d = _base()
    del d["confidence"]
    errs = validate_match_verdict(d, expected_edges=[0])
    assert any("confidence" in e for e in errs)


def test_wrong_edge_requires_citation():
    d = _base(verdict="WRONG_MERGE",
              edge_verdicts=[{"edge_index": 0, "verdict": "WRONG", "evidence": []}])
    errs = validate_match_verdict(d, expected_edges=[0])
    assert any("citation" in e for e in errs)


def test_edge_coverage_must_be_exact():
    errs = validate_match_verdict(_base(), expected_edges=[0, 1])
    assert any("edge" in e for e in errs)


def test_missed_link_requires_proposed_links():
    d = _base(verdict="MISSED_LINK", proposed_links=[])
    errs = validate_match_verdict(d, expected_edges=[0])
    assert any("proposed_links" in e for e in errs)


def test_insufficient_evidence_needs_rationale_only():
    d = _base(verdict="INSUFFICIENT_EVIDENCE", rationale="filing table truncated",
              edge_verdicts=[{"edge_index": 0, "verdict": "UNCERTAIN", "evidence": []}])
    assert validate_match_verdict(d, expected_edges=[0]) == []


def test_entity_packet_wrong_merge_needs_citation():
    d = _base(packet_type="entity", verdict="WRONG_MERGE", edge_verdicts=[])
    errs = validate_match_verdict(d, expected_edges=[])
    assert any("citation" in e for e in errs)


def test_duplicate_edge_index_rejected():
    d = _base(edge_verdicts=[
        {"edge_index": 0, "verdict": "CONFIRMED", "evidence": []},
        {"edge_index": 0, "verdict": "CONFIRMED", "evidence": []}
    ])
    errs = validate_match_verdict(d, expected_edges=[0])
    assert any("duplicate edge_index" in e for e in errs)


def test_wrong_edge_with_non_dict_citation():
    d = _base(verdict="WRONG_MERGE",
              edge_verdicts=[{"edge_index": 0, "verdict": "WRONG",
                            "evidence": ["not a dict"]}])
    errs = validate_match_verdict(d, expected_edges=[0])
    assert any("citation" in e for e in errs)
