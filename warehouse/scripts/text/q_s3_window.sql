-- Slice R phase 2: base-rate windows. Read-only.
select report_date, rate_name, kind, round(range_min,2) mn, round(range_max,2) mx, n_values, last_value_date, state
from int_text_base_rate_window where rate_name in ('SOFR','SONIA','EURIBOR','PRIME','CORRA') order by rate_name, report_date
