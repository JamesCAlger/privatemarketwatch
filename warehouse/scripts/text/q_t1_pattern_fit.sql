-- Text T1 first measurement, 2026-11-25: a candidate label pattern per fund, compared with production's issuer and
-- instrument, to size the stored-splits store. NOT the rule to build: written by hand from samples
-- (q_t1_label_vs_production.sql). Read-only.
-- Steps: (1) drop trailing pipe segments naming an affiliation or empty; (2) drop a trailing row number (1-2 digits);
-- (3) split head | tail: after the last pipe; at "Investment Type" (Apollo) or the first Apollo instrument phrase; at
-- the last " - " (BCRED, HPS, only when the tail names an instrument word); at the last comma whose tail names an
-- instrument word (Ares, Blue Owl); else (4) the longest tail that is an instrument text already seen for the fund
-- (the dictionary anchor); else no instrument.
-- Compared as lower-case letters and digits only. Apollo: production's issuer must end the head (industry and brand
-- come before it); the tail is compared with production's instrument (which keeps the rate and maturity text).
with pos as (
    select s.cik, s.report_date, s.accession, s.context_id, cf.identifier_label as label
        , h.issuer_name, h.instrument_description, coalesce(h.corrected_fields, '') as corrected_fields
    from cmp_row_set s
    join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where s.basis = 'published' and s.side = 'both' and cf.identifier_label is not null
)
, l1 as (
    select *
        , trim(regexp_replace(trim(regexp_replace(label, '(\s*\|\s*([^|]*(?i:affiliat|controlled)[^|]*)?)+$', '')), '\s+\d{1,2}$', '')) as l
    from pos
)
, s1 as (
    select *
        , case
            when cik = '0001837532' and l like '%Investment Type %' then 'marker'
            when cik = '0001837532' and regexp_matches(l, '(First Lien|Second Lien|Unsecured Debt|Subordinated Debt|Common Equity|Preferred Equity|Warrants|Structured Products|Secured Debt)') then 'phrase'
            when cik = '0001837532' then 'none'
            when l like '%|%' then 'pipe'
            when cik in ('0001803498', '0001838126') and regexp_matches(regexp_extract(l, '.* - (.*)$', 1), '(?i)(units?|interests?|stock|shares|notes?|class|warrants?|preferred|equity|loan|lp|membership)') then 'dash'
            when cik in ('0001287750', '0001812554') and regexp_matches(regexp_extract(l, ',\s*([^,]*)$', 1), '(?i)(loan|notes?|units?|stock|shares|interests?|warrants?|preferred|equity|partnership|certificates?|bonds?)') then 'comma'
            else 'none'
          end as shape
    from l1
)
, s2 as (
    select *
        , case shape
            when 'marker' then trim(regexp_extract(l, '^(.*?)\s*Investment Type ', 1))
            when 'phrase' then trim(regexp_extract(l, '^(.*?)\s*(First Lien|Second Lien|Unsecured Debt|Subordinated Debt|Common Equity|Preferred Equity|Warrants|Structured Products|Secured Debt)', 1))
            when 'pipe' then trim(regexp_extract(l, '^(.*)\|[^|]*$', 1))
            when 'dash' then trim(regexp_extract(l, '^(.*) - .*$', 1))
            when 'comma' then trim(regexp_extract(l, '^(.*),[^,]*$', 1))
          end as head0
        , case shape
            when 'marker' then trim(regexp_extract(l, 'Investment Type (.*)$', 1))
            when 'phrase' then trim(regexp_extract(l, '((First Lien|Second Lien|Unsecured Debt|Subordinated Debt|Common Equity|Preferred Equity|Warrants|Structured Products|Secured Debt).*)$', 1))
            when 'pipe' then trim(regexp_extract(l, '\|([^|]*)$', 1))
            when 'dash' then trim(regexp_extract(l, '.* - (.*)$', 1))
            when 'comma' then trim(regexp_extract(l, ',\s*([^,]*)$', 1))
          end as tail0
    from s1
)
, dict as (
    select distinct cik, tail0 as instr from s2 where shape in ('pipe', 'comma', 'dash') and length(tail0) >= 5
)
, anchored as (
    select s.accession, s.context_id, max_by(d.instr, length(d.instr)) as instr
    from s2 s join dict d on d.cik = s.cik and ends_with(s.l, d.instr) and length(s.l) > length(d.instr)
    where s.shape = 'none' and s.cik <> '0001837532'
    group by 1, 2
)
, s3 as (
    select s.*
        , case when a.instr is not null then 'anchor' else s.shape end as shape2
        , case when a.instr is not null then rtrim(trim(left(s.l, length(s.l) - length(a.instr))), ',') when s.shape = 'none' then s.l else s.head0 end as head
        , case when a.instr is not null then a.instr else s.tail0 end as tail
    from s2 s left join anchored a on a.accession = s.accession and a.context_id = s.context_id
)
, cmp as (
    select *
        , regexp_replace(lower(head), '[^a-z0-9]', '', 'g') as head_n
        , regexp_replace(lower(coalesce(tail, '')), '[^a-z0-9]', '', 'g') as tail_n
        , regexp_replace(lower(coalesce(issuer_name, '')), '[^a-z0-9]', '', 'g') as p_issuer_n
        , regexp_replace(lower(regexp_replace(coalesce(instrument_description, ''), '\s+\d{1,2}$', '')), '[^a-z0-9]', '', 'g') as p_instr_n
        , regexp_matches(corrected_fields, 'issuer_name') as issuer_corrected
        , regexp_matches(corrected_fields, 'instrument_description') as instr_corrected
    from s3
)
, judged as (
    select *
        , case when cik = '0001837532' then ends_with(head_n, p_issuer_n) and p_issuer_n <> '' else head_n = p_issuer_n end as issuer_ok
        , tail_n = p_instr_n as instr_ok
    from cmp
)
select cik, shape2
    , count(*) as n_rows, count(distinct label) as labels
    , count(distinct label) filter (where issuer_ok and instr_ok) as both_agree
    , count(distinct label) filter (where not issuer_ok and not issuer_corrected) as issuer_differs
    , count(distinct label) filter (where not issuer_ok and issuer_corrected) as issuer_differs_corrected
    , count(distinct label) filter (where not instr_ok and not instr_corrected) as instr_differs
    , count(distinct label) filter (where not instr_ok and instr_corrected) as instr_differs_corrected
    , any_value(left(label, 90) || ' => [' || head || '] [' || coalesce(tail, '') || '] vs [' || coalesce(issuer_name, '') || '] [' || left(coalesce(instrument_description, ''), 50) || ']') filter (where not issuer_ok and not issuer_corrected) as issuer_example
    , any_value(left(label, 90) || ' => [' || coalesce(tail, '') || '] vs [' || left(coalesce(instrument_description, ''), 60) || ']') filter (where not instr_ok and not instr_corrected) as instr_example
from judged group by 1, 2 order by 1, 3 desc
