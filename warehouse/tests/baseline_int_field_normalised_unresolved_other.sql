-- Baseline (D5): unresolved amount fields whose (field, reason) pair has no baseline of its own (the generic test
-- baseline_normalised_unresolved, one per pair listed in var normalised_unresolved_declared). Ceiling 0: a new kind of
-- unresolved field needs its own measured ceiling.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_normalised_unresolved_other']) }}
select accession, context_id, cik, report_date, field, reason
from {{ ref('int_field_normalised') }}
where status = 'unresolved'
  and field || '|' || reason not in (
    {%- for pair in var('normalised_unresolved_declared') %}'{{ pair }}'{% if not loop.last %}, {% endif %}{% endfor -%}
  )
