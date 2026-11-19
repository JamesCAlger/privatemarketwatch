-- Task 5: snapshot of every context's role, for the before/after comparison of the move (q_t5_compare.sql).
select r.*, cf.fair_value_source, cf.term_fact_source, cf.fair_value, cf.has_term_fact
from int_source_row r
join int_context_feature cf using (accession, context_id)
