-- Slice R phase 2: report dates of positions per fund. Read-only.
select cik, min(report_date), max(report_date), count(distinct report_date) from int_text_cell group by 1 order by 1
