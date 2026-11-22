-- Slice 3 Task 4: the rows of cmp_amount cause filer_concept_not_read with the filer fact that carries the value, by
-- report date and local name; and whether the filer fact's value equals production's.
select a.cik, a.report_date, f.concept_local, count(*) n
    , count(*) filter (where abs(f.value_numeric - a.value_production) < 1) as equals_production
    , min(a.accession) as an_accession, min(a.context_id) as a_context
from cmp_amount a
join stg_filed_fact f on f.accession = a.accession and f.context_id = a.context_id
join concept_map m on m.field = a.field and contains(f.concept_local, m.concept_local) and f.concept_local <> m.concept_local
where a.cause_detail = 'filer_concept_not_read'
group by all order by 1, 2, 3
limit 50
