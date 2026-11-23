-- Decides, for every position row, whether it is a commitment line whose fair value is printed again on another line of
-- the same borrower in the same schedule (is_repeated_commitment_value). Owner decision 2026-11-23: flag the lines now,
-- decide keep or drop after reproduction. A flag only: no role, value or published set changes here or because of it.
--
-- Background (docs/baseline_amounts_2026-11-22.md, owner item 1): a filer prints, under a schedule, a table of unfunded
-- commitments ("Investments | Commitment Type | Unfunded Commitment | Fair Value") whose fair value is the fair value
-- of the undrawn delayed-draw tranche; the same tranche is also a row of the schedule above, with par equal to the
-- commitment and the same fair value. Both pipelines carry that value twice.
--
-- Decided from row features only, never from a fund, a list of rows or a concept name:
--   commitment line  a position whose only term fact is a filer concept read through a fund rule concept_is_term_fact
--                    (int_context_feature.term_fact_source names a rule, not 'standard'), that is not an ownership
--                    percent (has_ownership_percent, from the seed concept_map), and that carries no cost fact. It has
--                    no par, share count, rate, spread, PIK rate or maturity of its own.
--   twin             another position of the same filing and the same scope that is not a commitment line, with the
--                    same fair value (not zero, not null) and the same borrower key.
--   borrower key     the first '|'-segment of the identifier label, lowercased, every run of other than a-z and 0-9
--                    made one space, and a trailing number (the filer's ordinal suffix, 'Corp 2') removed. The label
--                    text is the only borrower name this layer has; two lines that name the instrument differently in
--                    the same segment ('X, delayed draw term loan' and 'X, first lien loan') do not share a key, so
--                    the test can miss a twin. It cannot see a twin of a different borrower.
-- is_repeated_commitment_value is true on a commitment line with at least one twin. A zero fair value is never matched
-- (an undrawn line at zero says nothing about a repeat). The twin is not flagged: it is the schedule row.
with pos as (
    select
        s.accession
        , s.context_id
        , s.cik
        , s.report_date
        , s.scope
        , s.is_published
        , cf.fair_value
        , cf.term_fact_source is not null and cf.term_fact_source <> 'standard'
            and not cf.has_ownership_percent and cf.cost_fact_count = 0 as is_commitment_line
        , nullif(
            regexp_replace(
                trim(regexp_replace(lower(split_part(coalesce(cf.identifier_label, ''), '|', 1)), '[^a-z0-9]+', ' ', 'g'))
                , '( [0-9]+)+$', '')
            , '') as borrower_key
    from {{ ref('int_source_row') }} s
    join {{ ref('int_context_feature') }} cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.role = 'position'
)

, twin as (
    select
        l.accession
        , l.context_id
        , count(*) as twin_count
        , min(t.context_id) as twin_context_id
    from pos l
    join pos t
        on t.accession = l.accession
        and t.scope = l.scope
        and t.context_id <> l.context_id
        and not t.is_commitment_line
        and t.fair_value = l.fair_value
        and t.borrower_key = l.borrower_key
    where l.is_commitment_line and l.fair_value <> 0
    group by 1, 2
)

select
    p.accession
    , p.context_id
    , p.cik
    , p.report_date
    , p.scope
    , p.is_published
    , p.is_commitment_line
    , p.borrower_key
    , coalesce(t.twin_count, 0) as twin_count
    , t.twin_context_id
    , t.accession is not null as is_repeated_commitment_value
from pos p
left join twin t on t.accession = p.accession and t.context_id = p.context_id
