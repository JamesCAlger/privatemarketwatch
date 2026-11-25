-- Slice 5 Task 4: int_rate_corrected runs the rate chain again on the positions a rate correction acts on. Its run
-- before (no correction applied) must give exactly the rate rows of int_field_normalised on a filed position and of
-- int_field_reread run raw on a promoted one, or the second run is not the same chain. Compares every column, both ways.
with chain as (
    select n.*
    from {{ ref('int_field_normalised') }} n
    semi join (select accession, context_id from {{ ref('int_row_corrected') }} where row_reason = 'filed') r
        on r.accession = n.accession and r.context_id = n.context_id
    where n.field in {{ rate_output_fields() }}
    union all
    select rr.* exclude (run, read_unit)
    from {{ ref('int_field_reread') }} rr
    semi join (select accession, context_id from {{ ref('int_row_corrected') }} where row_reason <> 'filed') r
        on r.accession = rr.accession and r.context_id = rr.context_id
    where rr.run = 'raw' and rr.field in {{ rate_output_fields() }}
)

, before as (
    select * exclude (run, it_changed, ct_changed, pk_changed, kind_changed, row_failure)
    from {{ ref('int_rate_corrected') }}
    where run = 'before'
)

, chain_here as (
    select c.* from chain c
    semi join (select distinct accession, context_id from before) b on b.accession = c.accession and b.context_id = c.context_id
)

select 'only in int_rate_corrected' as side, * from (select * from before except all select * from chain_here)
union all
select 'only in the chain', * from (select * from chain_here except all select * from before)
