-- Slice 5 Task 3 proof: corrections by outcome and reason, per store and fund (target rows; a correction with several
-- targets counts once per target). Funds: Ares 0001287750, BCRED 0001803498, Blue Owl 0001812554, Apollo 0001837532,
-- HPS 0001838126.
select
    case when store like 'wrapper:%' then 'wrapper' else store end as store
    , outcome
    , coalesce(reason, '') as reason
    , count(*) filter (where cik = '0001287750') as ares
    , count(*) filter (where cik = '0001803498') as bcred
    , count(*) filter (where cik = '0001812554') as blue_owl
    , count(*) filter (where cik = '0001837532') as apollo
    , count(*) filter (where cik = '0001838126') as hps
    , count(*) as total
    , count(distinct correction_id) as corrections
from main.int_correction_application
group by all
order by 1, 2, 3
