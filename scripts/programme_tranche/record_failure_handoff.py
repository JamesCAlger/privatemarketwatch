"""Assemble a truthful failure handoff from completed preservation/test records."""
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from pipeline.programme.core import ContractError, atomic_json, read_json, record, sha
from scripts.diff_outputs import _is_material_delta, _numeric_delta

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=ROOT/'docs/production_stack/programme_tranche_evidence_2026-09-10'
SCRATCH=ROOT/'scratch/2026-09-10_programme_tranche/verification'


def main():
    output=EVIDENCE/'handoff-stopped-v1'
    output.mkdir(parents=True,exist_ok=False)
    testing=SCRATCH/'runtime-fix-focused-v1'
    test_result=read_json(testing/'result.json')
    preservation=read_json(EVIDENCE/'preservation-stopped-v1/result.json')
    semantic=SCRATCH/'after-fix-semantic-v1'
    semantic_result=read_json(semantic/'result.json')
    if any(result['exit_code'] or result['timed_out'] or not result['worker_stopped'] or
           result['protected_changes'] or result['protected_unreadable_paths_changed']
           for result in (test_result,semantic_result)):
        raise ContractError('Closeout verification is incomplete or changed protected outputs')
    # Preserve the first check's failure. Its comparison used the relative scale
    # of a small derived delta instead of the source totals being subtracted.
    # Diagnose each recorded difference from the two immutable source reports;
    # use the existing backstop's numeric rule without changing any threshold.
    before_report=read_json(ROOT/preservation['previous_report']['path'])['artifacts']
    after_report=read_json(ROOT/preservation['semantic_report']['path'])['artifacts']
    roundoff=[]
    for difference in preservation['semantic_changes_since_preparation']:
        location=difference.split(':')[0]
        family,group,index,column=location.strip('/').split('/')
        if not column.endswith('_delta'):
            raise ContractError('Unexplained non-delta semantic change')
        old_row=before_report[family][group][int(index)]
        new_row=after_report[family][group][int(index)]
        base=column[:-6]
        for suffix in ('_current','_baseline'):
            old,new=old_row[base+suffix],new_row[base+suffix]
            if _is_material_delta(base,_numeric_delta(new,old),new,old):
                raise ContractError('Material source-summary change remains unexplained')
        for row in (old_row,new_row):
            if row[column] != _numeric_delta(row[base+'_current'],row[base+'_baseline']):
                raise ContractError('Derived delta does not equal its recorded source subtraction')
        roundoff.append(dict(path=location,old_delta=old_row[column],new_delta=new_row[column],
            delta_change=new_row[column]-old_row[column],source_totals_within_existing_noise_rule=True))
    if preservation['status'] not in ('pass','unexplained_difference'):
        raise ContractError('Unknown preservation result')
    atomic_json(output/'semantic_disposition.json',dict(original_checker_status=preservation['status'],
        material_source_summary_changes=0,derived_delta_roundoff=roundoff,
        mechanism='Floating aggregate differences propagated through subtraction. Each original current/baseline total passes the unchanged semantic backstop numeric-noise rule; every recorded delta equals its source subtraction. Original input files separately match their frozen hashes.',
        original_preservation_result=record(ROOT,(EVIDENCE/'preservation-stopped-v1/result.json').relative_to(ROOT).as_posix())))
    suite=ET.parse(testing/'junit.xml').getroot().find('testsuite')
    counts={name:int(suite.attrib[name]) for name in ('tests','failures','errors','skipped')}
    if counts != dict(tests=60,failures=0,errors=0,skipped=0):
        raise ContractError('Unexpected focused verification result')
    for source,name in ((testing/'result.json','focused_result.json'),
        (testing/'junit.xml','focused_junit.xml'),(testing/'process.log','focused.log'),
        (semantic/'result.json','semantic_result.json'),
        (semantic/'semantic_diff_report.json','semantic_diff_report.json')):
        shutil.copy2(source,output/name)
    failure=read_json(EVIDENCE/'runtime-failure-v1/result.json')
    candidate=ROOT/'data/programme/candidates/t1-runtime-20260910-v3'
    expected=read_json(candidate/'attempts/unified-01/inputs.json')['identity']['controls']['controller_code']
    executed=EVIDENCE/'runtime-failure-v1/native.executed.py'
    if sha(executed) != expected['pipeline/programme/native.py']:
        raise ContractError('Executed native controller copy does not match the attempt')
    summary=dict(execution_status='blocked',engineering_tranche_complete=False,
        summary='The worker finished, but one unpinned package metadata file prevented completion. The narrow fix passes 60 focused tests. Original inputs and protected outputs are preserved; full-suite and integrated/recovery verification remain unrun.',
        worker=dict(rows=780425,seconds=failure['worker_elapsed_seconds'],exit_code=0,stopped=True,
            completed_stage=False,worker_reported_typed_pairs=2,controller_final_pair_verification=False),
        runtime_failure=dict(omitted_files=len(failure['missing_runtime_records']),
            changed_declared_files=len(failure['changed_declared_records']),posthoc_sealing=False),
        verification=dict(focused=counts,focused_seconds=float(suite.attrib['time']),
            full_suite='not run',corrected_native_candidate='not run',timeout_reuse_restore='not run',
            protected_files_checked=test_result['protected_readable_files'],protected_changes=0,
            semantic_scope='Five artifact families; full baseline byte scan not rerun',
            semantic_groups=preservation['baseline_divergence_groups'],
            material_source_summary_changes=0,derived_delta_roundoff_fields=len(roundoff),
            largest_delta_roundoff_usd=max((abs(row['delta_change']) for row in roundoff),default=0),
            original_preservation_checker=preservation['status'],original_inputs=preservation['original_input_files'],
            original_match_references=preservation['original_match_reference_files'],original_gold_unchanged=True),
        accepted_product_metrics=dict(criteria=28,metrics=50,measured=0,reason='No complete integrated candidate'),
        references=dict(dispositions=61,label_proposals=20,independently_reviewed=0),
        remediation_packets=4,production_adoption=False,sec_requests=0,paid_calls=0,
        next_decision='One additional fresh candidate attempt within the original deadline; see the concrete resume proposal',
        new_native_code=record(ROOT,'pipeline/programme/native.py'))
    atomic_json(output/'verification.json',summary)
    atomic_json(output/'complete.json',dict(status='failure_handoff',artifacts=[record(output,p.name)
        for p in sorted(output.iterdir()) if p.is_file()],code=record(ROOT,Path(__file__).relative_to(ROOT).as_posix())))
    print('Failure handoff recorded; engineering end-state remains incomplete',flush=True)


if __name__=='__main__':
    main()
