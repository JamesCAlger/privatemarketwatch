-- Finding 2 (fix round 1): every distinct identifier label that contains 'money market', with the role it got.
select cf.cik, cf.identifier_label, r.role, r.is_cash, count(*) n
from int_context_feature cf left join int_source_row r using (accession, context_id)
where lower(cf.identifier_label) like '%money market%'
group by all order by 1, 2
