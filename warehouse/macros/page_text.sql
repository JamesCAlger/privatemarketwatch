{#- Text helpers for the page-structure models (text slice P, 2026-11-26). -#}

{#- A printed cell's text as the page models read it: every run of white space (also the no-break space U+00A0)
    becomes one space, then the ends are trimmed. Empty text is ''. A null cell is ''. -#}
{% macro page_text(expr) -%}
trim(regexp_replace(coalesce({{ expr }}, ''), '[\s\x{00A0}]+', ' ', 'g'))
{%- endmacro %}

{#- A header's signature, for "new or changed" detection (spec section 4.2): lower case, footnote marks of the form
    "(1)" or "(1)(19)" (digits in brackets) removed, then every white space removed. "Par Amount/Units (1)" gives
    "paramount/units". -#}
{% macro page_signature(expr) -%}
lower(regexp_replace(regexp_replace(coalesce({{ expr }}, ''), '\(\d+\)', '', 'g'), '[\s\x{00A0}]', '', 'g'))
{%- endmacro %}

{#- The simple shape of a non-empty cell's text, the first that fits in this order:
    empty_marker  only dashes (-, en dash, em dash), '$', '%', brackets and spaces: '$', '-', an em dash, '%'
    footnote_mark one or more bracketed marks of up to three letters or digits, spaces allowed: '(2)', '(2)(11)', '(a)',
                  '(2)(10 )'
    date          d/m/yyyy-like ('5/8/2030', '12/2020', '09/2025') or a month name, day and year ('March 31, 2026')
    percent       a number followed by '%': '4.75%', '(0.5)%', '13.00 %'
    number        a number, optionally signed, with '$', thousands commas, decimals or brackets: '60,260', '(1,234)'
    text          anything else: 'SOFR +', 'S+525, 0.00% Floor', 'First lien senior secured loan' -#}
{% macro page_cell_shape(expr) -%}
case
    when regexp_full_match({{ expr }}, '[-\x{2013}\x{2014}$%()\s]+') then 'empty_marker'
    when regexp_full_match({{ expr }}, '(\(\s*[A-Za-z0-9]{1,3}\s*\)\s*)+') then 'footnote_mark'
    when regexp_full_match({{ expr }}, '\d{1,2}/(\d{1,2}/)?\d{2,4}')
        or regexp_full_match(lower({{ expr }}), '(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2},? \d{4}')
        then 'date'
    when regexp_full_match({{ expr }}, '\(?[-+]?\$?\s*\d[\d,]*(\.\d+)?\)?\s*%\)?') then 'percent'
    when regexp_full_match({{ expr }}, '\(?[-+]?\$?\s*\d[\d,]*(\.\d+)?\)?') then 'number'
    else 'text'
end
{%- endmacro %}
