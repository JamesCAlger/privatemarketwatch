PULLED 2026-09-04 (operator veto, session: q1p3 finalization)

rule_id: add_2026q1_maverick_bidco_tranches (row_add, 2026-03-31, $98.395M)

Reason: comparative-fact fabrication. The rule's three positions copy facts
from contexts c-1745/c-1746/c-1747 of accession 0001930087-26-000060 VERBATIM
(FV 37,062,000 / 56,372,000 / 4,961,000; rate 9.16%; principal identical) --
but all three contexts have instant = 2025-09-30 (prior-FYE comparative; Golub
has a 9/30 fiscal year end). The filing contains NO 2026-03-31 Maverick facts
(exactly 3 Maverick mentions in the whole document, all comparative). The true
2026-03-31 gap is -84.797M (the untagged equity schedule, per the honest
conf-0.99 escalation that refused to add rows); this rule added +98.395M of
prior-period loans to force the residual inside the band (+13.598M, 0.137%).

Same class as the 1905824/2008748 vetoes. The no_aggregate_addition and
dup-add guards (9f05815) do not catch this shape; a comparative-period check
on row_add source contexts would -- candidate for the next gate hardening.

Effect of the pull at next rebuild: Golub 2026-03-31 conservation returns to
its honest -0.854% FAIL (flagged); its pipeline_only blocker packet (98.4M)
disappears. Gates survive: reconcile 64/68 = 94.1 (bar 90), flagged_fv ~9.88
(bar 10).
