# FAIL Verification Playbooks

## C101

Missing `fair_value` on an indexable row. Compare the unified row with the raw
BDC or N-PORT row. If the raw source has fair value and unified does not, treat
as a confirmed data error. If the raw source is missing fair value too, the row
is still unsafe for index use. If the raw row cannot be found, use insufficient
evidence.

## X06

Principal amount is more than 10x fair value. X06 is a proxy -- a high
principal/FV ratio can mean several different things. The bundle already
contains fields that distinguish them. Apply the decision tree below in order;
stop at the first match.

### Decision tree

1. **Unfunded commitment (CONFIRMED_VALID_EXCEPTION, VALID_SOURCE_EXCEPTION)**
   Trigger: `issuer_name` or `instrument_description` contains "unfunded",
   "revolver", "delayed draw", or "commitment"; OR `fair_value` is zero/nominal
   ($0-$0.01), `cost` is zero/nominal, AND `interest_rate` = 0 / `coupon_type`
   is empty.  N-PORT raw `unit` = PA with `currency_value` near zero further
   confirms.  `nport_is_default` = N rules out default.

2. **Equity position with spurious principal (CONFIRMED_DATA_ERROR, SCALE_MISMATCH)**
   Trigger: `asset_category` is an equity type (EQUITY_COMMON, EQUITY_PREFERRED,
   EQUITY_OTHER) or `index_classification` is COMMON_EQUITY / PREFERRED_EQUITY,
   AND `cost` is within 2x of `fair_value`, AND `principal_amount` > 100x both.
   Equity positions have no meaningful dollar principal -- the XBRL parser
   captured a fact (shares, notional) that is not dollar principal.

3. **Scale / extraction error (CONFIRMED_DATA_ERROR, SCALE_MISMATCH)**
   Trigger: `cost` and `fair_value` agree (within 2x of each other) but
   `principal_amount` > 100x both.  The cost-FV agreement rules out distress;
   the principal divergence indicates a unit or parse error.  Check nearby
   holdings from the same filing -- if they show normal principal/FV ratios,
   the error is position-specific.

4. **Credit distress (CONFIRMED_VALID_EXCEPTION, VALID_SOURCE_EXCEPTION)**
   Trigger: `fair_value` > 0 (meaningful, not nominal), `interest_rate` > 0 or
   `coupon_type` is Fixed/Floating, AND FV / principal is between 0.01 and 0.80
   (i.e. 1-80 cents on the dollar).  Corroborating signals: `nport_is_default`
   = Y, `nport_are_interest_payments_in_arrears` = Y, large negative
   `bdc_unrealized_gain_loss`.

5. **N-PORT reporting convention (CONFIRMED_VALID_EXCEPTION, VALID_SOURCE_EXCEPTION)**
   Trigger: N-PORT source with `unit` = PA, `balance` = commitment notional,
   `currency_value` = funded amount near FV.  The principal field carries the
   notional while FV carries the mark.  Normal for performing private credit.

6. **Insufficient evidence**
   If none of the above patterns match, use INSUFFICIENT_EVIDENCE.  Record
   which signals were checked and why none were conclusive.

## X09

`pct_of_net_assets` is above 100. Check the CIK-quarter pct sum, fund
financials, leverage, and duplicate dimension-path evidence. Near-zero or
negative net assets can be a valid exception; duplicated position rows are a
confirmed data error.

### Named valid exception: master-feeder funds

A feeder fund that holds a single master fund position (plus a small cash
buffer) will routinely report pct_of_net_assets slightly above 100% for the
master holding. The mechanism: the feeder values the master at the master's
NAV, but the feeder's own net assets are lower by the feeder's accrued
liabilities (management fees, audit, legal). The cash buffer sits on top,
so the total pct sum exceeds 100%.

Signals:
- Fund has exactly 2 holdings: one large position (the master) and one small
  cash / money market position.
- The large position's `issuer_name` matches the fund's own name with "Master
  Fund" appended, or a related entity name.
- The pct > 100% is filer-reported (N-PORT `percentage` field), not
  pipeline-calculated.
- The pattern recurs across quarters (check historical holdings for the CIK).
- `fund_financials.csv` for the master CIK shows net_assets close to the
  feeder's holding FV.

Verdict: CONFIRMED_VALID_EXCEPTION, root_cause VALID_SOURCE_EXCEPTION.
The feeder's holdings contribute no useful index constituents -- the actual
private market positions live at the master fund level.

## C402

Debt maturity date year is before 1900. Compare parsed maturity date with the
raw source date. Two-digit year parsing and corrupted extraction are data
errors. Consistent sentinel values may be valid source exceptions.

## GAV_BDC01

BDC CIK-quarter GAV reconciliation ratio is extreme. The numerator is the
pipeline's BDC schedule holdings fair value and the preferred denominator is
reported investments at fair value. Review the reconciliation row, comparison
source, related row-level FAIL counts, position count stability, and filing
index.

Treat missing fair value, duplicated dimension paths, subtotal leakage, or
scale mismatch as CONFIRMED_DATA_ERROR. Treat wrong-period, wrong-entity, or
unreliable denominator selection as VALIDATOR_FALSE_POSITIVE. If the ratio is
extreme but the bundle does not show a mechanism, use INSUFFICIENT_EVIDENCE.

## GAV_NPORT01

N-PORT private-market holdings coverage is compared against a full-fund total
assets denominator. That is a scope-mismatch coverage signal, not by itself a
full-fund GAV FAIL, because the exported holdings intentionally exclude liquid
or out-of-scope N-PORT positions.

If sampled legacy `GAV_NPORT01` evidence shows only private-market-filtered
holdings versus full-fund total assets, classify it as VALIDATOR_FALSE_POSITIVE
for FAIL purposes and retain it as a scoped WARN/DISCLOSE signal. Only classify
as CONFIRMED_DATA_ERROR when the evidence shows the N-PORT export was intended
to represent the full portfolio or the source rows prove missing/duplicated
private-market holdings.
