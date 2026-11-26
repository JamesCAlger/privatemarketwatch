-- Slice P fix round 1, 2026-11-26: table_index gap between consecutive schedule tables of one filing, by fund, by
-- whether the published state of their positions changes across the gap. Read-only.
with t as (
    select s.cik, s.accession, s.table_index, s.schedule_seq
        , (select bool_or(p.is_published) from int_page_position p where p.accession = s.accession and p.table_index = s.table_index) as pub
    from int_page_schedule s
)
, g as (
    select *, table_index - lag(table_index) over (partition by accession order by table_index) as gap
        , lag(pub) over (partition by accession order by table_index) as prev_pub
        , lag(schedule_seq) over (partition by accession order by table_index) as prev_seq
    from t
)
select cik, least(gap, 5) as gap_capped, pub <> prev_pub as pub_changes, schedule_seq <> prev_seq as new_schedule, count(*) n
    , min(accession || ' t' || table_index) as ex
from g where gap is not null group by all order by 1, 2, 3, 4
