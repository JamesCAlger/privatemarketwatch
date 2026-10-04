from copy import deepcopy
import json
import pytest
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay


def fixture(tmp_path, *, legacy=False, hashed=False):
    directory = tmp_path / 'replay'
    directory.mkdir()
    packet = {'rule': {'id': 'C107'}, 'flag': {'row_id': 'ROW-A', 'rule_id': 'C107'},
              'provenance': {'builder_sha256': 'builder', 'holdings_sha256': 'holdings'},
              'evidence_status': {'status': 'blocked', 'blocking_reasons': ['missing_notes']},
              'source_candidates': []}
    case = ({'case_id': 'C107_ROW-A', 'after': 'blocked', 'reasons': ['missing_notes']} if legacy else
            {'rule': 'C107', 'row_id': 'ROW-A', 'status': 'blocked', 'blocking_reasons': ['missing_notes']})
    if hashed:
        case['packet_fingerprint'] = fingerprint(packet)
    summary = {'builder_sha256': 'builder', 'holdings_sha256': 'holdings', 'cases': [case],
               'status_counts': {'blocked': 1}}
    (directory / 'C107_ROW-A.json').write_text(json.dumps(packet), encoding='utf-8')
    (directory / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    return directory, packet, summary


@pytest.mark.parametrize('legacy', [False, True])
def test_complete_current_and_legacy_summary_shapes_are_supported(tmp_path, legacy):
    fixture(tmp_path, legacy=legacy)
    assert len(load_replay(tmp_path, 'replay')[1]) == 1


@pytest.mark.parametrize('mutation', ['flag_identity', 'status', 'reasons', 'holdings', 'declared_flag'])
def test_substituted_or_stale_packet_is_rejected(tmp_path, mutation):
    directory, packet, summary = fixture(tmp_path)
    if mutation == 'flag_identity':
        packet['flag']['rule_id'] = 'C104'
    elif mutation == 'status':
        packet['evidence_status']['status'] = 'ready_for_model'
    elif mutation == 'reasons':
        packet['evidence_status']['blocking_reasons'] = []
    elif mutation == 'holdings':
        packet['provenance']['holdings_sha256'] = 'other-snapshot'
    else:
        summary['cases'][0]['row_id'] = 'ROW-B'
    (directory / 'C107_ROW-A.json').write_text(json.dumps(packet), encoding='utf-8')
    (directory / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    with pytest.raises(ValueError):
        load_replay(tmp_path, 'replay')


def test_content_fingerprint_detects_evidence_changes_without_status_change(tmp_path):
    directory, packet, _ = fixture(tmp_path, hashed=True)
    packet['source_candidates'].append({'invented_candidate': True})
    (directory / 'C107_ROW-A.json').write_text(json.dumps(packet), encoding='utf-8')
    with pytest.raises(ValueError):
        load_replay(tmp_path, 'replay')


def test_duplicate_summary_members_are_rejected(tmp_path):
    directory, packet, summary = fixture(tmp_path)
    summary['cases'].append(deepcopy(summary['cases'][0]))
    other = deepcopy(packet)
    other['flag']['row_id'] = 'ROW-B'
    (directory / 'C107_ROW-B.json').write_text(json.dumps(other), encoding='utf-8')
    (directory / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    with pytest.raises(ValueError):
        load_replay(tmp_path, 'replay')


@pytest.mark.parametrize('mutation', [None, 'summary_hash', 'builder', 'packet_runtime', 'missing_runtime', 'early_block', 'invalid_accession', 'false_input_refusal'])
def test_runtime_binding_is_checked_without_requiring_source_for_early_blocks(tmp_path, mutation):
    directory, packet, summary = fixture(tmp_path)
    runtime = {'schema_version': 'jev-parser-runtime.v1', 'builder_sha256': 'builder',
               'date_helper_sha256': 'helper', 'beautifulsoup_version': 'version'}
    summary.update(parser_runtime=deepcopy(runtime), parser_runtime_sha256=fingerprint(runtime))
    packet['filing'] = {'status': 'cached_source_parsed', 'sha256': 'source',
                        'parser_runtime': deepcopy(runtime), 'parser_runtime_sha256': fingerprint(runtime)}
    if mutation == 'summary_hash':
        summary['parser_runtime_sha256'] = 'changed'
    elif mutation == 'builder':
        summary['parser_runtime']['builder_sha256'] = 'other'
        summary['parser_runtime_sha256'] = fingerprint(summary['parser_runtime'])
    elif mutation == 'packet_runtime':
        packet['filing']['parser_runtime']['date_helper_sha256'] = 'other'
        packet['filing']['parser_runtime_sha256'] = fingerprint(packet['filing']['parser_runtime'])
    elif mutation == 'missing_runtime':
        del packet['filing']['parser_runtime']
    elif mutation == 'early_block':
        packet['filing'] = {}
    elif mutation == 'invalid_accession':
        packet['filing'] = {'status': 'missing_or_invalid_accession'}
    elif mutation == 'false_input_refusal':
        packet['filing'] = {'status': 'missing_or_invalid_accession', 'sha256': 'source'}
    (directory / 'C107_ROW-A.json').write_text(json.dumps(packet), encoding='utf-8')
    (directory / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    if mutation in {None, 'early_block', 'invalid_accession'}:
        assert len(load_replay(tmp_path, 'replay')[1]) == 1
    else:
        with pytest.raises(ValueError, match='runtime'):
            load_replay(tmp_path, 'replay')
