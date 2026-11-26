-- Slice 5 Task 1, items b and f: the CI fixture's position count per fund and the rate rows that are not absent
-- no_fact, as built (int_field_normalised). Run on a fixture ci.duckdb.
select n.cik, n.context_id, n.field, n.status, n.reason, n.value, n.rate_kind, n.action
from main.int_field_normalised n
where n.field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread', 'maturity_date')
  and not (n.status = 'absent' and n.reason = 'no_fact')
union all
select cik, '(positions)', cast(count(*) as varchar), null, null, null, null, null
from main.int_source_row where role = 'position' group by cik
order by 1, 2, 3
