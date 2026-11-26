-- Text slice R phase 3: the counts the baseline ceilings are set to.
select 'int_text_rate_unread_groups' as baseline, count(*) as n
from (select cik, unit_key, shape, status from int_text_rate_read_cell where status not in ('read', 'no_value') group by all)
union all
select 'int_text_rate_constraint_fail', count(*) from int_text_rate_constraint where verdict = 'fail'
union all
select 'int_text_rate_constraint_dropped'
    , (select count(*) from int_text_rate_read where spread_status like 'constraint%')
      + (select count(*) from int_text_rate_read where pik_spread_status like 'constraint%')
      + (select count(*) from int_text_rate_read where floor_status like 'constraint%')
      + (select count(*) from int_text_rate_read where all_in_rate_status like 'constraint%')
union all
select 'int_text_proposal_contradicted', count(*) from int_text_proposal_verdict
where verdict = 'contradicted' and proposal_kind <> 'shape'
union all
select 'int_text_proposal_contradicted_small', count(*) from int_text_proposal_verdict
where verdict = 'contradicted_small' and proposal_kind <> 'shape'
union all
select 'int_text_leg_identity_fail', count(*) from int_text_check_leg_arithmetic where verdict = 'fail'
union all
select 'leg d not_testable', count(*) from int_text_check_leg_arithmetic where verdict = 'not_testable'
