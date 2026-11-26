-- Slice R fix round 1 (2026-11-26): every fund-quarter group the 0.90 bar fails (usable rows >= 10). Read-only.
select cik, basis, rate_label, cast(report_date as varchar) as q, usable, round(within_share, 3) as within
    , round(sofr_distance, 2) as sofr_dist
from int_text_check_base_cluster_group
where usable >= 10 and within_share < 0.90
order by basis desc, cik, rate_label, report_date
