"""Bounded stylesheet inventory on frozen source-first inputs; not a CSS renderer."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.jev_screening import fingerprint
from scripts.compare_jev_retrieval import load_replay
from scripts.jev_pilot_session import install_read_only_guard, read, sha, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--replay', required=True)
    parser.add_argument('--review-label', required=True)
    args = parser.parse_args()
    repo, run = args.repo.resolve(), args.run_root.resolve()
    if repo == ROOT or not run.is_relative_to(repo / 'data/pilot/jev_screening'):
        raise ValueError('Isolated pilot required')
    if not args.review_label.replace('_', '').isalnum():
        raise ValueError('Simple review label required')
    install_read_only_guard(repo, run)
    summary, packets = load_replay(run, args.replay)
    if len(packets) != 67:
        raise ValueError('Expected frozen 67-case scope')
    directory = run / args.review_label
    manifest = read(directory / 'manifest.json')
    if manifest['replay'] != args.replay or manifest['builder_sha256'] != summary['builder_sha256']:
        raise ValueError('Manifest version mismatch')
    expected = {fingerprint(p) for p in packets.values()}
    seen, sources = set(), {}
    for item in manifest['inventory']:
        path = (directory / item['file']).resolve()
        if path.parent != directory or sha(path) != item['sha256']:
            raise ValueError('Prepared input changed or escaped directory')
        prepared = read(path)
        binding = prepared['snapshot']['bundle_fingerprint']
        if binding not in expected or binding in seen:
            raise ValueError('Unexpected or duplicate packet')
        seen.add(binding)
        source = Path(prepared['source']['path']).resolve()
        digest = prepared['source']['sha256']
        if source in sources and sources[source] != digest:
            raise ValueError('Conflicting source bindings')
        sources[source] = digest
    if seen != expected or len(sources) != 26:
        raise ValueError('Incomplete frozen source coverage')
    records = []
    for index, (source, digest) in enumerate(sorted(sources.items()), 1):
        if not source.is_relative_to(repo / 'data/raw/filings/bdc_html') or source.stat().st_size > 40 * 1024 * 1024:
            raise ValueError('Source outside bounded cache')
        if sha(source) != digest:
            raise ValueError('Source changed')
        print(f'Stylesheet inventory: {index}/{len(sources)}', flush=True)
        html = source.read_bytes().decode('utf-8')
        blocks = re.findall(r'<style\b[^>]*>(.*?)</style\s*>', html, re.I | re.S)
        if sum(map(len, blocks)) > 1000000:
            raise ValueError('Stylesheet inventory exceeds cap')
        findings = []
        for block_index, css in enumerate(blocks):
            # Record positive lexical declarations only. Comments, media queries,
            # selector applicability and cascade are not resolved here.
            for match in re.finditer(r'[^{}]+\{[^{}]*\}', css):
                if re.search(r'(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\b', match[0], re.I):
                    if len(match[0]) > 10000 or len(findings) >= 100:
                        raise ValueError('Visibility rule inventory exceeds cap')
                    findings.append({'block_index': block_index, 'css_fragment': match[0]})
        links = [tag for tag in re.findall(r'<link\b[^>]*>', html, re.I)
                 if re.search(r'\bstylesheet\b', tag, re.I)]
        if len(links) > 50 or any(len(link) > 10000 for link in links):
            raise ValueError('External stylesheet inventory exceeds cap')
        imports = sum(len(re.findall(r'@import\b', css, re.I)) for css in blocks)
        records.append({'source_relative_path': str(source.relative_to(repo)), 'source_sha256': digest,
                        'style_blocks': len(blocks), 'style_characters': sum(map(len, blocks)),
                        'visibility_fragments': findings, 'stylesheet_links': links, 'import_count': imports})
        if sha(source) != digest:
            raise ValueError('Source changed during inventory')
    counts = Counter()
    for record in records:
        counts['style_blocks'] += record['style_blocks']
        counts['visibility_fragments'] += len(record['visibility_fragments'])
        counts['stylesheet_links'] += len(record['stylesheet_links'])
        counts['imports'] += record['import_count']
    report = {'replay': args.replay, 'review_manifest_sha256': sha(directory / 'manifest.json'),
              'source_count': len(records), 'counts': dict(counts), 'sources': records,
              'script_sha256': sha(Path(__file__)), 'api_calls': 0, 'production_changes': 0,
              'limitation': 'Lexical inventory only; no CSS applicability, cascade, media, scripting, external-resource or rendered-visibility certification. No external resources fetched.'}
    destination = run / ('stylesheet_inventory_' + fingerprint(report)[:16] + '.json')
    if not destination.exists():
        write(destination, report)
    print(json.dumps({'artifact': destination.name, 'sources': len(records), 'counts': counts}), flush=True)


if __name__ == '__main__':
    timer = threading.Timer(120, lambda: os._exit(124))
    timer.daemon = True
    timer.start()
    try:
        main()
    finally:
        timer.cancel()
