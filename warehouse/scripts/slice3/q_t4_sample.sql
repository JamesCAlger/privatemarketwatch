-- Slice 3 Task 4: up to n rows of cmp_amount for one field and cause detail (variables field, detail, n), spread over
-- funds and dates by a stable hash, with the printed row of the read fact (the principal's fact for the currency and
-- dollar principal). Used to choose and open the sample rows of each cause group.
with s as (
    select a.*, row_number() over (partition by a.cik order by hash(a.accession || a.context_id)) as k
    from cmp_amount a
    where a.field = getvariable('field') and a.cause_detail = getvariable('detail')
)
select s.cik, s.report_date, s.accession, s.context_id, s.value_new, s.value_production, s.currency_new
    , s.currency_production, s.new_action
    , left(cast(dr.cells as varchar), 330) as printed_row
from s
left join int_field_read r
    on r.accession = s.accession and r.context_id = s.context_id
    and r.field = case when s.field in ('principal_amount_currency', 'principal_amount_usd') then 'principal_amount'
                       else s.field end
left join stg_filed_fact_placement pl on pl.accession = r.accession and pl.fact_id = r.fact_id
left join stg_filed_document_row dr on dr.accession = pl.accession and dr.row_index = coalesce(pl.row_index, pl.shown_row_index)
where s.k <= getvariable('n')
order by s.cik, s.report_date
limit 40
