-- Text slice R phase 3: rates this layer leaves unread where production holds one (cmp_rate outcome new_empty, fields
-- interest_rate, interest_rate_cash, pik_rate, spread, both bases), and whether the rule-read model now reads the field
-- (interest_rate -> all_in_rate, interest_rate_cash -> cash_rate, pik_rate -> pik_rate, spread -> spread), and whether
-- the value equals production's (0.005). By fund, field and production's cause detail. Read-only.
with u as (
    select c.basis, c.cik, c.field, c.cause_detail, c.value_production, r.accession is not null as has_read_row
        , case c.field when 'interest_rate' then r.all_in_rate when 'interest_rate_cash' then r.cash_rate
                       when 'pik_rate' then r.pik_rate when 'spread' then r.spread end as v_new
        , case c.field when 'interest_rate' then r.all_in_rate_status when 'interest_rate_cash' then r.cash_rate_status
                       when 'pik_rate' then r.pik_rate_status when 'spread' then r.spread_status end as new_status
    from cmp_rate c
    left join int_text_rate_read r on r.accession = c.accession and r.context_id = c.context_id
    where c.outcome = 'new_empty' and c.field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread')
)
select basis, cik, field, cause_detail
    , count(*) as unread
    , count(*) filter (where v_new is not null) as now_read
    , count(*) filter (where v_new is not null and abs(v_new - value_production) <= 0.005) as equal_production
    , count(*) filter (where v_new is not null and abs(v_new - value_production) > 0.005) as differ_production
    , count(*) filter (where not has_read_row) as no_ruled_cell
    , string_agg(distinct new_status, ',') filter (where v_new is null and has_read_row) as statuses_not_read
from u
group by all
order by 1, 2, 3, 4
