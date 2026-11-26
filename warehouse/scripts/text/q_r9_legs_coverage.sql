-- Slice R round 3 (2026-11-26): per fund, shape units, shapes with leg evidence (a printed number compared with a tag on
-- at least one row) and the rows (positions) of those shapes, against all rows of rate-candidate shapes. Read-only.
with ev as (select shape_key from int_text_check_shape_legs group by 1 having sum(compared) > 0)
select s.cik, count(*) as shapes, count(e.shape_key) as shapes_with_evidence
    , sum(s.positions) as rows_all, sum(s.positions) filter (where e.shape_key is not null) as rows_with_evidence
from int_text_shape_unit s left join ev e using (shape_key)
group by 1 order by 1
