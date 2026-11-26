-- Slice R fix round 1 (2026-11-26): dated legend verdicts: per fund the read positions by verdict, the quarters with a
-- mixed or contradicting verdict, and per map_code rule the filings that agree / are mixed / have no legend. Read-only.
select 'fund' as block, cik as k, null as rule, sum(rows_read) as read, sum(agrees) as agrees, sum(mixed) as mixed
    , sum(contradicts) as contra, sum(unclear) as unclear, sum(no_legend_in_filing) as no_legend, sum(not_applicable) as na
    , string_agg(distinct strftime(report_date, '%Y-%m-%d'), ',' order by strftime(report_date, '%Y-%m-%d'))
        filter (where mixed + contradicts > 0) as bad_quarters
from int_text_check_legend_quarter group by 1, 2, 3
union all
select 'rule', cik, parameter, n_filings, agree_filings, mixed_filings, contradict_filings, unclear_filings, no_legend_filings
    , null, coalesce('agree ' || agree_dates, '') || coalesce(' mixed ' || mixed_dates, '')
from int_text_check_legend_rule
order by 1, 2, 3
