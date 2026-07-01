# Agent data-query tool -- the investigative keystone

Status: built (core + CLI + tests). Not yet granted to the live Codex worker sandbox.

## Why

The B2 agent could read the FILING (`evidence_cli`) but could not interrogate the EXTRACTED
data. Root-causing an extraction discrepancy requires seeing *what the pipeline pulled*
(the over/under-counted rows) against *the filing's truth*, and AGGREGATING it (by period, by
dimension, by legal entity) -- which is exactly how the Saratoga CLO look-through + the
compound 17.67M under-count were found by hand. Without this, the agent diagnoses an extraction
bug while blind to the extraction output, and we fall back to deterministic probes that
pre-decide the answer (the thing we are trying to stop doing).

## What it is

`pipeline/agent_data_query.py` (+ `scripts/review_agent/data_query_cli.py`): a READ-ONLY,
CIK-SCOPED query window over the cached extracted data. The extracted-data analog of
`evidence_cli`'s filing window. The agent uses BOTH.

Exposed tables, each pre-filtered to the one cik:

| table | source | use |
|---|---|---|
| `holdings` | unified `private_markets_holdings` | what the conservation gate sums |
| `staging` | raw `bdc_holdings` | carries `period` + the `dimensions_raw` hierarchy |
| `fund_financials` | companyfacts | independent balance-sheet anchor (`investments_at_fair_value`) |
| `conservation` | `conservation_gate_results` | the residual to drive to zero -- the SCORE |

Commands: `schema` (tables + columns + the cik's conservation residual = the starting score)
and `query --sql "<one SELECT>"`.

## Safety model

- **cik-scoped by construction**: each table is materialized PRE-FILTERED to the cik, so even
  `SELECT * FROM holdings` cannot see another filer. No cross-cik haystacking.
- **read-only**: `validate_sql` allows a single `SELECT`/`WITH` only -- no DDL/DML/PRAGMA/
  multi-statement/comments.
- **no file/network from agent SQL**: after the four tables are materialized, the session does
  `SET enable_external_access=false`, so `read_parquet`/`read_csv`/`ATTACH` are blocked at
  runtime (belt) on top of the validator (suspenders).
- **bounded**: results are row-capped (`row_cap`, default 500) with a `truncated` flag.

## Worked proof (cik 1377936, 2026-02-28)

`schema` returns the residual `value_sum=1,467,904,175 vs anchor=1,109,133,812 (32.3% overshoot)`.
One agent query splits it by legal entity and surfaces the COMPOUND defect directly:

```
<parent>                                   122 rows   1,091,468,217   (17,665,595 BELOW anchor)
SaratogaInvestmentCorpCLO20131LtdMember    246 rows     376,435,958   (the CLO over-count)
```

i.e. the agent can see, from data alone, both the 376M CLO over-inclusion AND the 17.67M parent
under-inclusion -- the same finding the manual investigation produced.

## How it slots into the target architecture (remaining work)

This is piece (1) of the investigate-to-zero loop. Still to build:
1. **Grant the tool to the worker sandbox** -- add the CLI to the B2 worker's allowed reads
   (alongside `evidence_cli`), cik pinned to the packet. (Not done; the live trial depends on it.)
2. **The investigative loop** -- agent: `schema` -> query the residual structure + read the
   filing -> hypothesize -> author rule(s) as auditable artifacts -> apply/regenerate/gate ->
   re-query the residual -> repeat until ~0 or escalate. Budget-bounded, anchor-scored.
3. **Auditable rule output** -- the agent's deliverable is a reviewable per-CIK rule (explicit
   predicate + per-quarter scope + evidence + measured before/after), not a blanket runtime drop.

Deterministic stays the validator (B3 held-out gate) and the safe executor; agentic owns the
investigation + the rule authoring. This tool is what makes the agentic half possible.
