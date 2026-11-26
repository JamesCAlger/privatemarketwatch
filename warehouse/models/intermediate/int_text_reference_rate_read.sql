-- Applies the reference-rate rules the wrapper copies already hold to the printed rows (text slice R phase 1,
-- 2026-11-26; decision 19-T7: measure the existing rules before any agent writes one). One row per position with a
-- printed row (int_page_position placement_status one_row, published or not): (accession, context_id).
--
-- Rules (stg_reading_rule, target reference_rate, inside their dates: valid_from <= report_date <= valid_to, a null end
-- open):
--   read_printed_column   parameter = a header text. The column it names in the position's table: a leaf of
--                         int_page_column whose header_signature, or the page_signature of whose sub_header_text, equals
--                         the page_signature of the parameter ("Ref. Rate" names the leaf "Interest" / "Ref. Rate").
--                         When several leaves of the table are named, the leftmost is taken (n_columns_named says how
--                         many).
--   map_code              parameter 'CODE=NAME': a code printed in the cell means NAME. Compared upper case.
--   label_is_unspecified  parameter = words that name no particular rate ("Base Rate"). Compared upper case.
-- cell_text: int_text_cell.text of that column on the position's row (the column's cells joined, footnote marks out).
-- code: macro rate_code of cell_text (the leading letters: 'SOFR' of "SOFR (Q)", 'S' of "S+525, 0.50% Floor").
-- reference_rate: the NAME of the map_code rule whose CODE equals the code; 'unspecified' when a label_is_unspecified
-- rule matches; else null. map_rule_id: the rule that gave it. column_rule_id: the read_printed_column rule.
-- No other vocabulary is used: a code no rule of the fund lists stays unmapped, even 'SOFR'. Production's global
-- fallbacks (SOFR/LIBOR words, S/L/E codes) are not copied.
-- status, the first that applies:
--   no_rule           the fund has no read_printed_column rule for reference_rate in force at the report date.
--   column_not_found  no leaf of the position's table is named by such a rule (also a table without a header).
--   cell_empty        the named column holds no text on the row.
--   no_code           the text does not start with a code (macro rate_code null: "N/A", "10.00%", "Estimated Yield:").
--   read              a map_code or label_is_unspecified rule matches the code.
--   code_not_mapped   a code was found and no rule maps it.
-- If two map_code rules of the fund matched one code at one date the smaller rule_id would be taken; none do
-- (n_map_rules says how many matched).
with position as (
    select accession, context_id, cik, report_date, is_published, table_index, row_index
    from {{ ref('int_page_position') }}
    where placement_status = 'one_row'
)

, rule as (
    select rule_id, cik, action, parameter, valid_from, valid_to
    from {{ ref('stg_reading_rule') }}
    where target = 'reference_rate' and action in ('read_printed_column', 'map_code', 'label_is_unspecified')
)

, column_rule as (
    select p.accession, p.context_id, r.rule_id, {{ page_signature('r.parameter') }} as rule_signature
    from position p
    join rule r
        on r.cik = p.cik and r.action = 'read_printed_column'
        and (r.valid_from is null or r.valid_from <= p.report_date) and (r.valid_to is null or p.report_date <= r.valid_to)
)

, named as (
    select cr.accession, cr.context_id, cr.rule_id, c.col_start, c.column_index
    from column_rule cr
    join position p on p.accession = cr.accession and p.context_id = cr.context_id
    join {{ ref('int_page_column') }} c
        on c.accession = p.accession and c.table_index = p.table_index
        and (c.header_signature = cr.rule_signature
             or (c.sub_header_text is not null and {{ page_signature('c.sub_header_text') }} = cr.rule_signature))
)

, picked as (
    select accession, context_id, rule_id, col_start
        , count(*) over (partition by accession, context_id) as n_columns_named
        , row_number() over (partition by accession, context_id order by column_index, rule_id) as rk
    from named
)

, celled as (
    select
        p.*
        , exists (select 1 from column_rule cr where cr.accession = p.accession and cr.context_id = p.context_id)
            as has_rule
        , k.rule_id as column_rule_id
        , k.col_start
        , coalesce(k.n_columns_named, 0) as n_columns_named
        , t.unit_key
        , t.text as cell_text
        , {{ rate_code('t.text') }} as code
    from position p
    left join picked k on k.accession = p.accession and k.context_id = p.context_id and k.rk = 1
    left join {{ ref('int_text_cell') }} t
        on t.accession = p.accession and t.row_index = p.row_index and t.col_start = k.col_start
)

, vocabulary as (
    select rule_id, cik, action, valid_from, valid_to
        , upper(trim(case when action = 'map_code' then split_part(parameter, '=', 1) else parameter end)) as code_key
        , case when action = 'map_code' then trim(split_part(parameter, '=', 2)) else 'unspecified' end as name
    from rule
    where action in ('map_code', 'label_is_unspecified')
)

, mapped as (
    select c.accession, c.context_id, min(v.rule_id) as map_rule_id, count(*) as n_map_rules
        , min_by(v.name, v.rule_id) as reference_rate
    from celled c
    join vocabulary v
        on v.cik = c.cik and v.code_key = upper(trim(c.code))
        and (v.valid_from is null or v.valid_from <= c.report_date) and (v.valid_to is null or c.report_date <= v.valid_to)
    group by 1, 2
)

select
    c.accession
    , c.context_id
    , c.cik
    , c.report_date
    , c.is_published
    , c.table_index
    , c.row_index
    , c.col_start
    , c.unit_key
    , c.column_rule_id
    , c.n_columns_named
    , c.cell_text
    , c.code
    , m.reference_rate
    , m.map_rule_id
    , coalesce(m.n_map_rules, 0) as n_map_rules
    , case
        when not c.has_rule then 'no_rule'
        when c.column_rule_id is null then 'column_not_found'
        when coalesce(c.cell_text, '') = '' then 'cell_empty'
        when c.code is null then 'no_code'
        when m.map_rule_id is not null then 'read'
        else 'code_not_mapped'
    end as status
from celled c
left join mapped m on m.accession = c.accession and m.context_id = c.context_id
