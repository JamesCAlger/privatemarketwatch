-- Baseline: a borrower should carry one sector. Measured at one date across the funds in scope.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['one_sector_per_borrower']) }}
select
    entity_id,
    count(distinct gics_sector_as_read)                                as sectors,
    string_agg(distinct gics_sector_as_read, ' / ' order by gics_sector_as_read) as sector_list,
    sum(fair_value)                                                    as fair_value
from {{ ref('fact_observation') }}
where report_date = cast('{{ var("baseline_date") }}' as date)
group by 1
having count(distinct gics_sector_as_read) > 1
