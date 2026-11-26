-- Judges each existing map_code rule for reference rates against the filer's own legend, filing by filing (text slice R
-- phase 1, 2026-11-26; dated in fix round 1). One row per map_code rule (stg_reading_rule action map_code, target
-- reference_rate): rule_id.
--
-- The rule's parameter 'CODE=NAME'; code_key and name_key upper case, white space removed.
-- Filings judged: every filing of the rule's fund that holds a schedule table (int_page_table) with a report date inside
-- the rule's dates (valid_from <= report_date <= valid_to, a null end open). Each filing is judged on its own legend
-- only (int_text_check_legend rows of that accession with the rule's code_key):
--   agrees               an entry's abbreviation equals the rule's name and none differs.
--   contradicts          an entry's abbreviation differs and none equals.
--   mixed                one equals and another differs: that filing defines the code two ways.
--   unclear              the filing's entries for the code carry no abbreviation (e.g. 'Federal Funds Rate ("F")').
--   no_legend_in_filing  the filing defines no such code.
-- Per rule: n_filings, and for each verdict its filings counted and their report dates listed (agree_dates, ...,
-- 'YYYY-MM-DD' joined by ','); no_legend_first/last_date. So "SR=SOFR rests on one filing" reads agree_filings 1,
-- agree_dates '2024-12-31', no_legend_filings 14.
-- state, a summary over the filings kept for the baseline (tests/baseline_int_text_legend_rule_disagrees.sql):
-- contradicts if any filing contradicts, else mixed if any is mixed, else agrees if any agrees, else unclear if any is
-- unclear, else not_in_legend. What a read row is checked against is its own filing's verdict
-- (int_text_check_legend_read), not this summary.
-- Text comparison only: 'TONAR' against a rule 'TONA' would count as a contradiction although both name the Tokyo
-- overnight rate.
with rule as (
    select rule_id, cik, parameter, valid_from, valid_to
        , upper(replace(split_part(parameter, '=', 1), ' ', '')) as code_key
        , upper(replace(split_part(parameter, '=', 2), ' ', '')) as name_key
    from {{ ref('stg_reading_rule') }}
    where action = 'map_code' and target = 'reference_rate'
)

, filing as (
    select accession, min(cik) as cik, min(report_date) as report_date
    from {{ ref('int_page_table') }}
    group by 1
)

, rule_filing as (
    select r.rule_id, f.accession, f.report_date, r.code_key, r.name_key, r.cik
    from rule r
    join filing f
        on f.cik = r.cik
        and (r.valid_from is null or r.valid_from <= f.report_date) and (r.valid_to is null or f.report_date <= r.valid_to)
)

, per_filing as (
    select rf.rule_id, rf.accession, rf.report_date
        , bool_or(l.abbreviation_key = rf.name_key) as has_same
        , bool_or(l.abbreviation_key <> rf.name_key) as has_other
        , count(l.code_key) as entries
    from rule_filing rf
    left join {{ ref('int_text_check_legend') }} l
        on l.accession = rf.accession and l.cik = rf.cik and l.code_key = rf.code_key
    group by 1, 2, 3
)

, verdict as (
    select *
        , case
            when entries = 0 then 'no_legend_in_filing'
            when has_same and has_other then 'mixed'
            when has_same then 'agrees'
            when has_other then 'contradicts'
            else 'unclear'
        end as verdict
    from per_filing
)

, summary as (
    select rule_id
        , count(*) as n_filings
        , count(*) filter (where verdict = 'agrees') as agree_filings
        , count(*) filter (where verdict = 'contradicts') as contradict_filings
        , count(*) filter (where verdict = 'mixed') as mixed_filings
        , count(*) filter (where verdict = 'unclear') as unclear_filings
        , count(*) filter (where verdict = 'no_legend_in_filing') as no_legend_filings
        , string_agg(strftime(report_date, '%Y-%m-%d'), ',' order by report_date) filter (where verdict = 'agrees')
            as agree_dates
        , string_agg(strftime(report_date, '%Y-%m-%d'), ',' order by report_date) filter (where verdict = 'contradicts')
            as contradict_dates
        , string_agg(strftime(report_date, '%Y-%m-%d'), ',' order by report_date) filter (where verdict = 'mixed')
            as mixed_dates
        , string_agg(strftime(report_date, '%Y-%m-%d'), ',' order by report_date) filter (where verdict = 'unclear')
            as unclear_dates
        , min(report_date) filter (where verdict = 'no_legend_in_filing') as no_legend_first_date
        , max(report_date) filter (where verdict = 'no_legend_in_filing') as no_legend_last_date
    from verdict
    group by 1
)

, abbreviation as (
    select rf.rule_id, string_agg(distinct l.abbreviation, ',' order by l.abbreviation) as legend_abbreviations
    from rule_filing rf
    join {{ ref('int_text_check_legend') }} l
        on l.accession = rf.accession and l.cik = rf.cik and l.code_key = rf.code_key
    where l.abbreviation is not null
    group by 1
)

select
    r.rule_id
    , r.cik
    , r.parameter
    , r.code_key
    , r.name_key
    , r.valid_from
    , r.valid_to
    , coalesce(s.n_filings, 0) as n_filings
    , coalesce(s.agree_filings, 0) as agree_filings
    , coalesce(s.contradict_filings, 0) as contradict_filings
    , coalesce(s.mixed_filings, 0) as mixed_filings
    , coalesce(s.unclear_filings, 0) as unclear_filings
    , coalesce(s.no_legend_filings, 0) as no_legend_filings
    , s.agree_dates
    , s.contradict_dates
    , s.mixed_dates
    , s.unclear_dates
    , s.no_legend_first_date
    , s.no_legend_last_date
    , a.legend_abbreviations
    , case
        when coalesce(s.contradict_filings, 0) > 0 then 'contradicts'
        when coalesce(s.mixed_filings, 0) > 0 then 'mixed'
        when coalesce(s.agree_filings, 0) > 0 then 'agrees'
        when coalesce(s.unclear_filings, 0) > 0 then 'unclear'
        else 'not_in_legend'
    end as state
from rule r
left join summary s on s.rule_id = r.rule_id
left join abbreviation a on a.rule_id = r.rule_id
