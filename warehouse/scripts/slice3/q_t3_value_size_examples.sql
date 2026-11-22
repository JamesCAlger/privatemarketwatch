-- Slice 3 Task 3: three example rows per fund and par_tagged_as_units mode: label, share count, cost, scale and the
-- principal it gives. Picked by a stable hash so the same rows come back each run.
with x as (
    select u.cik, u.parameter as mode, u.report_date, u.accession, u.context_id, cf.identifier_label
        , sh.value_filed as share_count, co.value_filed as cost, u.value_scale, n.value as principal_new
        , row_number() over (partition by u.cik, u.parameter order by hash(u.accession || u.context_id)) as k
    from int_field_rule u
    join int_context_feature cf on cf.accession = u.accession and cf.context_id = u.context_id
    join int_field_read sh on sh.accession = u.accession and sh.context_id = u.context_id and sh.field = 'shares'
    join int_field_read co on co.accession = u.accession and co.context_id = u.context_id and co.field = 'cost'
    join int_field_normalised n on n.accession = u.accession and n.context_id = u.context_id and n.field = 'principal_amount'
    where u.field = 'principal_amount' and u.action = 'par_tagged_as_units'
)
select cik, mode, report_date, accession, context_id, left(identifier_label, 90) as label, share_count, cost
    , value_scale, principal_new
from x where k <= 3 order by 1, 2, k
limit 60
