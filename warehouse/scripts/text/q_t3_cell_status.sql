-- Text slice R phase 3: cells of the read model by fund, field and status (rows and positions), plus grain duplicates.
select cik, coalesce(field, '(none)') as field, status, coalesce(code_step, '') as code_step
    , count(*) as cell_rows, count(distinct accession || '|' || context_id) as positions
from int_text_rate_read_cell
group by all
union all
select 'DUPLICATE KEYS', null, null, null, count(*), null
from (select accession, context_id, unit_key, number_index from int_text_rate_read_cell group by all having count(*) > 1)
order by 1, 2, 3, 4
