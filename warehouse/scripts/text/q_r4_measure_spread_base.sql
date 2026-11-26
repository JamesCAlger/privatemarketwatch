-- Slice R phase 1 measurement (2026-11-26): the spread-plus-base check per fund, code and quarter (codes with at least
-- one checked row), and the check states per fund. Read-only.
select 'by code' as block, cik, code_key, cast(report_date as varchar) as q, bool_and(is_read_sofr) as read_sofr
    , sum(positions) as rows, sum(checked) as checked, sum(passed) as passed
    , round(sum(passed) / nullif(sum(checked), 0), 3) as pass_share, round(median(median_residual), 3) as med_resid
    , sum(pik_present) as pik, sum(inputs_missing) as missing, sum(no_sofr_value) as no_sofr
from int_text_check_spread_base_unit
group by 1, 2, 3, 4
having sum(checked) > 0
union all
select 'by code all q', cik, code_key, 'all', bool_and(is_read_sofr), sum(positions), sum(checked), sum(passed)
    , round(sum(passed) / nullif(sum(checked), 0), 3), null, sum(pik_present), sum(inputs_missing), sum(no_sofr_value)
from int_text_check_spread_base_unit group by 1, 2, 3, 4
order by 1 desc, 2, 3, 4
