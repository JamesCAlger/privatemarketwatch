-- Slice 5 Task 4 diagnostic: positions whose cash-pay tag is read, per fund. Read-only.
select cik, status, count(*) from int_field_read where field = 'interest_rate_cash_tag' group by all order by 1, 2
