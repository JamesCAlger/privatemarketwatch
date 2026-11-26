{#- The base-level verdict of one implied base against one rate's window (int_text_base_rate_window), the first that
    applies (text slice R phase 2; moved into a macro in phase 3 so int_text_check_base_level and the read model's
    constraint 5, int_text_rate_constraint, share one version):
      not_tested     the inputs are not usable (tested is false).
      no_series      the window has no value or is stale (window state not 'ok').
      admissible     admissible_low <= implied_base <= admissible_high.
      floor_binding  outside, and a floor exists with abs(implied_base - floor) <= var text_floor_match.
      outside -#}
{% macro base_level_verdict(tested, window_state, implied_base, low, high, floor) -%}
case
    when not coalesce({{ tested }}, false) then 'not_tested'
    when {{ window_state }} is distinct from 'ok' then 'no_series'
    when {{ implied_base }} between {{ low }} and {{ high }} then 'admissible'
    when {{ floor }} is not null and abs({{ implied_base }} - {{ floor }}) <= {{ var('text_floor_match') }} then 'floor_binding'
    else 'outside'
end
{%- endmacro %}
