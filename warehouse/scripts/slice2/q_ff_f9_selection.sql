-- Final fix wave F9: every fund-quarter of int_filing_selected against production's accession(s) for that fund and date,
-- with the ones that do not select the same accession listed.
with p as (
    select cik, report_date, string_agg(distinct accession_number, ', ' order by accession_number) as prod_accessions
    from stg_holdings group by 1, 2
)
, s as (
    select s.cik, s.report_date, s.accession, s.selection_rule, s.refusal_reason, p.prod_accessions
        , case
            when s.accession is not null and p.prod_accessions = s.accession then 'same'
            when s.accession is null then 'refused'
            when p.prod_accessions is null then 'production_has_no_rows'
            else 'differs'
          end as outcome
    from int_filing_selected s
    left join p using (cik, report_date)
)
select outcome, count(*) as n, null as cik, null as report_date, null as accession, null as refusal_reason, null as prod_accessions
from s group by 1
union all
select outcome, null, cik, report_date::varchar, accession, refusal_reason, prod_accessions
from s where outcome <> 'same'
order by 1, 3, 4
