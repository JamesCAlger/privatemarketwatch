-- Slice 4 Task 4: cmp_rate rows whose cause is not_yet_explained, with the row's other rate pairs and production's
-- provenance columns.
select r.cik, r.report_date, r.accession, r.context_id, r.field, r.outcome, r.value_new, r.value_production,
    r.value_production_reported, r.text_new, r.text_production, r.new_action, r.new_status, r.new_reason,
    r.production_source, h.src_transforms, h.corrected_fields, h.asset_category, h.interest_rate, h.pik_rate,
    h.basis_spread, h.interest_rate_kind, h.bdc_investment_identifier
from cmp_rate r
join stg_holdings h on h.accession_number = r.accession and h.src_context_id = r.context_id
where r.cause = 'not_yet_explained'
order by r.accession, r.context_id, r.field
