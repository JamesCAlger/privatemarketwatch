-- Slice 3 Task 4: share of net assets filed above 0.50 on positions (production's size bound), with the comparison
-- side and production's value where the row is on both sides.
select n.cik, n.report_date, n.accession, n.context_id, n.value_filed, n.value, n.action, s.is_published, c.side
    , h.pct_of_net_assets as prod_pct, left(h.issuer_name, 40) as issuer
from int_field_normalised n
join int_source_row s on s.accession = n.accession and s.context_id = n.context_id
left join cmp_row_set c on c.accession = n.accession and c.context_id = n.context_id
left join stg_holdings h on h.accession_number = n.accession and h.src_context_id = n.context_id
where n.field = 'pct_of_net_assets' and n.value_filed > 0.5
order by n.cik, n.report_date
limit 200
