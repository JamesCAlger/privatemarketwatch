-- Decides rules 0 to 3 of the row roles (spec intermediate_spine.md 6.2) for every context of every parsed filing of the
-- five funds: superseded, not_schedule, comparative, or null when the context goes on to the later rules.
--
--   0  the filing is not the one selected for its quarter (int_filing_selected), including a refused quarter -> superseded
--   1  no investment identifier member -> not_schedule. Exception: a context whose only member is on the cash and cash
--      equivalents axis goes on, so that rule 8 can reach it (the spec lists rule 8 after rule 1; read literally, rule 8
--      could never fire). No such context exists in the five funds today.
--   2  the instant is not the filing's period end (an earlier instant, or a duration context) -> comparative
--   3  no fair value -> not_schedule. Fair-value facts that carry two different numbers -> unresolved.
with filing as (
    select
        c.accession
        , c.cik
        , c.report_date
        , s.accession as selected_accession
        , s.refusal_reason
    from {{ ref('int_filing_candidate') }} c
    join {{ ref('int_filing_selected') }} s on s.cik = c.cik and s.report_date = c.report_date
)

, cash_axis as (
    -- Contexts whose single member sits on the cash and cash equivalents axis (any prefix).
    select accession, context_id
    from {{ ref('stg_filed_context_member') }}
    group by 1, 2
    having count(*) = 1 and bool_and(axis like '%:CashAndCashEquivalentsAxis')
)

select
    cf.accession
    , cf.context_id
    , f.cik
    , f.report_date
    , ca.context_id is not null as is_cash_axis
    , case
        when f.selected_accession is distinct from cf.accession then 'superseded'
        when not cf.has_identifier_member and ca.context_id is null then 'not_schedule'
        when not cf.is_filing_period_end then 'comparative'
        when cf.fair_value_fact_count = 0 then 'not_schedule'
        when cf.fair_value is null then 'unresolved'
      end as role
    , case
        when f.selected_accession is distinct from cf.accession then 0
        when not cf.has_identifier_member and ca.context_id is null then 1
        when not cf.is_filing_period_end then 2
        when cf.fair_value is null then 3
      end as role_rule
    , case
        when f.selected_accession is distinct from cf.accession and f.refusal_reason is not null
            then 'quarter refused: ' || f.refusal_reason
        when f.selected_accession is distinct from cf.accession
            then 'filing not selected; selected ' || f.selected_accession
        when not cf.has_identifier_member and ca.context_id is null then 'no investment identifier member'
        when not cf.is_filing_period_end and cf.period_type = 'instant' then 'instant is not the period end'
        when not cf.is_filing_period_end then 'not an instant at the period end'
        when cf.fair_value_fact_count = 0 then 'no fair value fact'
        when cf.fair_value is null then 'fair value facts carry no single number'
      end as reason
from {{ ref('int_context_feature') }} cf
join filing f on f.accession = cf.accession
left join cash_axis ca on ca.accession = cf.accession and ca.context_id = cf.context_id
