-- Slice R phase 1: exploration of footnote texts that define rate codes: a quoted short code in brackets. Read-only.
with f as (
    select fi.cik, ft.accession, ft.text
    from stg_filed_footnote ft
    join (select distinct accession, cik from int_page_table) fi on fi.accession = ft.accession
    where regexp_matches(ft.text, '\(\s*["\x{201C}\x{201D}][A-Z]{1,6}["\x{201C}\x{201D}]')
)
, m as (
    select cik, unnest(regexp_extract_all(text, '.{0,80}\(\s*["\x{201C}\x{201D}][A-Za-z ]{1,10}["\x{201C}\x{201D}][^)]{0,40}\)')) as frag
    from f
)
select cik, frag, count(*) as n from m group by 1, 2 order by 1, n desc
