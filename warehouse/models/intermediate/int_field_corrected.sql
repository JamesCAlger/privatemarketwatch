-- Decides the corrected value of every field of every position after corrections (slice 5 Task 3; spec 6.5, D1: never
-- erase). One row per (accession, context_id, field): every row of int_row_corrected times the eleven fields of
-- int_field_normalised. value_filed and value_normalised stay beside value; no filed or normalised value is changed in
-- place. This task fills the amount fields (fair_value, cost, principal_amount, principal_amount_usd, shares,
-- pct_of_net_assets); the rate fields (interest_rate, interest_rate_cash, pik_rate, spread, maturity_date) are carried
-- through unchanged until Task 4.
--
-- Before corrections (the _normalised columns, and value, status and reason where nothing applies): a filed position's
-- row of int_field_normalised; a context corrections make a position, int_field_reread run raw (its filed facts under the
-- same rules). Corrections applied (int_correction_application outcome applied), in this order on a field:
--   withdrawal            value null, status withdrawn, reason correction_withdrawn
--   step converted        value = the corrected number (production replaces the published value; nothing is derived
--                         again: a corrected principal does not change the dollar principal, slice 5 Task 2), status
--                         corrected, reason correction_converted
--   step filed            on a row with an applied correction at step filed, every amount field takes the value of
--                         int_field_reread run filed_corrected (the corrected read, converted by the rules), except a
--                         field whose own correction at step filed did not apply (it keeps its value): status
--                         corrected where the value, status, currency or FX rate differ from before, reason
--                         correction_filed on the corrected field, derived_from_corrected_principal on the dollar
--                         principal of a corrected principal, rule_rerun_after_filed_correction on any other field the
--                         rules now read differently; action and rule_id are the rule of that run
--   companion             currency (of principal, cost, fair value) and fx_rate (of the dollar principal) take the
--                         companion's value; where the field itself is unchanged: status corrected, reason
--                         companion_corrected
-- Two applied corrections that set one column of one field row to the same value (no conflict): the one read last by
-- production wins (row_corrections_by_context, then the lowest correction_id); both are applied in
-- int_correction_application. correction_id names the correction that set value (or, on a companion-only change, the
-- companion; on a rule re-run, the lowest correction_id at step filed on the row); null where nothing applied. status:
-- normalised, absent or unresolved (as before corrections), corrected, withdrawn.
-- fx_rate_normalised and fx_rate (the dollar principal's FX rate) are added beside the brief's columns: the FX rate
-- companion (principal_fx_rate_to_usd) lands there.
-- (Join filters sit in CTEs, not in a join's ON clause: a filter there makes DuckDB plan a nested-loop join.)
with position as (
    select accession, context_id, cik, report_date, row_reason from {{ ref('int_row_corrected') }}
)

, filed_position as (
    select accession, context_id from position where row_reason = 'filed'
)

, promoted_position as (
    select accession, context_id from position where row_reason <> 'filed'
)

, base as (
    select
        n.accession, n.context_id, n.field, n.value_filed, n.value, n.currency, n.fx_rate, n.value_date, n.rate_kind
        , n.action, n.rule_id, n.status, n.reason
    from {{ ref('int_field_normalised') }} n
    semi join filed_position p on p.accession = n.accession and p.context_id = n.context_id
    union all
    select
        rr.accession, rr.context_id, rr.field, rr.value_filed, rr.value, rr.currency, rr.fx_rate, rr.value_date
        , rr.rate_kind, rr.action, rr.rule_id, rr.status, rr.reason
    from (select * from {{ ref('int_field_reread') }} where run = 'raw') rr
    semi join promoted_position p on p.accession = rr.accession and p.context_id = rr.context_id
)

, applied as (
    select
        *
        , row_number() over (
            partition by accession, context_id, field_row, value_column
            order by case store when 'row_corrections_by_context' then 0 else 1 end, correction_id
          ) as pick
    from {{ ref('int_correction_application') }}
    where outcome = 'applied'
)

, main_converted as (
    select accession, context_id, field_row as field, correction_id, is_withdrawal, number_after
    from applied
    where pick = 1 and value_column = 'value' and step <> 'filed'
)

, main_filed as (
    select accession, context_id, field_row as field, correction_id
    from applied
    where pick = 1 and value_column = 'value' and step = 'filed'
)

, main_filed_usd as (
    -- the dollar principal follows a principal corrected at step filed
    select accession, context_id, 'principal_amount_usd' as field, correction_id
    from main_filed
    where field = 'principal_amount'
)

, filed_not_applied as (
    -- a field whose own correction at step filed did not apply (failed, rejected, no_op) keeps its value from before:
    -- the run filed_corrected read every correction at step filed that passed the screen, this one included
    select distinct accession, context_id, field_row as field
    from {{ ref('int_correction_application') }}
    where step = 'filed' and value_column = 'value' and outcome <> 'applied'
)

, filed_row as (
    select accession, context_id, min(correction_id) as first_filed_id
    from main_filed
    group by 1, 2
)

, filed_after as (
    select rr.*
    from (select * from {{ ref('int_field_reread') }} where run = 'filed_corrected') rr
    semi join filed_row f on f.accession = rr.accession and f.context_id = rr.context_id
    anti join filed_not_applied x on x.accession = rr.accession and x.context_id = rr.context_id and x.field = rr.field
)

, companion_currency as (
    select accession, context_id, field_row as field, correction_id, is_withdrawal, currency_after
    from applied
    where pick = 1 and value_column = 'currency'
)

, companion_fx as (
    select accession, context_id, field_row as field, correction_id, is_withdrawal, number_after
    from applied
    where pick = 1 and value_column = 'fx_rate'
)

, combined as (
    select
        p.accession
        , p.context_id
        , b.field
        , p.cik
        , p.report_date
        , b.value_filed
        , b.value as value_normalised
        , b.currency as currency_normalised
        , b.fx_rate as fx_rate_normalised
        , b.value_date as value_date_normalised
        , b.rate_kind as rate_kind_normalised
        , b.action as action_normalised
        , b.rule_id as rule_id_normalised
        , b.status as status_normalised
        , b.reason as reason_normalised
        , mc.correction_id as converted_id
        , mc.is_withdrawal as converted_withdrawal
        , mc.number_after as converted_value
        , mf.correction_id as filed_id
        , mfp.correction_id as filed_principal_id
        , f.first_filed_id
        , fa.field is not null as has_filed_run
        , fa.value as filed_value
        , fa.currency as filed_currency
        , fa.fx_rate as filed_fx_rate
        , fa.action as filed_action
        , fa.rule_id as filed_rule_id
        , fa.status as filed_status
        , fa.reason as filed_reason
        , cc.correction_id as currency_id
        , cc.is_withdrawal as currency_withdrawal
        , cc.currency_after
        , cx.correction_id as fx_id
        , cx.is_withdrawal as fx_withdrawal
        , cx.number_after as fx_after
    from position p
    join base b on b.accession = p.accession and b.context_id = p.context_id
    left join main_converted mc on mc.accession = b.accession and mc.context_id = b.context_id and mc.field = b.field
    left join main_filed mf on mf.accession = b.accession and mf.context_id = b.context_id and mf.field = b.field
    left join main_filed_usd mfp on mfp.accession = b.accession and mfp.context_id = b.context_id and mfp.field = b.field
    left join filed_row f on f.accession = b.accession and f.context_id = b.context_id
    left join filed_after fa on fa.accession = b.accession and fa.context_id = b.context_id and fa.field = b.field
    left join companion_currency cc on cc.accession = b.accession and cc.context_id = b.context_id and cc.field = b.field
    left join companion_fx cx on cx.accession = b.accession and cx.context_id = b.context_id and cx.field = b.field
)

, stepped as (
    -- the value after step filed (the corrected read, converted), and whether it changed the field
    select
        *
        , case when has_filed_run then filed_value else value_normalised end as after_filed_value
        , case when has_filed_run then filed_currency else currency_normalised end as after_filed_currency
        , case when has_filed_run then filed_fx_rate else fx_rate_normalised end as after_filed_fx_rate
        , has_filed_run and (
            filed_value is distinct from value_normalised or filed_status is distinct from status_normalised
            or filed_currency is distinct from currency_normalised or filed_fx_rate is distinct from fx_rate_normalised
          ) as filed_changed
    from combined
)

select
    accession
    , context_id
    , field
    , cik
    , report_date
    , value_filed
    , value_normalised
    , case
        when converted_id is not null and converted_withdrawal then null
        when converted_id is not null then converted_value
        else after_filed_value
      end as value
    , currency_normalised
    , case
        when currency_id is not null and currency_withdrawal then null
        when currency_id is not null then currency_after
        else after_filed_currency
      end as currency
    , value_date_normalised
    , value_date_normalised as value_date
    , rate_kind_normalised
    , rate_kind_normalised as rate_kind
    , fx_rate_normalised
    , case
        when fx_id is not null and fx_withdrawal then null
        when fx_id is not null then fx_after
        else after_filed_fx_rate
      end as fx_rate
    , case when has_filed_run then filed_action else action_normalised end as action
    , case when has_filed_run then filed_rule_id else rule_id_normalised end as rule_id
    , case
        when converted_id is not null and converted_withdrawal then 'withdrawn'
        when converted_id is not null then 'corrected'
        when filed_changed then 'corrected'
        when currency_id is not null or fx_id is not null then 'corrected'
        else status_normalised
      end as status
    , case
        when converted_id is not null and converted_withdrawal then 'correction_withdrawn'
        when converted_id is not null then 'correction_converted'
        when filed_changed and filed_id is not null then 'correction_filed'
        when filed_changed and filed_principal_id is not null then 'derived_from_corrected_principal'
        when filed_changed then 'rule_rerun_after_filed_correction'
        when currency_id is not null or fx_id is not null then 'companion_corrected'
        else reason_normalised
      end as reason
    , case
        when converted_id is not null then converted_id
        when filed_changed then coalesce(filed_id, filed_principal_id, first_filed_id)
        when currency_id is not null then currency_id
        when fx_id is not null then fx_id
      end as correction_id
from stepped
