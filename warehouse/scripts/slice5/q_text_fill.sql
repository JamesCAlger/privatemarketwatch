-- Text spec measurement, 2026-11-25: production's text-derived fields on the rows both pipelines publish (cmp_row_set
-- side both, published), per fund: rows, filled, distinct values, rows where production's corrected_fields names
-- the field. Read-only.
with rows_ as (
    select h.*
    from cmp_row_set s
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where s.side = 'both' and s.basis = 'published'
)
, long as (
    unpivot (
        select cik, corrected_fields
            , issuer_name, instrument_description, instrument_type, asset_category, asset_class, exposure_type
            , index_classification, lien_position, coupon_type, reference_rate_type, reference_rate_source
            , extracted_industry, gics_sector, gics_sub_industry, nonaccrual_status
            , interest_rate_source, pik_rate_source, basis_spread_source, maturity_date_source
        from rows_
    ) on columns(* exclude (cik, corrected_fields)) into name field value val
)
, tot as (select cik, count(*) as n_rows from rows_ group by 1)
select l.field, l.cik, any_value(t.n_rows) as n_rows, count(*) as filled, round(100.0 * count(*) / any_value(t.n_rows), 1) as pct
    , count(distinct l.val) as distinct_values
    , count(*) filter (where regexp_matches(coalesce(l.corrected_fields, ''), '(^|;)' || l.field || '([;:=]|$)')) as corrected
from long l join tot t using (cik)
group by 1, 2 order by 1, 2
