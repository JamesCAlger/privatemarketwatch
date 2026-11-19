-- Final fix wave F7: filed labels with a plural or hyphenated money-market spelling, and how rules 0 to 9 decided them.
select r.role, r.role_rule, r.is_cash, r.cash_pattern_id, cf.identifier_label, count(*) as n
from int_source_row r
join int_context_feature cf using (accession, context_id)
where regexp_matches(lower(cf.identifier_label), 'money[\s-]+markets?\s+(\w+\s+)?(funds|portfolios|fund\(s\))|money-market')
group by all
order by all
