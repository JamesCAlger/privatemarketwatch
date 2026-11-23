-- Slice 4 Task 4: the rate facts filed on the rows this layer leaves unresolved values_differ (Task 2), with their
-- units, against production's values.
with rows as (
    select distinct accession, context_id from int_field_normalised where reason = 'values_differ'
)
select r.accession, r.context_id, f.concept_local, f.unit_id, f.value_numeric, h.interest_rate, h.basis_spread,
    h.pik_rate, h.corrected_fields
from rows r
join stg_filed_fact f on f.accession = r.accession and f.context_id = r.context_id
left join stg_holdings h on h.accession_number = r.accession and h.src_context_id = r.context_id
where regexp_matches(lower(f.concept_local), 'rate|spread|pik')
order by 1, 2, 3, 4
