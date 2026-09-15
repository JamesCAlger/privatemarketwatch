"""Measure a sealed export's citation coverage; do not adopt or repair data."""
import argparse
from pathlib import Path

import duckdb

from pipeline.delivery_coverage import build_census, load_history, metrics, verify_documents
from pipeline.programme.artifacts import literal, required
from pipeline.programme.core import ContractError, atomic_json, read_json, read_stage, sha
from pipeline.programme.runner import ROOT, candidate_path, heavy_lock


def evaluate(candidate, history, output):
    candidate, history, output = Path(candidate), Path(history).resolve(), Path(output).resolve()
    attempt = candidate / 'attempts/frontend-01'
    stage = read_json(attempt / 'result.json')
    read_stage(attempt, stage['identity'], required('frontend'))
    exported = read_json(attempt / 'bundle/frontend_export.json')
    if (output.exists() or output == history or output.is_relative_to(history)
            or not output.is_relative_to(ROOT / 'scratch')):
        raise ContractError('Use a new evidence directory outside the export')
    output.mkdir(parents=True)
    requests = output / 'browser_requests'
    requests.mkdir()
    inputs = {str(attempt / 'result.json'): sha(attempt / 'result.json')}
    # Bind the actual evaluated history to every sealed history export artifact.
    records = {r['path'][len('holdings_history/'):]: r for r in exported['artifacts']
               if r['path'].startswith('holdings_history/')}
    actual = {p.relative_to(history).as_posix() for p in history.rglob('*') if p.is_file()}
    if actual != set(records):
        raise ContractError('History file inventory differs from sealed export')
    for relative, item in records.items():
        path = history / relative
        if path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
            raise ContractError('History differs from sealed export: ' + relative)
        inputs[str(path)] = item['sha256']
    with duckdb.connect(str(output / 'census.duckdb'), config={'threads':2,'memory_limit':'-1'}) as con:
        manifest, history_inputs = load_history(con, history)
        inputs.update(history_inputs)
        if manifest['evidence_default'] != dict(status='unavailable',reason='No verified field locator in this release'):
            raise ContractError('Missing or changed explicit unavailable default')
        build_census(con, manifest['release_id'])
        documents, source_inputs = verify_documents(con, history,
            attempt / 'workspace/data/raw/filings/bdc_html', requests)
        inputs.update(source_inputs)
        result = metrics(con)
        link_references = con.execute('SELECT count(*) FROM delivery_links').fetchone()[0]
        errors = con.execute('SELECT count(*) FROM (SELECT * FROM delivery_graph_errors UNION ALL SELECT * FROM delivery_link_errors)').fetchone()[0]
        total, valid = con.execute('SELECT count(*),count(*) FILTER(WHERE valid) FROM delivery_fields WHERE displayed').fetchone()
        for name in ('delivery_graph_errors','delivery_link_errors'):
            con.execute('COPY ' + name + ' TO ' + literal(output / (name + '.csv')) + ' (HEADER)')
        result.update(release_id=manifest['release_id'],stage_result_sha256=inputs[str(attempt / 'result.json')],
            metadata_errors=errors,displayed_evidence_cells=total,valid_displayed_evidence_cells=valid,
            direct_field_link_references=link_references,
            evidence_path_or_unavailable=valid / total if total else None,
            misleading_links=None,misleading_links_status='UNASSESSABLE pending complete browser census',
            architecture_status='FAIL' if errors or not total or valid != total else 'BROWSER_PENDING',
            adoption='not_adopted')
    if any(sha(path) != expected for path, expected in inputs.items()):
        raise ContractError('Delivery input changed during evaluation')
    from pipeline import delivery_coverage
    result['evaluator_code'] = {str(p): sha(p) for p in (Path(__file__), Path(delivery_coverage.__file__))}
    atomic_json(output / 'inputs.json', inputs)
    atomic_json(requests / 'manifest.json',dict(release_id=manifest['release_id'],documents=documents,
        metadata_errors=errors))
    result['browser_request_manifest_sha256'] = sha(requests / 'manifest.json')
    atomic_json(output / 'result.json',result)
    print('Delivery census: ' + result['architecture_status'] + '; source coverage verdicts are reported separately', flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--history', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    with heavy_lock(candidate_path(args.candidate)):
        result = evaluate(candidate_path(args.candidate), args.history, args.output_dir)
    if result['architecture_status'] == 'FAIL':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
