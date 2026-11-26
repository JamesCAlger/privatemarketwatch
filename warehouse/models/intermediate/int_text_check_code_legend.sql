-- Checks each PROPOSED code mapping against the legend of the filing the code is printed in (text slice R phase 2,
-- 2026-11-26; the per-filing legend check of phase 1, int_text_check_legend_read, applied to the proposals). A
-- measurement of the proposals; it publishes nothing. One row per (unit_key, code_key, accession) where a read code row
-- of int_text_rate_proposed has a rate_name.
--
-- code_key: the printed code upper case, spaces removed. proposed_rate: the proposal's normalised rate name.
-- positions: the positions of that filing carrying the code in that column unit.
-- Legend entries: int_text_check_legend rows of the same filing and fund with the same code_key. Each entry's rate:
-- macro base_rate_name of its abbreviation, else of its name (the same normalisation the proposals went through, so
-- "BBSY" and "BBSW" are one rate, as are "CDOR" and "CORRA").
-- verdict:
--   agrees               some entry's rate equals proposed_rate and none differs.
--   contradicts          some entry's rate differs and none equals.
--   mixed                both: the filing defines the code two ways.
--   unclear              the entries' rates map to no base rate (the name and abbreviation name no series).
--   no_legend_in_filing  the filing defines no such code.
-- Only the row's own filing counts.
with code_row as (
    select unit_key, upper(replace(reference_rate_code, ' ', '')) as code_key, accession, min(cik) as cik
        , min(report_date) as report_date, min(rate_name) as proposed_rate, count(distinct context_id) as positions
    from {{ ref('int_text_rate_proposed') }}
    where field = 'reference_rate_code' and status = 'read' and rate_name is not null
    group by 1, 2, 3
)

, entry as (
    select cik, accession, code_key
        , coalesce({{ base_rate_name('abbreviation') }}, {{ base_rate_name('name') }}) as legend_rate
    from {{ ref('int_text_check_legend') }}
)

, judged as (
    select c.unit_key, c.code_key, c.accession
        , count(e.code_key) as entries
        , count(e.legend_rate) as entries_with_rate
        , bool_or(e.legend_rate = c.proposed_rate) as has_same
        , bool_or(e.legend_rate <> c.proposed_rate) as has_other
        , string_agg(distinct e.legend_rate, ',' order by e.legend_rate) as legend_rates
    from code_row c
    left join entry e on e.accession = c.accession and e.cik = c.cik and e.code_key = c.code_key
    group by 1, 2, 3
)

select
    c.unit_key
    , c.code_key
    , c.accession
    , c.cik
    , c.report_date
    , c.proposed_rate
    , c.positions
    , j.entries
    , j.legend_rates
    , case
        when j.entries = 0 then 'no_legend_in_filing'
        when j.has_same and j.has_other then 'mixed'
        when j.has_same then 'agrees'
        when j.has_other then 'contradicts'
        else 'unclear'
      end as verdict
from code_row c
join judged j on j.unit_key = c.unit_key and j.code_key = c.code_key and j.accession = c.accession
