-- Slice 3 Task 3 fix round 1, item 3: printed text beside the tagged share of net assets in one filing (variable acc).
select context_id, value_filed, printed_text, decimals
from int_field_read
where accession = getvariable('acc') and field = 'pct_of_net_assets' and status = 'read' and value_filed is not null
order by value_filed desc
limit 8
