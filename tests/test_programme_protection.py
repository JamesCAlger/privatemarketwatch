"""The controller must detect output mutations even from native file writers."""
import os

import pytest

from pipeline.programme import protection
from pipeline.programme.core import ContractError, atomic_json, identity, read_stage, seal, sha


@pytest.mark.parametrize('root', protection.ROOTS)
@pytest.mark.parametrize('operation', ['create', 'modify', 'delete', 'mtime'])
def test_native_output_changes_are_detected(tmp_path, root, operation):
    directory = tmp_path/root; directory.mkdir(parents=True)
    artifact = directory/'artifact.csv'; artifact.write_bytes(b'original')
    before = protection.inventory(tmp_path)
    if operation == 'create':
        (directory/'new.csv').write_bytes(b'new')
    elif operation == 'modify':
        artifact.write_bytes(b'changed size')
    elif operation == 'delete':
        artifact.unlink()
    else:
        info = artifact.stat()
        os.utime(artifact, ns=(info.st_atime_ns, info.st_mtime_ns+1000000000))
    result = protection.compare(before, protection.inventory(tmp_path))
    assert result['unchanged'] is False
    assert len(result['changed_paths']) == 1


def test_candidate_and_scratch_writes_do_not_change_protected_inventory(tmp_path):
    before = protection.inventory(tmp_path)
    for name in ('scratch/session/log.txt', 'data/programme/candidates/test/bundle/output.csv'):
        path = tmp_path/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('permitted work')
    assert protection.compare(before, protection.inventory(tmp_path))['unchanged'] is True


def test_unreadable_inventory_cannot_certify_preservation():
    partial = dict(records={}, unreadable=['data/output/unknown'], roots={})
    assert protection.compare(partial, partial)['unchanged'] is False


def test_root_disappearance_is_detected_even_when_empty(tmp_path):
    directory = tmp_path/'data/output'; directory.mkdir(parents=True)
    before = protection.inventory(tmp_path)
    directory.rmdir()
    assert protection.compare(before, protection.inventory(tmp_path))['roots_changed'] is True


def protected_stage(tmp_path):
    attempt = tmp_path/'attempt'; (attempt/'bundle').mkdir(parents=True)
    (attempt/'bundle/result.csv').write_text('value\n1\n')
    expected = identity('fixture', 'source', 'runtime', 'contract', {},
                        dict(protected_outputs='size-mtime-v1'))
    inventory = protection.inventory(tmp_path)
    for name in ('before', 'after'):
        atomic_json(attempt/('protected_'+name+'.json'), inventory)
    result = protection.compare(inventory, inventory)
    result.update(before_sha256=sha(attempt/'protected_before.json'),
                  after_sha256=sha(attempt/'protected_after.json'))
    atomic_json(attempt/'protected_result.json', result)
    atomic_json(attempt/'process_result.json', dict(exit_code=0, worker_stopped=True,
        input_fingerprint=expected['fingerprint'], protected_outputs_unchanged=True,
        protected_result_sha256=sha(attempt/'protected_result.json')))
    return attempt, expected


def test_changed_protection_evidence_cannot_be_sealed_or_reused(tmp_path):
    attempt, expected = protected_stage(tmp_path)
    protection.verify(attempt)
    seal(attempt, expected, ['result.csv'])
    read_stage(attempt, expected, ['result.csv'])
    atomic_json(attempt/'protected_before.json', dict(records={}, unreadable=[], roots={}))
    with pytest.raises(ContractError, match='proof is invalid'):
        read_stage(attempt, expected, ['result.csv'])


def test_failed_output_protection_blocks_otherwise_successful_stage(tmp_path):
    attempt, expected = protected_stage(tmp_path)
    from pipeline.programme.core import read_json
    process = read_json(attempt/'process_result.json')
    process['protected_outputs_unchanged'] = False
    atomic_json(attempt/'process_result.json', process)
    with pytest.raises(ContractError, match='proof is missing, changed or failed'):
        seal(attempt, expected, ['result.csv'])
    assert not (attempt/'complete.json').exists()
