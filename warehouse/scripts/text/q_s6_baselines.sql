-- Slice R phase 2: the three baseline counts. Read-only.
select 'number_not_parsed' k, count(*) n from int_text_rate_proposed where status='number_not_parsed'
union all select 'contradicted', count(*) from int_text_proposal_verdict where verdict='contradicted'
union all select 'identity_fail', count(*) from int_text_check_leg_arithmetic where verdict='fail'
