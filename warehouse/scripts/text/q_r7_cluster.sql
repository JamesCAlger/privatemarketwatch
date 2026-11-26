-- Slice R fix round 1 (2026-11-26): the cluster test per fund, quarter, basis and label (groups with at least 5 usable
-- rows), with centres, within share, main share and the SOFR distance (measurement only). Read-only.
select cik, basis, rate_label, cast(report_date as varchar) as q, usable, pik_present as pik, inputs_missing as miss
    , round(within_share, 3) as within, round(main_share, 3) as main
    , list_transform(centres, x -> round(x, 2)) as centres, round(sofr, 2) as sofr, round(sofr_distance, 2) as sofr_dist
    , is_sofr_like as sofr_like, check_state
from int_text_check_base_cluster_group
where usable >= 5
order by cik, basis desc, rate_label, report_date
