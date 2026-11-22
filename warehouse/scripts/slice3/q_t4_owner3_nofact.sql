-- Slice 3 Task 4, owner item 3: production holdings rows (published basis) whose context carries no fair-value fact of
-- any concept this layer reads (int_context_feature.fair_value_fact_count = 0: no concept_map fact and no fund-rule
-- fact), by fund, production fair value zero or not, and the side and cause cmp_row_set gives the row.
select h.cik, (h.fair_value = 0) as prod_fv_zero, c.side, c.cause, c.cause_detail, count(*) n
    , sum(h.fair_value) as prod_fv, min(h.report_date) as first_date, max(h.report_date) as last_date
from stg_holdings h
join int_context_feature cf on cf.accession = h.accession_number and cf.context_id = h.src_context_id
left join cmp_row_set c on c.accession = h.accession_number and c.context_id = h.src_context_id
where h.accounting_record_class is distinct from 'underlying_schedule'
  and coalesce(cf.fair_value_fact_count, 0) = 0
group by all order by 1, 2, 3, 4
limit 50
