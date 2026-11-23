-- Slice 3 Task 2, slice 4 Task 2: the columns each status must and must not carry.
-- read: a fact_id, a read_rule_id and at least one fact; a value unless the fact is nil, and no value if it is. A
-- number field carries a unit and its value in value_filed (value_date null); the date field maturity_date carries its
-- value in value_date (value_filed null; a date fact has no unit).
-- absent: no fact_id, no read_rule_id, no value, fact_count 0. unresolved: no value and no fact_id (none is chosen, D5),
-- a read_rule_id and at least two facts or a fact without a value.
with f as (
    select *
        , field = 'maturity_date' as is_date_field
        , case when field = 'maturity_date' then value_date is not null else value_filed is not null end as has_value
    from {{ ref('int_field_read') }}
)

select accession, context_id, field, status, reason, fact_id, read_rule_id, value_filed, value_date, is_nil, fact_count
from f
where (status = 'read' and (fact_id is null or read_rule_id is null or fact_count < 1
                            or (not is_date_field and unit is null)
                            or (is_date_field and value_filed is not null)
                            or (not is_date_field and value_date is not null)
                            or (is_nil and has_value) or (not is_nil and not has_value)))
   or (status = 'absent' and (fact_id is not null or read_rule_id is not null or value_filed is not null
                              or value_date is not null or fact_count <> 0 or is_nil))
   or (status = 'unresolved' and (fact_id is not null or value_filed is not null or value_date is not null
                                  or read_rule_id is null or is_nil or fact_count < 1))
