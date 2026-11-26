-- Slice R phase 2: positions per fund with at least one read value per field, and all positions with a proposed cell. Read-only.
select cik, count(*) positions,
  count(*) filter (where p_spread is not null) spread, count(*) filter (where p_floor is not null) floor,
  count(*) filter (where p_all_in_rate is not null) all_in, count(*) filter (where p_cash_rate is not null) cash,
  count(*) filter (where p_pik_rate is not null) pik, count(*) filter (where p_pik_spread is not null) pik_spread,
  count(*) filter (where p_fixed_rate is not null) fixed, count(*) filter (where rate_name is not null) rate_name,
  count(*) filter (where code is not null and rate_name is null) code_no_series,
  count(*) filter (where conflict_spread or conflict_floor or conflict_all_in_rate or conflict_pik_rate or conflict_cash_rate or conflict_fixed_rate or conflict_pik_spread) conflicts,
  count(*) filter (where conflict_rate_name) rate_conflicts
from int_text_rate_proposed_position group by 1 order by 1
