-- Slice 3 Task 4: the facts placed on one printed row (variables acc, row), with their context's role and whether the
-- context is on both sides of the comparison.
select pl.context_id, f.concept_local, f.value_numeric, s.role, s.is_published, c.side
from stg_filed_fact_placement pl
join stg_filed_fact f on f.accession = pl.accession and f.fact_id = pl.fact_id
left join int_source_row s on s.accession = pl.accession and s.context_id = pl.context_id
left join cmp_row_set c on c.accession = pl.accession and c.context_id = pl.context_id
where pl.accession = getvariable('acc') and coalesce(pl.row_index, pl.shown_row_index) = getvariable('row')
order by pl.context_id, f.concept_local
limit 40
