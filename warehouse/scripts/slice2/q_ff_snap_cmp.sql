-- Final fix wave: snapshot of cmp_row_set, for the before/after comparison (q_ff_cmp_moved.sql).
select c.*, cf.identifier_label
from cmp_row_set c
left join int_context_feature cf using (accession, context_id)
