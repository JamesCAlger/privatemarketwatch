-- Slice 4 Task 1: position rows of one fund (variable cik) in a scope other than the fund (the JV schedules), with the
-- term facts present, the term-fact source, the fair value and cost, and the label. Read-only. Used to see which
-- row features separate the commitment lines from the schedule rows.
select s.report_date, s.context_id, s.scope, s.role_rule, cf.term_fact_source
    , cf.has_principal, cf.has_shares, cf.has_rate, cf.has_spread, cf.has_pik_rate, cf.has_maturity
    , cf.fair_value, cf.cost, cf.cost_fact_count, cf.identifier_label
from int_source_row s
join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
where s.cik = getvariable('cik') and s.role = 'position' and s.scope <> 'fund'
  and cf.term_fact_source <> 'standard'
order by s.report_date, s.context_id
limit 200
