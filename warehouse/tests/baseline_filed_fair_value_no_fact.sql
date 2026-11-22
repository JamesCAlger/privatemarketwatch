-- Baseline: a published holdings row whose context exists but carries no fair-value fact (seed concept_map, field fair_value; matched on local name and namespace).
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['filed_fair_value_no_fact']) }}
with fv as (
    -- One filed fair value per context: the value of the fair-value facts (seed concept_map, field fair_value: local name and namespace pattern, not the prefix).
    -- A context with more than one distinct value is ambiguous and is counted by baseline_filed_fair_value_ambiguous.
    select accession, context_id, count(distinct value_numeric) as distinct_values, min(value_numeric) as filed_value
    from {{ ref('stg_filed_fact') }} f
    join {{ ref('concept_map') }} m
        on m.field = 'fair_value' and m.concept_local = f.concept_local and f.concept_namespace glob m.namespace_pattern
    group by 1, 2
)
select h.cik, h.report_date, h.accession_number, h.src_context_id, h.fair_value, h.corrected_fields
from {{ ref('stg_holdings') }} h
join {{ ref('stg_filed_context') }} c on c.accession = h.accession_number and c.context_id = h.src_context_id
left join fv on fv.accession = h.accession_number and fv.context_id = h.src_context_id
where h.accounting_record_class is distinct from 'underlying_schedule' and (fv.context_id is null or fv.distinct_values = 0)
