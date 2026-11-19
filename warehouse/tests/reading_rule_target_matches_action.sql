-- Every loaded rule names the target its action declares in seeds/reading_action.csv. A rule whose target differs
-- would be read by the models under its action while saying something else. (An action missing from the seed is
-- caught by the relationship test on stg_reading_rule.action.)
select r.rule_id, r.cik, r.origin, r.action, r.target, a.target as declared_target
from {{ ref('stg_reading_rule') }} r
join {{ ref('reading_action') }} a on a.action = r.action
where r.target is distinct from a.target
