-- 2026-11-26: Apollo's own legend for its reference-rate codes (footnote text naming a code in quotes). Read-only.
select distinct regexp_extract(n.text, '(subject to[^.]{0,120}\("[^)]{1,40}\))', 1) as legend
from stg_filed_footnote n join stg_filed_filing f using (accession)
where f.cik = '0001837532' and regexp_matches(n.text, 'subject to[^.]{0,120}\("')
order by 1
