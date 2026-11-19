-- A position never spans funds or accounting scopes (verified on the build of 2026-11-16).
-- It can span two borrower ids, so the borrower here is the latest one and is named as such.
select
    position_id,
    min(cik)                                    as cik,
    min(accounting_scope_id)                    as accounting_scope_id,
    arg_max(entity_id, report_date)             as entity_id_latest,
    arg_min(row_id, report_date)                as anchor_row_id,
    min(report_date)                            as first_report_date,
    max(report_date)                            as last_report_date,
    count(*)                                    as observation_count,
    arg_max(issuer_name, report_date)           as issuer_name_latest,
    arg_max(instrument_description, report_date) as instrument_description_latest
from {{ ref('stg_holdings') }}
group by 1
