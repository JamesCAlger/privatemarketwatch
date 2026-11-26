-- Slice P, 2026-11-26: shape of the printed page per fund, to design the page-structure models. Read-only.
-- A position's printed row = a visible placement of its fair-value fact. A schedule table = a table holding one.
with posn as (
    select accession, context_id, cik from int_source_row where role = 'position' and is_published
)
, plc as (
    select p.cik, p.accession, p.context_id, pl.row_index, pl.cell_index, pl.in_hidden, pl.shown_row_index
    from posn p
    join stg_filed_fact f on f.accession = p.accession and f.context_id = p.context_id and f.concept_local like 'InvestmentOwnedAtFairValue%'
    join stg_filed_fact_placement pl on pl.accession = f.accession and pl.fact_id = f.fact_id
)
, per_pos as (
    select p.cik, p.accession, p.context_id
        , count(distinct case when not plc.in_hidden then plc.row_index end) as visible_rows
        , count(distinct case when plc.in_hidden then coalesce(plc.shown_row_index, -1) end) as hidden_rows
    from posn p left join plc using (cik, accession, context_id) group by 1, 2, 3
)
, sched as (
    select distinct plc.cik, plc.accession, r.table_index
    from plc join stg_filed_document_row r on r.accession = plc.accession and r.row_index = plc.row_index
    where not plc.in_hidden
)
, w as (
    select s.cik, r.accession, r.table_index, r.row_index, r.cell_count, list_sum(r.cell_colspans) as width
        , list_max(r.cell_rowspans) as max_rowspan
    from sched s join stg_filed_document_row r on r.accession = s.accession and r.table_index = s.table_index
)
, tw as (
    select cik, accession, table_index, mode(width) as modal_width, count(*) as n_rows
        , count(*) filter (where max_rowspan > 1) as rows_with_rowspan
    from w group by 1, 2, 3
)
select '1 positions' as k, cik
    , count(*) as n
    , count(*) filter (where visible_rows = 1) as a
    , count(*) filter (where visible_rows > 1) as b
    , count(*) filter (where visible_rows = 0 and hidden_rows > 0) as c
    , count(*) filter (where visible_rows = 0 and hidden_rows = 0) as d
    , 'n positions | one visible row | several visible rows | hidden only | no placement' as legend
from per_pos group by 2
union all
select '2 schedule tables', cik, count(*), count(distinct accession), cast(median(n_rows) as bigint), max(n_rows), sum(rows_with_rowspan)
    , 'n tables | filings | median rows | max rows | rows with a rowspan'
from tw group by 2
union all
select '3 row widths', w.cik, count(*), count(*) filter (where w.width = tw.modal_width), count(*) filter (where w.width <> tw.modal_width)
    , count(distinct tw.modal_width), max(tw.modal_width)
    , 'n rows in schedule tables | width = table modal | width differs | distinct modal widths | max modal width'
from w join tw using (cik, accession, table_index) group by 2
order by 1, 2
