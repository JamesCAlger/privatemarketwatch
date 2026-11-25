-- Text T1 measurement, 2026-11-25: per fund, distinct labels of published positions (cmp_row_set side both or new,
-- published), label counts, and 6 sample labels per fund from the latest quarter. Read-only.
with pos as (
    select s.cik, s.report_date, s.accession, s.context_id, cf.identifier_label as label
    from cmp_row_set s
    join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.basis = 'published' and s.side = 'both'
)
, stats as (
    select cik, 'stats' as kind, cast(count(*) as varchar) || ' rows, ' || cast(count(distinct label) as varchar)
        || ' distinct labels, ' || cast(count(*) filter (where label is null) as varchar) || ' null, pipe '
        || cast(count(distinct label) filter (where label like '%|%') as varchar) || ', comma '
        || cast(count(distinct label) filter (where label like '%, %') as varchar) || ', dash '
        || cast(count(distinct label) filter (where label like '% - %') as varchar) as txt
    from pos group by 1
)
, samp as (
    select cik, 'sample' as kind, left(label, 230) as txt
    from (select distinct cik, label from pos where report_date = (select max(report_date) from pos p2 where p2.cik = pos.cik))
    qualify row_number() over (partition by cik order by hash(label)) <= 6
)
select * from stats union all select * from samp order by 1, 2 desc, 3
