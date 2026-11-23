-- Decides, for every position row and each of the ten tagged fields, which filed fact is the field's value, unchanged
-- (spec intermediate_spine.md 6.3). One row per (accession, context_id, field), present or not.
--
-- Fields: the five amounts fair_value, cost, principal_amount, shares, pct_of_net_assets (slice 3), and since slice 4
-- Task 2 interest_rate_tag, interest_rate_cash_tag, pik_rate, spread (numbers) and maturity_date (a date). The two _tag
-- fields are the interest-rate and the cash-pay concept as filed, before any reading decides which leg they hold.
-- Rows: every context int_source_row calls a position, published or not.
-- Concepts: the seed concept_map, column read_field (local name plus namespace glob, never the prefix: filed_layer.md
-- section 7 ruling 12). Its column field groups the two rate concepts as "a rate" for the row roles; it is not read
-- here. For fair value a fund rule concept_is_fair_value, and for cost a fund rule concept_is_cost (stg_reading_rule, slice
-- 3 Task 4 fix round 1), adds the filer's own concept, inside the rule's dates. int_context_feature reads only
-- concept_is_fair_value, so a cost rule moves no role. The standard concept wins: a fund rule's concept is read only where the context has no fact of a
-- standard concept for the field, as int_context_feature does. Facts of two seed rows of one field (the us-gaap and the
-- FASB supplement namespace of one local name) are read together.
-- What "as filed" means: value_filed is the instance value. In an inline filing the printed number carries scale and
-- sign attributes (fact_placement.scale, .sign); the instance holds the number after them (filed_layer.md section 2:
-- "values already scaled and signed"). Nothing else is done here: no currency conversion, no sign flip, no rescaling,
-- and a rate stays as tagged (0.0925 stays 0.0925; no times 100).
-- A date field (maturity_date): the filed layer stores a date fact as text (value_text, as written in the instance,
-- no unit, value_numeric null). It is read into value_date when the text is an ISO date (YYYY-MM-DD) that casts to a
-- date; value_filed stays null. A non-nil date fact whose text is not such a date makes the field unresolved
-- (not_a_date), like a number field's fact with no number.
-- Status:
--   read        one distinct value among the facts (repeats of one value agree; fact_count says how many), or only
--               nil facts (value null, is_nil true). A nil fact beside a value does not block the value.
--   unresolved  two different values, the same number in two units, or a non-nil fact with no number (a number field)
--               or no ISO date (a date field). No value is chosen (D5); fact_count and read_rule_id say what was found.
--   absent      no fact of any concept for the field.
-- The fact named on a read row: a fact with a number before a nil one, a fact placed in a printed row before one that
-- is not, then the first in the instance.
-- printed_text: the text of the same fact where the filed layer placed it: the printed text when the fact sits in a
-- kept table row; for a hidden fact, the text of the cell that shows it (-sec-ix-hidden); else null.
with position as (
    select accession, context_id, cik, report_date
    from {{ ref('int_source_row') }}
    where role = 'position'
)

, field_list as (
    -- value_kind: number (value_numeric) or date (value_text read as an ISO date)
    select field, value_kind
    from (values
        ('fair_value', 'number'), ('cost', 'number'), ('principal_amount', 'number'), ('shares', 'number')
        , ('pct_of_net_assets', 'number'), ('interest_rate_tag', 'number'), ('interest_rate_cash_tag', 'number')
        , ('pik_rate', 'number'), ('spread', 'number'), ('maturity_date', 'date')
    ) v(field, value_kind)
)

, filing as (
    select accession, cik, document_period_end_date
    from {{ ref('stg_filed_filing') }}
)

, position_fact as (
    select f.*
    from {{ ref('stg_filed_fact') }} f
    semi join position p on p.accession = f.accession and p.context_id = f.context_id
)

, standard_fact as (
    -- facts of a standard concept (seed concept_map, column read_field) for one of the ten fields; tier 1
    select
        f.accession
        , f.context_id
        , m.read_field as field
        , m.concept_map_id as read_rule_id
        , 1 as tier
        , f.fact_id
        , f.fact_index
        , f.unit_id
        , f.value_numeric
        , f.value_text
        , f.decimals
        , f.is_nil
    from position_fact f
    join {{ ref('concept_map') }} m
        on m.concept_local = f.concept_local and f.concept_namespace glob m.namespace_pattern
    where m.read_field in (select field from field_list)
)

, filer_fact as (
    -- facts of a filer's own fair-value or cost concept, by a fund rule concept_is_fair_value or concept_is_cost;
    -- tier 2
    select
        f.accession
        , f.context_id
        , case r.action when 'concept_is_fair_value' then 'fair_value' when 'concept_is_cost' then 'cost' end as field
        , r.rule_id as read_rule_id
        , 2 as tier
        , f.fact_id
        , f.fact_index
        , f.unit_id
        , f.value_numeric
        , f.value_text
        , f.decimals
        , f.is_nil
    from position_fact f
    join filing fi on fi.accession = f.accession
    join {{ ref('stg_reading_rule') }} r
        on r.action in ('concept_is_fair_value', 'concept_is_cost')
        and r.cik = fi.cik
        and f.concept_namespace glob r.sel_concept_namespace
        and r.sel_concept_local = f.concept_local
        and (r.sel_accession is null or r.sel_accession = f.accession)
        and (r.valid_from is null or r.valid_from <= fi.document_period_end_date)
        and (r.valid_to is null or r.valid_to >= fi.document_period_end_date)
)

