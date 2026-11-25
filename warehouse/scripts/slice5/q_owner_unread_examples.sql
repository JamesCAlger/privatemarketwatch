-- Owner question 2026-11-25: two examples of a rate production fills and this layer leaves unread. The label,
-- production's rate fields. Read-only.
select h.accession_number, h.src_context_id, left(cf.identifier_label, 150) as label, h.interest_rate, h.interest_rate_cash, h.pik_rate, h.basis_spread, h.interest_rate_source
from stg_holdings h
join int_context_feature cf on cf.accession = h.accession_number and cf.context_id = h.src_context_id
where (h.accession_number = '0001287750-25-000007' and h.src_context_id = 'c-1362')
   or (h.accession_number = '0001193125-26-102386' and h.src_context_id = 'C_b0d04bca-67da-4de2-89a4-95a6235da432')
   or (h.accession_number = '0001838126-24-000079' and h.src_context_id = 'c-601')
