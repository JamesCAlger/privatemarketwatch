-- Plan item K3 (owner 2026-11-26; slice R phase 3 fix round 1): a reading a hard constraint blocks is kept as a HELD
-- value beside the field, marked with the constraint, not written into the shared field and not dropped. One row per
-- (accession, context_id, field, rule_id): each read cell value of a field that int_text_rate_read did not apply
-- because of constraints 1 to 3.
--   field spread, pik_spread  constraint A1_spread_needs_reference_rate (no code printed on the position)
--   field floor               constraint A2_floor_needs_reference_rate
--   field fixed_rate          constraint A3_fixed_with_floating_terms (a fixed reading beside a reference rate, a
--                             printed code, a spread or a floor)
-- value: the printed value as the rule read it; rule_id, source_grade: the rule; cell_text: the printed text.
with blocked as (
    select accession, context_id, cik, report_date, is_published, 'spread' as field
        , 'A1_spread_needs_reference_rate' as constraint_name
    from {{ ref('int_text_rate_read') }} where spread_status = 'constraint_spread_needs_reference_rate'
    union all
    select accession, context_id, cik, report_date, is_published, 'pik_spread', 'A1_spread_needs_reference_rate'
    from {{ ref('int_text_rate_read') }} where pik_spread_status = 'constraint_spread_needs_reference_rate'
    union all
    select accession, context_id, cik, report_date, is_published, 'floor', 'A2_floor_needs_reference_rate'
    from {{ ref('int_text_rate_read') }} where floor_status = 'constraint_floor_needs_reference_rate'
    union all
    select accession, context_id, cik, report_date, is_published, 'fixed_rate', 'A3_fixed_with_floating_terms'
    from {{ ref('int_text_rate_read') }} where all_in_rate_status = 'constraint_fixed_with_floating_terms'
)

select
    b.accession
    , b.context_id
    , b.cik
    , b.report_date
    , b.is_published
    , b.field
    , b.constraint_name
    , c.rule_id
    , min(c.value) as value
    , any_value(c.source_grade) as source_grade
    , min(c.cell_text) as cell_text
from blocked b
join {{ ref('int_text_rate_read_cell') }} c
    on c.accession = b.accession and c.context_id = b.context_id and c.field = b.field and c.status = 'read'
group by all
