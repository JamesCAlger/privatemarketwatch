select
    -- keys
    h.row_id,
    h.cik,
    h.report_date,
    h.accession_number,
    h.position_id,
    h.entity_id,
    h.accounting_scope_id,
    h.accounting_record_class <> 'underlying_schedule' as is_published,
    -- value
    h.fair_value,
    h.cost_reported,
    h.cost,
    c.cost_method = 'not_filed'                        as cost_is_proxy,
    h.principal_amount,
    h.principal_amount_currency,
    h.principal_amount_usd,
    h.principal_fx_status,
    h.shares_held,
    -- share of net assets
    h.pct_of_net_assets                                as pct_of_net_assets_reported,
    h.pct_of_net_assets_calculated,
    -- rate
    h.interest_rate,
    h.interest_rate_kind,
    h.interest_rate_reported,
    h.interest_rate_cash,
    h.pik_rate,
    h.basis_spread,
    h.basis_spread_kind,
    h.reference_rate_type,
    h.reference_rate_source,
    h.coupon_type,
    -- maturity
    h.maturity_date,
    h.maturity_precision,
    -- status
    h.nonaccrual_status,
    h.nonaccrual_footnote,
    h.nonaccrual_dimension,
    p.pik_current_status,
    p.pik_terms_flag,
    -- as filed
    h.issuer_name                                      as issuer_name_as_filed,
    h.instrument_description,
    h.extracted_industry                               as industry_as_filed,
    h.bdc_investment_identifier                        as source_identifier,
    h.src_context_id,
    -- class and sector, as read this quarter
    h.asset_category                                   as asset_category_as_read,
    h.lien_position                                    as lien_position_as_read,
    h.instrument_type                                  as instrument_type_as_read,
    h.index_classification,
    h.exposure_type,
    h.asset_class,
    h.gics_sector                                      as gics_sector_as_read,
    h.gics_sub_industry                                as gics_sub_industry_as_read,
    -- flag
    h.corrected_fields is not null                     as has_correction
from {{ ref('stg_holdings') }} h
left join {{ ref('stg_position_pik_status') }} p
       on p.cik = h.cik and p.report_date = h.report_date and p.position_id = h.position_id
left join {{ ref('stg_cost_donor_audit') }} c
       on c.row_id = h.row_id
