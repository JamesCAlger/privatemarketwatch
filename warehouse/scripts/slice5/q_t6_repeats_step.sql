-- Slice 5 Task 6, consolidation measure (b), by step: the value corrections inside a same-fix repeat (position id, across
-- stores; definitions of q_t6_repeats_fund.sql) split by the step seed correction_field gives their field (filed,
-- converted, reading_input, companion: a field this layer holds; deferred: a field it does not hold yet).
--   across_stores: a position-field is one group whatever store corrects it (a fix by the context store in one quarter
--     and by the identifier store in the next is one repeat).
--   within_store: a repeat counts only inside one store (the sum of q_t6_repeats.sql over fields and stores).
-- Measure only.
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
    select distinct
        p.correction_id, p.cik, p.store, p.field, p.report_date
        , m.measure
        , case m.measure when 'position_id' then p.position_id else p.ident end as pos
        , case
            when trim(coalesce(p.value, '')) = '' then '<withdraw>'
            when try_cast(p.value as double) is not null and p.field in
                ('fair_value', 'cost', 'principal_amount', 'principal_amount_usd')
                then cast(round(try_cast(p.value as double), 0) as varchar)
            when try_cast(p.value as double) is not null then cast(round(try_cast(p.value as double), 6) as varchar)
            else trim(p.value)
          end as fix
    from placed p
    cross join (values ('position_id'), ('identifier')) m(measure)
)

, grouped as (
    -- g.store_key is '' for across_stores, the store for within_store
    select k.*, g.how, case g.how when 'within_store' then k.store else '' end as store_key
    from keyed k
    cross join (values ('across_stores'), ('within_store')) g(how)
    where k.pos is not null
)

, pf as (
    select how, measure, cik, store_key, field, pos, count(distinct report_date) as quarters
    from grouped group by all
)

, fx as (
    select how, measure, cik, store_key, field, pos, fix, count(distinct report_date) as quarters
    from grouped group by all
)

, in_repeat as (
    select distinct g.how, g.measure, g.cik, g.correction_id
    from grouped g
    join fx on fx.how = g.how and fx.measure = g.measure and fx.cik = g.cik and fx.store_key = g.store_key
        and fx.field = g.field and fx.pos = g.pos and fx.fix = g.fix and fx.quarters >= 2
)

, step as (
    select distinct correction_id, step from main.int_correction_target
)

select c.cik, coalesce(s.step, 'none') as step, count(*) as corrections
    , count(*) filter (where r.correction_id is not null) as corrections_in_repeat
from c
left join step s on s.correction_id = c.correction_id
left join (select correction_id from in_repeat where how = 'across_stores' and measure = 'position_id') r
    on r.correction_id = c.correction_id
group by all
order by 1, 2
