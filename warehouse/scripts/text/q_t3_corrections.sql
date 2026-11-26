-- Text slice R phase 3: row corrections on rate fields (applied or failed, int_correction_application) and on the
-- reference rate and coupon type (deferred, field_not_held) against the rule-read value of the same position.
-- Fields: interest_rate -> all_in_rate, basis_spread -> spread, pik_rate -> pik_rate, reference_rate_type ->
-- reference_rate, coupon_type -> rate_type. agrees: equal within 0.005 (text: upper case equal). Read-only.
with c as (
    -- the correction's value: value_after where applied, else the stored value (deferred rows carry none after)
    select a.cik, a.field, a.outcome, a.accession, a.context_id
        , case when a.outcome = 'applied' then a.value_after else s.value end as value_after
    from int_correction_application a
    join stg_correction s on s.correction_id = a.correction_id
    where a.field in ('interest_rate', 'basis_spread', 'pik_rate', 'reference_rate_type', 'coupon_type')
        and a.outcome in ('applied', 'failed', 'deferred')
)
, j as (
    select c.*, r.accession is not null as has_read
        , case c.field when 'interest_rate' then r.all_in_rate::varchar when 'basis_spread' then r.spread::varchar
                       when 'pik_rate' then r.pik_rate::varchar when 'reference_rate_type' then r.reference_rate
                       when 'coupon_type' then r.rate_type end as v_new
        , case c.field when 'interest_rate' then r.all_in_rate_status when 'basis_spread' then r.spread_status
                       when 'pik_rate' then r.pik_rate_status when 'reference_rate_type' then r.reference_rate_status
                       when 'coupon_type' then coalesce(r.rate_type, 'no_type') end as new_status
    from c
    left join int_text_rate_read r on r.accession = c.accession and r.context_id = c.context_id
)
select cik, field, outcome
    , case
        when not has_read then 'no_ruled_cell'
        when v_new is null and nullif(value_after, '') is null then 'both_empty'
        when v_new is null then 'rule_reads_nothing (' || new_status || ')'
        when nullif(value_after, '') is null then 'correction_empties'
        when try_cast(v_new as double) is not null and try_cast(value_after as double) is not null
             and abs(try_cast(v_new as double) - try_cast(value_after as double)) <= 0.005 then 'agrees'
        when upper(v_new) = upper(value_after) then 'agrees'
        else 'differs'
      end as result
    , count(*) as corrections
    , min(case when v_new is not null and nullif(value_after, '') is not null then v_new || ' vs ' || value_after end) as example
from j
group by all
order by 1, 2, 3, 4
