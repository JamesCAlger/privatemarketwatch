-- Slice R phase 1: trial of the legend pattern on footnotes (the model int_text_check_legend uses the same). Read-only.
with f as (
    select ft.accession, ft.footnote_id, replace(replace(ft.text, chr(8220), '"'), chr(8221), '"') as text
    from stg_filed_footnote ft
    where ft.accession in (select distinct accession from int_page_table)
)
, pat as (select '((?:[A-Z][A-Za-z.\-]*)(?:\s+(?:\([A-Z]{1,4}\)|[A-Z][A-Za-z.\-]*|of|and))*)\s*\(\s*"([A-Za-z ]{1,10})"\s*(?:or\s*"([A-Za-z ]{1,10})"\s*)?\)' as p)
, m as (
    select f.accession, regexp_extract_all(f.text, pat.p, 1) as names, regexp_extract_all(f.text, pat.p, 2) as c1
        , regexp_extract_all(f.text, pat.p, 3) as c2
    from f, pat
)
, u as (select accession, unnest(names) as name, unnest(c1) as c1, unnest(c2) as c2 from m)
select name, c1, c2, count(*) as n from u
where regexp_matches(name, '(?i)(rate|average|index|ibor|yield)')
group by all order by n desc
