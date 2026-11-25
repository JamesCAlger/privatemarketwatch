-- Text spec measurement, 2026-11-25: on published rows both pipelines hold, per fund, the values of production's
-- source columns and of its class columns. Read-only.
with rows_ as (
    select h.*
    from cmp_row_set s
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where s.side = 'both' and s.basis = 'published'
)
, long as (
    unpivot (
        select cik, reference_rate_source, interest_rate_source, pik_rate_source, basis_spread_source
            , maturity_date_source, asset_category, index_classification, coupon_type, lien_position, instrument_type
        from rows_
    ) on columns(* exclude (cik)) into name field value val
)
select field, val
    , count(*) filter (where cik = '0001287750') as ares
    , count(*) filter (where cik = '0001803498') as bcred
    , count(*) filter (where cik = '0001812554') as blue_owl
    , count(*) filter (where cik = '0001837532') as apollo
    , count(*) filter (where cik = '0001838126') as hps
from long group by 1, 2 order by 1, count(*) desc
