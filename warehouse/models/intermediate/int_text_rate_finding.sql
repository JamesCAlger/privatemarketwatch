-- Plan item K4 (owner 2026-11-26; slice R phase 3 fix round 1): one finding per (fund, constraint, rule), over the held
-- values (constraints 1 to 3, int_text_rate_held) and the constraint failures (4 and 5, int_text_rate_constraint
-- verdict fail). One row per finding_id.
--
-- finding_id (fix round 2): the first 16 hex characters of md5(cik | constraint_name | rule_key). rule_key is the stable
-- key of int_text_rate_rule (what the rule reads: fund, action, column signatures, shape, number index, role; code and
-- rate), not rule_id, which hashes the rule's evidence and dated parameters and so changes when a count, a date or the
-- evidence wording changes. Rules that differ only in evidence, counts or dates share a key and so a finding. The general
-- readings with no wrapper rule (rule ids 'reference_rate:<rate>', 'owner-2026-11-26-item-2') are their own key. No
-- position, row count, filing or date enters the id; first_report_date and the example are reported, not hashed.
-- rule_id: the smallest rule id of the key (for reading the rule). A failure of constraint 4 or 5 counts against every rule its fields were read with (rule_ids); a failure whose
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
    left(md5(u.cik || '|' || u.constraint_name || '|' || coalesce(k.rule_key, u.rule_id)), 16) as finding_id
    , u.cik
    , u.constraint_name
    , coalesce(k.rule_key, u.rule_id) as rule_key
    , min(u.rule_id) as rule_id
    , count(distinct u.accession || '|' || u.context_id) as positions
    , min(u.report_date) as first_report_date
    , max(u.report_date) as last_report_date
    , min_by(u.accession, u.accession || '|' || u.context_id) as example_accession
    , min_by(u.context_id, u.accession || '|' || u.context_id) as example_context_id
    , min_by(u.example, u.accession || '|' || u.context_id) as example
from unioned u
left join {{ ref('int_text_rate_rule') }} k on k.rule_id = u.rule_id
where u.rule_id is not null
group by u.cik, u.constraint_name, coalesce(k.rule_key, u.rule_id)
