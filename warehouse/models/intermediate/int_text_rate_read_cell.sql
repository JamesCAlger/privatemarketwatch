-- Reads every printed rate cell of a position with the ACCEPTED rate-text rules (int_text_rate_rule; text slice R phase
-- 3, 2026-11-26). Publishes nowhere outside the warehouse: only int_text_rate_read reads it. One row per (accession,
-- context_id, unit_key, number_index).
--
-- Cells: int_text_cell texts (not empty) on the row of a position (int_page_position one_row) in a column a rate_column
-- rule names (same fund, table_signature and header_signature). column_rule_id, column_holds: that rule.
-- number_index k >= 1: the k-th number of the text (macro text_numbers, as int_text_rate_proposed). A rate_role rule of
--   the fund for the same column, the exact shape (case kept) and k gives role, field and value:
--   spread_bps -> spread (number / 100); spread_pct -> spread; floor_pct -> floor; all_in_rate_pct -> all_in_rate;
--   cash_rate_pct -> cash_rate; pik_rate_pct -> pik_rate; pik_spread_pct -> pik_spread; fixed_rate_pct -> fixed_rate.
--   status read; no_role_rule when no rule covers the number (unstable, contradicted or unaccepted shapes, a case
--   variant of an accepted spelling, a role the owner did not accept).
-- number_index 0: the cell's leading code (int_text_cell.code), field reference_rate, the first step that applies:
--   not_a_code          a rate_text_not_a_code rule of the fund names the code (status not_a_code, no rate).
--   own legend          int_text_legend_rate of the cell's filing has the code: one_rate -> that rate, status read
--                       (step legend_own); two_rates -> status legend_two_rates (the filing decides nothing: owner items
--                       2, 3); unresolved -> status legend_rate_unknown.
--   fund code table     the fund's rate_code rules for the code: distance in days from the report date to the rule's
--                       [first, last] filing dates (0 inside, 0 for an undated rule); the nearest wins (step
--                       code_table); two rates at the same nearest distance -> status code_undecided. A dated rule is
--                       not carried across a filing whose own legend gives the code two names (owner item 2: carried
--                       only where no filing contradicts it); with no rule left the code falls to the next step.
--   self-named          the code equals a rate_name of seed reference_rate (case and spaces ignored) or a printed name
--                       of seed reference_rate_name: that rate (owner item 1, step self_named).
--   else                status code_no_rule.
--   rule_id / source_grade of a code row: legend_own and code_table take the fund's rate_code rule for that code and rate
--   nearest the report date (legend_own with no such rule: rule_id 'owner-2026-11-26-item-2', grade owner); self_named
--   takes 'reference_rate:' || rate, grade owner.
-- A cell with neither a code nor a number gives one row, number_index 0, field null, status no_value.
-- Fix round 1: a rate_role rule with a condition (condition_header_signature, condition_text) applies only where the
-- same row's cell in that column of the same table prints that text, and then wins over an unconditional rule for the
-- same number. whole_coupon: the rule says the number (a PIK rate) is also the all-in rate (owner item 9).
with column_rule as (
    select rule_id, cik, table_signature, header_signature, column_holds, source_grade, grade_rank
    from {{ ref('int_text_rate_rule') }}
    where action = 'rate_column'
)

, cell as (
    select c.accession, c.row_index, c.table_index, c.col_start, c.cik, c.report_date, c.is_published, c.unit_key
        , c.text, c.shape, c.code, {{ text_numbers('c.text') }} as numbers
        , upper(replace(c.code, ' ', '')) as code_key
        , r.rule_id as column_rule_id, r.column_holds, r.table_signature, r.header_signature
    from {{ ref('int_text_cell') }} c
    join column_rule r
        on r.cik = c.cik and r.table_signature = c.table_signature and r.header_signature = c.header_signature
    where c.text <> ''
)

, position_cell as (
    select c.*, p.context_id
    from cell c
    join {{ ref('int_page_position') }} p
        on p.accession = c.accession and p.row_index = c.row_index and p.placement_status = 'one_row'
)

, number_row as (
    select pc.*, t.k as number_index, pc.numbers[t.k] as number_value
    from position_cell pc, range(1, 1 + len(pc.numbers)) t(k)
)

