-- MEASUREMENT ONLY (fix round 2: renamed from int_text_check_base_cluster_group; no model and no worklist state reads
-- it): the implied-base clusters per fund, quarter, basis and rate label (text slice R fix round 1, 2026-11-26). One row
-- per (cik, report_date, basis, rate_label) of int_text_measure_implied_base. cluster_state is a description of the
-- clusters, not a verdict on a rule: wrong readings pass it (section 13 of the baseline note).
--
-- usable: rows with an implied base (int_text_measure_implied_base state usable); pik_present, inputs_missing: the rest.
-- Centres: the implied bases rounded to var text_cluster_centre_step (0.05); the var text_cluster_max_centres (3) most
-- frequent rounded values, ties to the smaller value, are the centres; centre_1 is the most frequent (the main centre).
-- within: usable rows whose implied base lies within var text_cluster_radius (0.30 percentage points) of the nearest
-- centre; within_share = within / usable. main_share: the share within the radius of centre_1 alone.
-- sofr: seed sofr_90day_avg at the report date (the latest value at most var text_sofr_max_age_days days old);
-- sofr_distance = abs(centre_1 - sofr), for every label, with is_sofr_like when rate_label is 'SOFR' or the fund's
-- legend (int_text_check_legend) gives the code the abbreviation SOFR. MEASUREMENT ONLY, a sanity bound
-- (var text_cluster_sofr_bound, 1.0): within_bound says whether the main centre is that close; it decides nothing.
-- cluster_state:
--   too_few_rows  fewer than var text_cluster_min_rows usable rows: not judged.
--   pass          within_share >= var text_cluster_min_share.
--   fail          otherwise.
-- The bar (min_rows, min_share) was set from the measured distribution in fix round 1; it is kept to describe the
-- clusters, not to accept anything.
{% set step = var('text_cluster_centre_step') %}
with row_base as (
    select cik, report_date, basis, rate_label, state, implied_base
        , round(implied_base / {{ step }}) * {{ step }} as rounded
    from {{ ref('int_text_measure_implied_base') }}
)

, mode_count as (
    select cik, report_date, basis, rate_label, rounded, count(*) as n
    from row_base
    where state = 'usable'
    group by 1, 2, 3, 4, 5
)

, centre as (
    select cik, report_date, basis, rate_label, rounded as centre, rk
    from (
        select *, row_number() over (partition by cik, report_date, basis, rate_label order by n desc, rounded) as rk
        from mode_count
    )
    where rk <= {{ var('text_cluster_max_centres') }}
)

, centre_list as (
    select cik, report_date, basis, rate_label, list(centre order by rk) as centres
    from centre
    group by 1, 2, 3, 4
)

, membership as (
    select r.cik, r.report_date, r.basis, r.rate_label
        , count(*) as usable
        , count(*) filter (where list_min(list_transform(c.centres, x -> abs(r.implied_base - x)))
                                 <= {{ var('text_cluster_radius') }} + 1e-9) as within
        , count(*) filter (where abs(r.implied_base - c.centres[1]) <= {{ var('text_cluster_radius') }} + 1e-9)
            as main_within
    from row_base r
    join centre_list c using (cik, report_date, basis, rate_label)
    where r.state = 'usable'
    group by 1, 2, 3, 4
)

, all_rows as (
    select cik, report_date, basis, rate_label, count(*) as rows
        , count(*) filter (where state = 'pik_present') as pik_present
        , count(*) filter (where state = 'inputs_missing') as inputs_missing
    from row_base
    group by 1, 2, 3, 4
)

, sofr_like as (
    select distinct cik, code_key from {{ ref('int_text_check_legend') }} where abbreviation_key = 'SOFR'
)

, sofr as (
    select date, sofr_90day_avg_pct from {{ ref('sofr_90day_avg') }}
)

, joined as (
    select
        a.*
        , coalesce(m.usable, 0) as usable
        , coalesce(m.within, 0) as within
        , m.within / nullif(m.usable, 0) as within_share
        , m.main_within / nullif(m.usable, 0) as main_share
        , c.centres
        , c.centres[1] as centre_1
        , a.rate_label = 'SOFR' or sl.code_key is not null as is_sofr_like
    from all_rows a
    left join membership m using (cik, report_date, basis, rate_label)
    left join centre_list c using (cik, report_date, basis, rate_label)
    left join sofr_like sl on sl.cik = a.cik and sl.code_key = a.rate_label and a.basis = 'hypothesis'
)

select
    j.*
    , case when j.report_date - s.date <= {{ var('text_sofr_max_age_days') }} then s.sofr_90day_avg_pct end as sofr
    , abs(j.centre_1 - case when j.report_date - s.date <= {{ var('text_sofr_max_age_days') }}
                            then s.sofr_90day_avg_pct end) as sofr_distance
    , abs(j.centre_1 - case when j.report_date - s.date <= {{ var('text_sofr_max_age_days') }}
                            then s.sofr_90day_avg_pct end) <= {{ var('text_cluster_sofr_bound') }} as within_bound
    , case
        when j.usable < {{ var('text_cluster_min_rows') }} then 'too_few_rows'
        when j.within_share >= {{ var('text_cluster_min_share') }} then 'pass'
        else 'fail'
    end as cluster_state
from joined j
asof left join sofr s on s.date <= j.report_date
