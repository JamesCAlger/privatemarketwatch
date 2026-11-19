-- Task 5: the row-set comparison before (out/t5_cmp_before.parquet, out/t5_excl_before.parquet) against now. Counts by
-- basis, side and cause on each side, and every row whose side, cause or detail changed.
with b as (select * from read_parquet('scripts/slice2/out/t5_cmp_before.parquet'))
, a as (select * from cmp_row_set)
select 'count' as k, basis, side, cause, cause_detail
    , (select count(*) from b x where x.basis = g.basis and x.side = g.side and x.cause is not distinct from g.cause and x.cause_detail is not distinct from g.cause_detail) as before
    , (select count(*) from a x where x.basis = g.basis and x.side = g.side and x.cause is not distinct from g.cause and x.cause_detail is not distinct from g.cause_detail) as after
    , null as accession, null as context_id
from (select basis, side, cause, cause_detail from b union select basis, side, cause, cause_detail from a) g
union all
select 'changed', coalesce(a.basis, b.basis), coalesce(b.side, '-') || ' -> ' || coalesce(a.side, '-')
    , coalesce(b.cause, '-') || ' -> ' || coalesce(a.cause, '-'), coalesce(b.cause_detail, '-') || ' -> ' || coalesce(a.cause_detail, '-')
    , null, null, coalesce(a.accession, b.accession), coalesce(a.context_id, b.context_id)
from b full join a on a.basis = b.basis and a.accession = b.accession and a.context_id = b.context_id
where b.side is distinct from a.side or b.cause is distinct from a.cause or b.cause_detail is distinct from a.cause_detail
union all
select 'excluded_quarters', cik, report_date::varchar, accessions, published_rows::varchar, null, null, 'before', null
from read_parquet('scripts/slice2/out/t5_excl_before.parquet')
union all
select 'excluded_quarters', cik, report_date::varchar, accessions, published_rows::varchar, null, null, 'after', null
from cmp_excluded_quarter
order by 1, 2, 3, 4
