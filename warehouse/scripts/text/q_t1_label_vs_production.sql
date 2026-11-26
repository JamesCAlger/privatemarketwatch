-- Text T1 measurement, 2026-11-25: sample labels per fund and label shape, with production's issuer and instrument
-- beside them, to write the candidate patterns from. Read-only.
with pos as (
    select s.cik, s.report_date, cf.identifier_label as label, h.issuer_name, h.instrument_description
    from cmp_row_set s
    join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where s.basis = 'published' and s.side = 'both' and cf.identifier_label is not null
)
, shaped as (
    select *, trim(regexp_replace(label, '\s*\|\s*[^|]*(?i:affiliat|controlled)[^|]*$', '')) as l0
    from pos
)
, s2 as (
    select *, case when l0 like '%|%' then 'pipe' when l0 like '%Investment Type %' then 'marker'
        when l0 like '% - %' then 'dash' when l0 like '%, %' then 'comma' else 'plain' end as shape
    from shaped
)
select cik, shape, min(report_date) as first_q, max(report_date) as last_q, count(*) as n_rows
    , list(distinct left(label, 150) || '  =>  [' || coalesce(issuer_name, '') || '] [' || coalesce(instrument_description, '') || ']')[1:4] as samples
from s2 group by 1, 2 order by 1, 5 desc
