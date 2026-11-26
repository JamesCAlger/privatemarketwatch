-- Slice R phase 2: shape units with no proposal. Read-only.
select s.unit_key, s.shape, s.positions from int_text_shape_unit s
where not exists (select 1 from text_proposed_shape_role p where s.unit_key = p.unit_key and s.shape_key_text = upper(p.shape))
order by positions desc
