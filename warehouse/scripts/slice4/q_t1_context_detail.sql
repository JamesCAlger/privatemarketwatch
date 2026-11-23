-- Slice 4 Task 1: features of a list of contexts of one filing set (variable ctx, a comma-separated list of
-- accession:context_id) and every other position of the same filing and scope with the same fair value. Read-only.
with want as (
    select split_part(x, ':', 1) as accession, split_part(x, ':', 2) as context_id
    from (select unnest(string_split(getvariable('ctx'), ',')) as x)
)
select s.report_date, s.context_id, s.scope, cf.fair_value, cf.cost, cf.cost_fact_count, cf.term_fact_source
    , cf.has_principal, cf.has_shares, cf.has_rate, cf.has_spread, cf.has_pik_rate, cf.has_maturity
    , cf.identifier_label
    , (select string_agg(t.context_id || ' ' || coalesce(tf.identifier_label, ''), '; ')
       from int_source_row t join int_context_feature tf on tf.accession = t.accession and tf.context_id = t.context_id
       where t.accession = s.accession and t.scope = s.scope and t.role = 'position' and t.context_id <> s.context_id
         and tf.fair_value = cf.fair_value) as value_twins
from want w
join int_source_row s on s.accession = w.accession and s.context_id = w.context_id
join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
order by s.report_date
