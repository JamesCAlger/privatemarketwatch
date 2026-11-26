-- Slice R phase 1, 2026-11-26: exploration. Column signatures per fund across filings, with filings, cells, and placed
-- concepts (top). Read-only.
select cik, header_signature, count(distinct accession) as filings, count(distinct table_signature) as tsigs
    , sum(data_cells) as cells, sum(placed_facts) as facts
    , round(sum(n_text) / nullif(sum(data_cells - n_footnote_mark), 0), 2) as sh_text
    , round(sum(n_percent) / nullif(sum(data_cells - n_footnote_mark), 0), 2) as sh_pct
    , left(min(placed_concepts), 80) as concepts
from int_page_column_filing
group by 1, 2
order by 1, cells desc