, candidate as (
    -- the facts of the best tier present for the context and field
    select *
    from (select * from standard_fact union all select * from filer_fact)
    qualify tier = min(tier) over (partition by accession, context_id, field)
)

, typed as (
    -- the value of each fact in its field's kind: a number, or a date read from the text (ISO form only)
    select
        c.* exclude (value_numeric, value_text)
        , fl.value_kind
        , case when fl.value_kind = 'number' then c.value_numeric end as value_numeric
        , case
            when fl.value_kind = 'date' and not c.is_nil and regexp_full_match(trim(c.value_text), '\d{4}-\d{2}-\d{2}')
                then try_cast(trim(c.value_text) as date)
          end as value_date
    from candidate c
    join field_list fl on fl.field = c.field
)

, described as (
    select
        c.*
        , case when u.denominator is null then u.numerator else u.numerator || '/' || u.denominator end as unit
        -- a non-nil fact with no value of its field's kind: no number, or no ISO date
        , not c.is_nil and c.value_numeric is null and c.value_date is null as is_not_numeric
        , case
            when pl.row_index is not null then pl.displayed_text
            when pl.shown_row_index is not null then dr.cells[pl.shown_cell_index + 1]
          end as printed_text
        , pl.row_index is not null or pl.shown_row_index is not null as is_placed
    from typed c
    left join {{ ref('stg_filed_unit') }} u on u.accession = c.accession and u.unit_id = c.unit_id
    left join {{ ref('stg_filed_fact_placement') }} pl on pl.accession = c.accession and pl.fact_id = c.fact_id
    left join {{ ref('stg_filed_document_row') }} dr
        on dr.accession = pl.accession and dr.row_index = pl.shown_row_index and pl.row_index is null
)

, summary as (
    select
        accession
        , context_id
        , field
        , count(*) as fact_count
        , count(*) filter (where is_nil) as nil_count
        , count(*) filter (where is_not_numeric) as not_numeric_count
        -- one of the two is always zero: a field has one value kind
        , count(distinct value_numeric) + count(distinct value_date) as value_distinct
        , count(distinct unit) filter (where not is_nil) as unit_distinct
        , min(read_rule_id) as any_rule_id
        , any_value(value_kind) as value_kind
    from described
    group by 1, 2, 3
)

, chosen as (
    select *
    from described
    qualify row_number() over (
        partition by accession, context_id, field
        order by is_nil, (not is_placed), fact_index
    ) = 1
)

, decided as (
    select
        s.accession
        , s.context_id
        , s.field
        , s.fact_count
        , case
            when s.not_numeric_count > 0 then 'unresolved'
            when s.value_distinct > 1 then 'unresolved'
            when s.unit_distinct > 1 then 'unresolved'
            else 'read'
          end as status
        , case
            when s.not_numeric_count > 0 and s.value_kind = 'date' then 'not_a_date'
            when s.not_numeric_count > 0 then 'fact_without_number'
            when s.value_distinct > 1 then 'values_differ'
            when s.unit_distinct > 1 then 'units_differ'
            when s.value_distinct = 0 then 'nil'
            when s.fact_count = 1 then 'one_fact'
            when s.nil_count > 0 then 'value_beside_nil'
            else 'same_value_repeated'
          end as reason
        , s.any_rule_id
        , ch.read_rule_id
        , ch.fact_id
        , ch.value_numeric
        , ch.value_date
        , ch.unit
        , ch.decimals
        , ch.printed_text
        , ch.is_nil
    from summary s
    join chosen ch on ch.accession = s.accession and ch.context_id = s.context_id and ch.field = s.field
)

select
    p.accession
    , p.context_id
    , fl.field
    , p.cik
    , p.report_date
    , coalesce(d.status, 'absent') as status
    , coalesce(d.reason, 'no_fact') as reason
    , case when d.status = 'read' then d.value_numeric end as value_filed
    -- filled only for the date field maturity_date (value_filed stays null there)
    , case when d.status = 'read' then d.value_date end as value_date
    , case when d.status = 'read' then d.unit end as unit
    , case when d.status = 'read' then d.decimals end as decimals
    , case when d.status = 'read' then d.fact_id end as fact_id
    , coalesce(d.fact_count, 0) as fact_count
    , case when d.status = 'read' then d.printed_text end as printed_text
    , coalesce(d.status = 'read' and d.is_nil, false) as is_nil
    -- the rule the facts were found under; on an unresolved row the rule of any of its facts (one tier, so one kind)
    , case when d.status = 'read' then d.read_rule_id else d.any_rule_id end as read_rule_id
from position p
cross join field_list fl
left join decided d on d.accession = p.accession and d.context_id = p.context_id and d.field = fl.field
