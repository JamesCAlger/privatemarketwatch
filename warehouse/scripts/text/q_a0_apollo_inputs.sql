-- Slice A, 2026-11-26: inputs for the Agent A test on Apollo. Field names and fill in int_field_corrected, correction
-- counts by field, and sample labels by quarter. Read-only.
select 'field' as k, field as a, status as b, count(*) as n, count(value) as with_value, count(value_date) as with_date, null as label
from int_field_corrected where cik = '0001837532' group by all
union all
select 'correction', field, kind, count(*), null, null, null from stg_correction where cik = '0001837532' group by all
union all
select 'label', cast(report_date as varchar), null, null, null, null, identifier_label
from (
    select s.report_date, cf.identifier_label
        , row_number() over (partition by s.report_date order by hash(cf.identifier_label)) as rn
    from cmp_row_set s join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.cik = '0001837532' and s.basis = 'published' and s.side = 'both'
) where rn <= 2
order by 1, 2, 3
