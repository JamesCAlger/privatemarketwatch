-- Decides which filing speaks for each fund and report date, or refuses the quarter with a reason (spec 6.1).
--
-- Ported from the pilot (branch filer-profile-pilot, scripts/profile_pilot/instance_select.py, amendment-rule.v1):
--   1. Candidates are the parsed filings of one fund with the same dei period end.
--   2. Refused: more than one form family (10-K vs 10-Q), a family that is not 10-K or 10-Q, a candidate whose
--      period end is in doubt (dei conflict, or identifier-axis fair values dated after the period end), or two
--      originals.
--   3. Measure: position facts; where no candidate has any, non-dei numeric facts at the period end.
--   4. A candidate is full when its count * 100 >= largest * filing_fullness_min (integer comparison).
--   5. An amendment with no numeric facts at the period end is cover-only and skipped. Any other candidate that is
--      not full is partial, and a partial candidate refuses the quarter.
--   6. The latest full candidate wins.
-- Difference from the pilot: the filed layer has no filing date, so "latest" is read as "an amendment is later
-- than the original it amends". Two full amendments for one quarter cannot be ordered and refuse the quarter
-- (two_full_amendments_order_unknown) rather than being ordered by accession number.
with candidate as (
    select
        *
        , replace(document_type, '/A', '') as form_family
    from {{ ref('int_filing_candidate') }}
)

, quarter as (
    select
        cik
        , report_date
        , count(*) as candidate_count
        , count(distinct form_family) as family_count
        , min(form_family) as form_family
        , count(*) filter (where not is_amendment) as original_count
        , bool_or(coalesce(dei_conflict, false) or schedule_max_date > report_date) as period_end_doubt
        , bool_or(position_fact_count > 0) as has_position_facts
    from candidate
    group by 1, 2
)

, measured as (
    select
        c.*
        , q.candidate_count
        , q.family_count
        , q.original_count
        , q.period_end_doubt
        , case when q.has_position_facts then 'identifier_axis_fair_value_facts' else 'non_dei_numeric_facts' end as measure
        , case when q.has_position_facts then c.position_fact_count else c.numeric_fact_count end as measure_count
    from candidate c
    join quarter q on q.cik = c.cik and q.report_date = c.report_date
)

, disposed as (
    select
        *
        , max(measure_count) over (partition by cik, report_date) as largest_count
        , case
            when measure_count * 100 >= max(measure_count) over (partition by cik, report_date) * {{ var('filing_fullness_min') }}
                then 'full'
            when is_amendment and numeric_fact_count = 0 then 'cover_only_amendment'
            when measure_count = 0 and not is_amendment then 'original_without_target_facts'
            else 'partial'
          end as disposition
    from measured
)

, decided as (
    select
        cik
        , report_date
        , min(candidate_count) as candidate_count
        , min(measure) as measure
        , case
            when min(family_count) > 1 then 'mixed_form_family'
            when min(form_family) not in ('10-K', '10-Q') then 'not_periodic_report'
            when bool_or(period_end_doubt) then 'candidate_period_end_mismatch'
            when min(original_count) > 1 then 'two_originals_same_quarter'
            when max(largest_count) = 0 then 'no_candidate_with_position_facts'
            when bool_or(disposition = 'partial' and is_amendment) then 'partial_amendment_needs_review'
            when bool_or(disposition = 'partial') then 'partial_original_needs_review'
            when count(*) filter (where disposition = 'full' and is_amendment) > 1 then 'two_full_amendments_order_unknown'
          end as refusal_reason
        , coalesce(
            min(accession) filter (where disposition = 'full' and is_amendment)
            , min(accession) filter (where disposition = 'full' and not is_amendment)
          ) as chosen_accession
        , bool_or(disposition = 'full' and is_amendment) as chosen_is_amendment
        , bool_or(disposition = 'cover_only_amendment') as has_cover_only_amendment
    from disposed
    group by 1, 2
)

select
    cik
    , report_date
    , case when refusal_reason is null then chosen_accession end as accession
    , case
        when refusal_reason is not null then null
        when chosen_is_amendment then 'latest_full_amendment'
        when has_cover_only_amendment then 'original_after_cover_only_amendment'
        else 'latest_full_candidate'
      end as selection_rule
    , refusal_reason
    , candidate_count
    , measure
from decided
