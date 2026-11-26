-- Text slice R phase 3: proposals whose verdict, proposal label or position count changed with the check fixes 1a-1d,
-- against the verdicts of fix round 1 saved before the change (path to the saved parquet is the first line's file;
-- edit it to rerun). One row per changed proposal.
with b as (
    select * from read_parquet('C:/Users/alger/AppData/Local/Temp/claude/be9193ded94737c2/b9cdb2bd-41b2-428c-b70e-94f2b13ccbda/scratchpad/verdict_before.parquet')
)
, a as (select * from int_text_proposal_verdict)
select coalesce(a.proposal_kind, b.proposal_kind) as kind, coalesce(a.cik, b.cik) as cik
    , coalesce(a.unit_key, b.unit_key) as unit_key, coalesce(a.shape, b.shape) as shape
    , coalesce(a.number_index, b.number_index) as k, coalesce(a.code, b.code) as code
    , b.proposal as proposal_before, a.proposal as proposal_after
    , b.verdict as verdict_before, a.verdict as verdict_after
    , b.positions as pos_before, a.positions as pos_after
    , b.nt_compared as compared_before, a.nt_compared as compared_after
    , a.checks_confirming, a.label_changed_by
from a
full join b on b.proposal_kind = a.proposal_kind and b.unit_key = a.unit_key
    and b.shape is not distinct from a.shape and b.number_index is not distinct from a.number_index
    and b.code is not distinct from a.code
where a.verdict is distinct from b.verdict or a.proposal is distinct from b.proposal
    or a.positions is distinct from b.positions or a.nt_compared is distinct from b.nt_compared
order by 1, 2, 3, 4, 5
