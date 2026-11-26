-- Final slice 5 review: the corrections q_t6_repeats_fund.sql counts "in a repeat" (across_stores, position_id),
-- split by the outcome this layer gave them, plus checks on the placement (null position ids, several production
-- rows per key, report dates). Same CTEs as q_t6_repeats_fund.sql. Read-only.
with c as (
    select correction_id, cik, store, field, value, accession, context_id, identifier, row_id
    from main.stg_correction
    where kind = 'value'
)
, h as (
    select cik, report_date, accession_number, src_context_id, trim(bdc_investment_identifier) as ident, row_id
        , position_id
    from main.stg_holdings
    semi join (select distinct accession from c where accession is not null) a on a.accession = stg_holdings.accession_number
    union all
    select cik, report_date, accession_number, src_context_id, trim(bdc_investment_identifier), row_id, position_id
    from main.stg_holdings
    where row_id in (select row_id from c where row_id is not null)
)
, placed as (
    select c.*, h.report_date, h.position_id, h.ident
    from c join h on h.accession_number = c.accession and h.src_context_id = c.context_id
    where c.context_id is not null
    union all
    select c.*, h.report_date, h.position_id, h.ident
    from c join h on h.accession_number = c.accession and h.ident = trim(c.identifier)
    where c.context_id is null and c.identifier is not null
    union all
    select c.*, h.report_date, h.position_id, h.ident
    from c join h on h.row_id = c.row_id
    where c.row_id is not null
)
, keyed as (
    select distinct p.correction_id, p.cik, p.field, p.report_date, p.position_id as pos
        , case
            when trim(coalesce(p.value, '')) = '' then '<withdraw>'
            when try_cast(p.value as double) is not null and p.field in
                ('fair_value', 'cost', 'principal_amount', 'principal_amount_usd')
                then cast(round(try_cast(p.value as double), 0) as varchar)
            when try_cast(p.value as double) is not null then cast(round(try_cast(p.value as double), 6) as varchar)
            else trim(p.value)
          end as fix
    from placed p
    where p.position_id is not null
)
, fx as (
    select cik, field, pos, fix, count(distinct report_date) as quarters, count(distinct correction_id) as corr
    from keyed group by all
)
, in_repeat as (
    select distinct k.correction_id
    from keyed k join fx using (cik, field, pos, fix)
    where fx.quarters >= 2
)
, outcome as (
    select correction_id, string_agg(distinct outcome || '|' || coalesce(reason, ''), ';' order by outcome || '|' || coalesce(reason, '')) as o
    from int_correction_application group by 1
)
select 'in_repeat_by_outcome' as what, coalesce(o.o, '<no application row>') as k, count(*) as n
from in_repeat r left join outcome o using (correction_id) group by all
union all
select 'placed_null_position_id', null, count(distinct correction_id) from placed where position_id is null
union all
select 'unplaced', null, count(*) from c where correction_id not in (select correction_id from placed)
union all
select 'placed_several_positions', null, count(*) from (
    select correction_id from placed where position_id is not null group by 1 having count(distinct position_id) > 1)
union all
select 'placed_several_dates', null, count(*) from (
    select correction_id from placed group by 1 having count(distinct report_date) > 1)
union all
select 'group_same_quarter_dupes', null, count(*) from (
    select cik, field, pos, fix, report_date from keyed group by all having count(distinct correction_id) > 1)
order by 1, 2
