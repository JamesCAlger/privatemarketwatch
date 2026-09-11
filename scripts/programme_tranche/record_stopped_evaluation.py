"""Record all required metrics as unmeasured after an unsealed candidate stops."""
from pathlib import Path

from pipeline.programme.catalog import CRITERIA, METRIC_UNITS
from pipeline.programme.core import atomic_json, digest, read_json, record
from pipeline.programme.measurement import CONTRACTS, evaluate
from scripts.programme_tranche.measure_candidate import GAPS

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=ROOT/'docs/production_stack/programme_tranche_evidence_2026-09-10'


def main():
    output=EVIDENCE/'evaluation-stopped-v1'
    output.mkdir(parents=True,exist_ok=False)
    failure=EVIDENCE/'runtime-failure-v1/result.json'
    snapshot=ROOT/'data/programme/candidates/t1-runtime-20260910-v3/snapshot.json'
    inputs=[record(ROOT,path.relative_to(ROOT).as_posix()) for path in
        (failure,snapshot,CONTRACTS/'working-v1.json',Path(__file__))]
    identity=digest(dict(execution='unsealed_stopped',files=inputs))
    observations={}
    for criterion,(_,metrics) in CRITERIA.items():
        for metric in metrics:
            observations[metric]=dict(schema_version=1,metric_id=metric,metric_version=1,
                candidate_fingerprint=identity,scope='cohort_70_required_history',quarter=None,
                design='unmeasured',denominator_known=False,eligible=0,assessed=0,missing_weight=0,
                value=None,unit=METRIC_UNITS[metric],formula='Not executed on a complete integrated candidate',
                evidence=[],references=[],reason='Candidate execution stopped before a supported stage was sealed. '+
                    GAPS.get(criterion,'Whole-history coverage measurement requires the completed integrated candidate.'))
    criteria=evaluate(read_json(CONTRACTS/'working-v1.json'),observations,identity,ROOT)
    atomic_json(output/'observations.json',observations)
    atomic_json(output/'criterion_results.json',criteria)
    atomic_json(output/'execution.json',dict(status='blocked',complete_candidate=False,
        financial_measurement_executed=False,identity_basis='Failed attempt and snapshot; not an accepted integrated stage graph',
        candidate_fingerprint=identity,inputs=inputs))
    atomic_json(output/'evaluation_manifest.json',dict(files=[record(output,path.name)
        for path in sorted(output.iterdir()) if path.is_file()],status='stopped_result_inventory_only'))
    print('Stopped result recorded: 28 criteria, 50 unmeasured metrics; no acceptance claim',flush=True)


if __name__=='__main__':
    main()
