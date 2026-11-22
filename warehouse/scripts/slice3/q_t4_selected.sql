-- Slice 3 Task 4: the selected filing per report date of one fund (variable cik).
select * from int_filing_selected where cik = getvariable('cik') order by report_date limit 40
