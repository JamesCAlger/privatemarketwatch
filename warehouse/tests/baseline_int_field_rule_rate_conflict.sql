-- Guard (ceiling 0): positions whose rate reading is a rule conflict. Before the controller ruling of 2026-11-23 the
-- 628 PIK-only rows of the two funds that declare both PIK-only readings (same priority, same row feature
-- pik_tag_only) were conflicts. Both actions now name unread_input, so those rows are text_not_read and this count is
-- 0; the test stays to catch any new rate-field conflict. One row per position (interest_rate and spread both
-- conflict on it), all rows published or not; is_published beside.
-- Ceiling int_field_rule_rate_conflict.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_field_rule_rate_conflict']) }}
select u.accession, u.context_id, u.cik, u.report_date, s.is_published, list(u.field order by u.field) as fields
from {{ ref('int_field_rule') }} u
join {{ ref('int_source_row') }} s on s.accession = u.accession and s.context_id = u.context_id
where u.resolution = 'rule_conflict' and u.field in {{ rate_rule_fields() }}
group by 1, 2, 3, 4, 5
