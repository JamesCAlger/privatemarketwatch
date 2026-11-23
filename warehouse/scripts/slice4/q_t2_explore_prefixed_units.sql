-- Slice 4 Task 2: every unit measure written with a prefix on facts of position rows, per fund (any concept). The
-- slice 3 deferred item: a filer writing xbrli:pure / xbrli:shares gets no unit kind in int_field_rule.
select p.cik
    , case when u.denominator is null then u.numerator else u.numerator || '/' || u.denominator end as unit
    , count(*) as facts
    , count(distinct f.concept_local) as concepts
    , min(f.concept_local) as a_concept
from stg_filed_fact f
join int_source_row p on p.accession = f.accession and p.context_id = f.context_id and p.role = 'position'
join stg_filed_unit u on u.accession = f.accession and u.unit_id = f.unit_id
where u.numerator like '%:%' and u.numerator not like 'iso4217:%'
group by all
order by 1, 2
