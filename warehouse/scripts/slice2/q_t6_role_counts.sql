-- Task 6: role counts by fund before (out/t6_roles_before.parquet) and after the fund rules.
with b as (select cik, role, count(*) n from read_parquet('scripts/slice2/out/t6_roles_before.parquet') group by 1, 2)
, a as (select cik, role, count(*) n from int_source_row group by 1, 2)
select coalesce(a.cik, b.cik) as cik, coalesce(a.role, b.role) as role, coalesce(b.n, 0) as before, coalesce(a.n, 0) as after
from a full join b on a.cik = b.cik and a.role = b.role
order by 1, 2
