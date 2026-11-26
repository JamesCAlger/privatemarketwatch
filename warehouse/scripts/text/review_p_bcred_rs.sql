-- Review slice P: BCRED table with rowspan header, raw rows and model cells.
with t as (select accession, table_index, header_row_index, header_last_row_in_table, width, header_form from int_page_table
  where accession='0001803498-22-000021' and table_index=(select table_index from stg_filed_document_row where accession='0001803498-22-000021' and row_index=3175))
select 'raw' k, dr.row_index, dr.row_in_table, t.width, t.header_form, t.header_last_row_in_table,
  list_transform(range(1, dr.cell_count+1), i -> coalesce(dr.cell_colspans[i],1)::varchar || 'x' || coalesce(dr.cell_rowspans[i],1)::varchar || ':' || left(coalesce(dr.cells[i],''),12)) as cells
from t join stg_filed_document_row dr on dr.accession=t.accession and dr.table_index=t.table_index where dr.row_in_table <= 6
union all
select 'cell', c.row_index, c.row_in_table, null, null, null, list(c.col_start||'-'||c.col_end||':'||left(c.text,12)||':'||c.span_rule order by c.cell_index)
from t join int_page_cell c on c.accession=t.accession and c.table_index=t.table_index where c.row_in_table <= 6 group by all
union all
select 'leaf', null, col.column_index, null, null, null, [col.col_start||'-'||col.col_end||' z'||col.zone_end||' '||col.header_signature]
from t join int_page_column col on col.accession=t.accession and col.table_index=t.table_index
order by 1,2,3
