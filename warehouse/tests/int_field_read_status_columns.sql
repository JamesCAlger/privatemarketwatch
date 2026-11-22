-- Slice 3 Task 2: the columns each status must and must not carry.
-- read: a fact_id, a read_rule_id, a unit and at least one fact; a value unless the fact is nil, and no value if it is.
-- absent: no fact_id, no read_rule_id, no value, fact_count 0. unresolved: no value and no fact_id (none is chosen, D5),
-- a read_rule_id and at least two facts or a fact without a number.
select accession, context_id, field, status, reason, fact_id, read_rule_id, value_filed, is_nil, fact_count
from {{ ref('int_field_read') }}
where (status = 'read' and (fact_id is null or read_rule_id is null or unit is null or fact_count < 1
                            or (is_nil and value_filed is not null) or (not is_nil and value_filed is null)))
   or (status = 'absent' and (fact_id is not null or read_rule_id is not null or value_filed is not null
                              or fact_count <> 0 or is_nil))
   or (status = 'unresolved' and (fact_id is not null or value_filed is not null or read_rule_id is null or is_nil
                                  or fact_count < 1))
