-- Final fix wave F3: every key pinned in var concept_rule_release_pinned (accession|context_id) must still be a row the
-- concept-release guard would list (macro concept_release_unmatched, in the compared quarters). A pin that no longer
-- matches one is stale and fails here, so a pin cannot outlive the row it excuses without being seen. Lists stale pins.
with rows_in as (
    select s.accession, s.context_id, s.cik, s.report_date, s.role, s.role_rule, s.is_cash, s.is_published
        , cf.term_fact_source
    from {{ ref('int_source_row') }} s
    join {{ ref('int_context_feature') }} cf on cf.accession = s.accession and cf.context_id = s.context_id
)
, prod as (
    select
        accession_number as accession
        , src_context_id as context_id
        , accounting_record_class is distinct from 'underlying_schedule' as is_published
    from {{ ref('stg_holdings') }}
    where src_context_id is not null
)
, excluded as (
    select cik, report_date from {{ ref('cmp_excluded_quarter') }}
)
, unmatched as (
    {{ concept_release_unmatched('rows_in', 'prod', 'excluded') }}
)
, pinned as (
    select unnest([{% for k in var('concept_rule_release_pinned', []) %}'{{ k }}'{% if not loop.last %}, {% endif %}{% endfor %}]::varchar[]) as release_key
)
select p.release_key
from pinned p
where p.release_key not in (select accession || '|' || context_id from unmatched)
