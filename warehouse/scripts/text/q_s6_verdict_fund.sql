-- Slice R phase 2: verdict counts per fund and kind (proposals; positions in brackets). Read-only.
select cik, proposal_kind, verdict, count(*) n, sum(positions) positions from int_text_proposal_verdict group by all order by 1,2,3
