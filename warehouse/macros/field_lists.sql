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

{#- Unit kind of a unit as filed (the unit text: numerator, or numerator/denominator), read from seeds/unit_kind.csv
    (slice 5 Task 1, owner decision 10 of 2026-11-23: the mapping is data). The row whose unit_pattern (RE2) matches the
    whole text gives the kind: usd, foreign, shares, pure, or other; a text no row matches is other. A text matching two
    rows fails tests/unit_kind_one_row_per_unit.sql; a unit read for an amount or rate field that no row lists fails
    tests/unit_kind_read_units_listed.sql. Before slice 5 the same mapping was written here as literals (iso4217:USD
    usd, another iso4217 code foreign, shares, pure and utr:Rate pure); the seed adds xbrli:shares and xbrli:pure. -#}
{% macro unit_kind(unit) -%}
coalesce((select min(uk.unit_kind) from {{ ref('unit_kind') }} uk where regexp_full_match({{ unit }}, uk.unit_pattern)),
         'other')
{%- endmacro %}
