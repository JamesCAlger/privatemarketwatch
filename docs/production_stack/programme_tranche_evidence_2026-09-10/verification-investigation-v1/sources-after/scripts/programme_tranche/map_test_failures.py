"""Map saved pytest progress symbols to a fresh collection; retain assumptions."""
from pathlib import Path
import re

from pipeline.programme.core import atomic_json, read_json, record, sha

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'scratch/2026-09-10_verification_investigation'
LOG = ROOT/'docs/production_stack/programme_tranche_evidence_2026-09-10/test-boundary-failure-v1/process.log'
COLLECTION = BASE/'collect-v2/telemetry/collection.json'


def main():
    nodes = read_json(COLLECTION)
    added = 'tests/test_agent_data_query.py::test_file_backed_query_cache_is_temporary_and_keeps_cik_scope'
    assert nodes.count(added) == 1
    previous = [node for node in nodes if node != added]
    progress = ''.join(match.group(1) for line in LOG.read_text(encoding='utf-8').splitlines()
                      if (match := re.fullmatch(r'([.FsxEX]+)(?:\s+\[\s*\d+%\])?', line)))
    failures = [dict(one_based_index=index+1, nodeid=previous[index])
                for index, symbol in enumerate(progress) if symbol == 'F']
    current = ROOT/'scratch/2026-09-10_programme_tranche/verification/full-suite-v1/progress_observation.json'
    observation = read_json(current)['current_test'].removesuffix(' (call)')
    result = dict(original_log=record(ROOT, LOG.relative_to(ROOT).as_posix()),
        collection=record(ROOT, COLLECTION.relative_to(ROOT).as_posix()),
        current_nodes=len(nodes), removed_new_test=added, inferred_original_nodes=len(previous),
        observed_progress=len(progress), failure_markers=len(failures), failures=failures,
        last_progress_nodes=previous[max(0,len(progress)-3):len(progress)+2],
        saved_worker_observation=observation, observation_index=previous.index(observation)+1,
        confidence='Candidate mapping from unchanged pytest order after removing the one newly added case; reproduce each failure to confirm its mechanism. No original collection manifest survived.')
    atomic_json(BASE/'failure_mapping.json', result)
    for item in failures:
        print(str(item['one_based_index'])+' '+item['nodeid'], flush=True)
    print('Observed progress '+str(len(progress))+'; original collection estimate '+str(len(previous)), flush=True)


if __name__ == '__main__':
    main()
