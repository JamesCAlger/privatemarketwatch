-- Owner question (b), 2026-11-25: the nearest column header printed above each of the 14 BCRED "Units" rows whose
-- principal production empties (a row above the principal's row whose cells name par, principal, units or shares).
-- Read-only.
with r as (
    select accession, context_id, report_date
    from cmp_amount
    where cause_detail = 'principal_emptied_before_section_reclass' and field = 'principal_amount' and basis = 'published'
)
, p as (
    select f.accession, f.context_id, min(pl.row_index) as row_index
    from stg_filed_fact f
    join stg_filed_fact_placement pl on pl.accession = f.accession and pl.fact_id = f.fact_id
    semi join r on r.accession = f.accession and r.context_id = f.context_id
    where f.concept_local = 'InvestmentOwnedBalancePrincipalAmount'
    group by 1, 2
)
, h as (
    select p.accession, p.context_id, p.row_index, d.row_index as header_row
        , array_to_string(list_filter(d.cells, x -> trim(x) <> ''), ' | ') as header
    from p
    join stg_filed_document_row d on d.accession = p.accession and d.row_index < p.row_index
        and d.row_index > p.row_index - 400
    where regexp_matches(lower(array_to_string(d.cells, ' ')), 'par |par/|principal|units|shares')
      and regexp_matches(lower(array_to_string(d.cells, ' ')), 'fair value')
    qualify row_number() over (partition by p.accession, p.context_id order by d.row_index desc) = 1
)
select r.report_date, left(r.context_id, 12) as ctx, h.row_index - h.header_row as rows_above, left(h.header, 200) as header
from r left join h on h.accession = r.accession and h.context_id = r.context_id
order by 1, 2
