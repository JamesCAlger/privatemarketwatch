-- Checks each reference rate an existing rule reads against the legend of the row's own filing (text slice R fix round
-- 1, 2026-11-26). One row per position of int_text_reference_rate_read with status read: (accession, context_id).
--
-- The rule that read it (map_rule_id, stg_reading_rule). For a map_code rule 'CODE=NAME' the filing's legend entries
-- (int_text_check_legend, same accession and fund, code_key = CODE upper case without spaces) give:
--   agrees               an entry's abbreviation equals NAME (upper case, spaces removed) and none differs.
--   contradicts          an entry's abbreviation differs and none equals.
--   mixed                both: this filing defines the code two ways.
--   unclear              the entries carry no abbreviation.
--   no_legend_in_filing  this filing defines no such code.
-- A read by a label_is_unspecified rule names no rate: not_applicable.
-- Only the row's own filing counts: a legend printed in another quarter neither confirms nor fails a row.
with read_row as (
    select r.accession, r.context_id, r.cik, r.report_date, r.unit_key, r.cell_text, r.code, r.reference_rate
        , r.map_rule_id, s.action
        , upper(replace(split_part(s.parameter, '=', 1), ' ', '')) as code_key
        , upper(replace(split_part(s.parameter, '=', 2), ' ', '')) as name_key
    from {{ ref('int_text_reference_rate_read') }} r
    join {{ ref('stg_reading_rule') }} s on s.rule_id = r.map_rule_id
    where r.status = 'read'
)

, judged as (
    select rr.accession, rr.context_id
        , bool_or(l.abbreviation_key = rr.name_key) as has_same
        , bool_or(l.abbreviation_key <> rr.name_key) as has_other
        , count(l.code_key) as entries
    from read_row rr
    left join {{ ref('int_text_check_legend') }} l
        on l.accession = rr.accession and l.cik = rr.cik and l.code_key = rr.code_key
    where rr.action = 'map_code'
    group by 1, 2
)

select
    rr.accession
    , rr.context_id
    , rr.cik
    , rr.report_date
    , rr.unit_key
    , rr.cell_text
    , rr.code
    , rr.reference_rate
    , rr.map_rule_id
    , case
        when rr.action <> 'map_code' then 'not_applicable'
        when j.entries = 0 then 'no_legend_in_filing'
        when j.has_same and j.has_other then 'mixed'
        when j.has_same then 'agrees'
        when j.has_other then 'contradicts'
        else 'unclear'
    end as legend_verdict
from read_row rr
left join judged j on j.accession = rr.accession and j.context_id = rr.context_id
