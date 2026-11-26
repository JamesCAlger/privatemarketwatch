-- Slice 5 Task 6, consolidation measure (b), per fund and store: q_t6_repeats.sql summed over fields (a position-field
-- is one position and one field, so the per-field counts add). Measure only. Definitions as in q_t6_repeats.sql:
-- Corrections: stg_correction kind value (row stores, wrapper values, the B2 leaf). Target row: production's holdings
-- row the correction keys (stg_holdings; context key -> accession and src_context_id; identifier key -> accession and
-- trimmed identifier; row id -> row_id), as production applies it. Its report_date is the quarter (wrapper entries
-- carry none of their own).
-- Same position, measure "position_id": production's position_id of the target row (one build; not stable across
--   builds). Measure "identifier": the same fund and the target row's identifier text, trimmed.
-- Same fix: same field and the same value: empty means withdraw; a number compared rounded (dollar fields to the
--   dollar, every other number to 6 decimals; the tolerances of cmp_amount / cmp_rate are 1 dollar and below 1e-6);
--   text trimmed. The value_unit is not part of the fix.
-- Within one store: a repeat is counted inside its store here (q_t6_repeats_fund.sql also counts across stores).
-- Columns: position_fields = distinct (position, field) the store corrects; in_2q = those corrected in 2+ quarters;
-- same_fix_2q = those with one fix value in 2+ quarters; corrections_in_repeat = distinct corrections inside such a
-- same-fix group; unplaced = corrections with no production row.
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

, pf as (
    select measure, cik, store, field, pos, count(distinct report_date) as quarters
    from keyed where pos is not null group by all
)

, fx as (
    select measure, cik, store, field, pos, fix, count(distinct report_date) as quarters
    from keyed where pos is not null group by all
)

, in_repeat as (
    select distinct k.measure, k.cik, k.store, k.field, k.correction_id
    from keyed k
    join fx on fx.measure = k.measure and fx.cik = k.cik and fx.store = k.store and fx.field = k.field
        and fx.pos = k.pos and fx.fix = k.fix and fx.quarters >= 2
)

, unplaced as (
    select cik, store, field, count(*) as unplaced
    from c where correction_id not in (select correction_id from placed)
    group by all
)

, corrections as (
    select cik, store, field, count(*) as corrections from c group by all
)

, per_field as (
    select
        m.measure
        , co.cik
        , co.store
        , co.field
        , co.corrections
        , coalesce(u.unplaced, 0) as unplaced
        , (select count(*) from pf where pf.measure = m.measure and pf.cik = co.cik and pf.store = co.store
            and pf.field = co.field) as position_fields
        , (select count(*) from pf where pf.measure = m.measure and pf.cik = co.cik and pf.store = co.store
            and pf.field = co.field and pf.quarters >= 2) as in_2q
        , (select count(distinct fx.pos) from fx where fx.measure = m.measure and fx.cik = co.cik and fx.store = co.store
            and fx.field = co.field and fx.quarters >= 2) as same_fix_2q
        , (select count(*) from in_repeat r where r.measure = m.measure and r.cik = co.cik and r.store = co.store
            and r.field = co.field) as corrections_in_repeat
    from corrections co
    cross join (values ('position_id'), ('identifier')) m(measure)
    left join unplaced u on u.cik = co.cik and u.store = co.store and u.field = co.field
)

select measure, cik, store, count(*) as fields, sum(corrections) as corrections, sum(unplaced) as unplaced
    , sum(position_fields) as position_fields, sum(in_2q) as in_2q, sum(same_fix_2q) as same_fix_2q
    , sum(corrections_in_repeat) as corrections_in_repeat
from per_field
group by all
order by measure, cik, store
