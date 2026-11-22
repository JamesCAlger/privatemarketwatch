-- Slice 3 Task 4 fix round 1, item 1: the equity-signature principal rows whose production class is not an equity or
-- fund class, with production's text columns (the inputs of its classifiers) and trail.
select a.cik, a.basis, a.report_date, a.accession, a.context_id, h.index_classification, h.asset_category
    , left(h.issuer_name, 45) as issuer, left(h.instrument_description, 45) as instrument
    , left(h.bdc_investment_identifier, 70) as identifier, h.corrected_fields
from cmp_amount a
join stg_holdings h on h.accession_number = a.accession and h.src_context_id = a.context_id
where a.field = 'principal_amount' and a.outcome = 'production_empty' and a.new_action = 'as_filed'
  and h.principal_amount is null and h.principal_amount_usd is null and h.principal_amount_currency is not null
  and h.index_classification not in ('COMMON_EQUITY', 'PREFERRED_EQUITY', 'PRIVATE_EQUITY_FUND', 'PRIVATE_CREDIT_FUND',
                                     'REAL_ESTATE_FUND', 'HEDGE_FUND')
order by a.report_date
limit 30
