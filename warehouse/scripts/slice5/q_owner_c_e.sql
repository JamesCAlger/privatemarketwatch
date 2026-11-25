-- Owner questions (c) and (e), 2026-11-25. (c) outcomes of the wrapper's untagged values, and the one failed cost.
-- (e) one of the seven Blue Owl rate corrections no rule reads: the correction, the filed facts, production's row.
select 'c_outcomes' as src, a.field as a, a.outcome as b, a.reason as c, cast(count(*) as varchar) as d, null as e, null as f, null as g
from int_correction_application a where a.store = 'wrapper:untagged_values' group by all
union all
select 'c_failed', a.accession, left(a.context_id, 14), a.field, a.value_after, a.reason, left(c.reason, 150), left(c.evidence, 250)
from int_correction_application a join stg_correction c using (correction_id)
where a.outcome = 'failed' and a.reason = 'conversion_unresolved'
union all
select 'e_correction', c.accession, c.field, c.value, c.store, c.identifier, left(c.reason, 250), left(c.evidence, 250)
from stg_correction c where c.accession = '0001812554-24-000014' and c.correction_id = '0b489df6e5a8158e'
union all
select 'e_fact', f.accession, f.concept_local, f.value_text, f.unit_id, null, null, null
from stg_filed_fact f where f.accession = '0001812554-24-000014' and f.context_id = 'c-1192'
union all
select 'e_holdings', h.accession_number, h.issuer_name, cast(h.interest_rate as varchar), h.interest_rate_kind, cast(h.pik_rate as varchar), cast(h.basis_spread as varchar), h.src_transforms || ' / corrected: ' || coalesce(h.corrected_fields, '')
from stg_holdings h where h.accession_number = '0001812554-24-000014' and h.src_context_id = 'c-1192'
union all
select 'e_label', cf.accession, left(cf.identifier_label, 120), null, null, null, null, null
from int_context_feature cf where cf.accession = '0001812554-24-000014' and cf.context_id = 'c-1192'
order by 1, 2, 3
