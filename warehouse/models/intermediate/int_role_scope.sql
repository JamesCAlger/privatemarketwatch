-- Decides rule 7's scope (whose schedule a context belongs to: the fund, or a JV or entity) and whether a filer rule
-- marks it as cash, for every context that rules 0 to 3 left open (spec 6.2, D7).
--
-- Filer rules come from stg_reading_rule, never copied here; a rule applies when its cik is the filer and the report
-- date is inside its valid range:
--   set_scope                       the context carries sel_member on sel_axis (local names, case ignored)
--   set_scope_by_label_suffix       a '|'-separated segment after the first equals sel_label
--   set_scope_by_identifier_suffix  sel_label is its own comma-separated part of the first segment (legacy forms; port
--                                   of pipeline/source_encodings.py reporting_suffix_expression, see below)
--   detached_schedule               the context sits after the first jump in context numbers of at least
--                                   var detached_min_context_gap (port of tag_detached_schedules)
--   set_is_cash                     the whole label equals sel_label
-- One global structural rule, not a filer rule: a member on an axis whose local name is
-- InvestmentCompanyNonconsolidatedSubsidiaryAxis or ScheduleOfEquityMethodInvestmentEquityMethodInvesteeNameAxis names
-- the entity whose schedule the row belongs to (the us-gaap meaning of those axes; production's accounting_scope.py
-- reads the same two axes). Labels are compared lowercased with white space collapsed.
with open_context as (
    select s.accession, s.context_id, s.cik, s.report_date, cf.identifier_label
        , regexp_replace(lower(trim(coalesce(cf.identifier_label, ''))), '\s+', ' ', 'g') as label_norm
        , list_transform(
            string_split(coalesce(cf.identifier_label, ''), '|')
            , x -> regexp_replace(lower(trim(x)), '\s+', ' ', 'g')
          ) as segments
    from {{ ref('int_role_structure') }} s
    join {{ ref('int_context_feature') }} cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.role is null
)

, rule as (
    select
        rule_id
        , cik
        , valid_from
        , valid_to
        , action
        , lower(sel_axis) as sel_axis
        , lower(sel_member) as sel_member
        , regexp_replace(lower(trim(sel_label)), '\s+', ' ', 'g') as sel_label
        , parameter
        , priority
    from {{ ref('stg_reading_rule') }}
    where action in ('set_scope', 'set_scope_by_label_suffix', 'set_scope_by_identifier_suffix', 'detached_schedule', 'set_is_cash')
)

, applicable as (
    select o.accession, o.context_id, r.*
    from open_context o
    join rule r on r.cik = o.cik
        and (r.valid_from is null or r.valid_from <= o.report_date)
        and (r.valid_to is null or r.valid_to >= o.report_date)
)

, member as (
    select
        accession
        , context_id
        , lower(regexp_replace(axis, '^.*:', '')) as axis_local
        , regexp_replace(member, '^.*:', '') as member_local
    from {{ ref('stg_filed_context_member') }}
)

, by_member as (
    select a.accession, a.context_id, a.rule_id, a.parameter as scope, a.priority
    from applicable a
    join member m on m.accession = a.accession and m.context_id = a.context_id
        and m.axis_local = a.sel_axis and lower(m.member_local) = a.sel_member
    where a.action = 'set_scope'
)

, by_label_suffix as (
    select a.accession, a.context_id, a.rule_id, a.parameter as scope, a.priority
    from applicable a
    join open_context o on o.accession = a.accession and o.context_id = a.context_id
    where a.action = 'set_scope_by_label_suffix'
      and list_contains(o.segments[2:], a.sel_label)
)

