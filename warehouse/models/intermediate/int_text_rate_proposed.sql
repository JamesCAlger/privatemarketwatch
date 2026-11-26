-- PROPOSAL, NOT A READING OF RECORD (text slice R phase 2, 2026-11-26). Reads the printed rate cells with the rules an
-- agent PROPOSED (seeds text_proposed_shape_role, text_proposed_code; run of record text_runs/2026-11-26_rates_run3).
-- Nothing downstream may publish from this model: it feeds only the int_text_check_* models and
-- int_text_proposal_verdict, which measure the proposals. No model of the spine or the marts reads it.
--
-- One row per (accession, context_id, unit_key, number_index): each position (int_page_position one_row) on a printed
-- row, each column unit the agent was asked about (text_proposed_column) whose cell on that row is not empty
-- (int_text_cell), and:
--   number_index k >= 1  the k-th number of the cell text, by macro text_numbers: the same number pattern macro
--                        text_shape masks to '#', so the k-th number is the k-th '#' of the shape ("S+525, 0.50% Floor":
--                        525 and 0.50). number_value: that number as printed.
--   number_index 0       the cell's leading code (int_text_cell.code, macro rate_code), field reference_rate_code; or,
--                        when the cell has neither a code nor a number ("N/A"), one row with field null, status no_value.
-- Shape: the cell's shape_key_text matched to the proposed shape upper-cased (proposals carry the bundle's display
-- shape). shape_key: as int_text_shape_unit (md5 of unit_key | shape_key_text, 16 hex).
-- The shape's proposal is usable only when every number of it has the same role in both option orders and both role
-- lists hold as many roles as the shape has '#' (text_proposed_shape_role same_in_both_orders and roles_fit_shape on
-- every row of the shape); role = the forward role then.
-- Role -> field and value (percent):
--   spread_bps -> spread, number / 100 ("S+525" = 5.25)    spread_pct -> spread       floor_pct -> floor
--   all_in_rate_pct -> all_in_rate                          cash_rate_pct -> cash_rate pik_rate_pct -> pik_rate
--   pik_spread_pct -> pik_spread                            fixed_rate_pct -> fixed_rate (cash or all-in not said)
--   pct_of_net_assets, other_number -> no field (status not_a_rate_role)   cannot_tell -> status role_cannot_tell
-- Code row: the code matched (upper case, spaces removed) to text_proposed_code of the same unit. reference_rate_code =
-- the printed code; reference_rate = the forward answer; rate_name = the agreed name normalised to the base-rate
-- vocabulary (empty -> null where the answer maps to no series: CIBOR, SORA, ...).
-- status, number rows, the first that applies:
--   no_proposal        the shape has no proposal (the bundle's shape cap left it out)
--   shape_unstable     the two orders differ on some number of the shape, or a role list does not fit the shape
--   role_cannot_tell   the proposed role is cannot_tell
--   not_a_rate_role    the proposed role is pct_of_net_assets or other_number
--   read
-- status, code rows: no_proposal (the code has no proposal), code_unstable (the two orders name different
-- rates), not_a_code (both orders say it is not a rate code, or name no rate), read.
-- field is set on read number rows and on every code row; value only on read number rows. fact_fields: int_text_cell.fact_fields (the tagged fields placed in this cell).
with proposed_unit as (
    select unit_key, column_holds_fwd as column_holds, same_in_both_orders as column_stable
    from {{ ref('text_proposed_column') }}
)

, shape_proposal as (
    select unit_key, upper(shape) as shape_key_text
        , bool_and(same_in_both_orders and roles_fit_shape) as stable
        , map_from_entries(list(struct_pack(k := number_index, v := role_fwd)) filter (where number_index > 0)) as roles
    from {{ ref('text_proposed_shape_role') }}
    group by 1, 2
)

, code_proposal as (
    select unit_key, upper(replace(code, ' ', '')) as code_key, any_value(reference_rate_fwd) as reference_rate
        , any_value(rate_name) as rate_name, bool_and(same_in_both_orders) as stable
        , bool_and(coalesce(basis_fwd, '') = 'not_a_code' or reference_rate_fwd is null) as not_a_code
    from {{ ref('text_proposed_code') }}
    group by 1, 2
)

, cell as (
    select c.accession, c.row_index, c.col_start, c.cik, c.report_date, c.is_published, c.unit_key, c.text, c.shape
        , c.shape_key_text, c.code, c.fact_fields, {{ text_numbers('c.text') }} as numbers
        , left(md5(c.unit_key || '|' || c.shape_key_text), 16) as shape_key
        , u.column_holds
    from {{ ref('int_text_cell') }} c
    join proposed_unit u on u.unit_key = c.unit_key
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

, number_read as (
    select n.*, sp.stable as shape_stable, sp.shape_key_text is not null as has_proposal
        , case when sp.stable then sp.roles[n.number_index] end as role
    from number_row n
    left join shape_proposal sp on sp.unit_key = n.unit_key and sp.shape_key_text = n.shape_key_text
)

, number_out as (
    select accession, context_id, cik, report_date, is_published, unit_key, column_holds, col_start, text as cell_text
        , shape, shape_key, number_index, number_value, role
        , case role
            when 'spread_bps' then 'spread' when 'spread_pct' then 'spread' when 'floor_pct' then 'floor'
            when 'all_in_rate_pct' then 'all_in_rate' when 'cash_rate_pct' then 'cash_rate'
            when 'pik_rate_pct' then 'pik_rate' when 'pik_spread_pct' then 'pik_spread'
            when 'fixed_rate_pct' then 'fixed_rate'
          end as field
        , case
            when not has_proposal then 'no_proposal'
            when not shape_stable then 'shape_unstable'
            when role = 'cannot_tell' then 'role_cannot_tell'
            when role in ('pct_of_net_assets', 'other_number') then 'not_a_rate_role'
            when role is null then 'shape_unstable'
            else 'read'
          end as status
        , fact_fields
    from number_read
)

, code_out as (
    select pc.accession, pc.context_id, pc.cik, pc.report_date, pc.is_published, pc.unit_key, pc.column_holds
        , pc.col_start, pc.text as cell_text, pc.shape, pc.shape_key, 0 as number_index, null::double as number_value
        , null::varchar as role, 'reference_rate_code' as field
        , case
            when cp.code_key is null then 'no_proposal'
            when not cp.stable then 'code_unstable'
            when cp.not_a_code then 'not_a_code'
            else 'read'
          end as status
        , pc.fact_fields, pc.code as reference_rate_code
        , case when cp.stable and not cp.not_a_code then cp.reference_rate end as reference_rate
        , case when cp.stable and not cp.not_a_code then nullif(cp.rate_name, '') end as rate_name
    from position_cell pc
    left join code_proposal cp on cp.unit_key = pc.unit_key and cp.code_key = upper(replace(pc.code, ' ', ''))
    where pc.code is not null
)

, empty_out as (
    select accession, context_id, cik, report_date, is_published, unit_key, column_holds, col_start, text as cell_text
        , shape, shape_key, 0 as number_index, null::double as number_value, null::varchar as role
        , null::varchar as field, 'no_value' as status, fact_fields
    from position_cell
    where code is null and len(numbers) = 0
)

select
    accession, context_id, cik, report_date, is_published, unit_key, column_holds, col_start, cell_text, shape
    , shape_key, number_index, number_value, role
    , case when status = 'read' then field end as field
    , status
    , case when status = 'read' then case when role = 'spread_bps' then number_value / 100 else number_value end end
        as value
    , null::varchar as reference_rate_code, null::varchar as reference_rate, null::varchar as rate_name
    , fact_fields
from number_out
union all
select
    accession, context_id, cik, report_date, is_published, unit_key, column_holds, col_start, cell_text, shape
    , shape_key, number_index, number_value, role, field, status, null::double as value
    , reference_rate_code, reference_rate, rate_name, fact_fields
from code_out
union all
select
    accession, context_id, cik, report_date, is_published, unit_key, column_holds, col_start, cell_text, shape
    , shape_key, number_index, number_value, role, field, status, null::double as value
    , null, null, null, fact_fields
from empty_out
