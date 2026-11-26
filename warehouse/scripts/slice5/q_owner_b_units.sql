-- Owner question (b), 2026-11-25: the 14 structured-credit rows whose principal production empties. The label, the
-- tagged principal, cost and fair value, and the printed row the principal sits in. Read-only.
with r as (
    select accession, context_id, report_date, value_new as principal
    from cmp_amount
    where cause_detail = 'principal_emptied_before_section_reclass' and field = 'principal_amount' and basis = 'published'
)
, p as (
    select f.accession, f.context_id, min(pl.row_index) as row_index
    from stg_filed_fact f
    join stg_filed_fact_placement pl on pl.accession = f.accession and pl.fact_id = f.fact_id
    where f.concept_local = 'InvestmentOwnedBalancePrincipalAmount'
    group by 1, 2
)
select r.report_date, r.context_id, left(cf.identifier_label, 70) as label, r.principal, cf.cost, cf.fair_value
    , round(cf.cost / nullif(r.principal, 0), 3) as cost_per_unit
    , array_to_string(list_filter(d.cells, x -> x <> ''), ' | ') as printed_row
from r
join int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
left join p on p.accession = r.accession and p.context_id = r.context_id
left join stg_filed_document_row d on d.accession = r.accession and d.row_index = p.row_index
order by 3, 1
