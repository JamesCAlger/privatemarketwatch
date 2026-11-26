-- Slice R fix round 1: where printed notes sit: rows whose first non-empty cell starts with "(n)" (alone or followed by
-- text in the same cell), per fund, with examples. Read-only.
with fil as (select distinct accession, cik from int_page_table)
, r as (
    select f.cik, d.accession, d.row_index, list_filter(list_transform(d.cells, x -> trim(regexp_replace(coalesce(x, ''), '[\s\x{00A0}]+', ' ', 'g'))), x -> x <> '') as ne
    from stg_filed_document_row d join fil f using (accession)
)
select cik, case when regexp_full_match(ne[1], '\(\d{1,3}\)') then 'mark alone, next=' || coalesce(left(ne[2], 30), 'none')
                 else 'mark+text' end as kind, count(*) n, min(left(array_to_string(ne, ' | '), 120)) ex
from r where len(ne) >= 1 and regexp_matches(ne[1], '^\(\d{1,3}\)') and (len(ne) >= 2 or length(ne[1]) > 6)
group by 1, case when regexp_full_match(ne[1], '\(\d{1,3}\)') then 'mark alone, next=' || coalesce(left(ne[2], 30), 'none') else 'mark+text' end
order by 1, 3 desc limit 40
