-- Slice P, 2026-11-26 (fix round 1: every row role, as macro page_field_fact): placed facts read as a field that fall
-- under more than one header signature in one table, with the signatures, counts and an example cell; then the facts
-- given no column, by fund, rule and field. Read-only.
with read_fact as (
    select accession, fact_id, min(field) as field from int_field_read
    where status = 'read' and fact_id is not null group by 1, 2
)
, mapped_fact as (
    select f.accession, f.fact_id, min(m.read_field) as field
    from stg_filed_fact f
    join concept_map m on m.concept_local = f.concept_local and m.read_field is not null
        and f.concept_namespace like replace(m.namespace_pattern, '*', '%')
    group by 1, 2
)
, ff as (
    select coalesce(r.accession, m.accession) as accession, coalesce(r.fact_id, m.fact_id) as fact_id
        , coalesce(r.field, m.field) as field, r.fact_id is not null as is_position_fact
    from read_fact r full join mapped_fact m on m.accession = r.accession and m.fact_id = r.fact_id
)
, f as (
    select t.cik, ff.accession, cc.table_index, ff.field, ff.is_position_fact, cc.header_signature, cc.column_rule, cc.text
    from ff
    join stg_filed_fact_placement pl on pl.accession = ff.accession and pl.fact_id = ff.fact_id
    join int_page_cell_column cc on cc.accession = pl.accession
        and cc.row_index = coalesce(pl.row_index, pl.shown_row_index)
        and cc.cell_index = coalesce(pl.cell_index, pl.shown_cell_index)
    join int_page_table t on t.accession = cc.accession and t.table_index = cc.table_index
)
, g as (
    select cik, accession, table_index, field, header_signature, count(*) as n, count(*) filter (where not is_position_fact) as n_other_rows
        , min(text) as example
    from f where header_signature is not null group by all
)
select 'split' as k, cik, accession || ' t' || table_index as at, field
    , string_agg(header_signature || '=' || n || ' (other rows ' || n_other_rows || ') [' || example || ']', ' ; ') as detail
from g
where (accession, table_index, field) in (
    select (accession, table_index, field) from g group by accession, table_index, field having count(*) > 1)
group by all
union all
select 'no_column', cik, column_rule, field, count(*)::varchar || ' facts in ' || count(distinct accession || table_index) || ' tables'
from f where column_rule like 'none_%' group by all
order by 1, 2, 3, 4
