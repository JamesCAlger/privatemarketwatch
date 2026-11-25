-- Slice 5 Task 5, BCRED trace: the 14 rows with principal_empty_class_not_equity and production's columns on them.
-- Read-only.
select a.report_date, a.accession, a.context_id, a.value_new as principal_new, h.bdc_investment_identifier,
    h.index_classification, h.asset_category, h.principal_amount, h.principal_amount_currency, h.principal_amount_usd,
    h.shares_held, h.corrected_fields, h.src_transforms, h.src_filled_fields
from cmp_amount a
join stg_holdings h on h.accession_number = a.accession and h.src_context_id = a.context_id
where a.cause_detail = 'principal_empty_class_not_equity' and a.field = 'principal_amount'
order by 1, 3
