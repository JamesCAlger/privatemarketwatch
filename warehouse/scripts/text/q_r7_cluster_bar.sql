-- Slice R fix round 1 (2026-11-26): how many fund-quarter groups (usable rows >= 10) a pass bar would fail, per basis
-- and SOFR-likeness, for candidate bars; and the main centre's SOFR distance above 1.0. Read-only.
select basis, is_sofr_like, count(*) as groups
    , count(*) filter (where within_share < 0.80) as below_80
    , count(*) filter (where within_share < 0.85) as below_85
    , count(*) filter (where within_share < 0.90) as below_90
    , count(*) filter (where within_share < 0.95) as below_95
    , count(*) filter (where sofr_distance > 1.0) as sofr_dist_over_1
    , round(median(within_share), 3) as median_within
from int_text_measure_implied_base_group where usable >= 10
group by 1, 2 order by 1, 2
