-- No fund has two fund rules of one action that can apply to the same thing at the same time: validity periods
-- overlap (an open end counts as unbounded) and the selectors can match the same fact or row. A duplicate would
-- multiply rows silently (int_role_subtotal joins the subtotal rule; int_context_feature takes min(rule_id)).
--   concept_is_fair_value, concept_is_cost,       : same concept namespace pattern and local name, and the same
--   concept_is_term_fact                           accession or no accession on either
--   subtotal_on_fair_value                       : any two
with r as (
    select rule_id, cik, action, sel_concept_namespace, sel_concept_local, sel_accession
        , coalesce(valid_from, date '0001-01-01') as vf, coalesce(valid_to, date '9999-12-31') as vt
    from {{ ref('stg_reading_rule') }}
    where action in ('concept_is_fair_value', 'concept_is_cost', 'concept_is_term_fact', 'subtotal_on_fair_value')
)
select a.cik, a.action, a.rule_id as rule_a, b.rule_id as rule_b
from r a
join r b on b.cik = a.cik and b.action = a.action and a.rule_id < b.rule_id
    and a.vf <= b.vt and b.vf <= a.vt
where a.action = 'subtotal_on_fair_value'
   or (a.sel_concept_namespace = b.sel_concept_namespace and a.sel_concept_local = b.sel_concept_local
       and (a.sel_accession is null or b.sel_accession is null or a.sel_accession = b.sel_accession))
