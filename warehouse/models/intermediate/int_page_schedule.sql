-- Decides which schedule tables of a filing belong to one schedule (text slice P, fix round 1, 2026-11-26). One row
-- per schedule table of int_page_table: (accession, table_index). A schedule printed over many pages is many tables;
-- a filing can hold several schedules (the fund's own, a joint venture's, a table of unfunded commitments).
--
-- table_signature: the table's leaf signatures (int_page_column.header_signature) in column order, joined by '|'.
-- Null for a table without a header.
-- title_key: int_page_table.title_text lower-cased, with '(continued)', footnote marks of the form '(1)' and all white
-- space removed. Null when there is no title or nothing is left.
-- schedule_seq: 1 for the filing's first schedule table (in table_index order), then +1 at each table that starts a new
-- schedule. A table starts a new schedule when
--   - its table_signature is not null and differs from the table_signature of the nearest earlier table that has one;
--     or
--   - its title_key is not null and differs from the nearest earlier non-null title_key in the filing, or there is no
--     earlier title (a titled joint-venture schedule after an untitled main schedule).
--   - or a printed table that is not a schedule table lies between it and the previous schedule table (table_index gap
--     above 1). Added in fix round 1 beyond the brief: one fund's joint-venture schedule has the main schedule's header
--     and no title inside its tables; measured, no gap falls inside a schedule of published positions.
-- Otherwise a table continues the schedule before it. The title comparison looks at the nearest
-- earlier title in the filing, not only within the running schedule (simpler; a schedule started by a signature change
-- without a title keeps the earlier title as its reference).
-- Headings do not carry across schedule_seq (int_page_heading, int_position_heading).
with table_signature as (
    select accession, table_index, string_agg(header_signature, '|' order by column_index) as table_signature
    from {{ ref('int_page_column') }}
    group by 1, 2
)

, keyed as (
    select
        t.accession
        , t.table_index
        , t.cik
        , t.report_date
        , t.title_text
        , s.table_signature
        , nullif(
            regexp_replace(
                regexp_replace(replace(lower(coalesce(t.title_text, '')), '(continued)', ''), '\(\d+\)', '', 'g'),
                '\s', '', 'g'),
            '') as title_key
    from {{ ref('int_page_table') }} t
    left join table_signature s on s.accession = t.accession and s.table_index = t.table_index
)

, with_previous as (
    select
        k.*
        , last_value(k.table_signature ignore nulls) over (
            partition by k.accession order by k.table_index rows between unbounded preceding and 1 preceding)
            as previous_signature
        , last_value(k.title_key ignore nulls) over (
            partition by k.accession order by k.table_index rows between unbounded preceding and 1 preceding)
            as previous_title_key
        , row_number() over (partition by k.accession order by k.table_index) as table_seq
        , k.table_index - lag(k.table_index) over (partition by k.accession order by k.table_index) as table_gap
    from keyed k
)

, flagged as (
    select
        w.*
        , w.table_seq = 1
            or w.table_gap > 1
            or (w.table_signature is not null and w.previous_signature is not null
                and w.table_signature <> w.previous_signature)
            or (w.title_key is not null and w.title_key is distinct from w.previous_title_key)
            as starts_schedule
    from with_previous w
)

select
    accession
    , table_index
    , cik
    , report_date
    , title_text
    , title_key
    , table_signature
    , starts_schedule
    , sum(case when starts_schedule then 1 else 0 end) over (
        partition by accession order by table_index rows between unbounded preceding and current row) as schedule_seq
from flagged
