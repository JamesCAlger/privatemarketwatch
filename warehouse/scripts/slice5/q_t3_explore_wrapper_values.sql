-- Slice 5 Task 3 exploration: wrapper untagged values by fund, field, the target's role, and the normalised value there.
select c.cik, c.field, s.role, s.role_rule, c.value, c.value_unit, n.value as value_normalised, n.status, n.currency
    , c.accession, c.context_id
from main.stg_correction c
left join main.int_source_row s on s.accession = c.accession and s.context_id = c.context_id
left join main.int_field_normalised n on n.accession = c.accession and n.context_id = c.context_id
    and n.field = case c.field when 'shares_held' then 'shares' else c.field end
where c.store = 'wrapper:untagged_values' and not (c.field = 'fair_value' and s.role_rule = 3)
order by 1, 3, 2
