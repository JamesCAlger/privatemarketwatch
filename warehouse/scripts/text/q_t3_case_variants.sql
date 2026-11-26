-- Text slice R phase 3, check fix 1b: proposed shapes of one unit whose upper-case forms coincide (case variants that
-- int_text_rate_proposed and int_text_proposal_verdict pooled through the upper-case shape key).
select unit_key, upper(shape) as shape_key_text, list(distinct shape order by shape) as shapes
    , count(distinct shape) as n_variants
    , list(distinct role_fwd order by role_fwd) as roles_fwd
from text_proposed_shape_role
group by 1, 2
having count(distinct shape) > 1
order by 1, 2
