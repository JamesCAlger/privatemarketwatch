-- Slice 4 Task 4: for each cause detail of cmp_rate, how many rows pass a check of the mechanism the cause names
-- (computed from values, independent of the rule that assigned the cause). Both bases.
with r as (
    select c.*, h.interest_rate as p_ir, h.interest_rate_cash as p_cash, h.pik_rate as p_pik, h.basis_spread as p_bs,
        h.interest_rate_kind as p_kind, h.asset_category, coalesce(h.src_transforms, '') as tr,
        h.interest_rate_reported as p_reported, h.bdc_investment_identifier as p_identifier
    from cmp_rate c
    join stg_holdings h on h.accession_number = c.accession and h.src_context_id = c.context_id
    where c.cause is not null
)
, filed as (
    select accession, context_id
        , any_value(value_filed) filter (where field = 'interest_rate_tag') as f_rate
        , any_value(value_filed) filter (where field = 'pik_rate') as f_pik
        , any_value(value_filed) filter (where field = 'spread') as f_spread
    from int_field_read group by 1, 2
)
, corr as (
    -- a loaded correction on the compared field itself whose value equals production's value (percent, or a
    -- fraction times 100; dates as text). Keyed by context id, or by accession and production's identifier, as
    -- cmp_rate joins it (slice 4 Task 5 repair b: before, any identifier-keyed correction of the accession matched)
    select distinct r.accession, r.context_id, r.field
    from r
    join stg_correction c on c.kind = 'value' and c.accession = r.accession
        and (c.context_id = r.context_id or (c.context_id is null and c.identifier = r.p_identifier))
    where c.field = case r.field when 'spread' then 'basis_spread' when 'rate_kind' then 'interest_rate_kind' else r.field end
      and (
          (r.field = 'maturity_date' and try_cast(c.value as date) = r.date_production)
          or (r.field = 'rate_kind' and c.value = r.text_production)
          or (r.value_production is not null and (abs(try_cast(c.value as double) - r.value_production) <= 1e-9
                                                  or abs(try_cast(c.value as double) * 100 - r.value_production) <= 1e-9))
          or (r.value_production is null and r.field not in ('maturity_date', 'rate_kind') and nullif(trim(c.value), '') is null)
      )
)
select r.basis, r.field, r.cause, r.cause_detail
    -- slice 4 Task 5 repair c: a check that the cause rule or the outcome already implies cannot fail; it restates
    -- the rule and is no independent check (the evidence for those groups is the rows opened)
    , case
        when r.cause_detail in ('rate_only_context_not_adopted', 'production_corrected_no_loaded_store',
                                'identifier_text_not_read', 'printed_maturity_not_read') then 'rule_restated'
        when r.cause_detail = 'scale_decided_by_size_in_production' and r.field = 'interest_rate_cash' then 'rule_restated'
        else 'independent'
      end as check_kind
    , count(*) as rows
    , count(*) filter (where r.outcome = 'production_empty') as production_empty_rows
    , count(*) filter (where case r.cause_detail
        -- production keeps a value between 0.5 and 50 as a percent and divides one of 50 or more by 100
        when 'scale_decided_by_size_in_production' then
            case r.field
                when 'interest_rate' then abs(r.p_ir - case when f.f_rate >= 50 then f.f_rate / 100 else f.f_rate end) <= 1e-9
                when 'rate_kind' then abs(r.p_reported - case when f.f_rate >= 50 then f.f_rate / 100 else f.f_rate end) <= 1e-9
                when 'interest_rate_cash' then r.p_cash is not null
                when 'pik_rate' then abs(r.p_pik - case when f.f_pik >= 50 then f.f_pik / 100 else f.f_pik end) <= 1e-9
                when 'spread' then abs(r.p_bs - case when f.f_spread >= 50 then f.f_spread / 100 else f.f_spread end) <= 1e-9
            end
        when 'two_values_filed_production_keeps_first' then r.p_reported is not null
        when 'loan_class_not_read' then r.asset_category is distinct from 'LOAN' and r.p_ir is null and r.p_kind = 'unresolved'
        when 'identifier_text_not_read' then r.production_source = 'identifier_text' or r.field in ('interest_rate', 'interest_rate_cash', 'rate_kind')
        when 'printed_maturity_not_read' then r.date_production is not null
        when 'whole_coupon_pik_not_read' then abs(r.p_pik - r.p_ir) <= 0.011 and coalesce(r.p_cash, 0) = 0
        when 'printed_reference_rate_column_not_read' then
            case when r.field = 'spread' then r.p_bs is null
                 else regexp_matches(r.tr, 'interest_rate:from_spread_tag') and abs(r.p_ir - f.f_spread * 100) <= 1e-9 end
        -- production read the PIK-only row as the coupon (rate = PIK) or as the margin (spread = PIK)
        when 'printed_rate_type_and_loan_class_not_read' then
            (r.field in ('interest_rate', 'rate_kind') and regexp_matches(r.tr, 'interest_rate:pik_only') and abs(r.p_ir - r.p_pik) <= 1e-9)
            or (r.field = 'spread' and regexp_matches(r.tr, 'basis_spread:pik_margin') and abs(r.p_bs - r.p_pik) <= 1e-9)
        when 'pik_only_reading_needs_printed_text' then
            (r.field in ('interest_rate', 'rate_kind') and regexp_matches(r.tr, 'interest_rate:pik_only') and abs(r.p_ir - r.p_pik) <= 1e-9)
            or (r.field = 'spread' and regexp_matches(r.tr, 'basis_spread:pik_margin') and abs(r.p_bs - r.p_pik) <= 1e-9)
        when 'printed_total_margin_not_read' then
            (regexp_matches(r.tr, 'basis_spread:cash_plus_pik_margin') and abs(r.p_bs - (f.f_spread + f.f_pik) * 100) <= 1e-6)
            or (not regexp_matches(r.tr, 'basis_spread:cash_plus_pik_margin') and abs(r.p_bs - f.f_spread * 100) <= 1e-9)
        when 'rate_only_context_not_adopted' then true
        when 'coupon_read_on_printed_floating_margin' then r.p_bs is not null and r.p_ir is null
        when 'correction_loaded_applied' then co.accession is not null
        when 'production_corrected_no_loaded_store' then true
      end) as mechanism_holds
    , count(*) filter (where r.cause_detail = 'printed_total_margin_not_read' and regexp_matches(r.tr, 'basis_spread:cash_plus_pik_margin')) as margin_summed
    , count(*) filter (where r.cause_detail = 'pik_only_reading_needs_printed_text' and regexp_matches(r.tr, 'interest_rate:pik_only')) as read_as_coupon
    , count(*) filter (where r.cause_detail = 'pik_only_reading_needs_printed_text' and regexp_matches(r.tr, 'basis_spread:pik_margin')) as read_as_margin
from r
left join filed f on f.accession = r.accession and f.context_id = r.context_id
left join corr co on co.accession = r.accession and co.context_id = r.context_id and co.field = r.field
group by all
order by 1, 2, 3, 4
