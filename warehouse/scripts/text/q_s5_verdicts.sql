-- Slice R phase 2: verdict counts per kind. Read-only.
select proposal_kind, verdict, count(*) n, sum(positions) positions from int_text_proposal_verdict group by all order by 1,2
