-- Slice R phase 2 fix round 1: contradicted and contradicted_small proposals with their evidence. Read-only.
select proposal_kind, verdict, cik, unit_key, coalesce(shape,'') shape, number_index, coalesce(code,'') code, proposal, positions,
  checks_confirming, checks_contradicting, checks_contradicting_small, nt_compared, nt_differs, leg_rows, leg_fail, base_tested, base_outside, roles_not_accepted
from int_text_proposal_verdict where verdict like 'contradicted%' order by 1, 2, cik
