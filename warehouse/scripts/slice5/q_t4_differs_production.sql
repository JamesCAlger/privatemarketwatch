-- Slice 5 Task 4: rate rows of int_field_corrected that name a correction (or sit on a position whose rate reading was
-- re-run) and differ from production's published row (stg_holdings by accession and context): the stop test of the
-- brief for the cash leg and the kind, and the other rate fields for the record. Read-only.
with h as (
    select accession_number as accession, src_context_id as context_id, interest_rate, interest_rate_cash, interest_rate_kind
        , pik_rate, basis_spread, maturity_date, corrected_fields, src_transforms, accounting_record_class
    from stg_holdings
)
, f as (
    select f.*, h.interest_rate as p_rate, h.interest_rate_cash as p_cash, h.interest_rate_kind as p_kind, h.pik_rate as p_pik
        , h.basis_spread as p_spread, h.corrected_fields, h.src_transforms, h.accounting_record_class
    from int_field_corrected f
    join h on h.accession = f.accession and h.context_id = f.context_id
    where f.correction_id is not null and f.field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread')
)
select field, cik, accession, context_id, value_normalised, value, rate_kind_normalised, rate_kind, status, reason, action
    , p_rate, p_cash, p_kind, p_pik, p_spread, corrected_fields, src_transforms
from f
where case field
        when 'interest_rate' then not coalesce(abs(value - p_rate) <= 1e-9, value is null and p_rate is null)
                                  or rate_kind is distinct from p_kind
        when 'interest_rate_cash' then not coalesce(abs(value - p_cash) <= 1e-9, value is null and p_cash is null)
        when 'pik_rate' then not coalesce(abs(value - p_pik) <= 1e-9, value is null and p_pik is null)
        when 'spread' then not coalesce(abs(value - p_spread) <= 1e-9, value is null and p_spread is null)
      end
order by field, cik, accession, context_id
