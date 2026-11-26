-- Slice R phase 2: claims checked for the note. Read-only.
select 'usable_rows_all_in_printed' k, cast(count(*) as varchar) v from int_text_check_base_level where is_proposed and input_state='usable' and all_in_source='printed'
union all select 'needs_owner_shapes_le4_positions', cast(count(*) as varchar) from int_text_proposal_verdict where proposal_kind='shape' and verdict='needs_owner' and positions <= 4
union all select 'unit_dates_' || unit_key, cast(first_report_date as varchar) || '..' || cast(last_report_date as varchar) from int_text_column_unit where unit_key in ('fc9493acdb2c4a08','4911badeb7733932','b4ee1994c58b2d08')
union all select 'ares_coupon_share', cast(dominant_share as varchar) || ' ' || dominant_rows || '/' || tagged_rows from int_text_check_column_tags where unit_key='1de53b4d55ea4050'
union all select 'or_rule_codes_contradicted', cast(count(*) as varchar) from int_text_proposal_verdict where proposal_kind='code' and stable and (base_outside >= 5 or (base_tested > 0 and base_outside / base_tested >= 0.1))
union all select 'or_rule_shapes_contradicted', cast(count(*) as varchar) from int_text_proposal_verdict where proposal_kind='shape' and stable and (nt_differs >= 5 or (nt_compared > 0 and nt_differs / nt_compared >= 0.1) or leg_fail >= 5 or (leg_rows > 0 and leg_fail / leg_rows >= 0.1))
