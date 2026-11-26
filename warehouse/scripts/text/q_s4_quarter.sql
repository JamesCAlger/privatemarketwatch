-- Slice R phase 2: base-level quarter table per proposed code (tested >= 10). Read-only.
select cik, code_key, proposed_rate, report_date, tested, admissible, floor_binding fb, outside,
  round(share_admissible,3) sh, best_alt_rate, best_alt_share, alt_admissible_rates, confirmed, discriminating
from int_text_check_base_level_quarter where tested >= 10 order by cik, code_unit_key, code_key, report_date
