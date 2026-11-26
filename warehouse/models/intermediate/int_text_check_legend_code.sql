-- Lists the rate codes printed in rate-candidate columns and whether a rule or the filer's legend says what they mean
-- (text slice R phase 1, 2026-11-26). One row per (cik, code_key).
--
-- Codes: macro rate_code of each non-empty position-row text (int_text_cell) of a rate-candidate column unit
-- (int_text_column_unit.is_rate_candidate); code_key upper case, white space removed. printed_codes: the distinct
-- printed forms, joined by ','. rows / positions: texts and positions carrying the code; n_units: column units;
-- first/last_report_date.
-- has_rule: the fund has a map_code or label_is_unspecified rule for reference_rate whose code is code_key (any dates).
-- has_legend: int_text_check_legend has an entry for the code in any of the fund's filings. legend_abbreviations: the
-- abbreviations those entries give, joined by ','.
-- state: rule_and_legend, rule_only, legend_only, neither. A code with neither is one no rule reads and the filer does
-- not define in a footnote the legend pattern finds; it may still be a plain name ('SOFR', 'LIBOR') or not a rate code
-- at all (words that start a cell, e.g. 'Fixed').
with unit as (
    select unit_key from {{ ref('int_text_column_unit') }} where is_rate_candidate
)

, coded as (
    select c.cik, upper(replace(c.code, ' ', '')) as code_key, c.code, c.unit_key, c.positions, c.report_date
    from {{ ref('int_text_cell') }} c
    join unit u on u.unit_key = c.unit_key
    where c.code is not null
)

, code_sum as (
    select cik, code_key, string_agg(distinct code, ',' order by code) as printed_codes, count(*) as rows
        , sum(positions) as positions, count(distinct unit_key) as n_units
        , min(report_date) as first_report_date, max(report_date) as last_report_date
    from coded
    group by 1, 2
)

, rule as (
    select distinct cik
        , upper(replace(case when action = 'map_code' then split_part(parameter, '=', 1) else parameter end, ' ', ''))
            as code_key
    from {{ ref('stg_reading_rule') }}
    where target = 'reference_rate' and action in ('map_code', 'label_is_unspecified')
)

, legend as (
    select cik, code_key, string_agg(distinct abbreviation, ',' order by abbreviation) as legend_abbreviations
        , count(distinct accession) as legend_filings
    from {{ ref('int_text_check_legend') }}
    group by 1, 2
)

select
    s.cik
    , s.code_key
    , s.printed_codes
    , s.rows
    , s.positions
    , s.n_units
    , s.first_report_date
    , s.last_report_date
    , r.code_key is not null as has_rule
    , l.code_key is not null as has_legend
    , coalesce(l.legend_filings, 0) as legend_filings
    , l.legend_abbreviations
    , case
        when r.code_key is not null and l.code_key is not null then 'rule_and_legend'
        when r.code_key is not null then 'rule_only'
        when l.code_key is not null then 'legend_only'
        else 'neither'
    end as state
from code_sum s
left join rule r on r.cik = s.cik and r.code_key = s.code_key
left join legend l on l.cik = s.cik and l.code_key = s.code_key
