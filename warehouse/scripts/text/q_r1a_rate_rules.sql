-- Slice R phase 1, 2026-11-26: the reference-rate and spread rules of the wrapper copies, every column. Read-only.
select * from stg_reading_rule
where target in ('reference_rate', 'spread') and rule_class in ('source', 'vocabulary', 'convention')
order by cik, action, rule_id
