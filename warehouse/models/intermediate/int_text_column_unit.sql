-- Decides the column units of each fund across its filings, and which of them are rate-candidate columns (text slice R
-- phase 1, 2026-11-26; spec section 4.1). One row per (cik, table_signature, header_signature): unit_key.
--
-- Units: every (accession, table_signature, header_signature) of int_page_column_filing, grouped across the fund's
-- filings. The same header in two kinds of table (the fund's schedule, a joint venture's, unfunded commitments) is two
-- units, as in int_page_column_filing. The unheaded '#footnote_marks' column is a unit with no header text.
-- header_text: the leaf's own text (int_page_column sub_header_text for a leaf of a two-line header, else header_text);
-- group_header_text: the upper line's text over a two-line leaf, else null. Each is the most frequent text among the
-- unit's leaf columns, ties to the smaller text. sub_header_signature: macro page_signature of that sub-header (null for
-- a one-line leaf).
-- first/last_report_date, n_filings: the filings holding the unit. n_tables: tables summed over filings.
-- data_cells, n_<shape>, share_<shape>: summed from int_page_column_filing (every data row, not only positions; footnote
-- marks left out of the shares).
-- position_cells: int_text_cell rows of the unit (position rows where the column holds a non-footnote cell).
-- rate_text_cells: those whose text is rate text (macro is_rate_text); rate_text_share = rate_text_cells / position_cells.
-- Tag profile: n_tag_<field>: position rows of the unit where a fact read as that field is placed in the column
-- (int_text_cell.fact_fields), for the four rate fields (spread, interest_rate_tag, interest_rate_cash_tag, pik_rate)
-- and maturity_date; tag_profile: every field 'field=n' joined by '; ', most frequent first, then by field.
-- read_rule_ids: the fund's read_printed_column rules (stg_reading_rule, any target) whose parameter's page_signature
-- equals the unit's header_signature or its sub_header_signature, joined by ','; null when none.
-- is_rate_candidate, the rule (any one is enough):
--   (a) has_rate_tags     a fact read as spread, interest_rate_tag, interest_rate_cash_tag or pik_rate is placed in the
--                         column on at least one position row; or
--   (b) read_rule_ids     an existing read_printed_column rule names the column; or
--   (c) rate_text_share >= var text_rate_candidate_share (0.20): at least 20% of the column's non-empty position-row
--                         texts look like rate text (a number followed by '%', or letters followed by '+').
-- A share-of-net-assets column passes (c) ("1.25%"); the rule is wide on purpose: the agent says "not a rate column".
with filing_unit as (
    select cik, table_signature, header_signature, accession, report_date, n_tables, data_cells, n_number, n_percent
        , n_date, n_text, n_empty_marker, n_footnote_mark
    from {{ ref('int_page_column_filing') }}
)

, leaf_text as (
    select s.cik, s.table_signature, c.header_signature
        , case when c.sub_header_text is not null then c.sub_header_text else c.header_text end as leaf_text
        , case when c.sub_header_text is not null then c.header_text end as group_text
        , case when c.sub_header_text is not null then {{ page_signature('c.sub_header_text') }} end as sub_signature
    from {{ ref('int_page_column') }} c
    join {{ ref('int_page_schedule') }} s on s.accession = c.accession and s.table_index = c.table_index
    where s.table_signature is not null
)

, leaf_mode as (
    select cik, table_signature, header_signature, leaf_text, group_text, sub_signature
    from (
        select cik, table_signature, header_signature, leaf_text, group_text, sub_signature
            , row_number() over (partition by cik, table_signature, header_signature
                                 order by count(*) desc, leaf_text, group_text nulls first) as rk
        from leaf_text
        group by 1, 2, 3, 4, 5, 6
    )
    where rk = 1
)

, filing_sum as (
    select cik, table_signature, header_signature
        , min(report_date) as first_report_date, max(report_date) as last_report_date
        , count(distinct accession) as n_filings, sum(n_tables) as n_tables
        , sum(data_cells) as data_cells, sum(n_number) as n_number, sum(n_percent) as n_percent, sum(n_date) as n_date
        , sum(n_text) as n_text, sum(n_empty_marker) as n_empty_marker, sum(n_footnote_mark) as n_footnote_mark
    from filing_unit
    group by 1, 2, 3
)

