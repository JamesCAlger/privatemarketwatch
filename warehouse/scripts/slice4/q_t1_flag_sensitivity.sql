-- Slice 4 Task 1: what the borrower test of int_repeated_commitment_value leaves out. For each fund, commitment lines
-- with a non-zero fair value, and how many have a non-commitment position of the same filing and scope with the same
-- fair value: any borrower (value only), the same first word of the borrower key, the same borrower key (the flag).
-- Read-only.
with p as (
    select r.*, cf.fair_value, split_part(r.borrower_key, ' ', 1) as first_word
    from int_repeated_commitment_value r
    join int_context_feature cf on cf.accession = r.accession and cf.context_id = r.context_id
)
, l as (select * from p where is_commitment_line and fair_value <> 0)
, m as (
    select l.cik, l.accession, l.context_id, l.is_repeated_commitment_value
        , bool_or(t.context_id is not null) as value_twin
        , bool_or(t.first_word = l.first_word) as first_word_twin
    from l
    left join p t on t.accession = l.accession and t.scope = l.scope and t.context_id <> l.context_id
        and not t.is_commitment_line and t.fair_value = l.fair_value
    group by all
)
select cik, count(*) as lines_nonzero
    , count(*) filter (where value_twin) as value_only_twin
    , count(*) filter (where first_word_twin) as first_word_twin
    , count(*) filter (where is_repeated_commitment_value) as flagged
from m
group by cik
order by cik
