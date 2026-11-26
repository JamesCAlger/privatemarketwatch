-- Slice P fix round 1, 2026-11-26: column units per fund (re-keyed on table signature), distinct table signatures per
-- filing, and footnote-mark cells (in the unheaded column and elsewhere). Read-only.
select cik
    , count(distinct accession) as filings
    , count(*) as units
    , round(count(*) / count(distinct accession), 1) as units_per_filing
    , count(distinct accession || table_signature) as table_kinds
    , sum(n_footnote_mark) filter (where header_signature = '#footnote_marks') as footnote_cells_unheaded
    , sum(n_footnote_mark) filter (where header_signature <> '#footnote_marks') as footnote_cells_in_headed
from int_page_column_filing group by 1 order by 1
