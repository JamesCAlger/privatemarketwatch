-- Text slice R phase 3: the 31 proposed column units, their signatures and the column verdict.
select u.cik, u.unit_key, u.table_signature, u.header_signature, u.header_text, u.group_header_text, p.column_holds_fwd
    , p.column_holds_rev, v.verdict, v.reason, v.positions
from text_proposed_column p
join int_text_column_unit u on u.unit_key = p.unit_key
left join int_text_proposal_verdict v on v.proposal_kind = 'column' and v.unit_key = p.unit_key
order by 1, 2
