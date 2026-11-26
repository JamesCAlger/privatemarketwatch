-- Text slice R phase 3: the fund code tables (rate_code rules) as loaded, with grade.
select cik, code, rate, first_filing_date, last_filing_date, evidence_accession, source_grade, left(evidence, 60) as evidence from int_text_rate_rule where action in ('rate_code', 'rate_text_not_a_code') order by cik, code_key, first_filing_date nulls first
