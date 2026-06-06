# Data Gap Assessment — Design vs. Pipeline

Assessed 2026-05-28. Compares the data required by the new frontend design (this folder) against what the SEC XBRL pipeline actually produces.

## Verdict

Most of the design is buildable from existing pipeline data plus straightforward new aggregations. Four items require new data sources that the pipeline does not currently have.

## What's covered

The pipeline produces position-level holdings (718K rows, 89 columns), fund-level financials (692 funds), index-level time series, and 22 frontend JSON exports. The following design elements map directly or with minor new aggregation work:

- **Homepage**: index levels + sparklines, universe stats, industry donut, portfolio characteristics band, manager concentration, yield leaderboard, fund universe table, distribution/leverage histograms
- **Index detail**: index level charts, return summary (from filing-reported net returns), top 25 constituents, top funds contributing, sector/manager composition, methodology text
- **Fund detail**: identity/snapshot, portfolio characteristics, top holdings table, position type breakdown, quarterly return series
- **Static pages**: Methodology, Data, About — no data dependency

## What needs new computation from existing data (no new sources)

These are all derivable from the current holdings CSV, fund financials, and index returns. They need new aggregation logic and/or export paths, not new data:

| Item | Work |
|---|---|
| AUM time series by wrapper type (BDC/interval/tender) | New aggregation in `export_frontend.py` from fund_list + vehicleType |
| Per-index portfolio characteristics | Split `portfolio_characteristics.json` by `index_classification` |
| Per-index sector/manager breakdowns | Filter existing concentration JSONs by index |
| Risk statistics (vol, Sharpe, drawdown, best/worst Q) | Rolling-window math on quarterly return series |
| Credit distress quarterly time series | Aggregate position-level unrealized G/L + non-accrual flags by quarter |
| Peer ranking engine (quartile cards on fund detail) | Percentile ranks across fund_list metrics |
| Fund-level filings export | Add `bdc_filings_index.csv` rows to per-fund JSON |
| Fund-level industry/position-type detail | Richer per-fund export from holdings |
| Index metadata constants (inception date, rebalance, base level) | Static config additions |
| NAV-price spread charts (homepage + BDC fund detail) | Requires market price data — assumed available per project decision |
| Common Equity co-invest flag | Regex on `issuer_name` / `investment_identifier` — 621 positions (3% of CE), high confidence |
| Common Equity hold period | First/last appearance per [CIK, position] across quarters — minimal left-censoring (55 of 20,384 positions touch the 2019 boundary) |
| Net index return series | Buildable from filing-reported fund-level net returns; no fee model needed |

## What's missing — requires new data sources

| # | Gap | Affected pages | Source needed | Difficulty |
|---|---|---|---|---|
| 1 | **External benchmark time series** (S&P LSTA Leveraged Loan Index, S&P 500, Russell 2000) | Index detail performance charts (benchmark line + return comparison) | Data license, manual entry, or free proxy | Low-medium |
| 2 | **Interval fund liquidity terms** (tender frequency, notice period, fees, lockup, gate provisions) | Interval fund detail — liquidity terms block | N-2 prospectus filings (not currently parsed) | High |
| 3 | **Tender offer history** (per-quarter: offered %, tendered %, fulfilled %, pro-rata flag) | Interval fund detail — tender history chart + table | N-CSR shareholder reports or 8-K filings (not currently ingested) | High |
| 4 | **Fund address** | Fund detail identity band | EDGAR entity metadata (available, just not pulled) | Trivial |

## Design changes from this assessment

| Original design element | Decision | Reason |
|---|---|---|
| Common Equity "Sponsor-Backed %" characteristic | **Drop** | 7 keyword hits out of 73,806 CE rows. SEC filings do not disclose deal sourcing. Would need PitchBook/Preqin. |
| Preferred Equity characteristics (cumulative, redeemable, perpetual flags) | **Drop** | N-PORT and BDC XBRL do not consistently expose these as structured fields. |
| Fee model / gross-net decomposition | **Drop** | Net returns available directly from filings. Fee drag as a separate metric adds complexity without adding a datapoint we don't already have. |
