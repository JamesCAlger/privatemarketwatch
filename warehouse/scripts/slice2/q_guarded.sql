-- Finding 1 (fix round 1): guarded intermediates in rule 6.
-- A guarded row (zero FV, or a rate/spread/PIK/maturity fact) is never a parent in int_role_subtotal. Where such a row
-- has pool descendants, they attach to the next eligible ancestor instead. The pilot's tree uses every kept row as a
-- node. This recomputes the subtotal test with the pilot's tree (all pool keys are nodes, only eligible rows tested)
-- and compares with int_role_subtotal.
with pool as (
    select cf.accession, cf.context_id, cf.cik, cf.fair_value, cf.cost, cf.cost_fact_count
        , coalesce(sc.scopes, 'fund') as scope
        , contains(cf.identifier_label, '|') as is_segmented
        , cf.fair_value <> 0 and not (cf.has_rate or cf.has_spread or cf.has_pik_rate or cf.has_maturity) as can_be_parent
        , array_to_string(list_filter(list_transform(string_split(cf.identifier_label, '|')
            , s -> trim(regexp_replace(lower(s), '[^a-z0-9]+', ' ', 'g'))), s -> s <> ''), ' | ') as key
    from int_role_text t
    join int_context_feature cf on cf.accession = t.accession and cf.context_id = t.context_id
    left join int_role_scope sc on sc.accession = t.accession and sc.context_id = t.context_id
    where t.text_rule is null
)
, decimals as (
    select f.accession, f.context_id
        , min(try_cast(f.decimals as integer)) filter (where f.concept_local = 'InvestmentOwnedAtFairValue') as fv_decimals
        , min(try_cast(f.decimals as integer)) filter (where f.concept_local = 'InvestmentOwnedAtCost') as cost_decimals
    from stg_filed_fact f semi join pool p on p.accession = f.accession and p.context_id = f.context_id
    where f.concept_local in ('InvestmentOwnedAtFairValue', 'InvestmentOwnedAtCost')
      and f.concept_namespace like 'http://fasb.org/us-gaap/%' and not coalesce(f.is_nil, false)
    group by 1, 2
)
, node_key as (
    select accession, scope, key, bool_or(is_segmented) as key_segmented, bool_or(can_be_parent) as eligible
    from pool where key <> '' group by 1, 2, 3
)
, child_prefix as (
    select p.accession, p.scope, p.context_id, p.tokens, n, array_to_string(p.tokens[1:n], ' ') as prefix
    from (select accession, scope, context_id, string_split(key, ' ') as tokens from pool where key <> '') p
    , unnest(range(1, len(p.tokens))) as r(n)
    where p.tokens[n] <> '|'
)
, valid_anc as (
    select c.accession, c.scope, c.context_id, c.n, c.prefix, k.eligible
    from child_prefix c join node_key k on k.accession = c.accession and k.scope = c.scope and k.key = c.prefix
    where not ((list_contains(c.tokens[1:c.n], '|') or k.key_segmented) and c.tokens[c.n + 1] <> '|')
)
, pilot_parent as (
    select accession, scope, context_id, arg_max(prefix, n) as parent_key from valid_anc group by 1, 2, 3
)
, children as (
    select d.accession, d.scope, d.parent_key, count(*) as child_count, sum(p.fair_value) as cfv, sum(p.cost) as ccost
        , count(*) filter (where p.cost is null) as cmiss
    from pilot_parent d join pool p on p.accession = d.accession and p.context_id = d.context_id group by 1, 2, 3
)
, pilot as (
    select p.accession, p.context_id, p.cik
        , coalesce(abs(p.fair_value - ch.cfv) <= greatest(0.5 * power(10, -coalesce(d.fv_decimals, 0)) * (ch.child_count + 1), 1)
          and (p.cost_fact_count = 0 or (p.cost is not null and ch.cmiss = 0
               and abs(p.cost - ch.ccost) <= greatest(0.5 * power(10, -coalesce(d.cost_decimals, 0)) * (ch.child_count + 1), 1))), false) as pilot_subtotal
    from pool p join children ch on ch.accession = p.accession and ch.scope = p.scope and ch.parent_key = p.key
    left join decimals d on d.accession = p.accession and d.context_id = p.context_id
    where p.can_be_parent
)
-- Guarded intermediates: guarded rows that are the pilot parent of at least one pool row and themselves sit under an
-- eligible ancestor.
, guarded_mid as (
    select distinct p.accession, p.context_id, p.cik
    from pool p
    join pilot_parent pp on pp.accession = p.accession and pp.scope = p.scope and pp.parent_key = p.key
    where not p.can_be_parent
      and exists (select 1 from valid_anc v where v.accession = p.accession and v.context_id = p.context_id and v.eligible)
)
select 'guarded_intermediate' as measure, cik, count(*) as n from guarded_mid group by all
union all
select 'differs: pilot subtotal, ours not', coalesce(p.cik, ''), count(*)
from pilot p left join int_role_subtotal s using (accession, context_id)
where p.pilot_subtotal and not coalesce(s.is_subtotal, false) group by all
union all
select 'differs: ours subtotal, pilot not', p.cik, count(*)
from int_role_subtotal s join pool p using (accession, context_id)
left join pilot pl using (accession, context_id)
where s.is_subtotal and not coalesce(pl.pilot_subtotal, false) group by all
order by 1, 2
