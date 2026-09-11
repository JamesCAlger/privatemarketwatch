"""Proposal evaluator: assessability and statistical bounds precede pass/fail."""
import math

PROPOSED={
 'roster_fv_recall':('min',.99),'roster_fv_precision':('min',.99),
 'roster_row_recall':('min',.95),'roster_row_precision':('min',.95),
 'fund_roster_fv_floor':('min',.95),'fund_roster_row_floor':('min',.90),
 'amount_field_accuracy':('min',.995),'other_field_accuracy':('min',.99),
 'primary_absolute_error_ratio':('max',.0025),'fund_primary_error_ratio':('max',.01),
 'primary_fund_coverage':('min',.95),'primary_source_fv_coverage':('min',.99),
 'entity_precision':('min',.995),'entity_recall':('min',.95),
 'position_precision':('min',.995),'position_recall':('min',.95),
 'complete_chain_rate':('min',.95),'sector_accuracy':('min',.95),
 'sector_fv_coverage':('min',.95),'sector_row_coverage':('min',.90),
 'reported_amount_highlight_fv_coverage':('min',.99),
 'reported_numeric_highlight_row_coverage':('min',.95),
 'evidence_path_or_unavailable':('min',1),'misleading_links':('max',0),
 'local_citation_p95_ms':('max',5000)
}

def zero_error_lower_bound(independent_trials,alpha=.05):
    if not isinstance(independent_trials,int) or independent_trials<=0:raise ValueError('Positive independent trial count required')
    return alpha**(1/independent_trials)

def evaluate(metric,observation):
    if metric not in PROPOSED:raise ValueError('Unknown proposed metric')
    direction,threshold=PROPOSED[metric]
    base=dict(metric=metric,operator=direction,threshold=threshold,approval='proposal_only',release_id=observation.get('release_id'))
    def result(status,reason,**kw):return dict(base,status=status,reason=reason,**kw)
    if not observation.get('release_id') or not observation.get('input_sha256'):
        return result('UNASSESSABLE','missing_candidate_identity')
    if observation.get('missing_weight',0)>0 or observation.get('denominator_known') is not True:
        return result('UNASSESSABLE','unknown_denominator_or_FV_weight')
    if observation.get('requires_reference') and not observation.get('independent_reference'):
        return result('UNASSESSABLE','reference_not_independently_established')
    if observation.get('eligible',0)<=0:
        return result('UNASSESSABLE','empty_population_requires_explicit_applicability_decision')
    if observation.get('design')=='census':
        if observation.get('assessed')!=observation['eligible']:
            return result('UNASSESSABLE','incomplete_census')
        value=observation.get('value');basis='census_value'
    elif observation.get('design')=='sample':
        if not observation.get('design_id') or not observation.get('interval_method'):
            return result('UNASSESSABLE','missing_sampling_design_or_uncertainty_method')
        value=observation.get('lower_95_bound' if direction=='min' else 'upper_95_bound');basis='one_sided_95_bound'
        if value is None:return result('UNASSESSABLE','missing_uncertainty_bound')
    else:return result('UNASSESSABLE','undeclared_measurement_design')
    if value is None or not math.isfinite(value):return result('UNASSESSABLE','invalid_value')
    passed=value>=threshold if direction=='min' else value<=threshold
    return result('PASS' if passed else 'FAIL','evaluated_against_proposal',comparison_value=value,basis=basis)

def programme_verdict(results):
    if not results:return 'UNASSESSABLE'
    if any(r['status']=='FAIL' for r in results):return 'FAIL_WITH_UNASSESSED_ITEMS' if any(r['status']=='UNASSESSABLE' for r in results) else 'FAIL'
    if any(r['status']!='PASS' for r in results):return 'UNASSESSABLE'
    return 'MEETS_EVALUATED_PROPOSAL; owner approval and complete metric inventory still required'
