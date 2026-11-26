{#- Text helpers for the rate-text models (text slice R phase 1, 2026-11-26). -#}

{#- The text shape of a column's text on a row: every number (a digit run, with groups of three digits after thousands
    commas and decimals: '525', '1,250', '0.50', '.75'; a comma not followed by three digits is kept, so "525," stays
    "#,") becomes '#', every run of white space (the no-break space too) becomes one space, the ends
    are trimmed, and (fix round 1) the space before '%' and the spaces around '+' are removed, so "SOFR + 5.25%",
    "SOFR +5.25 %" and "SOFR+5.25%" give one shape "SOFR+#%" (cells joined with a space made "# %" out of "10.00" and
    "%"). Letters and all other characters are kept, case too: the shape unit's key is the upper-case shape (macro
    text_shape_key), its display form the most frequent spelling. '#' is the placeholder because a rate code can be the
    letter N ("N+475" gives "N+#", never confused with a number). "S+525, 0.50% Floor" gives "S+#, #% Floor". -#}
{% macro text_shape(expr) -%}
regexp_replace(regexp_replace(
    trim(regexp_replace(regexp_replace(coalesce({{ expr }}, ''), '\d+(,\d{3})*(\.\d+)?|\.\d+', '#', 'g'), '[\s\x{00A0}]+', ' ', 'g')),
    ' %', '%', 'g'), ' ?\+ ?', '+', 'g')
{%- endmacro %}

{#- The key of a shape: macro text_shape upper-cased ("Base rate (Q)" and "Base Rate (Q)" are one shape unit). -#}
{% macro text_shape_key(expr) -%}
upper({{ text_shape(expr) }})
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

{#- Text slice R phase 2. The base-rate name a rate's printed name or abbreviation stands for, in the rate_name
    vocabulary of seed base_rate_series; null when it maps to none. The same rules, in the same order, as NAME_RULES of
    scripts/text/proposals_to_seeds.py (first match wins, upper-cased text searched): Canadian prime maps to none (no
    series); CDOR to CORRA and BBSY to BBSW (their only series is the same OECD proxy); then BKBM, SOFR, SONIA, EURIBOR,
    STIBOR, SARON, NIBOR, TONA (TONAR), KORIBOR, FEDFUNDS, LIBOR, PRIME. "Secured Overnight Financing Rate" gives SOFR,
    "Norwegian Interbank Offered Rate" NIBOR, "Bloomberg Short Term Bank Yield Index" null. -#}
{% macro base_rate_name(expr) -%}
case
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'CANADIAN PRIME|CAD PRIME|CAD BASE RATE|CANADIAN BASE') then null
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'CDOR|CANADIAN DOLLAR OFFERED') then 'CORRA'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'CORRA|CANADIAN OVERNIGHT REPO') then 'CORRA'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'BBSY|BANK BILL SWAP BID') then 'BBSW'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'BBSW|BANK BILL SWAP') then 'BBSW'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'BKBM|BANK BILL BENCHMARK|NEW ZEALAND BANK BILL') then 'BKBM'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'SOFR|SECURED OVERNIGHT FINANCING') then 'SOFR'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'SONIA|STERLING OVERNIGHT') then 'SONIA'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'EURIBOR|EURO INTERBANK') then 'EURIBOR'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'STIBOR|STOCKHOLM INTERBANK') then 'STIBOR'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'SARON|SWISS AVERAGE RATE OVERNIGHT') then 'SARON'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'NIBOR|NORWEGIAN INTERBANK') then 'NIBOR'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'TONAR|TONA|TOKYO OVERNIGHT') then 'TONA'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'KORIBOR|KOREA INTERBANK|KOREAN INTERBANK') then 'KORIBOR'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'FEDERAL FUNDS|FED FUNDS|FEDFUNDS') then 'FEDFUNDS'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'LIBOR|LONDON INTERBANK') then 'LIBOR'
    when regexp_matches(upper(coalesce({{ expr }}, '')), 'PRIME') then 'PRIME'
end
{%- endmacro %}
