# Obligations register v3 (2026-09-15)

Owner decision 2026-09-15. `obligations_v3.csv` is `obligations_v2.csv` with exactly 8 rows reclassified to the new status `not_yet_reporting`; every other byte is identical (same 13 columns, same 910-row order, ASCII, CRLF).

Rule applied to every row whose `eligibility_status` starts with `eligible_`: the `(cik, report_date)` has filing-gaps status `no_filing_for_quarter`, `earliest_periodic_report_date > report_date`, and `positive_investment_amount` is empty. Matching rows get `eligibility_status = not_yet_reporting`, `evidence_ids += ;EDGAR-<cik>-<quarter>`, and `follow_up = no periodic filing for quarter; earliest periodic report <date> (EDGAR submissions 2026-09-15)`.

`not_yet_reporting` means EDGAR lists no 10-K/10-Q for the quarter and the entity's first periodic report postdates it, so no holdings can be extracted from a filing. It is not a lifecycle finding about whether the fund was investing.

## Evidence

| File | sha256 |
|---|---|
| `scratch/2026-09-15_v1_blockers/filing_gaps_v1/filing_gaps.csv` (EDGAR submissions snapshot, `scripts/check_filing_gaps.py`, 99 fund-quarters) | `3b97bd4090a14612ecf66d4994248e65d3af71fe608f25baeda09fc1392c8b0b` |
| `obligations_v2.csv` (input) | `37da3d87f68c9002fbfbafab5b08b8713e752462edd1e9c1159116b261762d1e` |
| `obligations_v3.csv` (output) | `2dae5f78d65a19e4153b075e050df6dc2d49112135acf23796cef1d0e94cc012` |

Builder: `scratch/2026-09-15_v1_blockers/obligations_v3/make_obligations_v3.py` (asserts CRLF, ASCII, minimal-quoting round-trip of every unchanged line, and exactly 8 changes).

## Counts

| | v2 | v3 |
|---|---|---|
| rows | 910 | 910 |
| `eligible_source_investments` | 792 | 791 |
| `eligible_operating_interval` | 20 | 13 |
| eligible total | 812 | 804 |
| `not_yet_investment_operating` | 98 | 98 |
| `not_yet_reporting` | 0 | 8 |
| non-eligible total | 98 | 106 |
| eligible zero-output rows (E1 population) | 33 | 25 |

Per-quarter eligible / non-eligible under v3: 2023-03-31 45/25, 2023-06-30 52/18, 2023-09-30 53/17, 2023-12-31 58/12, 2024-03-31 59/11, 2024-06-30 63/7, 2024-09-30 64/6, 2024-12-31 66/4, 2025-03-31 67/3, 2025-06-30 69/1, 2025-09-30 69/1, 2025-12-31 69/1, 2026-03-31 70/0.

## The 8 changes

| line | cik | entity | report_date | v2 status | earliest periodic report | v2 follow_up |
|---|---|---|---|---|---|---|
| 106 | 0001646614 | Silver Point Specialty Lending Fund | 2023-03-31 | eligible_operating_interval | 2023-06-30 | missing_output_roster_or_cash_status_unreviewed |
| 457 | 0001899996 | Fidelity Private Credit Co LLC | 2023-03-31 | eligible_operating_interval | 2023-06-30 | missing_output_roster_or_cash_status_unreviewed |
| 483 | 0001901164 | T. Rowe Price OHA Select Private Credit Fund | 2023-03-31 | eligible_operating_interval | 2023-06-30 | missing_output_roster_or_cash_status_unreviewed |
| 564 | 0001916099 | Diameter Credit Co | 2023-12-31 | eligible_operating_interval | 2024-03-31 | missing_output_roster_or_cash_status_unreviewed |
| 718 | 0001954360 | Crescent Private Credit Income Corp | 2023-06-30 | eligible_operating_interval | 2023-09-30 | missing_output_roster_or_cash_status_unreviewed |
| 812 | 0002006758 | MidCap Apollo Institutional Private Lending | 2024-03-31 | eligible_operating_interval | 2024-06-30 | missing_output_roster_or_cash_status_unreviewed |
| 825 | 0002008748 | Lord Abbett Private Credit Fund | 2024-03-31 | eligible_operating_interval | 2024-09-30 | missing_output_roster_or_cash_status_unreviewed |
| 855 | 0002012139 | Fortress Private Lending Fund | 2025-03-31 | eligible_source_investments | 2025-06-30 | Direct June 2025 management statement and March 2025 comparative Level 3 rollforward; full source roster unavailable. |

All 8 now read `not_yet_reporting`, `evidence_ids` = prior value + `;EDGAR-<cik>-<report_date>`, `follow_up` = `no periodic filing for quarter; earliest periodic report <date> (EDGAR submissions 2026-09-15)`. Fortress keeps `PILOT-FORTRESS-2025Q1` in `evidence_ids`; its v2 follow-up text (above) is replaced, per the rule, and retained here.

Not reclassified, by design: 26North BDC (0001950976, 2023-12-31) stays `eligible_source_investments`; EDGAR lists a 10-K for that quarter (`filing_indexed`, 0001193125-24-063364) and the row carries a positive companyfacts total ($52.6M).

## Consumers

- `scripts/run_production_acceptance.py` and `scripts/run_context_census.py` now read v3. E1 checks 25 distinct zero-output obligations; E2 checks 804 distinct eligible obligations. Saved E2 assessments must match the current register hashes and exact key set.
- E3 audits all 106 exclusions: 98 `not_yet_investment_operating` plus 8 `not_yet_reporting`. The latter require verified submissions evidence of no primary filing and a later first report, with an indexed primary filing taking precedence as a contradiction. Later comparative investment facts are retained; they do not establish a primary filing or reverse the owner's reporting-based exclusion.
- `pipeline/quarter_evidence.py` requires one E3 record per excluded obligation and rejects duplicate or out-of-register records. Positive facts still contradict investment-activity exclusions. For reporting exclusions they are excused only with the register's reporting status and the certified EDGAR absence fields; an unsupported status cannot certify the denominator.
- Focused tests cover the 910-key partition, Golub's cached primary filing, reporting/lifecycle distinctions, missing or contradictory filing evidence, and duplicate audit records. Numerical threshold adoption remains deferred.
- Historical measurement scripts pinned to earlier candidates keep reading v2 by design: `scripts/programme_reference/measure_pilot.py` (writes v2), `scripts/programme_closeout/baseline_measure.py`, `scripts/programme_closeout/pik_source_example.py`, `scripts/programme_tranche/measure_candidate.py`.
