-- Baseline: published holdings fair value differs from the filed fair-value fact on the same context (exact after casting both to DECIMAL(38,2)). Rows with a recorded correction that names fair_value.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['filed_fair_value_differs_corrected']) }}
with fv as (
    -- One filed fair value per context: the value of the InvestmentOwnedAtFairValue facts of the us-gaap namespaces (matched on local name and namespace, not on the prefix).
    -- A context with more than one distinct value is ambiguous and is counted by baseline_filed_fair_value_ambiguous.
    select accession, context_id, count(distinct value_numeric) as distinct_values, min(value_numeric) as filed_value
    from {{ ref('stg_filed_fact') }}
    where concept_local = 'InvestmentOwnedAtFairValue' and concept_namespace like 'http://fasb.org/us-gaap/%'
    group by 1, 2
)
select h.cik, h.report_date, h.accession_number, h.src_context_id, h.fair_value, fv.filed_value, h.corrected_fields
from {{ ref('stg_holdings') }} h
join fv on fv.accession = h.accession_number and fv.context_id = h.src_context_id
where h.accounting_record_class is distinct from 'underlying_schedule'
  and fv.distinct_values = 1
  and coalesce(h.corrected_fields like '%fair_value%', false)
  and cast(h.fair_value as decimal(38,2)) <> cast(fv.filed_value as decimal(38,2))
