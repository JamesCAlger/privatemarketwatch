-- Builds the bundle an agent is given for one rate-candidate column (text slice R phase 1, 2026-11-26; spec section
-- 4.3; plan R2; dated content added in fix round 1). One row per rate-candidate column unit
-- (int_text_column_unit.is_rate_candidate), whatever its worklist state (the controller filters): unit_key.
--
-- Built from the filed layer and the page models only: no production value, nothing from stg_holdings, the comparison
-- models or the row corrections (tags are read before corrections). Numbers in cell texts are not masked. Bundles are
-- NOT anonymous: the table title, company names in example rows and filing accessions name the fund. cik is also a
-- column beside the JSON, for the controller.
-- Representative table: the unit's position rows' table with the latest report date, then the smaller accession, then
-- the smaller table_index. header_text, group_header_text and header_row all come from it (one filing, so footnote
-- marks agree).
-- bundle_json, keys in this order:
--   unit_key            the column unit's key.
--   header_text         the leaf's own header text in the representative table; group_header_text: the upper line
--                       over a two-line leaf, else null.
--   first_report_date, last_report_date   of the column unit (int_text_column_unit).
--   header_row          every leaf column of the representative table, left to right: {header, group_header}.
--   table_title         the most frequent non-null title_text (int_page_schedule) among the tables holding the unit's
--                       position rows, ties to the smaller text; null when none.
--   top_cells           the 12 most frequent distinct non-empty texts of the column on position rows: {text, rows}.
--   shapes              the column's shapes (int_text_shape_unit), most frequent first, ties by shape key, at most 40:
--                       {shape, rows, code, first_report_date, last_report_date, legs}. legs: the shape-legs evidence
--                       (int_text_check_shape_legs) for a parts-stating shape, the pairs where a printed number equals a
--                       tagged value at least once: {number, field, compared, equal, equal_bps}, by number then most
--                       equal; null for other shapes. shapes_total: how many shapes the column has.
--   example_rows        for each of the 3 most frequent shapes, one full printed row: the row of that shape whose text
--                       equals the shape's most frequent text, latest report date first, then smaller accession, then
--                       smaller row_index. {shape, report_date, cells: [{header, group_header, text}]} over every leaf
--                       column of that row's table ('' where the column is empty on the row).
--   tag_profile         {field, rows}: position rows of the column holding a fact read as the field, most first.
--   legend              the filer's legend entries (int_text_check_legend) for the codes printed in the column, one per
--                       (code, name, abbreviation): {code, name, abbreviation, filings: [{report_date, accession}]},
--                       by code, name, abbreviation; filings by report date. A rule's dates can be read from it.
--   caps                {top_cells: 12, shapes: 40, example_rows: 3, text_chars: 200}.
-- Not in the bundle (fix round 1, measured): the printed note a header's mark ("Reference Rate and Spread(2)") refers
-- to. The filed layer keeps table rows only, and no table row of any filing starts with such a mark followed by text
-- (0 of 348 header marks found; scripts/text/q_r7_note_rows.sql), so it cannot be found by a general rule.
-- Every text is cut to 200 characters. bundle_chars: length of bundle_json. Same filings, same bundle: every list has a
-- total order.
{% set text_chars = 200 %}
with unit as (
    select unit_key, cik, header_signature, first_report_date, last_report_date
    from {{ ref('int_text_column_unit') }}
    where is_rate_candidate
)

, cell as (
    select c.*
    from {{ ref('int_text_cell') }} c
    join unit u on u.unit_key = c.unit_key
)

, representative as (
    select unit_key, accession, table_index, col_start
    from (
        select unit_key, accession, table_index, col_start
            , row_number() over (partition by unit_key order by report_date desc, accession, table_index) as rk
        from cell
    )
    where rk = 1
)

, leaf as (
    select accession, table_index, col_start, column_index
        , left(case when sub_header_text is not null then sub_header_text else header_text end, {{ text_chars }}) as header
        , left(case when sub_header_text is not null then header_text end, {{ text_chars }}) as group_header
    from {{ ref('int_page_column') }}
)

, header_row as (
    select r.unit_key, list({'header': l.header, 'group_header': l.group_header} order by l.column_index) as header_row
        , max(case when l.col_start = r.col_start then l.header end) as header_text
        , max(case when l.col_start = r.col_start then l.group_header end) as group_header_text
    from representative r
    join leaf l on l.accession = r.accession and l.table_index = r.table_index
    group by 1
)

, title as (
    select unit_key, title_text
    from (
        select t.unit_key, s.title_text
            , row_number() over (partition by t.unit_key order by count(*) desc, s.title_text) as rk
        from (select distinct unit_key, accession, table_index from cell) t
        join {{ ref('int_page_schedule') }} s on s.accession = t.accession and s.table_index = t.table_index
        where s.title_text is not null
        group by t.unit_key, s.title_text
    )
    where rk = 1
)

, top_cell as (
    select unit_key, list({'text': left(text, {{ text_chars }}), 'rows': n} order by n desc, text) as top_cells
    from (
        select unit_key, text, count(*) as n
            , row_number() over (partition by unit_key order by count(*) desc, text) as rk
        from cell
        where text <> ''
        group by 1, 2
    )
    where rk <= 12
    group by 1
)

