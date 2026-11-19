-- Decides which fund and report dates are left out of the comparison with production (cmp_row_set): those where this
-- layer has position rows and production has no rows at all (owner, 2026-11-19: "leave the quarter out of the
-- comparison"). One row per fund and date with the accession(s) and the rows left out on each basis. A quarter here
-- re-enters the comparison when production is built with its filing.
select
    r.cik
    , r.report_date
    , string_agg(distinct r.accession, ', ' order by r.accession) as accessions
    , count(*) filter (where r.is_published) as published_rows
    , count(*) filter (where not r.is_published) as unpublished_rows
from {{ ref('int_source_row') }} r
where r.role = 'position'
  and not exists (
      select 1 from {{ ref('stg_holdings') }} h where h.cik = r.cik and h.report_date = r.report_date
  )
group by 1, 2
