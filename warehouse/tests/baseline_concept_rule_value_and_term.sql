-- Baseline (review finding I2, slice 2 Task 5). Where one fund concept rule gives a line both its fair value and its
-- term fact (Blue Owl's unfunded-commitment lines, owner decision D11), the term-fact cross-check cannot hold the
-- line back. These lines are expected to be commitments: zero or negative (fees) fair value, and never a total. A
-- published position whose fair value AND term fact both come from concept rules must have no positive fair value
-- and no label segment matching a rule 4 aggregate pattern (seeds/role_pattern.csv, rule_number 4, read here, not
-- copied). Ceiling 0.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['concept_rule_value_and_term']) }}
with lines as (
    select r.accession, r.context_id, r.cik, r.report_date, cf.identifier_label, cf.fair_value
        , cf.fair_value_source, cf.term_fact_source
    from {{ ref('int_source_row') }} r
    join {{ ref('int_context_feature') }} cf on cf.accession = r.accession and cf.context_id = r.context_id
    where r.role = 'position' and r.is_published
      and cf.fair_value_source <> 'standard' and cf.term_fact_source <> 'standard'
)
, total_like as (
    select l.accession, l.context_id, min(p.pattern_id) as pattern_id
    from lines l
    , unnest(string_split(coalesce(l.identifier_label, ''), '|')) as s(segment)
    join {{ ref('role_pattern') }} p
        on p.rule_number = 4 and p.applies_to = 'label_segment'
        and regexp_matches(trim(regexp_replace(lower(s.segment), '\s+', ' ', 'g')), p.pattern)
    group by 1, 2
)
select l.*, t.pattern_id as total_pattern_id
from lines l
left join total_like t on t.accession = l.accession and t.context_id = l.context_id
where l.fair_value > 0 or t.pattern_id is not null
