-- Slice P fix round 1, 2026-11-26: schedules per filing, run lengths of headings, column rules, per fund. Read-only.
select '1 schedules per filing' as k, cik, n_sched::varchar as a, count(*) as n, min(accession) as ex
from (select cik, accession, max(schedule_seq) as n_sched from int_page_schedule group by 1, 2) group by 1, 2, 3
union all
select '2 run length', cik, run_length::varchar, count(*), min(text) from int_page_heading group by 1, 2, 3
union all
select '3 column rule', t.cik, cc.column_rule, count(*), min(cc.text)
from int_page_cell_column cc join int_page_table t using (accession, table_index) group by 1, 2, 3
union all
select '4 prefix moved', t.cik, cc.text, count(*), min(cc.zone_signature || ' -> ' || cc.header_signature)
from int_page_cell_column cc join int_page_table t using (accession, table_index)
where cc.column_rule = 'prefix_of_next' and cc.zone_signature is distinct from cc.header_signature group by 1, 2, 3
union all
select '5 heading depth', p.cik, ph.heading_level::varchar, count(*), min(ph.text)
from int_position_heading ph join int_page_position p using (accession, context_id) where p.is_published group by 1, 2, 3
order by 1, 2, 3
