{#- Final fix wave F6: every cash row (is_cash) names what flagged it: a fund rule (cash_rule_id), a seed cash pattern
    (cash_pattern_id), or rule 8 (role_rule 8, the filed cash and cash equivalents axis, which has no seed or rule id).
    Lists cash rows that name none. -#}
{% test cash_row_names_its_source(model) %}
select accession, context_id, cik, role, role_rule
from {{ model }}
where is_cash
  and cash_rule_id is null
  and cash_pattern_id is null
  and role_rule <> 8
{% endtest %}
