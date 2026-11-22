{#- Contexts whose cost is tagged twice: exactly two distinct (unit, value) cost facts, one in US dollars and one in
    another currency (pipeline/cost_in_two_units.py two_unit_costs). Returns accession, context_id, usd_value,
    foreign_value, foreign_unit. Only contexts listed in `contexts` (a relation or CTE with accession, context_id) are
    read. The cost concept comes from seeds/concept_map.csv (field cost), never a literal. -#}
{% macro two_unit_cost_facts(contexts) %}
    select accession, context_id
        , max(value_numeric) filter (where unit = 'iso4217:USD') as usd_value
        , max(value_numeric) filter (where unit <> 'iso4217:USD') as foreign_value
        , max(unit) filter (where unit <> 'iso4217:USD') as foreign_unit
    from (
        select distinct f.accession, f.context_id, u.numerator as unit, f.value_numeric
        from {{ ref('stg_filed_fact') }} f
        semi join {{ contexts }} c on c.accession = f.accession and c.context_id = f.context_id
        join {{ ref('concept_map') }} m
            on m.field = 'cost' and m.concept_local = f.concept_local and f.concept_namespace glob m.namespace_pattern
        join {{ ref('stg_filed_unit') }} u on u.accession = f.accession and u.unit_id = f.unit_id
        where not f.is_nil and f.value_numeric is not null and u.denominator is null
    )
    group by 1, 2
    having count(*) = 2
        and count(*) filter (where unit = 'iso4217:USD') = 1
        and count(*) filter (where regexp_full_match(unit, 'iso4217:[A-Z]{3}') and unit <> 'iso4217:USD') = 1
{% endmacro %}
