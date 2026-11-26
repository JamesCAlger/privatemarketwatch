-- Slice 5 Task 4 (carried from the Task 3 review): identifier-keyed corrections matched here natively (the identifier
-- label of a position of the same filing) whose production holdings rows of the same filing and identifier name a
-- context other than the one(s) matched here: production would set another row than this layer does. Counted by
-- correction, against a ceiling set to the measured count (baseline_max.int_correction_identifier_production_context).
{{ config(tags=['baseline_ceiling'], severity='error', warn_if='>0',
          error_if='>' ~ var('baseline_max')['int_correction_identifier_production_context']) }}
with native as (
    select t.correction_id, t.cik, t.accession, t.context_id, t.field, c.identifier
    from {{ ref('int_correction_target') }} t
    join {{ ref('stg_correction') }} c on c.correction_id = t.correction_id
    where t.key_resolution = 'identifier_native'
)

, production as (
    select distinct n.correction_id, h.src_context_id
    from native n
    join {{ ref('stg_holdings') }} h
        on h.accession_number = n.accession and trim(h.bdc_investment_identifier) = n.identifier
)

, other as (
    -- production's contexts that are not a context matched here
    select p.correction_id, p.src_context_id
    from production p
    anti join native n on n.correction_id = p.correction_id and n.context_id = p.src_context_id
)

select
    n.correction_id
    , any_value(n.cik) as cik
    , any_value(n.accession) as accession
    , any_value(n.field) as field
    , string_agg(distinct n.context_id, ',') as contexts_here
    , (select string_agg(o.src_context_id, ',' order by o.src_context_id) from other o
       where o.correction_id = n.correction_id) as contexts_production_other
from native n
semi join other o on o.correction_id = n.correction_id
group by n.correction_id
