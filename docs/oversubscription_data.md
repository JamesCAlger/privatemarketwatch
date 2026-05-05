# Fund Oversubscription / Redemption Pressure — Data Availability

## Concept

**Oversubscription rate** = shares tendered / shares offered for repurchase.

- Rate = 1.0: fully subscribed
- Rate > 1.0: oversubscribed (pro-rata applies, investors get partial fills)
- Rate < 1.0: undersubscribed (all requests honored)

Relevant to interval funds, tender offer funds, and non-traded (semi-liquid) BDCs — all of which offer periodic share repurchases rather than continuous exchange liquidity.

## Data Sources by Vehicle Type

### Interval Funds (Rule 23c-3)

| Source | Data | Granularity | Demand Side? | In Pipeline? |
|---|---|---|---|---|
| N-PORT `REDEMPTION_FLOW_MON1/2/3` | Actual dollars redeemed per month | Quarterly | No — supply only | Yes (`redemption_pressure` in `fund_financials.csv`) |
| N-CSR / N-CSRS narrative | Shares tendered, shares accepted, % repurchased, pro-rata factor | Semi-annual (covers ~2 quarterly offers per filing) | Yes — exact | No |
| N-23C3A notifications | Offer terms (% offered, pricing date, deadline) | Per offer (quarterly) | No — forward-looking only | No |
| N-CEN `DID_REPURCHASE_SECURITY` | Boolean flag | Annual | No | No |

**Key constraint:** The mandatory quarterly repurchase caps redemptions at the offer percentage (typically 5% of NAV). N-PORT shows what was paid out, not what was requested. When `redemption_pressure` hits ~5%, the fund may have received 5% or 50% in requests — the degree of oversubscription is invisible.

**Binary signal:** `redemption_pressure` between 4.5-5.5% flags "at capacity" quarters. Sub-4.5% quarters are definitively undersubscribed with exact rates known.

**Coverage:** 34 interval fund CIKs with non-zero redemption data in N-PORT. ~19% of interval fund-quarters show the cap pattern.

### Tender Offer Funds

| Source | Data | Granularity | Demand Side? | In Pipeline? |
|---|---|---|---|---|
| SC TO-I/A (final amendment) | Shares tendered, shares accepted, proration %, repurchase price | Per offer (quarterly or semi-annual) | Yes — exact | No |
| N-PORT `REDEMPTION_FLOW` | Same as interval funds | Quarterly | No — supply only | Yes |
| N-CSR / N-CSRS narrative | Same as interval funds | Semi-annual | Yes — exact | No |

**Key advantage:** Tender offer funds file SC TO-I for each offer. The final amendment (SC TO-I/A) is filed ~5-6 weeks after offer expiration and contains exact results. 20 of 39 tender offer funds in the universe have these filings.

### Non-Traded (Semi-Liquid) BDCs

| Source | Data | Granularity | Demand Side? | In Pipeline? |
|---|---|---|---|---|
| SC TO-I/A (final amendment) | Shares tendered, shares accepted, proration %, repurchase price | Per offer (quarterly) | Yes — exact | No |
| XBRL `PaymentsForRepurchaseOfCommonStock` | Dollars repurchased | Quarterly (10-K/10-Q) | No — supply only | No (concept exists in companyfacts for 109 CIKs) |
| XBRL `StockRepurchasedDuringPeriodShares` | Shares repurchased | Quarterly | No — supply only | No |
| XBRL `StockRepurchaseProgramAuthorizedAmount1` | Program size (cap) | Point-in-time | No — capacity only | No |

**Major non-traded BDCs with SC TO-I filings:**

| CIK | Entity | NAV | SC TO-I/A Count |
|---|---|---|---|
| 1803498 | Blackstone Private Credit Fund | $48B | 21 + 34 amendments |
| 1812554 | Owl Rock Core Income Corp | $20B | 19 + 25 amendments |
| 1655887 | Owl Rock Capital Corp II | $950M | 33 + 40 amendments |
| 1918712 | Ares Strategic Income Fund | $10.5B | 10 + 12 amendments |
| 1837532 | Apollo Debt Solutions BDC | ~$5B | 16 + 15 amendments |

**Observed oversubscription events (Q1 2026):**
- Owl Rock Core Income: 22.8% acceptance rate (4.4x oversubscribed)
- Ares Strategic Income: 43.1% acceptance rate (2.3x oversubscribed)
- Blackstone Private Credit: 100% accepted in 18/20 quarters (sufficient liquidity reserves)

### Traded BDCs

Oversubscription does not apply. These trade on exchanges at market price. The analogous liquidity metric is **discount/premium to NAV** (market price vs. NAV per share).

## What Is Computable Today (No New Extraction)

1. **Interval fund binary signal**: `redemption_pressure` in `fund_financials.csv` (threshold 4.5-5.5% = at capacity). 34 CIKs, quarterly.
2. **Exact undersubscription rate**: For all interval fund quarters below the cap threshold.

## What Requires New Extraction

| Priority | Work | Yield |
|---|---|---|
| 1 | Parse SC TO-I/A final amendments (~20 non-traded BDCs + ~20 tender offer funds) | Exact quarterly oversubscription for ~$85B+ NAV |
| 2 | Add XBRL repurchase concepts to `fund_financials.py` | Supply-side quarterly for 109 BDCs (binary cap signal) |
| 3 | Parse N-CSR/N-CSRS repurchase tables (~34 interval funds) | Exact oversubscription degree, backfills cap-blind quarters |

## SC TO-I/A Parsing Notes

The final amendment filings follow a parseable structure:
- "X Shares validly tendered"
- "accepted for purchase Y Shares on a pro rata basis"
- "representing Z% of the Shares"
- Per-share repurchase price in tabular format
- Filing fee XBRL has `TxValtn` = aggregate max purchase price (offer amount)

Form type filter for EFTS: `forms=SC+TO-I,SC+TO-I/A`

## N-CSR/N-CSRS Parsing Notes

Repurchase results appear in a structured table within the shareholder report:
- "Repurchase Offer" or "Periodic Repurchase Offers" section
- Fields: Commencement Date, Repurchase Request Deadline, Amount Repurchased, Shares Repurchased, % Outstanding Offered, % Outstanding Repurchased
- Some funds include "Percentage of Shares Tendered that were Repurchased" (direct oversubscription metric)
- Pro-rata narrative: "the Fund repurchased approximately X% of the total number of shares tendered"

Form type filter for EFTS: `forms=N-CSR,N-CSRS`

## Fundamental Constraint

Exact oversubscription (demand side) only exists in narrative filings — SC TO-I/A for non-traded BDCs and tender offer funds, N-CSR/N-CSRS for interval funds. All structured/XBRL sources only show what was actually redeemed (supply side, capped at offer amount). There is no XBRL concept or structured field in any SEC form that captures "total shares tendered" directly.
