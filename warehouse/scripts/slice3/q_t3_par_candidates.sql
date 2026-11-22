-- Slice 3 Task 3: positions with shares and no principal, per fund, with the value-size band they fall in and the
-- structural features a par_tagged_as_units row mode could use (debt term facts, equity word in the label).
with sh as (select accession, context_id, cik, report_date, value_filed as sh from int_field_read where field = 'shares' and status = 'read' and value_filed > 0)
, pa as (select accession, context_id from int_field_read where field = 'principal_amount' and status = 'read' and value_filed is not null)
, co as (select accession, context_id, value_filed as cost from int_field_read where field = 'cost' and status = 'read')
, x as (
    select sh.*, co.cost, cf.has_rate, cf.has_spread, cf.has_pik_rate, cf.has_maturity
        , regexp_matches(lower(coalesce(cf.identifier_label, '')), '(^|[^a-z])(units?|shares?|stock|membership|warrants?)([^a-z]|$)') as eq_word
        , case when co.cost > 0 and sh.sh between 0.8 * co.cost and 1.25 * co.cost then 'near1'
               when co.cost > 0 and sh.sh * 1000 between 0.8 * co.cost and 1.25 * co.cost then 'near1000'
               when co.cost > 0 and sh.sh * 1000000 between 0.8 * co.cost and 1.25 * co.cost then 'near1e6'
               when co.cost > 0 and sh.sh between 0.5 * co.cost and 2 * co.cost then 'wide1'
               else 'out' end as band
    from sh anti join pa on pa.accession = sh.accession and pa.context_id = sh.context_id
    left join co on co.accession = sh.accession and co.context_id = sh.context_id
    join int_context_feature cf on cf.accession = sh.accession and cf.context_id = sh.context_id
)
select cik, band, (has_rate or has_spread) as rated, (has_rate or has_spread or has_pik_rate or has_maturity) as debt_term, eq_word, count(*) n
from x group by all order by all
limit 200
