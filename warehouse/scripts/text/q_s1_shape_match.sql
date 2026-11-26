-- Slice R phase 2: do the proposed shapes match the shape units (upper-cased)? Read-only.
with p as (select distinct unit_key, shape from text_proposed_shape_role)
select 'proposal_without_unit' k, count(*) n, sum(0) pos from p
where not exists (select 1 from int_text_shape_unit s where s.unit_key = p.unit_key and s.shape_key_text = upper(p.shape))
union all
select 'unit_without_proposal', count(*), sum(positions) from int_text_shape_unit s
where not exists (select 1 from p where s.unit_key = p.unit_key and s.shape_key_text = upper(p.shape))
union all
select 'units_not_in_proposals', count(*), sum(position_cells) from int_text_column_unit u where is_rate_candidate
  and not exists (select 1 from text_proposed_column c where c.unit_key=u.unit_key)
