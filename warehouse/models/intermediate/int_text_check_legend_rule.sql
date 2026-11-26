-- Judges each existing map_code rule for reference rates against the filer's own legend (text slice R phase 1,
-- 2026-11-26). One row per map_code rule (stg_reading_rule action map_code, target reference_rate): rule_id.
--
-- The rule's parameter 'CODE=NAME'; code_key and name_key upper case, white space removed.
-- Legend entries compared: int_text_check_legend rows of the rule's fund with the same code_key, in filings whose report
-- date lies inside the rule's dates (valid_from <= report_date <= valid_to, a null end open).
-- Per filing, from its entries for the code that carry an abbreviation:
--   agree       one equals the rule's name_key and none differs.
--   contradict  one differs and none equals.
--   both        one equals and another differs (the filer defines the code two ways in one filing).
--   unclear     the filing's entries for the code carry no abbreviation (the name printed in words only, e.g.
--               'Federal Funds Rate ("F")').
-- state:
--   contradicts    at least one filing contradicts.
--   mixed          no filing contradicts, at least one has both readings.
--   agrees         at least one filing agrees, none contradicts or has both.
--   unclear        only unclear filings.
--   not_in_legend  no legend entry for the code in the rule's dates.
-- legend_abbreviations: the distinct abbreviations the legend gives the code in those filings, joined by ','.
-- Text comparison only: 'TONAR' against a rule 'TONA' would count as a contradiction although both name the Tokyo
-- overnight rate. Every contradiction and mixed rule is listed in docs/baseline_text_rates_phase1_2026-11-26.md.
with rule as (
    select rule_id, cik, parameter, valid_from, valid_to
        , upper(replace(split_part(parameter, '=', 1), ' ', '')) as code_key
        , upper(replace(split_part(parameter, '=', 2), ' ', '')) as name_key
    from {{ ref('stg_reading_rule') }}
    where action = 'map_code' and target = 'reference_rate'
)

, entry as (
    select r.rule_id, l.accession, l.abbreviation, l.abbreviation_key, r.name_key
    from rule r
    join {{ ref('int_text_check_legend') }} l
        on l.cik = r.cik and l.code_key = r.code_key
        and (r.valid_from is null or r.valid_from <= l.report_date) and (r.valid_to is null or l.report_date <= r.valid_to)
)

, per_filing as (
    select rule_id, accession
        , bool_or(abbreviation_key = name_key) as has_same
        , bool_or(abbreviation_key <> name_key) as has_other
    from entry
    group by 1, 2
)

, summary as (
    select rule_id
        , count(*) filter (where has_same and not coalesce(has_other, false)) as agree_filings
        , count(*) filter (where has_other and not coalesce(has_same, false)) as contradict_filings
        , count(*) filter (where has_same and has_other) as both_filings
        , count(*) filter (where has_same is null) as unclear_filings
    from per_filing
    group by 1
)

, abbreviation as (
    select rule_id, string_agg(distinct abbreviation, ',' order by abbreviation) as legend_abbreviations
    from entry
    where abbreviation is not null
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
    , coalesce(s.agree_filings, 0) as agree_filings
    , coalesce(s.contradict_filings, 0) as contradict_filings
    , coalesce(s.both_filings, 0) as both_filings
    , coalesce(s.unclear_filings, 0) as unclear_filings
    , a.legend_abbreviations
    , case
        when coalesce(s.contradict_filings, 0) > 0 then 'contradicts'
        when coalesce(s.both_filings, 0) > 0 then 'mixed'
        when coalesce(s.agree_filings, 0) > 0 then 'agrees'
        when coalesce(s.unclear_filings, 0) > 0 then 'unclear'
        else 'not_in_legend'
    end as state
from rule r
left join summary s on s.rule_id = r.rule_id
left join abbreviation a on a.rule_id = r.rule_id
