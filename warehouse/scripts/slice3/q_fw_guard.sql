-- Slice 3 final fix wave guard (read-only): rows of each model that differ between the snapshot taken before the wave
-- (scripts/slice3/out/fw_<model>_before.parquet) and the built model now, in both directions. int_field_rule is
-- compared without tie_break_same_effect (the one column F3 may change) and that column's changes are counted apart;
-- cmp_amount is compared without cause and cause_detail, whose changes are listed by before and after.
with
isr_b as (select * from read_parquet('scripts/slice3/out/fw_int_source_row_before.parquet'))
, crs_b as (select * from read_parquet('scripts/slice3/out/fw_cmp_row_set_before.parquet'))
, ifr_b as (select * from read_parquet('scripts/slice3/out/fw_int_field_read_before.parquet'))
, ifn_b as (select * from read_parquet('scripts/slice3/out/fw_int_field_normalised_before.parquet'))
, rule_b as (select * exclude (tie_break_same_effect) from read_parquet('scripts/slice3/out/fw_int_field_rule_before.parquet'))
, rule_a as (select * exclude (tie_break_same_effect) from int_field_rule)
, cmp_b as (select * exclude (cause, cause_detail) from read_parquet('scripts/slice3/out/fw_cmp_amount_before.parquet'))
, cmp_a as (select * exclude (cause, cause_detail) from cmp_amount)
select 'int_source_row' as model, 'rows before' as what, (select count(*) from isr_b) as n
union all select 'int_source_row', 'rows now', (select count(*) from int_source_row)
union all select 'int_source_row', 'before not now', (select count(*) from (select * from isr_b except all select * from int_source_row))
union all select 'int_source_row', 'now not before', (select count(*) from (select * from int_source_row except all select * from isr_b))
union all select 'cmp_row_set', 'rows before', (select count(*) from crs_b)
union all select 'cmp_row_set', 'rows now', (select count(*) from cmp_row_set)
union all select 'cmp_row_set', 'before not now', (select count(*) from (select * from crs_b except all select * from cmp_row_set))
union all select 'cmp_row_set', 'now not before', (select count(*) from (select * from cmp_row_set except all select * from crs_b))
union all select 'int_field_read', 'rows before', (select count(*) from ifr_b)
union all select 'int_field_read', 'rows now', (select count(*) from int_field_read)
union all select 'int_field_read', 'before not now', (select count(*) from (select * from ifr_b except all select * from int_field_read))
union all select 'int_field_read', 'now not before', (select count(*) from (select * from int_field_read except all select * from ifr_b))
union all select 'int_field_normalised', 'rows before', (select count(*) from ifn_b)
union all select 'int_field_normalised', 'rows now', (select count(*) from int_field_normalised)
union all select 'int_field_normalised', 'before not now', (select count(*) from (select * from ifn_b except all select * from int_field_normalised))
union all select 'int_field_normalised', 'now not before', (select count(*) from (select * from int_field_normalised except all select * from ifn_b))
union all select 'int_field_rule (without tie_break_same_effect)', 'rows before', (select count(*) from rule_b)
union all select 'int_field_rule (without tie_break_same_effect)', 'rows now', (select count(*) from rule_a)
union all select 'int_field_rule (without tie_break_same_effect)', 'before not now', (select count(*) from (select * from rule_b except all select * from rule_a))
union all select 'int_field_rule (without tie_break_same_effect)', 'now not before', (select count(*) from (select * from rule_a except all select * from rule_b))
union all select 'int_field_rule', 'tie_break_same_effect changed: ' || coalesce(cast(b.tie_break_same_effect as varchar), 'null') || ' -> ' || coalesce(cast(a.tie_break_same_effect as varchar), 'null'), count(*)
    from read_parquet('scripts/slice3/out/fw_int_field_rule_before.parquet') b
    join int_field_rule a on a.accession = b.accession and a.context_id = b.context_id and a.field = b.field
    where a.tie_break_same_effect is distinct from b.tie_break_same_effect
    group by all
union all select 'cmp_amount (without cause, cause_detail)', 'rows before', (select count(*) from cmp_b)
union all select 'cmp_amount (without cause, cause_detail)', 'rows now', (select count(*) from cmp_a)
union all select 'cmp_amount (without cause, cause_detail)', 'before not now', (select count(*) from (select * from cmp_b except all select * from cmp_a))
union all select 'cmp_amount (without cause, cause_detail)', 'now not before', (select count(*) from (select * from cmp_a except all select * from cmp_b))
union all select 'cmp_amount cause moved', b.basis || ' ' || b.field || ': ' || coalesce(b.cause, '-') || '|' || coalesce(b.cause_detail, '-')
        || ' -> ' || coalesce(a.cause, '-') || '|' || coalesce(a.cause_detail, '-'), count(*)
    from read_parquet('scripts/slice3/out/fw_cmp_amount_before.parquet') b
    join cmp_amount a on a.basis = b.basis and a.accession = b.accession and a.context_id = b.context_id and a.field = b.field
    where a.cause is distinct from b.cause or a.cause_detail is distinct from b.cause_detail
    group by all
limit 100
