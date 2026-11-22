-- Decides nothing: one row per parsed filing with the two counts filing selection reads (pilot instance_select.py, measure_instance).
--
-- report_date          : the filing's dei DocumentPeriodEndDate.
-- position_fact_count  : fair-value facts (the seed concept_map, field fair_value) on instant contexts dated at report_date
--                        that carry an investment-identifier member.
-- numeric_fact_count   : facts with a unit, outside the dei namespace, on contexts whose instant or end date is report_date.
-- is_amendment         : the filing's own dei DocumentType ends in /A. dei AmendmentFlag is carried as evidence and never
--                        read by the selection: it is false on Ares's four 10-K/As.
-- schedule_max_date    : latest instant date of any identifier-axis fair-value fact in the filing; selection refuses a
--                        filing whose schedule is dated after its period end.
with fact_counts as (
    select
        f.accession
        , count(*) filter (
            where f.unit_id is not null
              and f.concept_namespace not like 'http://xbrl.sec.gov/dei/%'
              and coalesce(c.instant_date, c.end_date) = fi.document_period_end_date
        ) as numeric_fact_count
        , count(*) filter (
            where fv.concept_map_id is not null
              and cf.period_type = 'instant'
              and cf.is_filing_period_end
              and cf.has_identifier_member
        ) as position_fact_count
        , max(cf.instant_date) filter (
            where fv.concept_map_id is not null
              and cf.has_identifier_member
        ) as schedule_max_date
    from {{ ref('stg_filed_fact') }} f
    join {{ ref('stg_filed_filing') }} fi on fi.accession = f.accession
    join {{ ref('stg_filed_context') }} c on c.accession = f.accession and c.context_id = f.context_id
    join {{ ref('int_context_feature') }} cf on cf.accession = f.accession and cf.context_id = f.context_id
    -- a fact of the fair-value concept (local name and namespace pattern from the seed); at most one seed row matches
    -- a fact (tests/concept_map_one_row_per_fact.sql), so the join adds no rows
    left join {{ ref('concept_map') }} fv
        on fv.field = 'fair_value' and fv.concept_local = f.concept_local and f.concept_namespace glob fv.namespace_pattern
    group by 1
)

select
    fi.cik
    , fi.accession
    , fi.document_period_end_date as report_date
    , fi.document_type
    , fi.amendment_flag
    , coalesce(fi.document_type like '%/A', false) as is_amendment
    , fi.dei_conflict
    , coalesce(fc.position_fact_count, 0) as position_fact_count
    , coalesce(fc.numeric_fact_count, 0) as numeric_fact_count
    , fc.schedule_max_date
from {{ ref('stg_filed_filing') }} fi
left join fact_counts fc on fc.accession = fi.accession
where fi.cik in (select cik from {{ ref('stg_v05_scope') }})
