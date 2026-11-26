-- Decides which row each loaded correction acts on (slice 5 Task 3; spec intermediate_spine.md 6.5). One row per
-- (correction_id, target accession, target context_id); a correction with no target has one row with context_id null.
-- Nothing is applied here.
--
-- Key resolution, the first route that holds (key_resolution):
--   context            the correction names a context id (row store by context, wrapper entries, agent add_row): that
--                      context, when the filed layer has it; otherwise not_found
--   row_id             the correction names a production holdings row id (agent B2 leaf): the accession and context of
--                      that row in stg_holdings (and the correction's accession, when it names one, must equal it)
--   identifier_native  the correction names identifier text (row_corrections.csv): every position of the same filing
--                      whose identifier label (int_context_feature.identifier_label) equals the text. A text matching
--                      several positions acts on each (production sets every matching row), target_count says how many
--   production_bridge  identifier text that matches no position here: production's holdings rows of the same filing
--                      with the same identifier (trimmed) give the context (src_context_id). Owner decision 2,
--                      2026-11-24: approved as a NAMED DEBT. These corrections locate their row through production's
--                      holdings file and must be re-keyed by context before this layer can replace production. When
--                      production's rows name more than one context the bridge does not pick one: one row with
--                      context_id null, target_count the number of contexts named (int_correction_application rejects
--                      it, reason bridge_ambiguous)
--   not_found          none of the above
-- target_role is the context's role in int_source_row (null when there is no target). report_date is the
-- correction's, or the target's when the store gives none (wrapper entries). layer_field and step come from seed
-- correction_field (the row whose store_pattern matches the store).
with correction as (
    select
        c.correction_id
        , c.store
        , c.kind
        , c.cik
        , c.accession
        , c.context_id
        , c.identifier
        , c.row_id
        , c.field
        , c.report_date
        , nullif(m.layer_field, '') as layer_field
        , m.step
    from {{ ref('stg_correction') }} c
    left join {{ ref('correction_field') }} m
        on m.correction_field = c.field and regexp_full_match(c.store, m.store_pattern)
)

, by_context as (
    select c.correction_id, c.accession, c.context_id, 'context' as key_resolution, 1 as target_count
    from correction c
    semi join {{ ref('int_source_row') }} s on s.accession = c.accession and s.context_id = c.context_id
    where c.context_id is not null
)

, by_row_id as (
    select
        c.correction_id
        , h.accession_number as accession
        , h.src_context_id as context_id
        , 'row_id' as key_resolution
        , count(*) over (partition by c.correction_id) as target_count
    from correction c
    join {{ ref('stg_holdings') }} h
        on h.row_id = c.row_id and (c.accession is null or c.accession = h.accession_number)
    where c.context_id is null and c.row_id is not null and h.src_context_id is not null
)

, by_identifier as (
    select * from correction where context_id is null and row_id is null and identifier is not null
)

, native as (
    select
        i.correction_id
        , i.accession
        , s.context_id
        , 'identifier_native' as key_resolution
        , count(*) over (partition by i.correction_id) as target_count
    from by_identifier i
    join {{ ref('int_context_feature') }} f on f.accession = i.accession and f.identifier_label = i.identifier
    join {{ ref('int_source_row') }} s
        on s.accession = f.accession and s.context_id = f.context_id and s.role = 'position'
)

, bridge_context as (
    -- the distinct contexts production's rows of the same filing and identifier name, for corrections with no native
    -- position
    select distinct i.correction_id, i.accession, h.src_context_id as context_id
    from by_identifier i
    join {{ ref('stg_holdings') }} h
        on h.accession_number = i.accession and trim(h.bdc_investment_identifier) = i.identifier
    where h.src_context_id is not null
      and i.correction_id not in (select correction_id from native)
)

, bridge as (
    select
        correction_id
        , any_value(accession) as accession
        , case when count(*) = 1 then any_value(context_id) end as context_id
        , 'production_bridge' as key_resolution
        , count(*) as target_count
    from bridge_context
    group by correction_id
)

, resolved as (
    select * from by_context
    union all
    select * from by_row_id
    union all
    select * from native
    union all
    select * from bridge
)

, targeted as (
    select
        c.correction_id
        , c.store
        , c.kind
        , c.cik
        , coalesce(r.accession, c.accession) as accession
        , r.context_id
        , c.field
        , c.layer_field
        , c.step
        , coalesce(r.key_resolution, 'not_found') as key_resolution
        , coalesce(r.target_count, 0) as target_count
        , c.report_date as correction_report_date
    from correction c
    left join resolved r on r.correction_id = c.correction_id
)

select
    t.correction_id
    , t.store
    , t.kind
    , t.cik
    , t.accession
    , t.context_id
    , t.field
    , t.layer_field
    , t.step
    , t.key_resolution
    , t.target_count
    , s.role as target_role
    , coalesce(t.correction_report_date, s.report_date) as report_date
from targeted t
left join {{ ref('int_source_row') }} s on s.accession = t.accession and s.context_id = t.context_id
