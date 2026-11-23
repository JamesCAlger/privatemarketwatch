-- Slice 4 Task 2 (before the change): units of the term-fact concepts on position rows, per concept_map field and fund.
-- For a date fact also whether value_text parses as an ISO date.
select m.field, m.concept_map_id, p.cik
    , case when u.denominator is null then u.numerator else u.numerator || '/' || u.denominator end as unit
    , count(*) as facts
    , count(*) filter (where f.is_nil) as nil_facts
    , count(*) filter (where f.value_numeric is null and not f.is_nil) as no_number
    , count(*) filter (where not f.is_nil and try_cast(f.value_text as date) is null) as not_iso_date
    , min(f.value_text) as min_text, max(f.value_text) as max_text
from stg_filed_fact f
join int_source_row p on p.accession = f.accession and p.context_id = f.context_id and p.role = 'position'
join concept_map m on m.concept_local = f.concept_local and f.concept_namespace glob m.namespace_pattern
left join stg_filed_unit u on u.accession = f.accession and u.unit_id = f.unit_id
where m.field in ('rate', 'spread', 'pik_rate', 'maturity')
group by all
order by 1, 2, 3, 4
