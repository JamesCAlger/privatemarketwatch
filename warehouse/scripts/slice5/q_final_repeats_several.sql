-- Final slice 5 review: the value corrections that q_t6_repeats_fund.sql places on more than one production position.
-- Read-only.
with c as (
    select correction_id, cik, store, field, value, accession, context_id, identifier, row_id
    from main.stg_correction where kind = 'value'
)
, h as (
    select cik, report_date, accession_number, src_context_id, trim(bdc_investment_identifier) as ident, row_id, position_id
    from main.stg_holdings
    semi join (select distinct accession from c where accession is not null) a on a.accession = stg_holdings.accession_number
)
, placed as (
    select c.*, h.position_id from c join h on h.accession_number = c.accession and h.src_context_id = c.context_id
    where c.context_id is not null
    union all
    select c.*, h.position_id from c join h on h.accession_number = c.accession and h.ident = trim(c.identifier)
    where c.context_id is null and c.identifier is not null
)
select cik, store, field, accession, coalesce(context_id, identifier) as key, count(distinct position_id) as positions
from placed group by all having count(distinct position_id) > 1
order by 1, 2, 3
