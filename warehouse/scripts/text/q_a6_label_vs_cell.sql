with pos as (
    select s.report_date, s.accession, s.context_id
        , replace(regexp_replace(cf.identifier_label, '[\x{FEFF}\x{200B}\x{200C}\x{200D}\x{2060}]', '', 'g'), chr(160), ' ') as label
        , h.reference_rate_type as p_ref, h.basis_spread as p_spread, h.interest_rate as p_rate, h.pik_rate as p_pik
        , h.maturity_date as p_mat, h.coupon_type as p_coupon, coalesce(h.corrected_fields, '') as corrected_fields
    from cmp_row_set s
    join int_context_feature cf on cf.accession = s.accession and cf.context_id = s.context_id
    join stg_holdings h on h.accession_number = s.accession and h.src_context_id = coalesce(s.production_context_id, s.context_id)
    where s.cik = '0001837532' and s.basis = 'published' and s.side = 'both' and cf.identifier_label is not null
)
, tag as (
    select accession, context_id
        , max(case when field = 'spread' then value_normalised end) as t_spread
        , max(case when field = 'interest_rate' then value_normalised end) as t_rate
        , max(case when field = 'interest_rate_cash' then value_normalised end) as t_cash
        , max(case when field = 'pik_rate' then value_normalised end) as t_pik
        , max(case when field = 'maturity_date' then value_date_normalised end) as t_mat
    from int_field_corrected where cik = '0001837532' group by 1, 2
)
-- Agent A grammar v3 for Apollo (data/overrides/identifier_rate_grammars/0001837532.json), extractor by extractor.
-- One change: the interest_rate pattern ends in a lookahead, which DuckDB's regex engine does not support; the
-- lookahead is written as a consumed group. Group 1 of the first match is the same.
, g as (
    select pos.*
        , upper(nullif(regexp_extract(label, '(?i)\b(SONIA|SOFR|SF|LIBOR|BBSW|PRIME|EURIBOR|SARON|STIBOR|S|L|P|E|K|C|T|N)\s*\+\s*[0-9]{2,4}\b', 1), '')) as a_ref_code
        , try_cast(nullif(regexp_extract(label, '(?i)\b(?:SONIA|SOFR|SF|LIBOR|BBSW|PRIME|EURIBOR|SARON|STIBOR|S|L|P|E|K|C|T|N)\s*\+\s*([0-9]{2,4})\b', 1), '') as double) / 100 as a_spread
        , try_cast(nullif(regexp_extract(label, '(?i)Interest\s*Rate\s*([0-9]+(?:\.[0-9]+)?)\s*%?\s*(?:Cash|\(|PIK|Maturity)', 1), '') as double) as a_rate
        , try_cast(nullif(regexp_extract(label, '(?i)(?:Cash(?:\s+plus)?|\(?Includes?|\(?)\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:Floor\s+)?PIK', 1), '') as double) as a_pik
        , try_cast(nullif(regexp_extract(label, '(?i)(?:,\s*)?([0-9]+(?:\.[0-9]+)?)\s*%?\s*Floor', 1), '') as double) as a_floor
        , try_strptime(nullif(regexp_extract(label, '(?i)Maturity\s*Date\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})\b', 1), ''), '%m/%d/%Y')::date as a_mat
    from pos
)
, x as (
    select g.*, tag.t_spread, tag.t_rate, tag.t_cash, tag.t_pik, tag.t_mat
        , case a_ref_code when 'SF' then 'SOFR' when 'S' then 'SOFR' when 'L' then 'LIBOR' when 'P' then 'PRIME' when 'E' then 'EURIBOR' else a_ref_code end as a_ref
        , regexp_matches(label, '(?i)(secured debt|unsecured debt|subordinated|term loan|revolver|delayed draw|first lien|second lien|bond|note)') as debt_words
        , regexp_matches(label, '(?i)(interest rate|maturity date|[0-9]\s*%|\+\s*[0-9]{2,4})') as has_rate_text
    from g left join tag using (accession, context_id)
)
-- Slice A, 2026-11-26 (owner question): how often the label's reference rate, spread and floor differ from the
-- printed row of the same position. The same patterns are applied to the printed row (the row holding the
-- context's fair-value fact). Read-only.
, pr as (
    select f.accession, f.context_id, min(pl.row_index) as row_index
    from stg_filed_fact f
    join stg_filed_fact_placement pl on pl.accession = f.accession and pl.fact_id = f.fact_id and not pl.in_hidden
    where f.concept_local like 'InvestmentOwnedAtFairValue%'
      and f.accession in (select distinct accession from x)
    group by 1, 2
)
, j as (
    select x.*, replace(array_to_string(r.cells, ' | '), chr(160), ' ') as line
    from x left join pr using (accession, context_id)
    left join stg_filed_document_row r on r.accession = pr.accession and r.row_index = pr.row_index
)
, c as (
    select *
        , upper(nullif(regexp_extract(line, '(?i)\b(SONIA|SOFR|SF|LIBOR|BBSW|PRIME|EURIBOR|SARON|STIBOR|S|L|P|E|K|C|T|N)\s*\+\s*[0-9]{2,4}\b', 1), '')) as c_ref_code
        , try_cast(nullif(regexp_extract(line, '(?i)\b(?:SONIA|SOFR|SF|LIBOR|BBSW|PRIME|EURIBOR|SARON|STIBOR|S|L|P|E|K|C|T|N)\s*\+\s*([0-9]{2,4})\b', 1), '') as double) / 100 as c_spread
        , try_cast(nullif(regexp_extract(line, '(?i)(?:,\s*)?([0-9]+(?:\.[0-9]+)?)\s*%?\s*Floor', 1), '') as double) as c_floor
    from j
)
select fld, what, count(*) as n, min(ex) as example
from (
    select 'reference rate' as fld
        , case when line is null then 'no printed row' when a_ref_code is null and c_ref_code is null then 'neither has one'
               when c_ref_code is null then 'label only' when a_ref_code is null then 'cell only'
               when a_ref_code = c_ref_code then 'same' else 'differ' end as what
        , case when a_ref_code <> c_ref_code then a_ref_code || ' / ' || c_ref_code end as ex from c
    union all
    select 'spread'
        , case when line is null then 'no printed row' when a_spread is null and c_spread is null then 'neither has one'
               when c_spread is null then 'label only' when a_spread is null then 'cell only'
               when abs(a_spread - c_spread) < 0.005 then 'same' else 'differ' end
        , case when abs(a_spread - c_spread) >= 0.005 then a_spread || ' / ' || c_spread end from c
    union all
    select 'floor'
        , case when line is null then 'no printed row' when a_floor is null and c_floor is null then 'neither has one'
               when c_floor is null then 'label only' when a_floor is null then 'cell only'
               when abs(a_floor - c_floor) < 0.005 then 'same' else 'differ' end
        , case when abs(a_floor - c_floor) >= 0.005 then a_floor || ' / ' || c_floor end from c
) group by all order by 1, 3 desc
