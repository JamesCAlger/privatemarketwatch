-- Slice 5 Task 4: positions of int_rate_corrected (run corrected) by fund, change flags and row failure; and the run
-- before against int_field_normalised (filed) / int_field_reread raw (promoted). Read-only.
with pos as (
    select distinct cik, accession, context_id, it_changed, ct_changed, pk_changed, kind_changed, row_failure
    from int_rate_corrected where run = 'corrected'
)
, base as (
    select n.* from int_field_normalised n semi join (select accession, context_id from int_row_corrected where row_reason = 'filed') r using (accession, context_id)
    where n.field in ('interest_rate','interest_rate_cash','pik_rate','spread','maturity_date')
    union all
    select rr.* exclude (run, read_unit) from int_field_reread rr semi join (select accession, context_id from int_row_corrected where row_reason <> 'filed') r using (accession, context_id)
    where rr.run = 'raw' and rr.field in ('interest_rate','interest_rate_cash','pik_rate','spread','maturity_date')
)
, b as (select * exclude (run, it_changed, ct_changed, pk_changed, kind_changed, row_failure) from int_rate_corrected where run = 'before')
, bb as (select x.* from base x semi join (select distinct accession, context_id from b) y using (accession, context_id))
select 'positions' as what, cik, it_changed, ct_changed, pk_changed, kind_changed, row_failure, count(*) as n
from pos group by all
union all
select 'before_not_in_base', null, null, null, null, null, null, count(*) from (select * from b except all select * from bb)
union all
select 'base_not_in_before', null, null, null, null, null, null, count(*) from (select * from bb except all select * from b)
order by 1, 2, 3, 4, 5, 6, 7
