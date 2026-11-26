-- MEASUREMENT ONLY (fix round 2: renamed from int_text_check_base_cluster; no model and no worklist state reads it):
-- the base rate each position implies (text slice R fix round 1, 2026-11-26). One row per (accession, context_id,
-- basis) for every position of int_text_reference_rate_read whose cell gives a code. Measured in fix round 2: it has no
-- power to tell a right reading from a wrong one (two codes of one fund and quarter mixed together still cluster;
-- reading the all-in rate as the spread gives implied base 0 on every row, which clusters perfectly), so it judges
-- nothing (docs/baseline_text_rates_phase1_2026-11-26.md section 13).
--
-- Idea: loans on one base rate in one quarter reset to a few published values (the 1, 3 and 6 month tenors), so
-- all-in minus spread clusters at a few points when the code is read right. Needs no base-rate table.
-- Inputs (int_field_normalised: the filed tags converted to percent, before any row correction; status normalised):
--   spread  field spread.   all_in  field interest_rate with rate_kind all_in.   pik  field pik_rate.
-- implied_base = all_in - spread. PIK: a row whose pik is above 0 is left out (state pik_present). Its all-in rate holds
-- a PIK leg, and whether the filer's spread includes that leg differs by fund (int_text_check_shape_legs: one fund's
-- spread includes it, others print it apart), so no cash leg is derived; the measured share of such rows is small
-- (docs/baseline_text_rates_phase1_2026-11-26.md section 5).
-- basis and rate_label (two rows per position at most):
--   rule        the code as an existing rule reads it: rate_label = int_text_reference_rate_read.reference_rate, only
--               rows with status read.
--   hypothesis  every row with a code, rate_label = the printed code (upper case, spaces removed), whether or not a rule
--               maps it. This is a hypothesis table for this check only ("what if this code is one base rate"); it reads
--               nothing.
-- state: inputs_missing (spread or all_in missing), pik_present, usable.
with coded as (
    select accession, context_id, cik, report_date, is_published, unit_key, code, reference_rate, status
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

, based as (
    select c.accession, c.context_id, c.cik, c.report_date, c.is_published, c.unit_key, c.code
        , 'rule' as basis, c.reference_rate as rate_label
    from coded c
    where c.status = 'read'
    union all
    select c.accession, c.context_id, c.cik, c.report_date, c.is_published, c.unit_key, c.code
        , 'hypothesis', upper(replace(c.code, ' ', ''))
    from coded c
)

select
    b.*
    , f.spread
    , f.all_in
    , f.pik
    , case when f.spread is not null and f.all_in is not null and coalesce(f.pik, 0) <= 0 then f.all_in - f.spread end
        as implied_base
    , case
        when f.spread is null or f.all_in is null then 'inputs_missing'
        when coalesce(f.pik, 0) > 0 then 'pik_present'
        else 'usable'
    end as state
from based b
left join field f on f.accession = b.accession and f.context_id = b.context_id
