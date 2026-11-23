-- Slice 4 Task 4: rows production changed by the two wrapper procedures this layer does not build, from production's
-- own labels: pik_rate:whole_coupon_printed in src_transforms, and a rate field named in src_filled_fields; and how the
-- PIK pair of those rows came out in cmp_rate.
with p as (
    select h.cik, h.report_date, h.accession_number as accession, h.src_context_id as context_id
        , regexp_matches(coalesce(h.src_transforms, ''), 'pik_rate:whole_coupon_printed') as whole_coupon
        , regexp_matches(coalesce(h.src_filled_fields, ''), 'interest_rate|basis_spread|pik_rate') as adopted
    from stg_holdings h
)
select p.cik, case when whole_coupon then 'whole_coupon' else 'adopt_adjacent' end as procedure_label
    , count(*) as production_rows
    , count(c.accession) as rows_compared
    , count(*) filter (where c.outcome = 'equal') as pik_equal
    , count(*) filter (where c.outcome = 'differs') as pik_differs
    , count(*) filter (where c.outcome = 'new_empty') as pik_new_empty
    , count(*) filter (where c.cause_detail = 'correction_loaded_applied') as pik_correction_first
from p
left join cmp_rate c on c.accession = p.accession and c.context_id = p.context_id and c.field = 'pik_rate'
where whole_coupon or adopted
group by all
order by 1, 2
