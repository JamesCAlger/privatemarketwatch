{#
  Rules 4 and 5 of the row roles (spec intermediate_spine.md 6.2), shared by int_role_text and the fixture test
  tests/int_source_row_text_patterns.sql, so that the test reads the real patterns in seeds/role_pattern.csv.

  open_context: the name of a CTE with columns accession, context_id, identifier_label. The macro continues the
  caller's WITH list (it starts with a comma), so the caller opens WITH with that CTE.
  Returns a select with one row per input row: accession, context_id, text_rule (4, 5 or null), pattern_id (the
  aggregate pattern that decided), cash_pattern_id (a rule 5 exception that matched: the row names a money-market fund).

  A pattern is matched against each '|'-separated segment of the label, lowercased, with white space collapsed and
  trimmed. A rule fires when a segment matches one of its 'aggregate' patterns and no segment matches one of its
  'position' patterns (an exception). Rule 4 is tried before rule 5.
#}
{% macro role_text_rules(open_context) %}
, _segment as (
    select
        accession
        , context_id
        , trim(regexp_replace(lower(unnest(string_split(identifier_label, '|'))), '\s+', ' ', 'g')) as segment
    from {{ open_context }}
    where identifier_label is not null
)

, _matched as (
    select s.accession, s.context_id, p.rule_number, p.role, p.pattern_id
    from _segment s
    join {{ ref('role_pattern') }} p on regexp_matches(s.segment, p.pattern)
)

, _by_rule as (
    select
        accession
        , context_id
        , rule_number
        , min(pattern_id) filter (where role = 'aggregate') as aggregate_pattern_id
        , min(pattern_id) filter (where role = 'position') as exception_pattern_id
    from _matched
    group by 1, 2, 3
)

select
    o.accession
    , o.context_id
    , case
        when r4.aggregate_pattern_id is not null and r4.exception_pattern_id is null then 4
        when r5.aggregate_pattern_id is not null and r5.exception_pattern_id is null then 5
      end as text_rule
    , case
        when r4.aggregate_pattern_id is not null and r4.exception_pattern_id is null then r4.aggregate_pattern_id
        when r5.aggregate_pattern_id is not null and r5.exception_pattern_id is null then r5.aggregate_pattern_id
      end as pattern_id
    , r5.exception_pattern_id as cash_pattern_id
from {{ open_context }} o
left join _by_rule r4 on r4.accession = o.accession and r4.context_id = o.context_id and r4.rule_number = 4
left join _by_rule r5 on r5.accession = o.accession and r5.context_id = o.context_id and r5.rule_number = 5
{% endmacro %}
