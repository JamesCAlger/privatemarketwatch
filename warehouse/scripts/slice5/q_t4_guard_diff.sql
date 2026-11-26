-- Slice 5 Task 4: rows where int_rate_corrected run before differs from the chain (int_field_normalised for a filed
-- position, int_field_reread raw for a promoted one). Read-only.
with base as (
    select 'filed' as src, n.* from int_field_normalised n semi join (select accession, context_id from int_row_corrected where row_reason = 'filed') r using (accession, context_id)
    where n.field in ('interest_rate','interest_rate_cash','pik_rate','spread','maturity_date')
    union all
    select 'promoted', rr.* exclude (run, read_unit) from int_field_reread rr semi join (select accession, context_id from int_row_corrected where row_reason <> 'filed') r using (accession, context_id)
    where rr.run = 'raw' and rr.field in ('interest_rate','interest_rate_cash','pik_rate','spread','maturity_date')
)
, b as (select * exclude (run, it_changed, ct_changed, pk_changed, kind_changed, row_failure) from int_rate_corrected where run = 'before')
, bb as (select x.* exclude (src) from base x semi join (select distinct accession, context_id from b) y using (accession, context_id))
select 'before' as side, * from (select * from b except all select * from bb)
union all
select 'chain', * from (select * from bb except all select * from b)
order by context_id, field, side
