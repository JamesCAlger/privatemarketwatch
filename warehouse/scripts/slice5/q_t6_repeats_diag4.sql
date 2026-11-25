-- Slice 5 Task 6, measure (b) check, fourth diagnostic: on the store-date variant, position-fields with two or more different fixes that each repeat, and the corrections outside the largest such group (a count that keeps only one fix per position-field would leave them out), across stores and within each store. Base: q_t6_repeats_fund.sql with the quarter taken from the correction's own report_date (null on wrapper entries, which then cannot repeat) instead of the production row's, to explain the difference from the plan's appendix. Counted two ways.
--   across_stores: a position-field is one group whatever store corrects it (a fix by the context store in one quarter
--     and by the identifier store in the next is one repeat).
--   within_store: a repeat counts only inside one store (the sum of q_t6_repeats.sql over fields and stores).
-- Measure only.
with c as (
    select correction_id, cik, store, field, value, accession, context_id, identifier, row_id, report_date as store_date
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
    select c.* exclude (store_date), c.store_date as report_date, h.position_id, h.ident
    from c join h on h.accession_number = c.accession and h.src_context_id = c.context_id
    where c.context_id is not null
    union all
    select c.* exclude (store_date), c.store_date as report_date, h.position_id, h.ident
    from c join h on h.accession_number = c.accession and h.ident = trim(c.identifier)
    where c.context_id is null and c.identifier is not null
    union all
    select c.* exclude (store_date), c.store_date as report_date, h.position_id, h.ident
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

, rep as (
    select how, cik, store_key, field, pos, fix, quarters
        , (select count(distinct g.correction_id) from grouped g where g.how = fx.how and g.measure = fx.measure
            and g.cik = fx.cik and g.store_key = fx.store_key and g.field = fx.field and g.pos = fx.pos and g.fix = fx.fix)
            as n
        , row_number() over (partition by how, measure, cik, store_key, field, pos order by quarters desc, fix) as rk
        , count(*) over (partition by how, measure, cik, store_key, field, pos) as fixes
    from fx
    where measure = 'position_id' and quarters >= 2
)

select how, cik, count(distinct (store_key, field, pos)) filter (where fixes > 1) as position_fields_two_fixes
    , coalesce(sum(n) filter (where rk > 1), 0) as corrections_outside_largest
from rep group by all order by 1, 2


