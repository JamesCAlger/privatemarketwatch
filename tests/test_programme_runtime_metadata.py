"""Legacy package metadata must be pinned before any candidate work starts."""
from types import SimpleNamespace
import importlib.metadata
import pytest

from pipeline.programme import native
from pipeline.programme.core import digest
from pipeline.programme.bootstrap import read_guard
from pipeline.programme import runtime_content
from pipeline.programme.core import ContractError
import time


def test_legacy_manifest_omission_is_covered_in_both_package_roots(tmp_path, monkeypatch):
    environment=tmp_path/'environment'; environment.mkdir()
    executable=environment/'python.exe'; executable.write_bytes(b'fake runtime')
    codex=tmp_path/'cli/codex.exe'; codex.parent.mkdir(); codex.write_bytes(b'fake sandbox')
    user_site=tmp_path/'user/site-packages'; user_site.mkdir(parents=True)
    environment_site=environment/'Lib/site-packages'; environment_site.mkdir(parents=True)
    paths=[]
    for root,kind in ((environment_site,'egg-info'),(user_site,'dist-info')):
        directory=root/('example-1.0.'+kind); directory.mkdir()
        metadata=directory/'entry_points.txt'; metadata.write_text('[plugins]\nexample=example:main\n')
        paths.append(metadata)
    monkeypatch.setattr(native.sys,'executable',str(executable))
    monkeypatch.setattr(native.site,'getusersitepackages',lambda: str(user_site))
    monkeypatch.setattr(native,'codex_executable',lambda: codex)
    # Installed legacy metadata is allowed to provide an incomplete file list.
    monkeypatch.setattr(importlib.metadata,'distributions',lambda: [
        SimpleNamespace(metadata={'Name':'example'},version='1.0',files=[])])
    def forbid_full_scan(roots):
        raise AssertionError('New candidates must not scan the complete environment')
    monkeypatch.setattr(native, 'physical_runtime_files', forbid_full_scan)
    before=native.runtime_identity()
    assert before['identity_policy'] == 'package-metadata-v1'
    declared={item['path']:item for item in before['content']}
    assert all(path.as_posix() in declared for path in paths)
    paths[0].write_text('[plugins]\nexample=different:main\n')
    after=native.runtime_identity()
    assert digest(before) != digest(after)
    extra=paths[1].parent/'plugin-policy.json'; extra.write_text('{"allow": false}')
    assert digest(after) != digest(native.runtime_identity())
    package_data = environment/'unrelated-package-data.bin'
    package_data.write_bytes(b'Not part of the package fingerprint')
    stable = native.runtime_identity()
    package_data.write_bytes(b'Installed contents are an explicit trust boundary')
    assert digest(stable) == digest(native.runtime_identity())


def test_single_file_egg_metadata_is_included_without_unrelated_data(tmp_path):
    metadata=tmp_path/'legacy.egg-info'; metadata.write_text('Name: legacy\nVersion: 1\n')
    unrelated=tmp_path/'unrelated.txt'; unrelated.write_text('Not package metadata')
    assert native.package_metadata_files([tmp_path]) == {metadata.absolute()}


def test_physical_inventory_covers_non_package_assets_and_only_skips_redirected_bytecode(tmp_path):
    paths = [tmp_path/'share/settings.json', tmp_path/'plugins/entry_points.txt',
             tmp_path/'opaque.data', tmp_path/'bin/extension.pyd']
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'input')
    cache = tmp_path/'__pycache__/ignored.pyc'
    cache.parent.mkdir(); cache.write_bytes(b'old bytecode')
    assert native.physical_runtime_files([tmp_path]) == set(paths)
    extra = tmp_path/'new-file-without-extension'; extra.write_bytes(b'new')
    assert extra in native.physical_runtime_files([tmp_path])


def test_read_guard_rejects_existing_unrecorded_runtime_input_before_consumption(tmp_path):
    runtime = tmp_path/'runtime'; runtime.mkdir()
    known = runtime/'known.json'; known.write_text('{}')
    unexpected = runtime/'unlisted.txt'; unexpected.write_text('must fail')
    attempt = tmp_path/'attempt'; attempt.mkdir()
    local = attempt/'temp/output'; local.parent.mkdir(); local.write_text('local')
    check = read_guard(attempt, dict(content_roots=[str(runtime)], content=[dict(path=str(known))]))
    assert check(known) == known.resolve()
    assert check(local) == local.resolve()
    assert check(runtime/'missing-optional-file') == (runtime/'missing-optional-file').resolve()
    with pytest.raises(PermissionError, match='Unrecorded runtime input'):
        check(unexpected)
    with pytest.raises(PermissionError, match='Undeclared Python input'):
        check(tmp_path/'outside')


