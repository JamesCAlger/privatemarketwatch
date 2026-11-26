-- Decides, for each report date and each base rate, the range of values a loan on that rate can have reset to (text
-- slice R phase 2, 2026-11-26). One row per (report_date, rate_name). Read by int_text_check_base_level only.
--
-- Report dates: every report date of int_text_rate_proposed_position. Rates: every rate_name of seed base_rate_series.
-- Series used (seed base_rate_fred): the rate's published daily series where it has one (SOFR, SONIA, PRIME,
-- FEDFUNDS), else its monthly OECD proxy (LIBOR, EURIBOR, CORRA, BBSW, BKBM, STIBOR, SARON, NIBOR, TONA, KORIBOR). A rate
-- with both (SONIA: daily and the UK monthly proxy) uses the daily one only; the backward SOFR averages (kind average)
-- are not used: overnight SOFR over the window already spans them.
-- Window: loans reset to a term rate fixed 1 to 6 months before the report date, so the window is the trailing var
-- text_base_window_days (190) days: daily values dated in [report_date - 190, report_date]; monthly values (dated the
-- first of their month) whose month overlaps that window (month start <= report_date and month end >= report_date -
-- 190). range_min, range_max: the smallest and largest value in the window; n_values; last_value_date (for a monthly
-- value, its month end).
-- tolerance: var text_base_tolerance_published (daily) or text_base_tolerance_proxy (monthly proxy), added below the
-- minimum and above the maximum. upper_extra: for SOFR only, var text_base_sofr_adjustment_max (0.26): the credit
-- spread adjustment (0.10 / 0.15 / 0.25 by tenor) many SOFR loans add on top of SOFR, and term SOFR runs above overnight
-- SOFR when cuts are not expected; admissible_low = range_min - tolerance, admissible_high = range_max + tolerance +
-- upper_extra.
-- state: ok; no_values (no value in the window); stale (the latest value in the window is more than
-- var text_sofr_max_age_days (7) days before the report date for a daily series, more than
-- var text_base_monthly_max_age_days (62) days for a monthly one: the euro and UK proxies end 2026-01).
with report_date as (
    select distinct report_date from {{ ref('int_text_rate_proposed_position') }}
)

, series as (
    select s.series_id, s.rate_name, s.frequency, s.kind
        , row_number() over (partition by s.rate_name
                             order by case s.kind when 'published' then 1 when 'proxy' then 2 else 3 end, s.series_id)
            as rk
    from {{ ref('base_rate_series') }} s
    where s.kind in ('published', 'proxy')
)

, chosen as (
    select series_id, rate_name, frequency, kind from series where rk = 1
)

, value_span as (
    select c.rate_name, c.series_id, c.frequency, c.kind, f.date as value_start
        , case when c.frequency = 'monthly' then cast(f.date + interval 1 month - interval 1 day as date) else f.date end
            as value_end
        , f.value_pct
    from chosen c
    join {{ ref('base_rate_fred') }} f on f.series_id = c.series_id
)

, windowed as (
    select d.report_date, v.rate_name, min(v.value_pct) as range_min, max(v.value_pct) as range_max
        , count(*) as n_values, max(v.value_end) as last_value_date
    from report_date d
    join value_span v
        on v.value_start <= d.report_date
        and v.value_end >= d.report_date - {{ var('text_base_window_days') }}
    group by 1, 2
)

select
    d.report_date
    , c.rate_name
    , c.series_id
    , c.frequency
    , c.kind
    , w.range_min
    , w.range_max
    , coalesce(w.n_values, 0) as n_values
    , w.last_value_date
    , case when c.kind = 'published' then {{ var('text_base_tolerance_published') }}
           else {{ var('text_base_tolerance_proxy') }} end as tolerance
    , case when c.rate_name = 'SOFR' then {{ var('text_base_sofr_adjustment_max') }} else 0 end as upper_extra
    , w.range_min - case when c.kind = 'published' then {{ var('text_base_tolerance_published') }}
                         else {{ var('text_base_tolerance_proxy') }} end as admissible_low
    , w.range_max + case when c.kind = 'published' then {{ var('text_base_tolerance_published') }}
                         else {{ var('text_base_tolerance_proxy') }} end
        + case when c.rate_name = 'SOFR' then {{ var('text_base_sofr_adjustment_max') }} else 0 end as admissible_high
    , case
        when w.n_values is null then 'no_values'
        when c.frequency = 'daily' and w.last_value_date < d.report_date - {{ var('text_sofr_max_age_days') }}
            then 'stale'
        when c.frequency = 'monthly' and w.last_value_date < d.report_date - {{ var('text_base_monthly_max_age_days') }}
            then 'stale'
        else 'ok'
      end as state
from report_date d
cross join chosen c
left join windowed w on w.report_date = d.report_date and w.rate_name = c.rate_name
