-- as_filed and reported_in_usd change nothing: the value equals value_filed (for principal_amount_usd, value_filed is
-- the principal). to_usd: the value is the principal times the rate, and the rate and its date are filled. No other
-- action carries a rate.
select accession, context_id, field, action, value, value_filed, fx_rate
from {{ ref('int_field_normalised') }}
where status = 'normalised'
  and (
      (action in ('as_filed', 'reported_in_usd') and value is distinct from value_filed)
      or (action = 'to_usd' and (fx_rate is null or fx_rate_date is null or value is distinct from value_filed * fx_rate))
      or (action <> 'to_usd' and (fx_rate is not null or fx_rate_date is not null))
  )
