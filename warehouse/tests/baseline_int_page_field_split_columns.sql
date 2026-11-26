-- Text slice P3 baseline (2026-11-26), a fund-neutral rule: within one schedule table, the placed facts of one tagged
-- field (int_field_read, status read: fair value, cost, principal, shares, share of net assets, the two rate tags, PIK
-- rate, spread, maturity date; a hidden fact counts in the cell that shows it) should fall under one header
-- signature. One row per (accession, table_index, field) where they fall under two or more, against a ceiling set to
-- the measured count (baseline_max.int_page_field_split_columns). Measured 2026-11-26: 27. One fund 23 (PIK rate 13,
-- rate tag 7, spread 3), a second 2 (PIK rate 1, rate tag 1), a third 2 (spread 2). In every case looked at, the filer prints the
-- odd value in the neighbouring rate column (a PIK coupon such as "13.75% PIK" in "Reference Rate and Spread", or a
-- coupon "12.55% (4.13% PIK)" carrying the spread tag in "Coupon"), so the column units are as printed; the split is
-- the filer's. Detail query: scripts/text/q_p1_split_detail.sql.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_page_field_split_columns']) }}
select fr.accession, cc.table_index, fr.field, count(distinct cc.header_signature) as signatures
from {{ ref('int_field_read') }} fr
join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = fr.accession and pl.fact_id = fr.fact_id
join {{ ref('int_page_cell_column') }} cc
    on cc.accession = pl.accession
    and cc.row_index = coalesce(pl.row_index, pl.shown_row_index)
    and cc.cell_index = coalesce(pl.cell_index, pl.shown_cell_index)
where fr.status = 'read' and cc.header_signature is not null
group by 1, 2, 3
having count(distinct cc.header_signature) > 1
