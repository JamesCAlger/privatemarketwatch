# Classify UNCLASSIFIED Holdings Chunk

You are classifying investment holdings that the heuristic classifier could not resolve. You will process a single chunk file containing ~50 entities, one per line.

## Input

Read the chunk file at `data/output/unclassified_agent_chunk_NNN.txt`. Each line is pipe-delimited:

```
name_norm||issuer_name_raw||source||issuer_category||total_fv||interest_rate||shares||instrument||identifier
```

Fields:
- `name_norm`: normalized issuer name (lowercase, no legal suffixes)
- `issuer_name_raw`: original issuer name as filed
- `source`: `bdc` (10-K/10-Q) or `nport` (N-PORT quarterly)
- `issuer_category`: `CORPORATE` or `FUND` or `OTHER`
- `total_fv`: total fair value across all positions (USD)
- `interest_rate`: sample interest rate (or `nan`)
- `shares`: sample shares held (or `nan`)
- `instrument`: sample instrument description (or `nan`)
- `identifier`: sample BDC investment identifier string (or `nan`)

## Task

Process EVERY row, one at a time. Do NOT skip rows. Do NOT batch-classify. For each row, determine the verdict by examining the name, source, category, and financial signals.

### Verdict Definitions

**AGGREGATE_HEADER** -- The name is NOT a real company or fund. It is a section header, category label, subtotal row, industry grouping, or asset-type bucket that leaked from a filing's schedule of investments. Examples:
- Bare industry labels: "Beverage, Food & Tobacco", "U.S. Corporate Debt", "Financial Services"
- Asset type headers: "Senior Secured Loans", "First Lien Debt", "Equity Investments"
- Subtotal/total rows: "Total First Lien", "Other cash accounts"
- Country + instrument combos: "United States of America 1st Lien/Secured Loans"
- Affiliation headers: "Non-Controlled Non-Affiliated Investments"

If in doubt whether something is a real entity vs. a header, consider: would a real company have this exact name? "Software" is a header. "Software AG" is a company.

**JV_SUBSIDIARY** -- The entity is a joint venture, co-investment vehicle, SPV, warehouse facility, or funding vehicle created by the fund itself. These are NOT independent portfolio companies. Examples:
- "Credit Opportunities Partners JV LLC"
- "CD&R Mercury Co-Investor, L.P."
- "Blue Owl Credit SLF LLC"

**CLASSIFIED** -- The entity is a real company or fund that you can assign to an index classification. Use web search if needed to determine what the entity does.

**UNRESOLVABLE** -- After reasonable effort (including web search), you cannot determine what this entity is. Use sparingly.

### Index Classifications (only when verdict = CLASSIFIED)

| Classification | When to use |
|---|---|
| `DIRECT_LENDING` | Corporate borrower with a loan (term loan, revolver, credit facility, secured/unsecured debt). Most BDC holdings are this. |
| `COMMON_EQUITY` | Common stock, LLC interest, membership interest, warrants in an operating company |
| `PREFERRED_EQUITY` | Preferred stock, preferred units in an operating company |
| `HEDGE_FUND` | Hedge fund (Millennium, Elliott, Point72, D.E. Shaw, multi-strategy, macro, long/short) |
| `PRIVATE_EQUITY_FUND` | PE fund, buyout fund, growth equity fund, venture fund, secondaries fund |
| `PRIVATE_CREDIT_FUND` | Credit fund, CLO, BDC, direct lending fund, loan fund |
| `REAL_ESTATE_FUND` | Real estate fund, REIT fund, property fund |
| `STRUCTURED_CREDIT` | CLO tranche, structured note, securitization vehicle |
| `CASH` | Money market fund, treasury, cash equivalent |

### Asset Class (only when verdict = CLASSIFIED)

| Asset class | When to use |
|---|---|
| `LOAN` | Debt instrument (term loan, revolver, note, bond) |
| `EQUITY_COMMON` | Common equity, LLC interest, warrant |
| `EQUITY_PREFERRED` | Preferred equity |
| `FUND` | Fund interest (hedge, PE, credit, RE fund) |
| `UNKNOWN` | Cannot determine asset class |

### Confidence

- `high` -- Name is unambiguous or web search confirms (e.g., "Millennium International" is clearly a hedge fund)
- `medium` -- Reasonable inference from name pattern (e.g., "Acme Capital Partners I, L.P." is likely PE)
- `low` -- Uncertain, best guess

## Output

Write results to `data/output/campaign_results/unclassified/unclassified_agent_results_NNN.csv` (same NNN as the input chunk). CSV with header row and these columns:

```
name_norm,verdict,new_index_classification,asset_class,confidence,evidence
```

The `evidence` field is a single sentence explaining your reasoning. No commas in evidence -- use semicolons if needed.

### Example output rows:

```
name_norm,verdict,new_index_classification,asset_class,confidence,evidence
millennium,CLASSIFIED,HEDGE_FUND,FUND,high,Millennium International is a well-known multi-strategy hedge fund
u.s. corporate debt,AGGREGATE_HEADER,,,,Bare asset-type category label from schedule of investments
cd&r mercury co-investor,JV_SUBSIDIARY,,,,Clayton Dubilier & Rice co-investment vehicle
signifyd,CLASSIFIED,COMMON_EQUITY,EQUITY_COMMON,medium,Signifyd is a fraud prevention software company; held as equity
other cash accounts,AGGREGATE_HEADER,,,,Generic cash bucket label not a real entity
```

## Procedure

1. Read the chunk file
2. For EACH row (do not skip any):
   a. Parse the pipe-delimited fields
   b. Examine the name -- is it an aggregate header or JV/SPV?
   c. If `issuer_category=FUND` and the name is a known fund, classify by fund type
   d. If `issuer_category=CORPORATE`, use the name + instrument + identifier to determine if it is a lending position (DIRECT_LENDING) or equity position (COMMON_EQUITY/PREFERRED_EQUITY)
   e. Use web search when the name alone is ambiguous -- search for "[company name] company" or "[fund name] fund"
   f. Write one output row
3. After processing ALL rows, write the CSV
4. Report a summary: how many of each verdict type

## Important Rules

- Process EVERY row. The output CSV must have exactly as many data rows as the input chunk has lines.
- Do NOT guess based on position in the file or similarity to neighboring rows. Each row is independent.
- When using web search, search for the SPECIFIC entity name. Do not assume.
- For N-PORT FUND entities with names like "[Name] Offshore Fund Ltd" or "[Name] International Fund" -- these are almost always hedge funds. Classify as HEDGE_FUND with high confidence if the name contains "offshore fund", "international fund", or the manager is a known hedge fund.
- For BDC CORPORATE entities with no financial signals (all nan), look at the `instrument` and `identifier` fields for clues. "LLC Interest" or "equity investment" suggests COMMON_EQUITY. Absence of instrument info with a HoldCo/TopCo name often means equity.