, position_sum as (
    select cik, table_signature, header_signature
        , count(*) as position_cells
        , count(*) filter (where rate_text) as rate_text_cells
        , count(*) filter (where list_contains(fact_fields, 'spread')) as n_tag_spread
        , count(*) filter (where list_contains(fact_fields, 'interest_rate_tag')) as n_tag_interest_rate
        , count(*) filter (where list_contains(fact_fields, 'interest_rate_cash_tag')) as n_tag_interest_rate_cash
        , count(*) filter (where list_contains(fact_fields, 'pik_rate')) as n_tag_pik_rate
        , count(*) filter (where list_contains(fact_fields, 'maturity_date')) as n_tag_maturity_date
    from {{ ref('int_text_cell') }}
    where text <> ''
    group by 1, 2, 3
)

, field_count as (
    select cik, table_signature, header_signature, field, count(*) as n
    from (select cik, table_signature, header_signature, unnest(fact_fields) as field from {{ ref('int_text_cell') }})
    group by all
)

, tag_profile as (
    select cik, table_signature, header_signature, string_agg(field || '=' || n, '; ' order by n desc, field) as tag_profile
    from field_count
    group by 1, 2, 3
)

, read_rule as (
    select rule_id, cik, {{ page_signature('parameter') }} as rule_signature
    from {{ ref('stg_reading_rule') }}
    where action = 'read_printed_column'
)

, unit as (
    select
        left(md5(f.cik || '|' || f.table_signature || '|' || f.header_signature), 16) as unit_key
        , f.cik
        , f.table_signature
        , f.header_signature
        , l.leaf_text as header_text
        , l.group_text as group_header_text
        , l.sub_signature as sub_header_signature
        , f.first_report_date
        , f.last_report_date
        , f.n_filings
        , f.n_tables
        , f.data_cells
        , f.n_number
        , f.n_percent
        , f.n_date
        , f.n_text
        , f.n_empty_marker
        , f.n_footnote_mark
        , f.n_number / nullif(f.data_cells - f.n_footnote_mark, 0) as share_number
        , f.n_percent / nullif(f.data_cells - f.n_footnote_mark, 0) as share_percent
        , f.n_date / nullif(f.data_cells - f.n_footnote_mark, 0) as share_date
        , f.n_text / nullif(f.data_cells - f.n_footnote_mark, 0) as share_text
        , f.n_empty_marker / nullif(f.data_cells - f.n_footnote_mark, 0) as share_empty_marker
        , coalesce(p.position_cells, 0) as position_cells
        , coalesce(p.rate_text_cells, 0) as rate_text_cells
        , p.rate_text_cells / nullif(p.position_cells, 0) as rate_text_share
        , coalesce(p.n_tag_spread, 0) as n_tag_spread
        , coalesce(p.n_tag_interest_rate, 0) as n_tag_interest_rate
        , coalesce(p.n_tag_interest_rate_cash, 0) as n_tag_interest_rate_cash
        , coalesce(p.n_tag_pik_rate, 0) as n_tag_pik_rate
        , coalesce(p.n_tag_maturity_date, 0) as n_tag_maturity_date
        , t.tag_profile
    from filing_sum f
    left join leaf_mode l
        on l.cik = f.cik and l.table_signature = f.table_signature and l.header_signature = f.header_signature
    left join position_sum p
        on p.cik = f.cik and p.table_signature = f.table_signature and p.header_signature = f.header_signature
    left join tag_profile t
        on t.cik = f.cik and t.table_signature = f.table_signature and t.header_signature = f.header_signature
)

, unit_rule as (
    select u.unit_key, string_agg(r.rule_id, ',' order by r.rule_id) as read_rule_ids
    from unit u
    join read_rule r
        on r.cik = u.cik and (r.rule_signature = u.header_signature or r.rule_signature = u.sub_header_signature)
    group by 1
)

select
    u.*
    , ur.read_rule_ids
    , (u.n_tag_spread + u.n_tag_interest_rate + u.n_tag_interest_rate_cash + u.n_tag_pik_rate) > 0 as has_rate_tags
    , coalesce(u.rate_text_share >= {{ var('text_rate_candidate_share') }}, false) as has_rate_text
    , (u.n_tag_spread + u.n_tag_interest_rate + u.n_tag_interest_rate_cash + u.n_tag_pik_rate) > 0
        or ur.read_rule_ids is not null
        or coalesce(u.rate_text_share >= {{ var('text_rate_candidate_share') }}, false) as is_rate_candidate
from unit u
left join unit_rule ur on ur.unit_key = u.unit_key
