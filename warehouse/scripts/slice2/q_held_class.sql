-- class of every production-only row this layer holds unresolved (causes new_wrong and owner_review). Classes were
-- defined after reading all 133 printed lines and facts (out_held_dump.tsv); the rules below reproduce that reading.
with h as (
  select c.basis, c.cik, c.report_date, c.accession, c.context_id, cf.identifier_label as label, c.fair_value, c.cause,
    exists (select 1 from stg_filed_fact f where f.accession=c.accession and f.context_id=c.context_id and f.concept_local ilike '%Commitment%') as has_commitment_fact
  from cmp_row_set c join int_context_feature cf using (accession, context_id)
  where c.side='production_only' and c.role='unresolved' and c.cause in ('new_wrong','owner_review')
)
select cik, report_date, accession, context_id, label, fair_value,
  case
    when regexp_matches(label, '^(BCRED (Emerald|Verdelite) JV|Specialty Lending Company LLC|ULTRA III, LLC)') then 'own_jv_or_fund_interest'
    when has_commitment_fact then 'unfunded_commitment_line'
    when fair_value = 0 and lower(label) like '%revolving loan%' then 'undrawn_revolver_zero_value'
    else 'equity_or_fund_interest_no_units_tagged'
  end as class, basis, cause
from h order by cik, class, label, report_date
