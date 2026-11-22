-- Slice 3 Task 2: negative values read, per fund and field.
select cik, field, count(*) as rows, min(value_filed) as min_value
from int_field_read where status = 'read' and value_filed < 0
group by all order by 1, 2
