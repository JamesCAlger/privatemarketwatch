-- Slice 3 final fix wave F4 (measure only, nothing built): int_role_subtotal as compiled, with the pool's cost taken from
-- the filer-concept cost (int_field_read under a concept_is_cost rule) where the standard cost is missing. Lists every
-- parent whose is_subtotal or near-miss reason would differ from the built model. Generated from the compiled model.
select s.accession, s.context_id, b.is_subtotal as built_is_subtotal, s.is_subtotal as with_filer_cost
    , b.near_miss_reason as built_reason, s.near_miss_reason as reason_with_filer_cost
from (
-- Decides rule 6 of the row roles (spec 6.2): which context is a subtotal of other contexts, read from labels and sums.
-- One row per context that rules 0 to 5 left open and that has at least one direct child.
--
-- Pool: the contexts of one filing that rules 0 to 5 left open (period end, investment identifier, a fair value).
--   Parents and children are matched within one scope (int_role_scope; 'fund' when none): a subtotal sums rows of its
--   own schedule, so a JV row is never the parent of a fund row or the reverse.
-- Key: the label cut into '|'-separated segments; each segment lowercased, every run of other than a-z and 0-9 made one
--   space; empty segments dropped; segments joined with ' | ' ('|' is its own word). Port of the pilot's _key.
-- Parent: a pool context whose key is a proper word prefix of another pool context's key. The prefix must not end on
--   '|'; when the prefix holds a '|', or any context carrying the prefix key has a '|' in its raw label, it must end on a
--   whole segment (pilot _ancestor_keys). A child's parent is its LONGEST such prefix (its direct parent).
-- Only a context that rule 6 could remove can be a parent: non-zero fair value and no rate, spread, PIK rate or
--   maturity fact (the guard). A row with those terms is a position and cannot be the subtotal of anything, so it does
--   not hide its own descendants from the subtotal above it.
-- Difference from the pilot (fix round 1). In the pilot every kept row is a node of the prefix tree, so a guarded row X
--   whose label starts other rows' labels takes those rows as its children, and the subtotal G above X sums X only.
--   Here X's descendants attach to G, so G sums X and X's descendants. Two cases:
--   (a) X's descendants are siblings, not parts, of X (Ares 'X, First lien loan' over 'X, First lien loan 2'): G
--       passes here and fails in the pilot (the pilot's "hierarchy blocking" limit);
--   (b) X is a true subtotal that carries a rate or maturity: G double-counts X's descendants and fails here, where
--       the pilot would pass it.
--   Measured 2026-11-19 on all parsed filings (warehouse/scripts/slice2/q_guarded.sql, the pilot's tree with this
--   model's test): 23 guarded intermediates (Ares 21, Apollo 2), all of kind (a) (loans over 'loan 2' lines). Subtotal
--   here and not under the pilot's tree: 22 (Ares 21, Apollo 1). Subtotal under the pilot's tree and not here (case
--   b): 0. If case (b) ever appears it shows as a G that is unresolved or a position, not as a silent removal.
-- Test: the parent's fair value equals the sum of its direct children's fair values, and, when the parent has a cost
--   fact, its cost equals the sum of their costs. Tolerance per measure: half a unit of the parent fact's decimals times
--   (children + 1), at least 1 (pilot _tol). A null is never read as zero: a parent whose cost facts give no single
--   number, or a child with no single cost number, fails the cost test (reason cost_not_comparable).
-- Level by level: the pilot removes the deepest subtotals first and re-tests the level above against what is left.
--   Testing every parent against its direct children in one pass gives the same answer: a removed subtotal equals its
--   children's sum, so the level above sees the same total either way. It can differ only by rounding within the
--   tolerances, or where a removed subtotal has no cost of its own (then the level above fails the cost test here and
--   is kept; the pilot would have summed the grandchildren's costs). So the repeat is not needed and SQL suffices.
-- Fund rule subtotal_on_fair_value (stg_reading_rule; owner decision D12, Apollo): for that filer, inside the rule's
--   dates, a parent whose fair value ties is a subtotal even where the cost test fails or cannot be made. The tree,
--   the fair-value tolerance and the guard are unchanged. subtotal_rule_id names the rule where it decided.
with filer_cost as (
    select r.accession, r.context_id, r.value_filed from "warehouse"."main"."int_field_read" r
    join "warehouse"."main"."stg_reading_rule" rr on rr.rule_id = r.read_rule_id and rr.action = 'concept_is_cost'
    where r.field = 'cost' and r.status = 'read'
)

, fair_value_only_rule as (
    select rule_id, cik, valid_from, valid_to
    from "warehouse"."main"."stg_reading_rule"
    where action = 'subtotal_on_fair_value'
)

, pool as (
    select
        cf.accession
        , cf.context_id
        , cf.fair_value
        , coalesce(cf.cost, fc.value_filed) as cost
        , cf.cost_fact_count + case when fc.context_id is not null then 1 else 0 end as cost_fact_count
        , cf.cik
        , cf.instant_date as report_date
        , coalesce(sc.scopes, 'fund') as scope
        , contains(cf.identifier_label, '|') as is_segmented
        , cf.fair_value <> 0 and not (cf.has_rate or cf.has_spread or cf.has_pik_rate or cf.has_maturity) as can_be_parent
        , array_to_string(
            list_filter(
                list_transform(
                    string_split(cf.identifier_label, '|')
                    , s -> trim(regexp_replace(lower(s), '[^a-z0-9]+', ' ', 'g'))
                )
                , s -> s <> ''
            )
            , ' | '
          ) as key
    from "warehouse"."main"."int_role_text" t
    join "warehouse"."main"."int_context_feature" cf on cf.accession = t.accession and cf.context_id = t.context_id
    left join "warehouse"."main"."int_role_scope" sc on sc.accession = t.accession and sc.context_id = t.context_id
    left join filer_cost fc on fc.accession = t.accession and fc.context_id = t.context_id
    where t.text_rule is null
)

, decimals as (
    select
        f.accession
        , f.context_id
        , min(try_cast(f.decimals as integer)) filter (where m.field = 'fair_value') as fv_decimals
        , min(try_cast(f.decimals as integer)) filter (where m.field = 'cost') as cost_decimals
    from "warehouse"."main"."stg_filed_fact" f
    semi join pool p on p.accession = f.accession and p.context_id = f.context_id
    -- the fair-value and cost concepts, by local name and namespace pattern from the seed concept_map
    join "warehouse"."main"."concept_map" m
        on m.field in ('fair_value', 'cost') and m.concept_local = f.concept_local
        and f.concept_namespace glob m.namespace_pattern
    where not coalesce(f.is_nil, false)
    group by 1, 2
)

, parent_key as (
    select accession, scope, key, bool_or(is_segmented) as key_segmented
    from pool
    where key <> ''
    group by 1, 2, 3
    having bool_or(can_be_parent)
)

, child_prefix as (
    select
        p.accession
        , p.scope
        , p.context_id
        , p.tokens
        , n
        , array_to_string(p.tokens[1:n], ' ') as prefix
    from (
        select accession, scope, context_id, string_split(key, ' ') as tokens
        from pool
        where key <> ''
    ) p
    , unnest(range(1, len(p.tokens))) as r(n)
    where p.tokens[n] <> '|'
)

, direct_parent as (
    select
        c.accession
        , c.scope
        , c.context_id
        , arg_max(c.prefix, c.n) as parent_key
    from child_prefix c
    join parent_key k on k.accession = c.accession and k.scope = c.scope and k.key = c.prefix
    where not ((list_contains(c.tokens[1:c.n], '|') or k.key_segmented) and c.tokens[c.n + 1] <> '|')
    group by 1, 2, 3
)

, children as (
    select
        d.accession
        , d.scope
        , d.parent_key
        , count(*) as child_count
        , sum(p.fair_value) as child_fair_value
        , sum(p.cost) as child_cost
        , count(*) filter (where p.cost is null) as child_cost_missing
    from direct_parent d
    join pool p on p.accession = d.accession and p.context_id = d.context_id
    group by 1, 2, 3
)

, tested as (
    select
        p.accession
        , p.context_id
        , p.key
        , ch.child_count
        , ch.child_fair_value
        , ch.child_cost
        , abs(p.fair_value - ch.child_fair_value)
            <= greatest(0.5 * power(10, -coalesce(d.fv_decimals, 0)) * (ch.child_count + 1), 1) as fair_value_matches
        , p.cost_fact_count > 0 as cost_needed
        , fr.rule_id as fair_value_only_rule_id
        , p.cost is not null and ch.child_cost_missing = 0 as cost_comparable
        , abs(p.cost - ch.child_cost)
            <= greatest(0.5 * power(10, -coalesce(d.cost_decimals, 0)) * (ch.child_count + 1), 1) as cost_matches
    from pool p
    join children ch on ch.accession = p.accession and ch.scope = p.scope and ch.parent_key = p.key
    left join decimals d on d.accession = p.accession and d.context_id = p.context_id
    left join fair_value_only_rule fr on fr.cik = p.cik
        and (fr.valid_from is null or fr.valid_from <= p.report_date)
        and (fr.valid_to is null or fr.valid_to >= p.report_date)
    where p.can_be_parent
)

select
    accession
    , context_id
    , child_count
    , child_fair_value
    , child_cost
    , coalesce(fair_value_matches and (not cost_needed or (cost_comparable and cost_matches)), false)
      or coalesce(fair_value_matches and fair_value_only_rule_id is not null, false) as is_subtotal
    -- The fund rule, where the row is a subtotal only through it (fair value ties, the cost test does not pass).
    , case
        when coalesce(fair_value_matches and (not cost_needed or (cost_comparable and cost_matches)), false) then null
        when coalesce(fair_value_matches, false) then fair_value_only_rule_id
      end as subtotal_rule_id
    -- Why the general rule 6 does not pass, whether or not a fund rule then makes the row a subtotal.
    , case
        when not fair_value_matches then 'fair_value_differs'
        when cost_needed and not cost_comparable then 'cost_not_comparable'
        when cost_needed and not cost_matches then 'cost_differs'
      end as near_miss_reason
from tested
) s
full join main.int_role_subtotal b on b.accession = s.accession and b.context_id = s.context_id
where s.is_subtotal is distinct from b.is_subtotal or s.near_miss_reason is distinct from b.near_miss_reason
limit 200

