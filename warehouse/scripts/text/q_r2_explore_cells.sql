-- Slice R phase 1, 2026-11-26: exploration. Most frequent cell texts of rate-like columns on position rows. Read-only.
with pos as (select distinct accession, row_index from int_page_position where placement_status = 'one_row')
, c as (
    select p.cik, cc.header_signature, cc.text
    from int_page_cell_column cc
    join pos on pos.accession = cc.accession and pos.row_index = cc.row_index
    join int_page_table p on p.accession = cc.accession and p.table_index = cc.table_index
    where cc.header_signature in ('reference', 'spread', 'coupon', 'referencerateandspread', 'interestrate', 'interest',
        'interest/ref.rate', 'interest/cash', 'interest/pik')
)
, s as (
    select cik, header_signature, regexp_replace(text, '\d+(\.\d+)?', '#', 'g') as shape, count(*) as n, min(text) as ex
    from c group by 1, 2, 3
)
select * from (
    select *, row_number() over (partition by cik, header_signature order by n desc) as rk,
        count(*) over (partition by cik, header_signature) as n_shapes
    from s) where rk <= 14
order by cik, header_signature, rk
