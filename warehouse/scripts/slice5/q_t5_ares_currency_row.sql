-- Slice 5 Task 5: the one currency row a principal correction moves away from production (Ares 2022-12-31). The
-- correction, its outcome, and production's principal columns. Read-only.
select 'correction' as what, c.correction_id, c.store, c.field, c.value, c.value_unit, a.outcome, a.reason,
    a.value_before, a.value_after, a.currency_after, null as production
from stg_correction c
join int_correction_application a on a.correction_id = c.correction_id
where c.correction_id = 'a5bc76bcc2479299'
union all
select 'production', null, null, null, cast(principal_amount as varchar), principal_amount_currency, null, null, null,
    cast(principal_amount_usd as varchar), null, corrected_fields
from stg_holdings
where accession_number = '0001287750-23-000010' and src_context_id = 'ie6a91f4a72834ea4b64f0579f8515441_I20221231'