, role_candidate as (
    -- a conditional rule applies only where its condition holds; where it holds it wins over an unconditional rule
    select n.accession, n.context_id, n.unit_key, n.number_index, r.rule_id, r.role, r.source_grade, r.grade_rank
        , r.whole_coupon, r.condition_text is not null as conditional
    from number_row n
    join {{ ref('int_text_rate_rule') }} r
        on r.action = 'rate_role' and r.cik = n.cik and r.table_signature = n.table_signature
        and r.header_signature = n.header_signature and r.shape = n.shape and r.number_index = n.number_index
    where r.condition_text is null
       or exists (
            select 1 from {{ ref('int_text_cell') }} o
            where o.accession = n.accession and o.row_index = n.row_index and o.table_index = n.table_index
              and o.header_signature = r.condition_header_signature
              and upper(trim(o.text)) = upper(trim(r.condition_text)))
    qualify row_number() over (partition by n.accession, n.context_id, n.unit_key, n.number_index
                               order by r.condition_text is null, r.rule_id) = 1
)

, number_read as (
    select n.*, r.rule_id, r.role, r.source_grade, r.grade_rank, coalesce(r.whole_coupon, false) as whole_coupon
        , r.conditional
    from number_row n
    left join role_candidate r
        on r.accession = n.accession and r.context_id = n.context_id and r.unit_key = n.unit_key
        and r.number_index = n.number_index
)

, number_out as (
    select accession, context_id, cik, report_date, is_published, table_index, row_index, unit_key, column_rule_id
        , column_holds, text as cell_text, shape, number_index, number_value, role
        , case role
            when 'spread_bps' then 'spread' when 'spread_pct' then 'spread' when 'floor_pct' then 'floor'
            when 'all_in_rate_pct' then 'all_in_rate' when 'cash_rate_pct' then 'cash_rate'
            when 'pik_rate_pct' then 'pik_rate' when 'pik_spread_pct' then 'pik_spread'
            when 'fixed_rate_pct' then 'fixed_rate'
          end as field
        , case when role = 'spread_bps' then number_value / 100 when role is not null then number_value end as value
        , null::varchar as code, null::varchar as reference_rate
        , case when rule_id is null then 'no_role_rule' else 'read' end as status
        , null::varchar as code_step
        , rule_id, source_grade, grade_rank
        , whole_coupon and rule_id is not null as whole_coupon
    from number_read
)

, code_cell as (
    select * from position_cell where code is not null
)

, not_a_code as (
    select distinct c.accession, c.context_id, c.unit_key, r.rule_id, r.source_grade, r.grade_rank
    from code_cell c
    join {{ ref('int_text_rate_rule') }} r on r.action = 'rate_text_not_a_code' and r.cik = c.cik and r.code_key = c.code_key
)

, own_legend as (
    select c.accession, c.context_id, c.unit_key, l.verdict, l.rates
    from code_cell c
    join {{ ref('int_text_legend_rate') }} l on l.cik = c.cik and l.accession = c.accession and l.code_key = c.code_key
)

, table_candidate as (
    select c.accession, c.context_id, c.unit_key, r.rule_id, r.rate, r.source_grade, r.grade_rank
        , case
            when r.first_filing_date is null or c.report_date between r.first_filing_date and r.last_filing_date then 0
            when c.report_date < r.first_filing_date then date_diff('day', c.report_date, r.first_filing_date)
            else date_diff('day', r.last_filing_date, c.report_date)
          end as distance
    from code_cell c
    join {{ ref('int_text_rate_rule') }} r on r.action = 'rate_code' and r.cik = c.cik and r.code_key = c.code_key
    -- owner item 2 ("carry ... where no filing contradicts it"): a dated entry is not carried across a filing of the
    -- fund whose own legend gives the code two names (the code changed meaning there)
    where r.first_filing_date is null
       or not exists (
            select 1 from {{ ref('int_text_legend_rate') }} l
            where l.cik = c.cik and l.code_key = c.code_key and l.verdict = 'two_rates'
              and l.report_date > least(c.report_date, r.last_filing_date)
              and l.report_date < greatest(c.report_date, r.first_filing_date))
)

, table_nearest as (
    select *, count(distinct rate) over (partition by accession, context_id, unit_key) as n_nearest_rates
    from table_candidate
    qualify distance = min(distance) over (partition by accession, context_id, unit_key)
)

, table_pick as (
    select accession, context_id, unit_key, min(n_nearest_rates) as n_nearest_rates
        , min_by(rate, rule_id) as rate, min(rule_id) as rule_id, min_by(source_grade, rule_id) as source_grade
        , min_by(grade_rank, rule_id) as grade_rank
    from table_nearest
    group by 1, 2, 3
)

