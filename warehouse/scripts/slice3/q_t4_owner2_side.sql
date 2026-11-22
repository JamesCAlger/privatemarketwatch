-- Slice 3 Task 4, owner items 2 and 3: the comparison side and cause of the given contexts (variable ctxs, a
-- comma-separated list typed at the command line for this diagnostic only), with production's fair value and cost.
select c.cik, c.report_date, c.accession, c.context_id, c.side, c.role, c.role_rule, c.cause, c.cause_detail
    , h.fair_value as prod_fv, h.cost as prod_cost, h.corrected_fields
from cmp_row_set c
left join stg_holdings h on h.accession_number = c.accession and h.src_context_id = c.context_id
where list_contains(string_split(getvariable('ctxs'), ','), c.context_id)
order by c.report_date
limit 20
