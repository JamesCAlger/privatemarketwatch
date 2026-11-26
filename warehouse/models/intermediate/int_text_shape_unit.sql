-- Decides the text shapes within each rate-candidate column (text slice R phase 1, 2026-11-26; spec section 4.1: "a
-- text shape within a column"). One row per (unit_key, shape_key_text): shape_key.
--
-- Columns: the column units of int_text_column_unit with is_rate_candidate (rule in that model's header).
-- Rows: the unit's position-row texts of int_text_cell that are not empty.
-- shape_key_text: macro text_shape_key (fix round 1): numbers become '#', white space collapsed, no space before '%' or
-- around '+', upper case. "SOFR + 5.25%" and "Sofr +5.25 %" are one shape. shape: the display form, the most frequent
-- spelling (macro text_shape) among the unit's texts of that key, ties to the smaller spelling.
-- shape_key: the first 16 hex characters of md5(unit_key | shape_key_text).
-- cell_count: texts of the shape; positions: positions on those rows (a row can hold two); first/last_report_date;
-- n_report_dates.
-- examples: the 3 most frequent distinct texts of the shape, ties to the smaller text, as a list in that order.
-- code: the shape's leading rate code (macro rate_code), the most frequent spelling; letters are kept in the shape, so
-- every text of a shape has the same code up to case.
-- n_fact_<field>: texts of the shape whose row holds a fact read as that field in this column.
with unit as (
    select unit_key, cik
    from {{ ref('int_text_column_unit') }}
    where is_rate_candidate
)

, cell as (
    select c.*
    from {{ ref('int_text_cell') }} c
    join unit u on u.unit_key = c.unit_key
    where c.text <> ''
)

, text_count as (
    select unit_key, shape_key_text, text, count(*) as n
    from cell
    group by 1, 2, 3
)

, example as (
    select unit_key, shape_key_text, list(text order by n desc, text) filter (where rk <= 3) as examples
        , count(*) as distinct_texts
    from (
        select *, row_number() over (partition by unit_key, shape_key_text order by n desc, text) as rk
        from text_count
    )
    group by 1, 2
)

, display as (
    select unit_key, shape_key_text, shape, code
    from (
        select unit_key, shape_key_text, shape, min(code) as code
            , row_number() over (partition by unit_key, shape_key_text order by count(*) desc, shape) as rk
        from cell
        group by 1, 2, 3
    )
    where rk = 1
)

, shape_sum as (
    select
        unit_key
        , shape_key_text
        , min(cik) as cik
        , count(*) as cell_count
        , sum(positions) as positions
        , min(report_date) as first_report_date
        , max(report_date) as last_report_date
        , count(distinct report_date) as n_report_dates
        , count(*) filter (where list_contains(fact_fields, 'spread')) as n_fact_spread
        , count(*) filter (where list_contains(fact_fields, 'interest_rate_tag')) as n_fact_interest_rate
        , count(*) filter (where list_contains(fact_fields, 'interest_rate_cash_tag')) as n_fact_interest_rate_cash
        , count(*) filter (where list_contains(fact_fields, 'pik_rate')) as n_fact_pik_rate
        , count(*) filter (where list_contains(fact_fields, 'maturity_date')) as n_fact_maturity_date
        , count(*) filter (where len(fact_fields) > 0) as n_fact_any
    from cell
    group by 1, 2
)

select
    left(md5(s.unit_key || '|' || s.shape_key_text), 16) as shape_key
    , s.unit_key
    , s.cik
    , s.shape_key_text
    , d.shape
    , d.code
    , s.cell_count
    , s.positions
    , s.first_report_date
    , s.last_report_date
    , s.n_report_dates
    , e.distinct_texts
    , e.examples
    , s.n_fact_spread
    , s.n_fact_interest_rate
    , s.n_fact_interest_rate_cash
    , s.n_fact_pik_rate
    , s.n_fact_maturity_date
    , s.n_fact_any
from shape_sum s
join example e on e.unit_key = s.unit_key and e.shape_key_text = s.shape_key_text
join display d on d.unit_key = s.unit_key and d.shape_key_text = s.shape_key_text
