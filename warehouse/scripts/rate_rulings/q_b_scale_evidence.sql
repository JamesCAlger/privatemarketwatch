-- Rate ruling B (owner, 2026-11-23): evidence per fund, filing and field for values filed above 1 in a ratio unit
-- (pure, utr:Rate). For each such read row: the printed number of the same fact (int_field_read.printed_text, the
-- displayed inline-XBRL text), whether it equals the tag read as a percent (printed = tag), or as basis points
-- (printed = tag times 100), whether a percent sign is printed in the fact's own cell or the next cell, and the
-- inline scale attribute. Run with scripts/slice2/run_sql.py.
with r as (
    select r.cik, r.accession, r.report_date, r.field, r.context_id, r.value_filed, r.unit, r.printed_text, r.fact_id
    from int_field_read r
    where r.field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread')
      and r.status = 'read' and not r.is_nil and r.unit in ('pure', 'utr:Rate') and r.value_filed > 1
)

, p as (
    select
        r.*
        , pl.scale
        , pl.format
        , try_cast(replace(regexp_extract(r.printed_text, '[0-9][0-9,]*(\.[0-9]+)?', 0), ',', '') as double) as printed_number
        , coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 1], '') as own_cell
        , coalesce(dr.cells[coalesce(pl.cell_index, pl.shown_cell_index) + 2], '') as next_cell
    from r
    left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
    left join stg_filed_document_row dr
        on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
)

select
    cik, accession, report_date, field, unit
    , count(*) as rows_above_one
    , count(*) filter (where printed_number is null) as printed_missing
    , count(*) filter (where abs(printed_number - value_filed) <= 1e-9) as printed_equals_percent
    , count(*) filter (where abs(printed_number - value_filed * 100) <= 1e-7) as printed_equals_bps
    , count(*) filter (where printed_number is not null and abs(printed_number - value_filed) > 1e-9
                       and abs(printed_number - value_filed * 100) > 1e-7) as printed_disagrees
    , count(*) filter (where own_cell like '%\%%' escape '\' or ltrim(next_cell) like '\%%' escape '\') as percent_sign
    , string_agg(distinct coalesce(scale, 'null'), ',') as scales
    , min(value_filed) as min_filed
    , max(value_filed) as max_filed
from p
group by all
order by cik, report_date, field, unit
