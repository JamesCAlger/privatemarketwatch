-- Slice 5 Task 3 proof: contexts corrections make positions, per fund, quarter and row reason, with the role they had,
-- whether production has a row for them on the published basis, and their corrected fair value.
select r.cik, r.report_date, r.row_reason, r.role_filed, r.role_rule_filed, r.is_published, count(*) as contexts
    , count(*) filter (where exists (
        select 1 from main.stg_holdings h
        where h.accession_number = r.accession and h.src_context_id = r.context_id
          and coalesce(h.accounting_record_class, '') <> 'underlying_schedule')) as in_production_published
    , sum(f.value) as fair_value_corrected
    , sum(c.value) as cost_corrected
from main.int_row_corrected r
left join main.int_field_corrected f on f.accession = r.accession and f.context_id = r.context_id and f.field = 'fair_value'
left join main.int_field_corrected c on c.accession = r.accession and c.context_id = r.context_id and c.field = 'cost'
where r.row_reason <> 'filed'
group by all
order by 1, 2, 3
