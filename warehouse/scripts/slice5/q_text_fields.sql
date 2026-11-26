-- Text spec measurement, 2026-11-25: the columns of production's holdings (stg_holdings), and the parked corrections
-- (deferred, field_not_held) by correction field. Read-only.
select 'column' as src, column_name as a, column_type as b, null as n from (describe stg_holdings)
union all
select 'deferred', a.field, a.store, count(*) from int_correction_application a
where a.outcome = 'deferred' group by all
order by 1, 4 desc nulls last, 2