, shape_ranked as (
    select shape_key, unit_key, shape, shape_key_text, cell_count, code, examples, first_report_date, last_report_date
        , row_number() over (partition by unit_key order by cell_count desc, shape_key_text) as rk
        , count(*) over (partition by unit_key) as shapes_total
    from {{ ref('int_text_shape_unit') }}
)

, legs as (
    select shape_key
        , list({'number': number_label, 'field': tag_field, 'compared': compared, 'equal': equal, 'equal_bps': equal_bps}
               order by number_label, equal desc, equal_bps desc, tag_field) as legs
    from {{ ref('int_text_check_shape_legs') }}
    where equal > 0 or equal_bps > 0
    group by 1
)

, shape_list as (
    select s.unit_key, min(s.shapes_total) as shapes_total
        , list({'shape': left(s.shape, {{ text_chars }}), 'rows': s.cell_count, 'code': s.code,
                'first_report_date': cast(s.first_report_date as varchar),
                'last_report_date': cast(s.last_report_date as varchar), 'legs': g.legs} order by s.rk) as shapes
    from shape_ranked s
    left join legs g on g.shape_key = s.shape_key
    where s.rk <= 40
    group by 1
)

, example_pick as (
    select unit_key, shape, shape_rank, accession, row_index, table_index, report_date
    from (
        select s.unit_key, s.shape, s.rk as shape_rank, c.accession, c.row_index, c.table_index, c.report_date
            , row_number() over (partition by s.unit_key, s.shape_key_text
                                 order by (c.text = s.examples[1]) desc, c.report_date desc, c.accession, c.row_index)
                as rk
        from shape_ranked s
        join cell c on c.unit_key = s.unit_key and c.shape_key_text = s.shape_key_text
        where s.rk <= 3
    )
    where rk = 1
)

, example_cells as (
    select e.unit_key, e.shape, e.shape_rank, e.report_date
        , list({'header': l.header, 'group_header': l.group_header, 'text': left(coalesce(t.text, ''), {{ text_chars }})}
               order by l.column_index) as cells
    from example_pick e
    join leaf l on l.accession = e.accession and l.table_index = e.table_index
    left join {{ ref('int_text_cell') }} t
        on t.accession = e.accession and t.row_index = e.row_index and t.col_start = l.col_start
    group by 1, 2, 3, 4
)

, example_rows as (
    select unit_key
        , list({'shape': left(shape, {{ text_chars }}), 'report_date': cast(report_date as varchar), 'cells': cells}
               order by shape_rank) as example_rows
    from example_cells
    group by 1
)

, tag_profile as (
    select unit_key, list({'field': field, 'rows': n} order by n desc, field) as tag_profile
    from (
        select unit_key, field, count(*) as n
        from (select unit_key, unnest(fact_fields) as field from cell where text <> '')
        group by 1, 2
    )
    group by 1
)

, legend_entry as (
    select cik, code_key, code, name, abbreviation
        , list({'report_date': cast(report_date as varchar), 'accession': accession} order by report_date, accession)
            as filings
    from {{ ref('int_text_check_legend') }}
    group by 1, 2, 3, 4, 5
)

, legend as (
    select k.unit_key
        , list({'code': l.code, 'name': left(l.name, {{ text_chars }}), 'abbreviation': l.abbreviation,
                'filings': l.filings} order by l.code, l.name, l.abbreviation) as legend
    from (select distinct unit_key, cik, upper(replace(code, ' ', '')) as code_key from cell where code is not null) k
    join legend_entry l on l.cik = k.cik and l.code_key = k.code_key
    group by 1
)

, bundle as (
    select
        u.unit_key
        , u.cik
        , w.state as worklist_state
        , to_json({
            'unit_key': u.unit_key,
            'header_text': h.header_text,
            'group_header_text': h.group_header_text,
            'first_report_date': cast(u.first_report_date as varchar),
            'last_report_date': cast(u.last_report_date as varchar),
            'header_row': h.header_row,
            'table_title': left(t.title_text, {{ text_chars }}),
            'top_cells': tc.top_cells,
            'shapes': sl.shapes,
            'shapes_total': sl.shapes_total,
            'example_rows': er.example_rows,
            'tag_profile': tp.tag_profile,
            'legend': lg.legend,
            'caps': {'top_cells': 12, 'shapes': 40, 'example_rows': 3, 'text_chars': {{ text_chars }}}
        })::varchar as bundle_json
    from unit u
    left join {{ ref('int_text_worklist') }} w on w.work_key = u.unit_key
    left join header_row h on h.unit_key = u.unit_key
    left join title t on t.unit_key = u.unit_key
    left join top_cell tc on tc.unit_key = u.unit_key
    left join shape_list sl on sl.unit_key = u.unit_key
    left join example_rows er on er.unit_key = u.unit_key
    left join tag_profile tp on tp.unit_key = u.unit_key
    left join legend lg on lg.unit_key = u.unit_key
)

select unit_key, cik, worklist_state, bundle_json, length(bundle_json) as bundle_chars
from bundle
