-- Reads the filer's own definitions of rate codes from its footnotes (text slice R phase 1, 2026-11-26; spec section 11:
-- "the filing's own legend"). One row per (cik, accession, code, name, abbreviation) found; a check, not a rule.
--
-- Footnotes: stg_filed_footnote of the filings that hold a schedule table (int_page_table), curly double quotes turned
-- into straight ones.
-- Pattern (RE2), anywhere in the text: a name, then in brackets one quoted code or two joined by 'or':
--   name   a word starting with a capital letter (letters, '.', '-'), followed by more such words, 'of', 'and', or a
--          bracketed group of 1 to 4 capitals, each after white space: "Secured Overnight Financing Rate",
--          "Sterling (SP) Overnight Interbank Average Rate", "U.S. Prime Rate", "KORIBOR" (in "subject to 3 months
--          KORIBOR", lower-case words end the name).
--   codes  ("CODE") or ("CODE1" or "CODE2"), each 1 to 10 letters or spaces.
-- Forms read: 'Secured Overnight Financing Rate ("SOFR" or "S")', 'subject to 3 months KORIBOR ("K")',
-- 'Canadian Overnight Repo Rate Average ("CORRA" or "C")', 'Federal Funds Rate ("F")'.
-- Kept only when the name contains (any case) 'rate', 'average', 'index', 'ibor' or 'yield': a rate's name. This leaves
-- out "(GAAP)", "(NAV)", "(PIK)", currency names such as 'Canadian Dollars ("CAD")'.
-- Rows per match: two codes give two rows, the first code and the second, both with abbreviation = the first code
-- ("SOFR" or "S" gives code SOFR and code S, abbreviation SOFR). One code gives one row; its abbreviation is the name
-- when the name is one word of 2 or more capitals ('KORIBOR' for "KORIBOR ("K")"), else the code when it has 3 or
-- more characters ('SOFR' for 'Secured Overnight Financing Rate ("SOFR")'), else null ('Federal Funds Rate ("F")': the
-- abbreviation is not printed).
-- code_key, abbreviation_key: upper case, white space removed. n_footnotes: footnotes of the filing holding the entry.
with filing as (
    select accession, min(cik) as cik, min(report_date) as report_date
    from {{ ref('int_page_table') }}
    group by 1
)

, footnote as (
    select f.cik, f.report_date, ft.accession, ft.footnote_id
        , replace(replace(ft.text, chr(8220), '"'), chr(8221), '"') as text
    from {{ ref('stg_filed_footnote') }} ft
    join filing f on f.accession = ft.accession
)

{% set legend_pattern = '((?:[A-Z][A-Za-z.\\-]*)(?:\\s+(?:\\([A-Z]{1,4}\\)|[A-Z][A-Za-z.\\-]*|of|and))*)\\s*\\(\\s*"([A-Za-z ]{1,10})"\\s*(?:or\\s*"([A-Za-z ]{1,10})"\\s*)?\\)' %}

, matched as (
    select cik, report_date, accession, footnote_id
        , regexp_extract_all(text, '{{ legend_pattern }}', 1) as names
        , regexp_extract_all(text, '{{ legend_pattern }}', 2) as first_codes
        , regexp_extract_all(text, '{{ legend_pattern }}', 3) as second_codes
    from footnote
)

, entry as (
    select cik, report_date, accession, footnote_id, unnest(names) as name, trim(unnest(first_codes)) as first_code
        , trim(unnest(second_codes)) as second_code
    from matched
)

, rate_entry as (
    select *
    from entry
    where regexp_matches(name, '(?i)(rate|average|index|ibor|yield)')
)

, coded as (
    select cik, report_date, accession, footnote_id, name, first_code as code
        , case
            when second_code <> '' then first_code
            when regexp_full_match(name, '[A-Z]{2,}') then name
            when length(first_code) >= 3 then first_code
        end as abbreviation
    from rate_entry
    union all
    select cik, report_date, accession, footnote_id, name, second_code as code, first_code as abbreviation
    from rate_entry
    where second_code <> ''
)

select
    cik
    , accession
    , min(report_date) as report_date
    , code
    , name
    , abbreviation
    , upper(replace(code, ' ', '')) as code_key
    , upper(replace(abbreviation, ' ', '')) as abbreviation_key
    , count(distinct footnote_id) as n_footnotes
from coded
group by cik, accession, code, name, abbreviation
