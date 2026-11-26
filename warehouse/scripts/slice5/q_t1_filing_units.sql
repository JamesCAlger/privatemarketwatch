-- Slice 5 Task 1, item b: every unit text written in the filings of the build (all facts, any concept, any row), as
-- numerator or numerator/denominator, with facts and filings using it and whether its measures carry a prefix outside
-- iso4217, xbrli and utr (a filer's own unit). Re-measures appendix A8 on the filed layer. Row limit: the caller's.
with u as (
    select
        f.accession
        , case when u.denominator is null then u.numerator else u.numerator || '/' || u.denominator end as unit
        , u.numerator
        , u.denominator
    from main.stg_filed_fact f
    join main.stg_filed_unit u on u.accession = f.accession and u.unit_id = f.unit_id
)
select
    unit
    , (numerator like '%:%' and split_part(numerator, ':', 1) not in ('iso4217', 'xbrli', 'utr'))
      or (denominator like '%:%' and split_part(denominator, ':', 1) not in ('iso4217', 'xbrli', 'utr')) as filer_unit
    , count(*) as facts
    , count(distinct accession) as filings
from u
group by all
order by filer_unit, facts desc