def test_parallel_hashes_cover_every_file_in_deterministic_order(tmp_path):
    files = [tmp_path / name for name in ('c', 'a', 'b')]
    for path in files:
        path.write_text(path.name)
    actual = runtime_content.hash_files(set(files), time.monotonic())
    assert actual == [runtime_content.hash_file(path) for path in sorted(files)]


def test_runtime_change_during_hash_is_rejected(tmp_path, monkeypatch):
    path = tmp_path/'input'; path.write_text('before')
    original = runtime_content.sha
    def change_during_read(value):
        result = original(value)
        value.write_text('changed after read')
        return result
    monkeypatch.setattr(runtime_content, 'sha', change_during_read)
    with pytest.raises(ContractError, match='changed while fingerprinting'):
        runtime_content.hash_file(path)


def test_missing_runtime_tree_cannot_be_silently_skipped(tmp_path):
    with pytest.raises(ContractError, match='root is missing'):
        native.physical_runtime_files([tmp_path/'missing'])


def test_package_read_guard_keeps_external_sources_outside_trusted_roots(tmp_path):
    runtime = tmp_path/'runtime'; runtime.mkdir()
    package_data = runtime/'package/data.json'; package_data.parent.mkdir()
    package_data.write_text('{}')
    attempt = tmp_path/'candidate'; attempt.mkdir()
    policy = dict(identity_policy='package-metadata-v1', content_roots=[str(runtime)], content=[])
    check = read_guard(attempt, policy)
    assert check(package_data) == package_data.resolve()
    assert check(attempt/'bundle/data.csv') == (attempt/'bundle/data.csv').resolve()
    with pytest.raises(PermissionError, match='Undeclared Python input'):
        check(runtime/'../source-filings.json')


def test_unknown_runtime_policy_is_rejected(tmp_path):
    with pytest.raises(ContractError, match='Unsupported runtime identity'):
        native.runtime_identity(policy='unchecked')
    with pytest.raises(ContractError, match='Unsupported runtime read'):
        read_guard(tmp_path, dict(identity_policy='unchecked', content_roots=[], content=[]))


def test_historical_runtime_proofs_keep_their_original_policy(monkeypatch):
    monkeypatch.setattr(native, 'runtime_identity', lambda **kwargs: kwargs)
    assert native.runtime_for_record({}) == dict(policy='physical-content-v1')
    assert native.runtime_for_record(dict(identity_policy='package-metadata-v1')) == dict(policy='package-metadata-v1')


def test_observed_runtime_reads_are_hash_bound_but_not_claimed_as_prevalidated(tmp_path):
    from pipeline.programme import runner
    from pipeline.programme.core import atomic_json, read_json, sha
    candidate = tmp_path/'candidate'
    attempt = candidate/'attempts/identity-01'
    (attempt/'bundle').mkdir(parents=True)
    runtime = tmp_path/'runtime'; runtime.mkdir()
    dependency = runtime/'package-data.json'; dependency.write_text('{"value": 1}')
    atomic_json(candidate/'runtime.json', dict(identity_policy='package-metadata-v1',
        content_roots=[str(runtime)], content=[]))
    atomic_json(attempt/'bundle/read_ledger.json', dict(python_paths=[str(dependency)]))
    runner.capture_runtime_reads(attempt)
    observed = read_json(attempt/'runtime_reads.json')
    assert observed['identity_policy'] == 'package-metadata-v1'
    assert 'after execution' in observed['role']
    assert observed['records'][0]['sha256'] == sha(dependency)
    atomic_json(attempt/'process_result.json', dict(runtime_reads_sha256=sha(attempt/'runtime_reads.json')))
    runner.verify_runtime_reads(attempt)
    dependency.write_text('{"value": 2}')
    with pytest.raises(ContractError, match='dependency changed'):
        runner.verify_runtime_reads(attempt)
