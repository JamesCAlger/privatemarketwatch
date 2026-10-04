"""Cached evidence cannot silently outlive a parsing dependency change."""
from copy import deepcopy

import pytest

from pipeline import jev_bundles as jb


def cache_source(tmp_path):
    directory = tmp_path / '1'
    directory.mkdir()
    (directory / '000000000125000001.html').write_text('<html><body>Frozen source</body></html>', encoding='utf-8')
    return {'cik': '0000000001', 'accession_number': '0000000001-25-000001'}


@pytest.mark.parametrize('field,value', [
    ('date_helper_sha256', 'a' * 64), ('beautifulsoup_version', 'changed'),
    ('lxml_version', [99, 0, 0]), ('libxml_runtime_version', [99, 0, 0]),
    ('python_version', '99.0.0'),
])
def test_changed_dependency_refuses_cached_evidence(tmp_path, monkeypatch, field, value):
    row = cache_source(tmp_path)
    runtime = deepcopy(jb.parser_runtime())
    monkeypatch.setattr(jb, 'parser_runtime', lambda: deepcopy(runtime))
    parsed = []
    monkeypatch.setattr(jb, 'parse_source', lambda raw: parsed.append(raw) or {'tables': []})
    cache = jb.SourceCache(html_cache_dir=tmp_path)
    first, metadata = cache.load(row)
    assert first is not None and metadata['status'] == 'cached_source_parsed'
    assert cache.load(row)[0] is first and len(parsed) == 1
    original_hash = cache.runtime_hash
    runtime[field] = value
    result, metadata = cache.load(row)
    assert result is None and metadata['status'] == 'parser_runtime_changed'
    assert not cache.entries and len(parsed) == 1
    fresh = jb.SourceCache(html_cache_dir=tmp_path)
    assert fresh.runtime_hash != original_hash
    assert fresh.load(row)[0] is not None and len(parsed) == 2


def test_dependency_change_during_parse_is_not_cached(tmp_path, monkeypatch):
    row = cache_source(tmp_path)
    runtime = deepcopy(jb.parser_runtime())
    monkeypatch.setattr(jb, 'parser_runtime', lambda: deepcopy(runtime))
    cache = jb.SourceCache(html_cache_dir=tmp_path)
    def changed_during_parse(raw):
        runtime['date_helper_sha256'] = 'b' * 64
        return {'tables': []}
    monkeypatch.setattr(jb, 'parse_source', changed_during_parse)
    parsed, metadata = cache.load(row)
    assert parsed is None and metadata['status'] == 'parser_runtime_changed'
    assert not cache.entries


def test_metadata_cannot_mutate_cache_dependency_binding(tmp_path):
    row = cache_source(tmp_path)
    cache = jb.SourceCache(html_cache_dir=tmp_path)
    _, metadata = cache.load(row)
    original = deepcopy(cache.runtime)
    metadata['parser_runtime']['lxml_version'][0] = 99
    metadata['parser_runtime']['date_helper_sha256'] = 'c' * 64
    assert cache.runtime == original
    assert cache.load(row)[1]['status'] == 'cached_source_parsed'


def test_recorded_runtime_is_content_bound_and_explicit(tmp_path):
    row = cache_source(tmp_path)
    cache = jb.SourceCache(html_cache_dir=tmp_path)
    _, metadata = cache.load(row)
    assert metadata['parser_runtime_sha256'] == jb.parser_runtime_fingerprint(metadata['parser_runtime'])
    assert metadata['parser_sha256'] == metadata['parser_runtime']['builder_sha256']
    assert len(metadata['parser_runtime']['date_helper_sha256']) == 64
    assert metadata['parser_runtime']['schema_version'] == 'jev-parser-runtime.v1'
