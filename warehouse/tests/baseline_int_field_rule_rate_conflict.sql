-- Baseline (slice 4 Task 3, controller ruling): positions whose rate reading is a rule conflict. Two funds declare both
-- PIK-only readings (pik_only_is_coupon and pik_only_is_margin, same priority, same row feature pik_tag_only);
-- production separates them by printed text (reference rate present: margin; printed Fixed with no reference rate:
-- coupon; loan rows only; pipeline/financial_conventions.py prepare), which waits for the text spec. One row per
-- position (interest_rate and spread both conflict on it), all rows published or not; is_published beside.
-- Ceiling int_field_rule_rate_conflict.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_rule_rate_conflict']) }}
select u.accession, u.context_id, u.cik, u.report_date, s.is_published, list(u.field order by u.field) as fields
from {{ ref('int_field_rule') }} u
join {{ ref('int_source_row') }} s on s.accession = u.accession and s.context_id = u.context_id
where u.resolution = 'rule_conflict' and u.field in {{ rate_rule_fields() }}
group by 1, 2, 3, 4, 5
