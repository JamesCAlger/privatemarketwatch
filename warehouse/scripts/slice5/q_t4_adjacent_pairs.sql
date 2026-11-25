-- Slice 5 Task 4 diagnostic: production's adopt_rate_only_contexts pairing (pipeline/source_encodings.py lines 689-748)
-- on the filed contexts of every fund with an identifier member, before the model is built. Read-only.
with base as (
    select
        cf.accession, cf.cik, cf.context_id, cf.instant_date
        , try_cast(regexp_extract(cf.context_id, '([0-9]+)$', 1) as bigint) as ordinal
        , left(regexp_replace(lower(cf.identifier_label), '[^a-z0-9]', '', 'g'), 16) as issuer_key
        , cf.fair_value_fact_count = 0 and cf.cost_fact_count = 0 and not cf.has_principal
          and (cf.has_rate or cf.has_spread or cf.has_pik_rate) as rate_only
        , cf.fair_value_fact_count > 0 and cf.has_principal and not (cf.has_rate or cf.has_spread or cf.has_pik_rate)
          as value_only
        , cf.identifier_label
    from int_context_feature cf
    where cf.has_identifier_member and cf.cik in (select cik from stg_v05_scope)
)
, givers as (select *, count(*) over (partition by accession, instant_date, issuer_key) as n from base where rate_only)
, takers as (select *, count(*) over (partition by accession, instant_date, issuer_key) as n from base where value_only)
select g.cik, t.instant_date, g.accession, t.context_id as taker, g.context_id as giver, g.n as gn, t.n as tn
    , length(g.issuer_key) as key_len, abs(g.ordinal - t.ordinal) as gap
    , rt.role as taker_role, rg.role as giver_role, rg.role_rule as giver_rule
    , t.identifier_label as taker_label, g.identifier_label as giver_label
from givers g join takers t using (accession, instant_date, issuer_key)
left join int_source_row rt on rt.accession = t.accession and rt.context_id = t.context_id
left join int_source_row rg on rg.accession = g.accession and rg.context_id = g.context_id
where abs(g.ordinal - t.ordinal) <= 2
order by gap, g.cik, t.instant_date, taker
