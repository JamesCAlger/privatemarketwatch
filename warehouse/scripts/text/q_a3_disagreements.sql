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
-- Slice A task A3: (1) where the grammar and the tag disagree, which one production holds; (2) the grammar against
-- the row corrections on the same fields; (3) the grammar's reference rate against production's. Read-only.
, pn as (
    select x.*
        , case when p_spread is null then null when abs(p_spread) < 1 then p_spread * 100 else p_spread end as pp_spread
        , case when p_pik is null then null when abs(p_pik) < 1 then p_pik * 100 else p_pik end as pp_pik
    from x
)
, c as (
    select sc.accession, sc.context_id, sc.field, sc.value_number, sc.value_text, sc.value_date, sc.is_withdrawal
    from int_correction_screen sc
    where sc.cik = '0001837532' and sc.field in ('basis_spread', 'pik_rate', 'interest_rate', 'reference_rate_type', 'maturity_date', 'coupon_type')
)
select '1 spread: grammar vs tag disagree' as block
    , case when abs(pp_spread - a_spread) <= 0.05 then 'production = label' when abs(pp_spread - t_spread) <= 0.05 then 'production = tag'
           when pp_spread is null then 'production empty' else 'production = neither' end as what
    , case when corrected_fields like '%basis_spread%' then 'corrected' else 'not corrected' end as note, count(*) as n
from pn where a_spread is not null and t_spread is not null and abs(a_spread - t_spread) > 0.05 group by all
union all
select '1 maturity: grammar vs tag disagree'
    , case when p_mat = a_mat then 'production = label' when p_mat = t_mat then 'production = tag' when p_mat is null then 'production empty' else 'production = neither' end
    , case when abs(date_diff('day', a_mat, t_mat)) <= 31 then 'within a month' when abs(date_diff('day', a_mat, t_mat)) between 360 and 370 then 'a year apart' else 'other' end, count(*)
from pn where a_mat is not null and t_mat is not null and a_mat <> t_mat group by all
union all
select '2 corrections: ' || c.field
    , case when c.is_withdrawal then 'correction withdraws the value'
           when c.field = 'basis_spread' then case when a_spread is null then 'label has none' when abs(a_spread - case when abs(c.value_number) < 1 then c.value_number * 100 else c.value_number end) <= 0.05 then 'grammar reproduces' else 'grammar differs' end
           when c.field = 'pik_rate' then case when a_pik is null then 'label has none' when abs(a_pik - case when abs(c.value_number) < 1 then c.value_number * 100 else c.value_number end) <= 0.05 then 'grammar reproduces' else 'grammar differs' end
           when c.field = 'interest_rate' then case when a_rate is null then 'label has none' when abs(a_rate - case when abs(c.value_number) < 1 then c.value_number * 100 else c.value_number end) <= 0.05 then 'grammar reproduces' else 'grammar differs' end
           when c.field = 'reference_rate_type' then case when a_ref is null then 'label has none' when upper(c.value_text) = a_ref then 'grammar reproduces' else 'grammar differs' end
           when c.field = 'maturity_date' then case when a_mat is null then 'label has none' when c.value_date = a_mat then 'grammar reproduces' else 'grammar differs' end
           else 'not read by the grammar' end
    , null, count(*)
from c join pn using (accession, context_id) group by all
union all
select '3 reference rate: grammar vs production'
    , case when a_ref is null and p_ref is null then 'both empty' when a_ref is null then 'production only' when p_ref is null then 'grammar only'
           when upper(p_ref) = a_ref then 'same' else 'differ' end
    , case when a_ref is not null and p_ref is not null and upper(p_ref) <> a_ref then a_ref || ' vs ' || p_ref end, count(*)
from pn group by all
order by 1, 4 desc
