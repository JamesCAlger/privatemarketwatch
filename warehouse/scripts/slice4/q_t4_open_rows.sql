-- Slice 4 Task 4: open the printed schedule row of a sample of each cause group of cmp_rate. Up to 4 rows per
-- (field, cause, cause_detail), chosen by a hash of the key (deterministic), from the filed layer: the row of the
-- document holding the position's fair-value fact. Prints this layer's and production's values beside the text.
with open as (
    select r.*, hash(r.accession || '|' || r.context_id || '|' || r.field) as h
    from cmp_rate r
    where r.cause is not null
)
, sample as (
    select * from open
    qualify row_number() over (partition by field, cause, cause_detail order by h) <= 4
)
, fv as (
    select s.accession, s.context_id, s.field, rd.fact_id
    from sample s
    join int_field_read rd on rd.accession = s.accession and rd.context_id = s.context_id and rd.field = 'fair_value'
)
, printed as (
    select f.accession, f.context_id, f.field, array_to_string(dr.cells, ' | ') as row_text
    from fv f
    join stg_filed_fact_placement pl on pl.accession = f.accession and pl.fact_id = f.fact_id
    join stg_filed_document_row dr on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
    qualify row_number() over (partition by f.accession, f.context_id, f.field order by dr.row_index) = 1
)
select s.field, s.cause, s.cause_detail, s.cik, s.report_date, s.accession, s.context_id, s.outcome,
    coalesce(s.value_new::varchar, s.date_new::varchar, s.text_new) as new,
    coalesce(s.value_production::varchar, s.date_production::varchar, s.text_production) as production,
    s.new_reason, s.production_source, left(p.row_text, 260) as printed_row
from sample s
left join printed p on p.accession = s.accession and p.context_id = s.context_id and p.field = s.field
order by s.field, s.cause, s.cause_detail, s.accession, s.context_id
