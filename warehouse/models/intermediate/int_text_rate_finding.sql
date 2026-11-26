-- Plan item K4 (owner 2026-11-26; slice R phase 3 fix round 1): one finding per (fund, constraint, rule), over the held
-- values (constraints 1 to 3, int_text_rate_held) and the constraint failures (4 and 5, int_text_rate_constraint
-- verdict fail). One row per finding_id.
--
-- finding_id: the first 16 hex characters of md5(cik | constraint_name | rule_id): built from those three only, so the
-- same rule failing the same constraint in the same fund has the same id in every build (no row, date or count enters
-- it). A failure of constraint 4 or 5 counts against every rule its fields were read with (rule_ids); a failure whose
-- field came from a tag only names no rule for that field (the other fields' rules still carry the finding).
-- positions: distinct positions; first/last_report_date; example_accession, example_context_id: the smallest key;
-- example: the held value and printed text (held) or the compared numbers (failure).
with held as (
    select cik, constraint_name, rule_id, accession, context_id, report_date
        , field || '=' || value || ' "' || coalesce(cell_text, '') || '"' as example
    from {{ ref('int_text_rate_held') }}
)

, failed as (
    select f.cik, f.constraint_name, unnest(f.rule_ids) as rule_id, f.accession, f.context_id, f.report_date
        , coalesce(f.reference_rate, '') || ' lhs=' || coalesce(round(f.lhs, 4)::varchar, '') || ' rhs='
          || coalesce(round(f.rhs, 4)::varchar, '') || ' window=' || coalesce(round(f.range_min, 2)::varchar, '') || '..'
          || coalesce(round(f.range_max, 2)::varchar, '') as example
    from {{ ref('int_text_rate_constraint') }} f
    where f.verdict = 'fail'
)

, unioned as (
    select * from held
    union all
    select * from failed
)

select
    left(md5(cik || '|' || constraint_name || '|' || rule_id), 16) as finding_id
    , cik
    , constraint_name
    , rule_id
    , count(distinct accession || '|' || context_id) as positions
    , min(report_date) as first_report_date
    , max(report_date) as last_report_date
    , min_by(accession, accession || '|' || context_id) as example_accession
    , min_by(context_id, accession || '|' || context_id) as example_context_id
    , min_by(example, accession || '|' || context_id) as example
from unioned
where rule_id is not null
group by cik, constraint_name, rule_id
