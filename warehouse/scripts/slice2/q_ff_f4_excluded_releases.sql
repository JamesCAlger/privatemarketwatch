-- Final fix wave F4: releases in a fund-quarter production lacks (cmp_excluded_quarter), by guard and fund-quarter.
-- fund_rule: a fund rule position_without_term_fact made the row a position (position_rule_id).
-- concept_rule: a position at rule 7 or 9, not cash, whose only term fact is a fund concept rule (as the macro
-- concept_release_unmatched reads it).
select 'fund_rule' as guard, s.cik, s.report_date, count(*) as n
from int_source_row s
join cmp_excluded_quarter x on x.cik = s.cik and x.report_date = s.report_date
where s.position_rule_id is not null
group by all
union all
select 'concept_rule', s.cik, s.report_date, count(*)
from int_source_row s
join int_context_feature cf using (accession, context_id)
join cmp_excluded_quarter x on x.cik = s.cik and x.report_date = s.report_date
where s.role = 'position' and s.role_rule in (7, 9) and not s.is_cash
  and cf.term_fact_source is not null and cf.term_fact_source <> 'standard'
group by all
order by 1, 2, 3
