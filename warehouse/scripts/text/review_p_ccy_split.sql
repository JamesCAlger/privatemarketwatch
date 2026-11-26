-- Review slice P: currency-symbol cells whose column differs from the next non-empty cell's column (number), by fund.
with c as (
  select cc.*, t.cik, lead(cc.header_signature) over (partition by cc.accession, cc.row_index order by cc.cell_index) next_sig,
    lead(cc.shape) over (partition by cc.accession, cc.row_index order by cc.cell_index) next_shape
  from int_page_cell_column cc join int_page_table t using (accession, table_index)
)
select cik, regexp_full_match(text, '\$') as is_usd, header_signature, next_sig, count(*) n
from c where regexp_full_match(text, '(\$|€|£|A\$|C\$|kr|₣|NZ\$|CHF|SEK|NOK|DKK|EUR|GBP|CAD|AUD)') and next_shape in ('number')
  and header_signature is distinct from next_sig
group by all order by 1, n desc