-- Legacy identifier forms, ported from reporting_suffix_expression: the label is its own part of the first segment,
-- after a comma or a space-number-space at the end, after a bare space at the end, or before a comma at the start; the
-- comma form also takes the label with a number fused in or a trailing full stop. Vetoes: one word then the label (the
-- fund's own interest), and a joint name ('X and <label>', '<label>, and X').
, suffix_rule as (
    select
        a.*
        , regexp_replace(a.sel_label, '([.^$*+?()\[\]{}|\\])', '\\\1', 'g') as lab
        , case when contains(a.sel_label, ' ')
            then regexp_replace(regexp_replace(a.sel_label, ' [^ ]*$', ''), '([.^$*+?()\[\]{}|\\])', '\\\1', 'g') || ' [0-9]?'
            else '' end
          || regexp_replace(regexp_replace(a.sel_label, '^.* ', ''), '([.^$*+?()\[\]{}|\\])', '\\\1', 'g') || '\.?' as loose
    from applicable a
    where a.action = 'set_scope_by_identifier_suffix'
)

, by_identifier_suffix as (
    select r.accession, r.context_id, r.rule_id, r.parameter as scope, r.priority
    from suffix_rule r
    join open_context o on o.accession = r.accession and o.context_id = r.context_id
    where (
            regexp_matches(o.segments[1], '^.+?(?:,\s*|,?\s+[0-9]+\s+)' || r.lab || '(?: [0-9]+)?$')
            or regexp_matches(o.segments[1], '^.+?,\s*' || r.loose || '(?: ?[0-9]+)?$')
            or regexp_matches(o.segments[1], '^.+[^,0-9 ] ' || r.lab || '(?: [0-9]+)?$')
            or regexp_matches(o.segments[1], '^' || r.lab || ',\s*.+$')
          )
      and not regexp_matches(o.segments[1], '^[a-z]+ ' || r.lab || '(?: [0-9]+)?$')
      and not regexp_matches(o.segments[1], '^' || r.lab || ',\s*and\b')
      and not regexp_matches(o.segments[1], '\band,?\s+' || r.loose || '(?: ?[0-9]+)?$')
)

, detached_pool as (
    select
        a.accession
        , a.context_id
        , a.rule_id
        , a.parameter as scope
        , a.priority
        , try_cast(regexp_extract(a.context_id, '([0-9]+)$', 1) as bigint) as ordinal
    from applicable a
    join {{ ref('int_context_feature') }} cf on cf.accession = a.accession and cf.context_id = a.context_id
    where a.action = 'detached_schedule' and cf.has_identifier_member
)

, detached_gap as (
    select *, ordinal - lag(ordinal) over (partition by accession, rule_id order by ordinal) as gap
    from detached_pool
    where ordinal is not null
)

, by_detached as (
    select g.accession, g.context_id, g.rule_id, g.scope, g.priority
    from detached_gap g
    join (
        select accession, rule_id, min(ordinal) filter (where gap >= {{ var('detached_min_context_gap') }}) as first_detached
        from detached_gap
        group by 1, 2
    ) s on s.accession = g.accession and s.rule_id = g.rule_id
    where g.ordinal >= s.first_detached
)

, by_axis as (
    select m.accession, m.context_id, null::varchar as rule_id, m.member_local as scope, 10 as priority
    from member m
    join open_context o on o.accession = m.accession and o.context_id = m.context_id
    where m.axis_local in ('investmentcompanynonconsolidatedsubsidiaryaxis', 'scheduleofequitymethodinvestmentequitymethodinvesteenameaxis')
)

, scope_match as (
    select *, 'set_scope' as how from by_member
    union all select *, 'set_scope_by_label_suffix' from by_label_suffix
    union all select *, 'set_scope_by_identifier_suffix' from by_identifier_suffix
    union all select *, 'detached_schedule' from by_detached
    union all select *, 'global_subsidiary_axis' from by_axis
)

, scope_decided as (
    select
        accession
        , context_id
        , count(distinct scope) as scope_count
        , min(scope) as scope
        , string_agg(distinct scope, '; ' order by scope) as scopes
        , arg_max(rule_id, priority) as rule_id
        , arg_max(how, priority) as how
    from scope_match
    group by 1, 2
)

, cash as (
    select a.accession, a.context_id, min(a.rule_id) as cash_rule_id
    from applicable a
    join open_context o on o.accession = a.accession and o.context_id = a.context_id
    where a.action = 'set_is_cash' and o.label_norm = a.sel_label
    group by 1, 2
)

select
    o.accession
    , o.context_id
    , coalesce(d.scope_count, 0) as scope_count
    , case when d.scope_count = 1 then d.scope end as scope
    , d.scopes
    , d.rule_id as scope_rule_id
    , d.how as scope_how
    , c.cash_rule_id
from open_context o
left join scope_decided d on d.accession = o.accession and d.context_id = o.context_id
left join cash c on c.accession = o.accession and c.context_id = o.context_id
