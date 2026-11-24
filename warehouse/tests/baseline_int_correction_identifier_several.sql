-- Slice 5 Task 3 baseline: identifier-keyed corrections whose text matches several positions of the filing. Each acts
-- on every one of them (production sets every matching row); counted here by correction, against a ceiling, so a new
-- ambiguous label is seen. Ceiling baseline_max.int_correction_identifier_several.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_correction_identifier_several']) }}
select correction_id, any_value(cik) as cik, any_value(accession) as accession, any_value(field) as field,
    count(*) as targets, string_agg(context_id, ',' order by context_id) as contexts
from {{ ref('int_correction_target') }}
where key_resolution = 'identifier_native' and target_count > 1
group by correction_id
