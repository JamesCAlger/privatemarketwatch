-- Owner ruling B (2026-11-23): no normalised rate rests on a number filed above 1 in a ratio unit unless int_rate_scale
-- kept it as a percent under a scale rule. The rate tag and the PIK rate feed interest_rate and interest_rate_cash;
-- the PIK rate feeds pik_rate; the spread feeds spread.
with undecided as (
    select accession, context_id, field
    from {{ ref('int_rate_scale') }}
    where outcome <> 'kept_as_percent'
)

, fed as (
    select * from (values
        ('interest_rate_tag', 'interest_rate'), ('interest_rate_tag', 'interest_rate_cash'),
        ('interest_rate_cash_tag', 'interest_rate'), ('interest_rate_cash_tag', 'interest_rate_cash'),
        ('pik_rate', 'interest_rate'), ('pik_rate', 'interest_rate_cash'), ('pik_rate', 'pik_rate'),
        ('spread', 'spread')
    ) v(read_field, field)
)

select n.accession, n.context_id, n.field, n.value, u.field as undecided_input
from undecided u
join fed f on f.read_field = u.field
join {{ ref('int_field_normalised') }} n
    on n.accession = u.accession and n.context_id = u.context_id and n.field = f.field
where n.status = 'normalised'