-- the fund's table rule for a given (code, rate), nearest the report date: the rule a legend_own reading cites
, table_for_rate as (
    select accession, context_id, unit_key, rate, rule_id, source_grade, grade_rank
    from table_candidate
    qualify row_number() over (partition by accession, context_id, unit_key, rate order by distance, rule_id) = 1
)

, self_named as (
    select c.accession, c.context_id, c.unit_key, coalesce(rr.rate_name, rn.rate_name) as rate
    from code_cell c
    left join {{ ref('reference_rate') }} rr on upper(replace(rr.rate_name, ' ', '')) = c.code_key
    left join {{ ref('reference_rate_name') }} rn on rn.printed_name = upper(trim(c.code))
    where coalesce(rr.rate_name, rn.rate_name) is not null
)

, code_decided as (
    select c.*
        , case
            when nc.rule_id is not null then 'not_a_code'
            when ol.verdict = 'two_rates' then 'legend_two_rates'
            when ol.verdict = 'unresolved' then 'legend_rate_unknown'
            when ol.verdict = 'one_rate' then 'read'
            when tp.n_nearest_rates > 1 then 'code_undecided'
            when tp.rate is not null then 'read'
            when sn.rate is not null then 'read'
            else 'code_no_rule'
          end as status
        , case
            when nc.rule_id is not null or ol.verdict in ('two_rates', 'unresolved') then null
            when ol.verdict = 'one_rate' then 'legend_own'
            when tp.n_nearest_rates > 1 then null
            when tp.rate is not null then 'code_table'
            when sn.rate is not null then 'self_named'
          end as code_step
        , ol.rates[1] as legend_rate
        , tp.rate as table_rate, tp.rule_id as table_rule_id, tp.source_grade as table_grade, tp.grade_rank as table_rank
        , sn.rate as self_rate
        , nc.rule_id as not_a_code_rule_id, nc.source_grade as not_a_code_grade, nc.grade_rank as not_a_code_rank
    from code_cell c
    left join not_a_code nc on nc.accession = c.accession and nc.context_id = c.context_id and nc.unit_key = c.unit_key
    left join own_legend ol on ol.accession = c.accession and ol.context_id = c.context_id and ol.unit_key = c.unit_key
    left join table_pick tp on tp.accession = c.accession and tp.context_id = c.context_id and tp.unit_key = c.unit_key
    left join self_named sn on sn.accession = c.accession and sn.context_id = c.context_id and sn.unit_key = c.unit_key
)

, code_out as (
    select d.accession, d.context_id, d.cik, d.report_date, d.is_published, d.table_index, d.row_index, d.unit_key
        , d.column_rule_id, d.column_holds, d.text as cell_text, d.shape, 0 as number_index, null::double as number_value
        , null::varchar as role, 'reference_rate' as field, null::double as value, d.code
        , case d.code_step when 'legend_own' then d.legend_rate when 'code_table' then d.table_rate
                           when 'self_named' then d.self_rate end as reference_rate
        , d.status, d.code_step
        , case d.code_step
            when 'legend_own' then coalesce(tr.rule_id, 'owner-2026-11-26-item-2')
            when 'code_table' then d.table_rule_id
            when 'self_named' then 'reference_rate:' || d.self_rate
            else d.not_a_code_rule_id
          end as rule_id
        , case d.code_step
            when 'legend_own' then coalesce(tr.source_grade, 'owner')
            when 'code_table' then d.table_grade
            when 'self_named' then 'owner'
            else d.not_a_code_grade
          end as source_grade
        , case d.code_step
            when 'legend_own' then coalesce(tr.grade_rank, 3)
            when 'code_table' then d.table_rank
            when 'self_named' then 3
            else d.not_a_code_rank
          end as grade_rank
    from code_decided d
    left join table_for_rate tr
        on tr.accession = d.accession and tr.context_id = d.context_id and tr.unit_key = d.unit_key
        and tr.rate = d.legend_rate and d.code_step = 'legend_own'
)

, empty_out as (
    select accession, context_id, cik, report_date, is_published, table_index, row_index, unit_key, column_rule_id
        , column_holds, text as cell_text, shape, 0 as number_index, null::double as number_value, null::varchar as role
        , null::varchar as field, null::double as value, null::varchar as code, null::varchar as reference_rate
        , 'no_value' as status, null::varchar as code_step, null::varchar as rule_id, null::varchar as source_grade
        , null::integer as grade_rank
    from position_cell
    where code is null and len(numbers) = 0
)

select * from number_out
union all by name
select * from code_out
union all by name
select * from empty_out
