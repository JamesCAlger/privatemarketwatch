-- Slice R phase 2: every proposal not accepted by a check and not nothing_to_read. Read-only.
select proposal_kind, verdict, cik, unit_key, coalesce(shape, code, '') item, proposal, positions,
  checks_confirming, checks_weak, checks_contradicting, nt_compared, nt_differs, leg_rows, leg_fail,
  legend_filings_agree lga, legend_filings_contradict lgc, legend_filings_mixed lgm, base_quarters_tested bqt,
  base_quarters_confirmed bqc, base_quarters_discriminating bqd, base_tested bt, base_outside bo
from int_text_proposal_verdict where verdict not in ('accepted_by_check', 'nothing_to_read')
order by proposal_kind, verdict, cik, positions desc
