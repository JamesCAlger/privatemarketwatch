-- Baseline: a published holdings row with no fair value (null) on a context that has one filed fair-value value.
-- The difference tests compare with <>, which drops a null; this test counts those rows so none goes unaccounted.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['filed_fair_value_null']) }}
with fv as (
    -- One filed fair value per context: the value of the InvestmentOwnedAtFairValue facts of the us-gaap namespaces (matched on local name and namespace, not on the prefix).
    -- A context with more than one distinct value is ambiguous and is counted by baseline_filed_fair_value_ambiguous.
    select accession, context_id, count(distinct value_numeric) as distinct_values, min(value_numeric) as filed_value
    from {{ ref('stg_filed_fact') }}
    where concept_local = 'InvestmentOwnedAtFairValue' and concept_namespace like 'http://fasb.org/us-gaap/%'
    group by 1, 2
)
select h.cik, h.report_date, h.accession_number, h.src_context_id, fv.filed_value, h.corrected_fields
from {{ ref('stg_holdings') }} h
join fv on fv.accession = h.accession_number and fv.context_id = h.src_context_id
where h.accounting_record_class is distinct from 'underlying_schedule'
  and fv.distinct_values = 1
  and h.fair_value is null
