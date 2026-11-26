-- Summarises the dated legend check per column unit and quarter (text slice R fix round 1, 2026-11-26). One row per
-- (unit_key, report_date) with a read position: how many of its read positions agree with, contradict, are mixed
-- under, are unclear under, or have no legend in their own filing (int_text_check_legend_read), and the reads by a
-- label_is_unspecified rule (not_applicable). A unit's legend verdict is this list of quarters, not one flag.
select
    unit_key
    , report_date
    , min(cik) as cik
    , count(*) as rows_read
    , count(*) filter (where legend_verdict = 'agrees') as agrees
    , count(*) filter (where legend_verdict = 'contradicts') as contradicts
    , count(*) filter (where legend_verdict = 'mixed') as mixed
    , count(*) filter (where legend_verdict = 'unclear') as unclear
    , count(*) filter (where legend_verdict = 'no_legend_in_filing') as no_legend_in_filing
    , count(*) filter (where legend_verdict = 'not_applicable') as not_applicable
from {{ ref('int_text_check_legend_read') }}
group by 1, 2
