-- Slice P fix round 2, 2026-11-26: published positions per fund and kept heading level, and the most common kept
-- stacks of positions with no level-2 heading in the funds that have level 2. Read-only.
with st as (
    select accession, context_id, string_agg(heading_level || ':' || left(text, 35), ' / ' order by heading_level) as stack
        , bool_or(heading_level = 2) as has_2
    from int_position_heading group by 1, 2
)
, nl2 as (
    select p.cik, st.stack, count(*) as n, min(p.accession || ' ' || p.context_id) as ex
    from int_page_position p join st using (accession, context_id)
    where p.is_published and p.cik in ('0001803498', '0001812554', '0001838126') and not st.has_2
    group by 1, 2
)
select 'level' as k, p.cik, ph.heading_level::varchar as a, count(*) as n, null as ex
from int_position_heading ph join int_page_position p using (accession, context_id)
where p.is_published group by 1, 2, 3
union all
select 'no_level_2', cik, stack, n, ex from nl2
qualify row_number() over (partition by cik order by n desc) <= 4
order by 1, 2, 4 desc
