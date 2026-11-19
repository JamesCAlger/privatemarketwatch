{#- The text a fund rule's label_pattern is matched against: the first '|'-segment of an identifier label, lowercased,
    trimmed, white space collapsed (the form int_role_scope compares). One definition for the model and the test of
    the rules' label fixtures. -#}
{% macro label_first_segment(label) -%}
regexp_replace(lower(trim(split_part(coalesce({{ label }}, ''), '|', 1))), '\s+', ' ', 'g')
{%- endmacro %}
