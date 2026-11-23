-- Owner ruling B (2026-11-23): a scale rule (fund rule ratio_value_is_percent) names one fund, one filing (accession)
-- and, in its parameter, one read field and the printed form its evidence rests on: '<field> percent' or
-- 'spread basis_points' (a printed margin over a reference rate is a spread; a rate tag printed as a margin is a
-- different defect and gets no scale rule). It takes no other selector and no dates (the filing fixes the date).
-- At most one rule per fund, filing and field.
select rule_id, cik, sel_accession, parameter, 'scale rule needs cik, accession and a known field and reading, and nothing else' as problem
from {{ ref('stg_reading_rule') }}
where action = 'ratio_value_is_percent'
  and (cik is null or sel_accession is null
       or not regexp_full_match(coalesce(parameter, ''),
                                '(interest_rate_tag|interest_rate_cash_tag|pik_rate|spread) percent|spread basis_points')
       or sel_axis is not null or sel_member is not null or sel_label is not null or sel_label_pattern is not null
       or sel_feature is not null or sel_concept_namespace is not null or sel_concept_local is not null
       or valid_from is not null or valid_to is not null)
union all
select min(rule_id), cik, sel_accession, split_part(parameter, ' ', 1), 'two scale rules for one fund, filing and field'
from {{ ref('stg_reading_rule') }}
where action = 'ratio_value_is_percent'
group by cik, sel_accession, split_part(parameter, ' ', 1)
having count(*) > 1

