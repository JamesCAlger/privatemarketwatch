-- A position has a single fair value, dated at its filing's period end.
select r.accession, r.context_id, r.role_rule, cf.fair_value, cf.is_filing_period_end
from {{ ref('int_source_row') }} r
join {{ ref('int_context_feature') }} cf on cf.accession = r.accession and cf.context_id = r.context_id
where r.role = 'position' and (cf.fair_value is null or not cf.is_filing_period_end)
