-- Text T1 measurement, 2026-11-25: a CRUDE candidate split of each published position's label, to size the three
-- stores before any design (not the rule to build). Steps: drop a last pipe segment naming an affiliation; then the
-- instrument is (1) the text after the last pipe, else (2) the text between "Investment Type" and "Interest Rate" or
-- the end, else (3) the text after the last " - ", else (4) the last ", " segment when it names an instrument word,
-- else none. A trailing row number (1-2 digits) is dropped from the instrument. Output per fund: rows, distinct
-- labels, labels by shape, distinct instrument texts, and what the last four quarters add that no earlier quarter
-- had. Read-only.
with pos as (
    select s.cik, s.report_date, cf.identifier_label as label
    from cmp_row_set s
    join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.basis = 'published' and s.side = 'both' and cf.identifier_label is not null
)
, stripped as (
    select *, trim(regexp_replace(label, '\s*\|\s*[^|]*(?i:affiliat|controlled)[^|]*$', '')) as l0 from pos
)
, split as (
    select *
        , case
            when l0 like '%|%' then 'pipe'
            when l0 like '%Investment Type %' then 'marker'
            when l0 like '% - %' then 'dash'
            when regexp_matches(regexp_extract(l0, ', ([^,]*)$', 1),
                    '(?i)(loan|notes?|units?|stock|shares|interests?|warrants?|preferred|equity|partnership)') then 'comma'
            else 'none'
          end as shape
    from stripped
)
, parsed as (
    select *
        , nullif(trim(regexp_replace(case shape
            when 'pipe' then regexp_extract(l0, '\|\s*([^|]*)$', 1)
            when 'marker' then regexp_extract(l0, 'Investment Type (.*?)( Interest Rate.*)?$', 1)
            when 'dash' then regexp_extract(l0, '.* - (.*)$', 1)
            when 'comma' then regexp_extract(l0, ', ([^,]*)$', 1)
          end, '\s+\d{1,2}$', '')), '') as instrument
    from split
)
, first_seen_label as (select cik, label, min(report_date) as first_date from parsed group by 1, 2)
, first_seen_instr as (select cik, instrument, min(report_date) as first_date from parsed where instrument is not null group by 1, 2)
, quarters as (select cik, report_date, dense_rank() over (partition by cik order by report_date desc) as back from (select distinct cik, report_date from parsed))
select p.cik, 'a_total' as measure, null as report_date
    , count(*) as n_rows, count(distinct label) as labels
    , count(distinct label) filter (where shape = 'pipe') as pipe
    , count(distinct label) filter (where shape = 'marker') as marker
    , count(distinct label) filter (where shape = 'dash') as dash
    , count(distinct label) filter (where shape = 'comma') as comma
    , count(distinct label) filter (where shape = 'none') as no_instrument
    , count(distinct instrument) as instrument_texts
from parsed p group by 1
union all
select q.cik, 'b_new_in_quarter', q.report_date
    , (select count(*) from parsed p where p.cik = q.cik and p.report_date = q.report_date)
    , (select count(*) from first_seen_label f where f.cik = q.cik and f.first_date = q.report_date)
    , null, null, null, null, null
    , (select count(*) from first_seen_instr f where f.cik = q.cik and f.first_date = q.report_date)
from quarters q where q.back <= 4
order by 1, 2, 3
