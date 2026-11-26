-- Slice P, 2026-11-26: the first rows of one schedule table per fund (latest filing, third schedule table), as
-- non-empty cells with their starting column. To see header rows and heading rows. Read-only.
with posn as (
    select accession, context_id, cik, report_date from int_source_row where role = 'position' and is_published
)
, prow as (
    select distinct p.cik, p.report_date, p.accession, pl.row_index
    from posn p
    join stg_filed_fact f on f.accession = p.accession and f.context_id = p.context_id and f.concept_local like 'InvestmentOwnedAtFairValue%'
    join stg_filed_fact_placement pl on pl.accession = f.accession and pl.fact_id = f.fact_id and not pl.in_hidden
)
, st as (
    select pr.cik, pr.accession, r.table_index, min(pr.row_index) as first_pos_row
        , dense_rank() over (partition by pr.cik order by pr.report_date desc, pr.accession) as filing_rank
        , dense_rank() over (partition by pr.cik, pr.accession order by r.table_index) as table_rank
    from prow pr join stg_filed_document_row r on r.accession = pr.accession and r.row_index = pr.row_index
    group by pr.cik, pr.report_date, pr.accession, r.table_index
)
, pick as (select * from st where filing_rank = 1 and table_rank = 3)
, cells as (
    select p.cik, r.row_index, r.row_in_table, r.fact_count, p.first_pos_row, i
        , r.cells[i] as txt
        , coalesce(list_sum(r.cell_colspans[1:i-1]), 0) as col_start
    from pick p join stg_filed_document_row r on r.accession = p.accession and r.table_index = p.table_index
    cross join unnest(generate_series(1, r.cell_count)) as t(i)
    where r.row_in_table <= 13
)
select cik, row_in_table as r, fact_count as facts, row_index >= first_pos_row as at_or_after_first_pos
    , left(string_agg(col_start || ':' || left(trim(txt), 28), ' | ' order by i) filter (where trim(replace(txt, chr(160), ' ')) <> ''), 330) as cells
from cells group by all order by cik, r
