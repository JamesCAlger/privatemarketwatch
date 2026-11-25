-- Slice 5 Task 5: the published cmp_rate rows whose detail ceiling rose in this task, by detail, against the snapshot
-- taken at the start of the task (rows added to a detail, and rows that left it). Read-only.
with b as (select * from read_parquet('../scratch/2026-11-25_slice5_t5/snap/cmp_rate_before.parquet'))
, a as (select * from cmp_rate)
, keyed as (
    select coalesce(a.field, b.field) as field, coalesce(a.accession, b.accession) as accession,
        coalesce(a.context_id, b.context_id) as context_id, b.cause_detail as before_detail, a.cause_detail as after_detail,
        a.outcome
    from a full join b on b.accession = a.accession and b.context_id = a.context_id and b.field = a.field
    where coalesce(a.basis, b.basis) = 'published'
)
select field, after_detail as detail, 'added' as move, accession, context_id, before_detail, outcome
from keyed
where after_detail in ('identifier_text_not_read', 'printed_rate_type_and_loan_class_not_read',
                       'printed_reference_rate_column_not_read', 'cash_equals_all_in_owner_ruling',
                       'printed_maturity_not_read', 'same_identifier_context_fill_not_built')
  and after_detail is distinct from before_detail
union all
select field, before_detail, 'left', accession, context_id, after_detail, outcome
from keyed
where before_detail in ('identifier_text_not_read', 'printed_rate_type_and_loan_class_not_read',
                        'printed_reference_rate_column_not_read', 'cash_equals_all_in_owner_ruling',
                        'printed_maturity_not_read')
  and after_detail is distinct from before_detail
order by 1, 2, 3, 4, 5
