-- Slice 5 Task 5: the rows carried from Task 4 (controller notes) in cmp_rate after the change, and the 7 Blue Owl
-- rate corrections that failed (rate_reading_unresolved). Read-only.
with carried as (
    select accession, context_id from (values
        ('0001838126-25-000017', 'c-157'),
        ('0001287750-25-000038', 'c-1268'),
        ('0001287750-25-000007', 'c-1544'),
        ('0001628280-26-020206', 'c-934'), ('0001628280-26-033248', 'c-912'), ('0001838126-25-000073', 'c-903'),
        ('0000950170-24-031479', 'C_1de7bac0-e623-43c0-baa0-84f215e548a2'),
        ('0000950170-24-058684', 'C_a98dfaae-3949-4d9e-8d76-c18c1c405aa5')
    ) v(accession, context_id)
    union
    select accession, context_id from int_correction_application where reason = 'rate_reading_unresolved'
)
select r.accession, r.context_id, r.field, r.outcome, r.cause, r.cause_detail,
    coalesce(cast(r.value_new as varchar), r.text_new) as new,
    coalesce(cast(r.value_normalised as varchar), r.text_normalised) as normalised,
    coalesce(cast(r.value_production as varchar), r.text_production) as prod, r.new_reason, r.correction_id
from cmp_rate r
join carried c using (accession, context_id)
where r.field in ('interest_rate', 'interest_rate_cash', 'rate_kind', 'pik_rate', 'spread')
order by 1, 2, 3
