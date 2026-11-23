-- Slice 4 Task 4: printed_total_margin_not_read rows where production's spread is neither the filed spread nor the
-- filed spread plus the filed PIK rate.
with f as (
    select accession, context_id
        , any_value(value_filed) filter (where field = 'pik_rate') as f_pik
        , any_value(value_filed) filter (where field = 'spread') as f_spread
    from int_field_read group by 1, 2
)
select c.cik, c.report_date, c.accession, c.context_id, c.value_production, f.f_spread, f.f_pik, h.src_transforms,
    h.corrected_fields, h.basis_spread_source
from cmp_rate c
join f on f.accession = c.accession and f.context_id = c.context_id
join stg_holdings h on h.accession_number = c.accession and h.src_context_id = c.context_id
where c.cause_detail = 'printed_total_margin_not_read'
  and abs(c.value_production - f.f_spread * 100) > 1e-9
  and abs(c.value_production - (f.f_spread + f.f_pik) * 100) > 1e-6
