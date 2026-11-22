-- Slice 3 Task 4 fix round 1: production's raw extraction (data/output/bdc_holdings.parquet) for one accession and
-- context (variables acc, ctx): the amount columns as extracted, before staging. Read-only.
select *
from read_parquet('../data/output/bdc_holdings.parquet')
where accession_number = getvariable('acc') and src_context_id = getvariable('ctx')
limit 5
