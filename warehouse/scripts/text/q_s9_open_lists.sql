-- Slice R phase 2 fix round 1: every needs_owner, contradicted_small and unstable proposal, grouped by kind, verdict,
-- reason and fund, as compact lists ('shape #k role (positions)' or 'code=rate (positions)'). Read-only.
select proposal_kind, verdict, coalesce(reason, '') why, cik, count(*) n, sum(positions) positions,
  string_agg(case proposal_kind when 'role' then '"' || shape || '" #' || number_index || ' ' || role
                                when 'code' then code || '=' || proposal
                                when 'shape' then '"' || shape || '"'
                                else unit_key || ' ' || proposal end || ' (' || positions || ')', '; '
             order by positions desc) items
from int_text_proposal_verdict
where verdict in ('needs_owner', 'contradicted_small', 'unstable', 'partly_accepted')
group by all order by 1, 2, 3, 4
