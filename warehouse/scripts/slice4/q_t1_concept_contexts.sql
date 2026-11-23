-- Slice 4 Task 1: every context of one fund (variable cik, given as a LIKE pattern so it stays text) that carries a fact
-- of one concept (variable concept), with its role, scope, whether its filing is selected, and its fair value.
-- Reconciles the 35 commitment contexts of docs/baseline_amounts_2026-11-22.md with the position rows. Read-only.
select s.report_date, s.accession, s.context_id, s.role, s.role_rule, s.scope, cf.fair_value, cf.identifier_label
from stg_filed_fact f
join int_source_row s on s.accession = f.accession and s.context_id = f.context_id
join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
where s.cik like getvariable('cik') and f.concept_local = getvariable('concept')
group by all
order by s.report_date, s.context_id
limit 100
