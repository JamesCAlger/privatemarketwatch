-- Slice 4 Task 1: candidate commitment lines (position, no cost fact, no standard term fact: the term fact comes from a
-- fund concept rule) with a non-zero fair value, and every other position row of the same filing and scope with the same
-- fair value, by value only (no borrower test yet), with both labels. Read-only. Variable cik ('%' for all funds).
with pos as (
    select s.accession, s.context_id, s.cik, s.report_date, s.scope, s.is_published
        , cf.fair_value, cf.cost_fact_count, cf.term_fact_source, cf.identifier_label
    from int_source_row s
    join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.role = 'position' and s.cik like getvariable('cik')
)
, line as (
    select * from pos
    where term_fact_source is distinct from 'standard' and cost_fact_count = 0 and fair_value <> 0
)
select l.cik, l.report_date, l.context_id, l.scope, l.fair_value, l.identifier_label as line_label
    , t.context_id as twin_context, t.term_fact_source as twin_term_source, t.identifier_label as twin_label
from line l
left join pos t on t.accession = l.accession and t.scope = l.scope and t.context_id <> l.context_id
    and t.fair_value = l.fair_value
order by l.cik, l.report_date, l.context_id, t.context_id
limit 400
