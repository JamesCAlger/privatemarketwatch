# BDC Sector Breakdown (XBRL Industry Axis)

## What it is

BDC 10-K/10-Q XBRL filings contain per-industry aggregate data via the `EquitySecuritiesByIndustryAxis` dimension. This gives per-CIK, per-quarter sector concentration breakdowns -- total fair value, cost, and % of net assets for each industry sector a BDC is invested in.

## Data source

The data comes from cached XBRL instance documents in `data/raw/filings/bdc_xbrl/{cik}/`. The extraction reads XML contexts that have the `EquitySecuritiesByIndustryAxis` dimension but do NOT have `InvestmentIdentifierAxis` (which marks position-level data).

### XBRL structure

Each industry-level aggregate appears as a context with explicit dimension members:

```xml
<context id="ia7ba5a...">
  <segment>
    <explicitMember dimension="us-gaap:EquitySecuritiesByIndustryAxis">
      glad:HealthcareEducationAndChildcareMember
    </explicitMember>
    <explicitMember dimension="us-gaap:InvestmentTypeAxis">
      glad:DebtSecuritiesSecuredFirstLienDebtMember
    </explicitMember>
  </segment>
  <period><instant>2024-12-31</instant></period>
</context>
```

Facts reported against these contexts:
- `InvestmentOwnedAtFairValue` -- aggregate FV for this industry
- `InvestmentOwnedAtCost` -- aggregate cost basis
- `InvestmentOwnedPercentOfNetAssets` -- % of net assets
- `ConcentrationRiskPercentage1` -- alternative % measure (duration contexts)

## Why it's aggregate-only

For ~110 of ~174 CIKs with this data, the industry breakdown is reported only at the aggregate level (total FV per sector), NOT per-position. Per-position industry data would require parsing it out of the `InvestmentIdentifierAxis` member strings (e.g., "Senior Secured Loans | First Lien | Acme Corp | Technology"), which is filer-specific. The `extracted_industry` field on unified holdings handles that separately via identifier parsing.

## Member name normalization

Raw XBRL member names like `glad:HealthcareEducationAndChildcareMember` are normalized to readable labels:
1. Strip namespace prefix (`glad:`)
2. Remove `Member` / `Sector` suffix
3. Convert CamelCase to space-separated lowercase

Result: `healthcare education and childcare`

Industry labels are filer-reported and NOT standardized across BDCs. The same sector may appear as "Healthcare" in one BDC and "Healthcare Education And Childcare" in another.

## Output

`data/output/bdc_sector_breakdown.csv`

| Column | Type | Description |
|--------|------|-------------|
| `cik` | str | SEC CIK |
| `entity_name` | str | BDC name |
| `report_date` | str | Balance sheet date |
| `industry_sector` | str | Normalized industry label |
| `investment_type` | str | Investment type (e.g., "debt securities secured first lien debt"), empty if not broken down |
| `fair_value` | float | Aggregate FV for this sector |
| `cost` | float | Aggregate cost basis |
| `pct_of_net_assets` | float | % of net assets (decimal, e.g., 0.223 = 22.3%) |

## Coverage

- ~174 CIKs with industry axis data (out of ~229 with XBRL)
- ~15 sectors per CIK on average
- Estimated ~26K total rows

## Usage

```bash
# Extract as part of financials step
python -m pipeline.main --financials

# Or rebuild from cached XBRL (no downloads)
python scripts/rebuild_outputs.py --financials
```

The frontend export (`--export-frontend`) produces `industry_breakdown.json` with both index-level (cross-CIK aggregate) and per-CIK breakdowns.
