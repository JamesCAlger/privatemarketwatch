# Pulled 2026-10-08: a restored-position rule that invented fair value

`1920145_restore_2026q1_principal_only_debt_positions.json` (Goldman Sachs Private Credit Corp.,
2026-03-31) added two rows, Auctane, Inc. (193,000,000) and Tiger Acquisition, LLC (156,392,000),
with the principal as the fair value.

The 10-Q for that quarter (0001193125-26-219885) prints both with a par and no cost or value:
"Auctane, Inc. Air Freight & Logistics S + 4.75 % 12/31/32 193,000 - -" and "Tiger Acquisition,
LLC (dba Sabre Industries) ... S + 5.25 % 05/01/34 156,392 - -". They are undrawn commitments.

The gap the rule closed (349.3M) was measured against "Total Investments and Investments in
Affiliated Money Market Fund ... 16,852,129". That total includes the money-market fund
(343,539). The filed total of investments is 16,508,590. The gap was the money-market fund plus
one 5.8M row lost to a dedup step, not two missing positions.

Decision D-059 in `docs/investigations/v05_decision_log.md`. Nothing reads this directory.
