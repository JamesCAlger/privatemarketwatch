-- Slice R fix round 1: printed note rows "(n)" + text, per fund: how many filings have them, and the share of header
-- marks of rate-candidate columns (latest filing) that find a note row in the same filing. Read-only.
with fil as (select distinct accession, cik from int_page_table)
, r as (
    select d.accession, d.row_index, list_filter(list_transform(d.cells, x -> trim(regexp_replace(coalesce(x, ''), '[\s\x{00A0}]+', ' ', 'g'))), x -> x <> '') as ne
    from stg_filed_document_row d join fil using (accession)
)
, notes as (
    select accession, ne[1] as mark, ne[2] as note_text, row_index
    from r where len(ne) >= 2 and regexp_full_match(ne[1], '\(\d{1,3}\)') and length(ne[2]) >= 15
)
, hdr as (
    select c.cik, c.accession, c.table_index, coalesce(c.sub_header_text, '') || ' ' || c.header_text as htxt
    from int_page_column c
)
, marks as (select cik, accession, unnest(regexp_extract_all(htxt, '\(\d{1,3}\)')) as mark from hdr)
select f.cik, count(distinct m.accession || m.mark) as header_marks
    , count(distinct m.accession || m.mark) filter (where n.accession is not null) as found
from marks m join fil f using (accession, cik)
left join (select distinct accession, mark from notes) n on n.accession = m.accession and n.mark = m.mark
group by 1 order by 1
