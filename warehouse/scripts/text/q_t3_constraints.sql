-- Text slice R phase 3, owner addition A: constraints 4 and 5 by fund, reference rate and verdict / input state.
select cik, constraint_name, reference_rate, coalesce(verdict, '') as verdict, coalesce(input_state, '') as input_state
    , coalesce(all_in_source, '') as all_in_source, count(*) as positions
from int_text_rate_constraint
group by all
order by 1, 2, 3, 4, 5, 6
