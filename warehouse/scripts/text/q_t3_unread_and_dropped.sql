-- Text slice R phase 3: (1) unread printed cells by fund, shape and status (the groups of
-- tests/baseline_int_text_rate_unread.sql, with an example text); (2) readings not applied under constraints 1 to 3, by
-- fund, field, status, detail and the rule that read them.
select 'unread' as block, cik, shape, status, count(*) as cells, count(distinct accession || '|' || context_id) as positions
    , min(cell_text) as example, null as rule_id
from int_text_rate_read_cell
where status not in ('read', 'no_value')
group by 1, 2, 3, 4
union all
select 'dropped', r.cik, d.field, d.status || coalesce(' / ' || d.detail, ''), count(*), count(*), min(c.cell_text)
    , string_agg(distinct c.rule_id, ',')
from (
    select cik, accession, context_id, 'spread' as field, spread_status as status, spread_detail as detail
    from int_text_rate_read where spread_status like 'constraint%'
    union all select cik, accession, context_id, 'pik_spread', pik_spread_status, null from int_text_rate_read
    where pik_spread_status like 'constraint%'
    union all select cik, accession, context_id, 'floor', floor_status, null from int_text_rate_read
    where floor_status like 'constraint%'
    union all select cik, accession, context_id, 'fixed_rate', all_in_rate_status, null from int_text_rate_read
    where all_in_rate_status like 'constraint%'
) d
join int_text_rate_read r on r.accession = d.accession and r.context_id = d.context_id
left join int_text_rate_read_cell c on c.accession = d.accession and c.context_id = d.context_id and c.field = d.field
    and c.status = 'read'
group by 1, 2, 3, 4
order by 1 desc, 2, 6 desc
