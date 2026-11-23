-- Slice 4 Task 3: rows the unbuilt procedure rate_only_contexts adopt_adjacent would touch, per fund and quarter
-- (production: pipeline/source_encodings.py adopt_rate_only_contexts). Funds from stg_reading_not_loaded. A giver is a
-- context with a rate, spread or PIK fact and no fair value, cost or principal; a taker a position-period context with a
-- fair value and a principal and no rate facts. Paired within one filing and instant date when their numeric context
-- suffixes differ by one, they share the first 16 letters and digits of the identifier (at least 8), and neither side
-- has a second candidate under that key. Approximation: the context ordinal is the trailing digits of the context id,
-- as production reads it; production reads facts from its own raw table, here from int_context_feature.
with fund as (
    select distinct cik from stg_reading_not_loaded where wrapper_key = 'rate_only_contexts'
)
, base as (
    select c.cik, c.accession, c.context_id, c.instant_date
        , try_cast(regexp_extract(c.context_id, '([0-9]+)$', 1) as bigint) as ordinal
        , left(regexp_replace(lower(c.identifier_label), '[^a-z0-9]', '', 'g'), 16) as issuer_key
        , c.fair_value is null and c.cost is null and not c.has_principal
          and (c.has_rate or c.has_spread or c.has_pik_rate) as rate_only
        , c.fair_value is not null and c.has_principal and not (c.has_rate or c.has_spread or c.has_pik_rate) as value_only
    from int_context_feature c
    semi join fund f on f.cik = c.cik
    where c.has_identifier_member and c.is_filing_period_end
)
, givers as (select *, count(*) over (partition by accession, instant_date, issuer_key) as n from base where rate_only)
, takers as (select *, count(*) over (partition by accession, instant_date, issuer_key) as n from base where value_only)
, pairs as (
    select t.cik, t.accession, t.instant_date, t.context_id as taker, g.context_id as giver
    from givers g join takers t using (accession, instant_date, issuer_key)
    where g.n = 1 and t.n = 1 and length(g.issuer_key) >= 8 and abs(g.ordinal - t.ordinal) = 1
)
select p.cik, s.report_date, count(*) as pairs
    , count(*) filter (where s.role = 'position') as taker_is_position
    , count(*) filter (where s.is_published) as taker_published
from pairs p
left join int_source_row s on s.accession = p.accession and s.context_id = p.taker
group by all
order by 1, 2
