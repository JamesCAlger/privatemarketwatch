-- MEASUREMENT ONLY (renamed in fix round 1 from int_text_check_spread_base; no model and no worklist state reads it):
-- spread plus the SOFR 90-day average against the filed all-in rate, on each position whose reference-rate column gives
-- a code (text slice R phase 1, 2026-11-26). One row per position of int_text_reference_rate_read with a code:
-- (accession, context_id). Measured: with the 90-day backward average it fails correct readings in quarters when SOFR
-- moved (7 of 15; docs/baseline_text_rates_phase1_2026-11-26.md section 5), so the check that judges rules is the
-- cluster test int_text_check_base_cluster. It never compares with production.
--
-- Inputs on the same position:
--   spread    int_field_normalised field spread, status normalised (the tag before row corrections; percent). The tag only: no existing rule
--             reads a spread from text, so the rule-read cell gives no spread yet (spread_source 'tag').
--   all_in    int_field_normalised field interest_rate, status normalised, rate_kind all_in (percent).
--   pik       int_field_normalised field pik_rate, status normalised (percent).
--   floor     from the rule-read cell text (int_text_reference_rate_read.cell_text): the number before '% Floor'
--             ("S+525, 0.75% Floor" gives 0.75); null when not printed.
--   sofr      seed sofr_90day_avg: the latest date on or before the report date, used only when it is at most
--             var text_sofr_max_age_days (7) days old.
-- base: greatest(sofr, floor) when a floor is printed, else sofr (no floor assumed: a loan whose floor is above SOFR
-- but not printed in the read cell fails here).
-- residual: abs(spread + base - all_in), percentage points.
-- check_state, the first that applies:
--   inputs_missing  spread or all_in missing.
--   pik_present     pik above 0: the all-in rate may include a PIK leg; not judged.
--   no_sofr_value   no SOFR value within the age limit.
--   pass            residual <= var text_spread_base_tolerance (0.25).
--   fail            otherwise.
-- is_read_sofr: the existing rules read the code as SOFR (reference_rate = 'SOFR'). This is the check of the brief: the
-- per-unit summary (int_text_measure_sofr_level_unit) keeps the rows of every code, so a code no rule maps yet ('SF',
-- 'SOFR') shows how it would fare if read as SOFR; that is evidence for a proposed rule, not a reading.
with coded_read as (
    select accession, context_id, cik, report_date, is_published, unit_key, cell_text, code, reference_rate, status
    from {{ ref('int_text_reference_rate_read') }}
    where code is not null
)

, field as (
    select accession, context_id
        , max(case when field = 'spread' then value end) as spread
        , max(case when field = 'interest_rate' and rate_kind = 'all_in' then value end) as all_in
        , max(case when field = 'pik_rate' then value end) as pik
    from {{ ref('int_field_normalised') }}
    where field in ('spread', 'interest_rate', 'pik_rate') and status = 'normalised'
    group by 1, 2
)

, sofr as (
    select date, sofr_90day_avg_pct from {{ ref('sofr_90day_avg') }}
)

, joined as (
    select
        r.*
        , f.spread
        , 'tag' as spread_source
        , f.all_in
        , f.pik
        , try_cast(nullif(regexp_extract(r.cell_text, '(\d+(?:\.\d+)?)\s*%\s*[Ff]loor', 1), '') as double) as floor
        , s.date as sofr_date
        , s.sofr_90day_avg_pct as sofr_value
    from coded_read r
    left join field f on f.accession = r.accession and f.context_id = r.context_id
    asof left join sofr s on s.date <= r.report_date
)

, based as (
    select
        j.*
        , case when j.sofr_date is not null and j.report_date - j.sofr_date <= {{ var('text_sofr_max_age_days') }}
               then j.sofr_value end as sofr
    from joined j
)

select
    accession
    , context_id
    , cik
    , report_date
    , is_published
    , unit_key
    , code
    , reference_rate
    , coalesce(reference_rate = 'SOFR', false) as is_read_sofr
    , cell_text
    , spread
    , spread_source
    , all_in
    , pik
    , floor
    , sofr_date
    , sofr
    , case when floor is not null then greatest(sofr, floor) else sofr end as base
    , abs(spread + case when floor is not null then greatest(sofr, floor) else sofr end - all_in) as residual
    , case
        when spread is null or all_in is null then 'inputs_missing'
        when coalesce(pik, 0) > 0 then 'pik_present'
        when sofr is null then 'no_sofr_value'
        when abs(spread + case when floor is not null then greatest(sofr, floor) else sofr end - all_in)
             <= {{ var('text_spread_base_tolerance') }} then 'pass'
        else 'fail'
    end as check_state
from based
