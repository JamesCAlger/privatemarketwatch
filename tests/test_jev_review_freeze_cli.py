from copy import deepcopy
import json
import sys
import pytest
from scripts.freeze_jev_review_findings import main
from scripts.jev_pilot_session import sha
from scripts.prepare_jev_blind_review import review_input


@pytest.fixture
def handoff(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    run = repo / 'data/pilot/jev_screening/test'
    directory = run / 'prepared'
    directory.mkdir(parents=True)
    source = repo / 'data/raw/source.html'
    source.parent.mkdir(parents=True)
    source.write_text('Synthetic test source', encoding='utf-8')
    holdings = repo / 'data/output/private_markets_holdings.csv'
    holdings.parent.mkdir(parents=True)
    holdings.write_text('synthetic snapshot', encoding='utf-8')
    packet = {'rule': {'id': 'C107', 'fields': ['cost']},
              'output_position': {'cost': '-1000', 'cost_currency': 'USD'},
              'provenance': {'holdings_sha256': sha(holdings)}}
    prepared = review_input(packet, source, sha(source))
    prepared_path = directory / 'input.json'
    prepared_path.write_text(json.dumps(prepared), encoding='utf-8')
    manifest = {'production_clearance_enabled': False, 'inventory': [
        {'review_id': prepared['review_id'], 'file': 'input.json', 'sha256': sha(prepared_path)}]}
    (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    completed = deepcopy(prepared)
    completed['review_form'].update(reviewer='Synthetic test reviewer', source_first_attestation=True,
        started_at='2026-10-04T01:00:00Z', completed_at='2026-10-04T01:01:00Z', active_seconds=30,
        disposition='unresolved', reason='Cannot establish tranche', unresolved_questions=['Which tranche?'])
    completed_path = run / 'completed.json'
    completed_path.write_text(json.dumps(completed), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['freeze', '--repo', str(repo), '--run-root', str(run),
        '--prepared-label', 'prepared', '--review-id', prepared['review_id'], '--completed', str(completed_path)])
    return {'run': run, 'source': source, 'holdings': holdings, 'prepared': prepared_path,
            'completed': completed_path}


def test_cli_seals_unresolved_record_without_audit_or_clearance(handoff):
    main()
    paths = list((handoff['run'] / 'source_first_findings').glob('*.json'))
    assert len(paths) == 1
    record = json.loads(paths[0].read_text())
    assert record['findings']['findings']['disposition'] == 'unresolved'
    assert record['findings']['bundle_audit_completed'] is False
    assert record['findings']['production_clearance_enabled'] is False


@pytest.mark.parametrize('changed', ['source', 'holdings', 'prepared'])
def test_changed_source_snapshot_or_prepared_input_is_rejected(handoff, changed):
    handoff[changed].write_text('changed after preparation', encoding='utf-8')
    with pytest.raises(ValueError):
        main()
    assert not (handoff['run'] / 'source_first_findings').exists()


def test_existing_findings_are_never_overwritten(handoff):
    main()
    path = next((handoff['run'] / 'source_first_findings').glob('*.json'))
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        main()
    assert path.read_bytes() == before
