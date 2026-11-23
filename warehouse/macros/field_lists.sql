{#- The one place that names which fields the conversion layer (int_field_rule, int_field_normalised) works on, and how
    a filed unit maps to a unit kind. Slice 4 Task 3. -#}

{#- The five amount fields of int_field_read that get a conversion rule (slice 3). principal_amount_usd is added by
    int_field_rule itself. -#}
{% macro amount_rule_fields() -%}
('fair_value', 'cost', 'principal_amount', 'shares', 'pct_of_net_assets')
{%- endmacro %}

{#- The int_field_read fields the rate rules read (slice 4 Task 2): the two rate tags as filed, the PIK rate, the spread
    and the maturity date. -#}
{% macro rate_read_fields() -%}
('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread', 'maturity_date')
{%- endmacro %}

{#- The rate fields int_field_rule chooses a rule for (slice 4 Task 3). interest_rate_cash takes the rule of
    interest_rate: one reading decides both legs. -#}
{% macro rate_rule_fields() -%}
('interest_rate', 'pik_rate', 'spread', 'maturity_date')
{%- endmacro %}

{#- The rate fields int_field_normalised stores. -#}
{% macro rate_output_fields() -%}
('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
{%- endmacro %}

{#- An action is built for a field when its slice is 3, when built_early_for_field names the field, or (slice 4 Task 3)
    when its slice is 4 and the field is a rate field. seeds/reading_action.csv gives the two columns. -#}
{% macro action_is_built(built_in_slice, built_early_for_field, field) -%}
coalesce({{ built_in_slice }} = '3' or {{ built_early_for_field }} = {{ field }}
         or ({{ built_in_slice }} = '4' and {{ field }} in {{ rate_output_fields() }}), false)
{%- endmacro %}

{#- Unit kind of a unit as filed: iso4217:USD is usd, another iso4217 code is foreign, shares, a ratio unit is pure,
    anything else other. Ratio units: pure, and utr:Rate (the XBRL unit type registry's rate unit; controller ruling,
    slice 4 Task 3: a ratio unit gets the same kind as pure). No amount field of the five funds is filed in utr:Rate
    (scripts/slice4/q_t3_amount_units.sql), so adding it moves no amount row. -#}
{% macro unit_kind(unit) -%}
case
    when {{ unit }} = 'iso4217:USD' then 'usd'
    when regexp_full_match({{ unit }}, 'iso4217:[A-Z]{3}') then 'foreign'
    when {{ unit }} = 'shares' then 'shares'
    when {{ unit }} in ('pure', 'utr:Rate') then 'pure'
    else 'other'
end
{%- endmacro %}
