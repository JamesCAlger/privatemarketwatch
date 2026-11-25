-- Slice 5 Task 5: Ares 0001287750-25-000007 c-1544, production rate 9.23 where this layer has none. Production's row
-- and its neighbours c-1540..c-1548 in production and here (label, fair value, rate facts). Read-only.
with ctx as (
    select cf.accession, cf.context_id, cf.identifier_label, cf.fair_value, cf.fair_value_fact_count, cf.has_term_fact,
        try_cast(regexp_extract(cf.context_id, '(\d+)$', 1) as integer) as ord
    from int_context_feature cf
    where cf.accession = '0001287750-25-000007'
)
, facts as (
    select f.context_id, string_agg(f.concept_local || '=' || coalesce(cast(f.value_numeric as varchar), '?'), '; '
        order by f.concept_local) as facts
    from stg_filed_fact f
    where f.accession = '0001287750-25-000007'
    group by 1
)
select c.context_id, c.ord, c.identifier_label, c.fair_value, c.has_term_fact, r.role, r.role_rule,
    h.interest_rate, h.basis_spread, h.pik_rate, h.interest_rate_kind, h.interest_rate_source, h.src_filled_fields,
    h.src_transforms, h.corrected_fields, h.fair_value as prod_fv, fa.facts
from ctx c
left join int_source_row r on r.accession = c.accession and r.context_id = c.context_id
left join stg_holdings h on h.accession_number = c.accession and h.src_context_id = c.context_id
left join facts fa on fa.context_id = c.context_id
where c.ord between 1538 and 1550
order by c.ord
