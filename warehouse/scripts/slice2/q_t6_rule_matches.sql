-- Task 6: per label-pattern fund rule, open contexts it matches, how many it released (role position through it), and
-- the roles of the matched contexts it did not release (a match on a row that has a term fact or that rules 4 to 6
-- decide does nothing).
select r.cik, f.position_rule_id as rule_id, s.role, s.role_rule, s.position_rule_id is not null as released
    , count(*) as n
from int_role_fund_position f
join int_source_row s using (accession, context_id)
join stg_reading_rule r on r.rule_id = f.position_rule_id
group by all
order by all
