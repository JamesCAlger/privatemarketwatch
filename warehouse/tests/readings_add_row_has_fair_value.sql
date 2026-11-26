-- Slice 5 Task 2: every position an agent row_add adds (add_group_id) carries a fair value, and one accession and
-- context id. Production refuses a row_add position without a numeric fair value (pipeline/agent_rule.py).
select add_group_id, count(*) filter (where field = 'fair_value') as fair_values
    , count(distinct accession) as accessions, count(distinct context_id) as contexts
from {{ ref('stg_correction') }}
where kind = 'add_row'
group by add_group_id
having count(*) filter (where field = 'fair_value') <> 1 or count(distinct accession) <> 1 or count(distinct context_id) <> 1
