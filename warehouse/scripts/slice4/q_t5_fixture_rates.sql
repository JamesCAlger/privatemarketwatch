-- Slice 4 Task 5: the rate rows of the CI fixture's positions as built (int_field_normalised), with the rule that
-- converted each (global default id, or 'fund:' and the action) and the rule resolution. Run on a fixture ci.duckdb.
select n.context_id, n.field, n.status, n.reason, n.value, n.value_date, n.rate_kind, n.action
    , case when r.origin = 'global_default' then r.rule_id when fr.action is not null then 'fund:' || fr.action end
        as converted_by
    , r.resolution
from main.int_field_normalised n
left join main.int_field_rule r
    on r.accession = n.accession and r.context_id = n.context_id
    and r.field = case when n.field = 'interest_rate_cash' then 'interest_rate' else n.field end
left join main.stg_reading_rule fr on fr.rule_id = r.rule_id
where n.cik = '0000000001'
  and n.field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
  and not (n.status = 'absent' and n.reason = 'no_fact')
order by n.context_id, n.field
