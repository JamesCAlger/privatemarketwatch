-- Task 4 (records): role counts per role and fund today, and published positions, for HANDOFF.md.
select role, count(*) as contexts, count(*) filter (where is_published) as published
    , count(*) filter (where cik = '0001287750') as ares, count(*) filter (where cik = '0001803498') as bcred
    , count(*) filter (where cik = '0001812554') as blue_owl, count(*) filter (where cik = '0001837532') as apollo
    , count(*) filter (where cik = '0001838126') as hps
from int_source_row group by 1 order by 2 desc
