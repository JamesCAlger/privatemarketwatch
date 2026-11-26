{#- Text helpers for the rate-text models (text slice R phase 1, 2026-11-26). -#}

{#- The text shape of a column's text on a row: every number (a digit run, with groups of three digits after thousands
    commas and decimals: '525', '1,250', '0.50', '.75'; a comma not followed by three digits is kept, so "525," stays
    "#,") becomes '#', every run of white space (the no-break space too) becomes one space, the ends
    are trimmed. Letters and all other characters are kept. '#' is the placeholder because a rate code can be the
    letter N ("N+475" gives "N+#", never confused with a number). "S+525, 0.50% Floor" gives "S+#, #% Floor". -#}
{% macro text_shape(expr) -%}
trim(regexp_replace(regexp_replace(coalesce({{ expr }}, ''), '\d+(,\d{3})*(\.\d+)?|\.\d+', '#', 'g'), '[\s\x{00A0}]+', ' ', 'g'))
{%- endmacro %}

{#- The leading rate code or words of a text: one or more words of letters (dots allowed inside a word, words joined by
    single spaces) at the start of the text, ended by '+', '(', a digit or the end of the text. "SOFR (Q)" gives
    'SOFR', "S+525, 0.50% Floor" 'S', "SR + 5.50%" 'SR', "Base Rate (Q)" 'Base Rate', "Fixed" 'Fixed'. Null when the
    text does not start that way: "N/A" (a slash), "10.00%", "Estimated Yield:" (a colon). -#}
{% macro rate_code(expr) -%}
nullif(regexp_extract(coalesce({{ expr }}, ''), '^([A-Za-z][A-Za-z.]*(?: [A-Za-z][A-Za-z.]*)*?)\s*(?:\+|\(|\d|$)', 1), '')
{%- endmacro %}

{#- Whether a text looks like rate text: a number followed by '%' (spaces allowed between), or letters followed by '+'
    (spaces allowed). "5.25%", "10.00 %", "S+", "SOFR +" do; "SOFR (Q)", "1,250", "N/A" do not. -#}
{% macro is_rate_text(expr) -%}
regexp_matches(coalesce({{ expr }}, ''), '\d\s*%|[A-Za-z]\s*\+')
{%- endmacro %}

{#- The numbers of a text in order, as doubles (thousands commas dropped): "S+150 Cash plus 5.75% PIK, 1.00% Floor"
    gives [150, 5.75, 1.0]. -#}
{% macro text_numbers(expr) -%}
list_transform(regexp_extract_all(coalesce({{ expr }}, ''), '\d+(?:,\d{3})*(?:\.\d+)?|\.\d+'), x -> try_cast(replace(x, ',', '') as double))
{%- endmacro %}
