-- Text slice R phase 3: distinct legend (name, abbreviation) pairs of the five funds, for the reference-rate name table.
select upper(name) as name_key, abbreviation_key, list(distinct code_key order by code_key) as codes, list(distinct cik order by cik) as ciks, count(distinct accession) as filings from int_text_check_legend group by 1, 2 order by 1, 2
