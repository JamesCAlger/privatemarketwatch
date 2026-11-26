-- Slice R phase 2 fix round 1: per-filing legend verdicts for codes proposed as CDOR, CORRA, BBSY, BBSW. Read-only.
select l.cik, l.unit_key, l.code_key, l.proposed_rate, l.report_date, l.verdict, l.legend_rates, l.positions
from int_text_check_code_legend l where l.proposed_rate in ('CDOR','CORRA','BBSY','BBSW') order by 1,2,3,5
