-- Row roles against the printed page (measurement, 2026-11-26). The role is built from the tagged row's label and
-- amounts (slice 2); this reads the label printed on the row where the context's facts sit. Read-only.
-- printed label = the first non-empty cell of the printed row. "total label" = it starts with Total or Subtotal.
with placed as (
    select fp.accession, fp.context_id, min(fp.row_index) as row_index, count(distinct fp.row_index) as n_rows
    from stg_filed_fact_placement fp
    where fp.row_index is not null and not fp.in_hidden
    group by 1, 2
)
, label as (
    select accession, row_index, arg_min(text, col_start) as printed_label
    from int_page_cell where trim(text) <> '' group by 1, 2
)
select r.cik, r.role
    , count(*) as tagged_rows
    , count(*) filter (where p.context_id is null) as not_on_a_printed_row
    , count(*) filter (where p.n_rows > 1) as on_several_rows
    , count(*) filter (where p.n_rows = 1 and regexp_matches(l.printed_label, '(?i)^\s*(sub\s*-?\s*)?total')) as total_label
    , count(*) filter (where p.n_rows = 1 and l.printed_label is not null and not regexp_matches(l.printed_label, '(?i)^\s*(sub\s*-?\s*)?total')) as other_label
    , count(*) filter (where p.n_rows = 1 and l.printed_label is null) as no_label_cell
    , min(l.printed_label) filter (where p.n_rows = 1 and (r.role = 'position') = regexp_matches(l.printed_label, '(?i)^\s*(sub\s*-?\s*)?total')) as example_against_role
from int_source_row r
left join placed p using (accession, context_id)
left join label l on l.accession = p.accession and l.row_index = p.row_index
where r.role in ('position', 'aggregate', 'unresolved')
group by 1, 2 order by 1, 2
