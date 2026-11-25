-- Decides which position takes the rate facts of a neighbouring rate-only context (slice 5 Task 4, owner decision 5:
-- built as a general structural rule). One row per taker context, with its giver context, the facts it takes and the
-- rule it takes them under.
--
-- The rule: a fund rule with action adopt_adjacent_rate_context (stg_reading_rule; the wrapper declaration
-- source_encodings.rate_only_contexts 'adopt_adjacent', loader version 7), read on every filing of its fund inside its
-- dates (a rule naming a filing reads that filing only). Never a list of contexts. Ported from production's
-- pipeline/source_encodings.py adopt_rate_only_contexts (lines 689-748), on this layer's filed contexts
-- (int_context_feature):
--   candidates  every context with an identifier member, within one filing and one period (instant date)
--   giver       rate facts (interest rate or cash-pay rate, spread, PIK rate) and no fair value, cost or principal fact
--   taker       a fair value fact and a principal fact and no rate fact
--   key         the identifier label lowercased, every character other than a-z and 0-9 removed, first 16 kept
--   pair        giver and taker under one key, each the only candidate on its side under that key (filing, period,
--               key), the key at least 8 characters long, and context numbers (the trailing digits of the context id)
--               that differ by exactly one
-- Production reads the same fields from its raw rows: a value is present when it is not blank. Here a fact counts as
-- present as int_context_feature counts it (a nil fact counts; no nil rate, spread or PIK fact sits on any candidate of
-- the rule's fund, so the two agree today).
-- What moves: the giver's reads of interest_rate_tag, interest_rate_cash_tag, pik_rate and spread (production's
-- RATE_FIELDS interest_rate, basis_spread, pik_rate; this layer reads the rate as two tags). int_rate_normalised gives
-- them to the taker, chooses the taker's rate rules on them and reads them under those rules like any filed fact; the
-- maturity date and the amounts stay the taker's. The giver keeps its role (not_schedule, role rule 3): production
-- removes the giver row, this layer never had it as a position.
-- moved_fields: the read fields the giver carries a fact for (comma separated, in a fixed order). giver_fact_ids: those
-- facts. taker_is_position: the taker is a filed position (int_source_row role position); only those are read again.
-- Rule naming: a value read from a moved fact names the conversion rule it was read under (int_field_normalised
-- rule_id); this model names the rule that moved the fact (rule_id), so the value's rule chain is the two together.
with rule as (
    select rule_id, cik, sel_accession, valid_from, valid_to
    from {{ ref('stg_reading_rule') }}
    where action = 'adopt_adjacent_rate_context'
)

, filing as (
    select accession, cik, document_period_end_date as report_date
    from {{ ref('stg_filed_filing') }}
    where cik in (select cik from rule)
)

, candidate as (
    select
        cf.accession
        , cf.context_id
        , cf.cik
        , f.report_date
        , cf.instant_date
        , try_cast(regexp_extract(cf.context_id, '([0-9]+)$', 1) as bigint) as ordinal
        , left(regexp_replace(lower(cf.identifier_label), '[^a-z0-9]', '', 'g'), 16) as issuer_key
        , cf.fair_value_fact_count = 0 and cf.cost_fact_count = 0 and not cf.has_principal
          and (cf.has_rate or cf.has_spread or cf.has_pik_rate) as is_giver
        , cf.fair_value_fact_count > 0 and cf.has_principal and not (cf.has_rate or cf.has_spread or cf.has_pik_rate)
          as is_taker
    from {{ ref('int_context_feature') }} cf
    join filing f on f.accession = cf.accession
    where cf.has_identifier_member
)

, giver as (
    select *, count(*) over (partition by accession, instant_date, issuer_key) as side_count
    from candidate
    where is_giver
)

, taker as (
    select *, count(*) over (partition by accession, instant_date, issuer_key) as side_count
    from candidate
    where is_taker
)

, pair as (
    select
        t.accession
        , t.context_id as taker_context_id
        , g.context_id as giver_context_id
        , t.cik
        , t.report_date
        , t.instant_date
        , t.issuer_key
    from giver g
    join taker t on t.accession = g.accession and t.instant_date = g.instant_date and t.issuer_key = g.issuer_key
    where g.side_count = 1 and t.side_count = 1 and length(g.issuer_key) >= 8 and abs(g.ordinal - t.ordinal) = 1
)

, ruled as (
    -- the rule each pair is taken under; two rules on one pair would have the same effect, the lowest id is named
    select p.*, min(r.rule_id) as rule_id
    from pair p
    join rule r
        on r.cik = p.cik
        and (r.sel_accession is null or r.sel_accession = p.accession)
        and (r.valid_from is null or r.valid_from <= p.report_date)
        and (r.valid_to is null or r.valid_to >= p.report_date)
    group by all
)

, giver_fact as (
    -- the giver's facts of the four moved read fields (concept_map read_field)
    select r.accession, r.giver_context_id, m.read_field, f.fact_id
    from ruled r
    join {{ ref('stg_filed_fact') }} f on f.accession = r.accession and f.context_id = r.giver_context_id
    join {{ ref('concept_map') }} m
        on m.concept_local = f.concept_local and f.concept_namespace glob m.namespace_pattern
    where m.read_field in ('interest_rate_tag', 'interest_rate_cash_tag', 'pik_rate', 'spread')
)

, moved as (
    select
        accession
        , giver_context_id
        , concat_ws(','
            , max(case when read_field = 'interest_rate_tag' then 'interest_rate_tag' end)
            , max(case when read_field = 'interest_rate_cash_tag' then 'interest_rate_cash_tag' end)
            , max(case when read_field = 'pik_rate' then 'pik_rate' end)
            , max(case when read_field = 'spread' then 'spread' end)
          ) as moved_fields
        , string_agg(cast(fact_id as varchar), ',' order by cast(fact_id as varchar)) as giver_fact_ids
    from giver_fact
    group by 1, 2
)

select
    r.accession
    , r.taker_context_id
    , r.giver_context_id
    , r.cik
    , r.report_date
    , r.instant_date
    , r.issuer_key
    , r.rule_id
    , m.moved_fields
    , m.giver_fact_ids
    , coalesce(s.role = 'position', false) as taker_is_position
from ruled r
left join moved m on m.accession = r.accession and m.giver_context_id = r.giver_context_id
left join {{ ref('int_source_row') }} s on s.accession = r.accession and s.context_id = r.taker_context_id
