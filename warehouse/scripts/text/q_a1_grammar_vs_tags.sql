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
-- Slice A tasks A1-A2: per quarter, what the grammar reads and how it agrees with the tags. Read-only.
select cast(report_date as varchar) as quarter
    , count(*) as n_rows
    , count(*) filter (where has_rate_text) as rate_text
    , count(*) filter (where has_rate_text and a_mat is not null) as mat_read
    , count(*) filter (where a_mat is not null and t_mat is not null) as mat_both
    , count(*) filter (where a_mat = t_mat) as mat_agree
    , count(*) filter (where a_mat is null and t_mat is not null) as mat_tag_only
    , count(*) filter (where a_spread is not null) as spr_read
    , count(*) filter (where a_spread is not null and t_spread is not null) as spr_both
    , count(*) filter (where abs(a_spread - t_spread) <= 0.05) as spr_agree
    , count(*) filter (where a_spread is null and t_spread is not null) as spr_tag_only
    , count(*) filter (where a_rate is not null) as rate_read
    , count(*) filter (where a_rate is not null and coalesce(t_rate, t_cash) is not null) as rate_both
    , count(*) filter (where abs(a_rate - t_rate) <= 0.05 or abs(a_rate - t_cash) <= 0.05) as rate_agree
    , count(*) filter (where a_pik is not null) as pik_read
    , count(*) filter (where a_pik is not null and t_pik is not null) as pik_both
    , count(*) filter (where abs(a_pik - t_pik) <= 0.05) as pik_agree
    , count(*) filter (where a_pik is null and t_pik is not null) as pik_tag_only
    , count(*) filter (where a_ref is not null) as ref_read
    , count(*) filter (where a_floor is not null) as floor_read
from x group by rollup(report_date) order by 1 nulls last
