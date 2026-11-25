-- Owner question (a), 2026-11-25: the two Apollo spreads production keeps at 4.5. Production's row, the filed facts on
-- the context, and the corrections on it. Read-only.
with k as (
    select '0000950170-24-031479' as accession, 'C_1de7bac0%' as ctx
    union all select '0000950170-24-058684', 'C_a98dfaae%'
)
select 'holdings' as src, h.accession_number as accession, left(h.src_context_id, 12) as ctx, h.issuer_name as a
    , cast(h.interest_rate as varchar) as b, h.interest_rate_kind as c, cast(h.interest_rate_cash as varchar) as d
    , cast(h.pik_rate as varchar) as e, cast(h.basis_spread as varchar) as f, h.src_transforms as g, h.corrected_fields as h
from stg_holdings h join k on h.accession_number = k.accession and h.src_context_id like k.ctx
union all
select 'fact', f.accession, left(f.context_id, 12), f.concept_local, f.value_text, f.unit_id, null, null, null, null, null
from stg_filed_fact f join k on f.accession = k.accession and f.context_id like k.ctx
union all
select 'correction', c.accession, left(c.context_id, 12), c.field, c.value, c.store, c.kind, null, null, left(c.reason, 200), left(c.evidence, 200)
from stg_correction c join k on c.accession = k.accession and c.context_id like k.ctx
union all
select 'here', n.accession, left(n.context_id, 12), n.field, cast(n.value as varchar), n.status, n.reason, null, null, n.action, null
from int_field_corrected n join k on n.accession = k.accession and n.context_id like k.ctx
where n.field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread')
order by 2, 1, 4
