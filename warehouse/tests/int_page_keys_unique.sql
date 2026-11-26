-- Text slice P (2026-11-26; fix round 1 keys): the key of each page-structure model is unique, and int_page_position has a row for every
-- position of int_source_row. Returns one row per duplicated key (n > 1) or missing position (n = 0).
select 'int_page_position' as model, accession || '|' || context_id as key, count(*) as n
from {{ ref('int_page_position') }} group by 1, 2 having count(*) > 1
union all
select 'int_page_position', s.accession || '|' || s.context_id, 0
from {{ ref('int_source_row') }} s
anti join {{ ref('int_page_position') }} p on p.accession = s.accession and p.context_id = s.context_id
where s.role = 'position'
union all
select 'int_page_table', accession || '|' || table_index, count(*)
from {{ ref('int_page_table') }} group by 1, 2 having count(*) > 1
union all
select 'int_page_cell', accession || '|' || row_index || '|' || cell_index, count(*)
from {{ ref('int_page_cell') }} group by 1, 2 having count(*) > 1
union all
select 'int_page_column', accession || '|' || table_index || '|' || col_start, count(*)
from {{ ref('int_page_column') }} group by 1, 2 having count(*) > 1
union all
select 'int_page_cell_column', accession || '|' || row_index || '|' || cell_index, count(*)
from {{ ref('int_page_cell_column') }} group by 1, 2 having count(*) > 1
union all
select 'int_page_column_filing', accession || '|' || table_signature || '|' || header_signature, count(*)
from {{ ref('int_page_column_filing') }} group by 1, 2 having count(*) > 1
union all
select 'int_page_schedule', accession || '|' || table_index, count(*)
from {{ ref('int_page_schedule') }} group by 1, 2 having count(*) > 1
union all
select 'int_page_heading', accession || '|' || row_index, count(*)
from {{ ref('int_page_heading') }} group by 1, 2 having count(*) > 1
union all
select 'int_position_heading', accession || '|' || context_id || '|' || heading_depth, count(*)
from {{ ref('int_position_heading') }} group by 1, 2 having count(*) > 1
