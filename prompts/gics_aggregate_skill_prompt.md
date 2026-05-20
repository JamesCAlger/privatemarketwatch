# GICS Classification + Aggregate Header Flagging -- CC Skill Prompt

You are classifying unresolved entities from SEC private markets filings. Each entity is an `issuer_name` that the automated pipeline could not classify into a GICS sub-industry. Your job is to triage each entity into one of four verdicts, using web search when needed.

## Setup

Load your assigned batch:

```python
import pandas as pd
batch = pd.read_csv("data/output/gics_skill_batches/batch_NNN.csv")
```

Each row has:
- `entity_id`: Unique ID within this batch
- `issuer_name_raw`: Original issuer name from the filing
- `name_norm`: Normalized name (lowercase, legal suffixes stripped) -- this is the cache key
- `search_name`: Best search term (DBA extracted, loan descriptors stripped)
- `total_fv`: Total fair value in dollars (priority signal)
- `n_positions`: Number of holdings positions affected
- `n_funds`: Number of distinct funds holding this name
- `typical_class`: Most common index classification (DIRECT_LENDING, COMMON_EQUITY, etc.)
- `sample_fund`: Example fund name holding this entity
- `sample_identifier`: Example raw BDC investment identifier (may contain instrument details)

## Four Verdicts

For each entity, assign exactly one verdict:

### 1. GICS -- Real Company
The entity is an identifiable operating company. Classify it into exactly one GICS sub-industry from the reference list below.

**Signals**: Legal entity suffixes (LLC, Inc., Corp., Ltd.), identifiable business operations, web search returns company information, held by multiple funds.

### 2. AGGREGATE_HEADER -- Leaked Category/Subtotal Row
The entity is NOT a real company -- it is a category label, section header, or subtotal that leaked through the pipeline's aggregate filter.

**Signals**:
- No entity signals (no LLC, Inc., Corp., etc.)
- Reads like a category label: "Senior Secured First Lien Term Loans", "Debt Investments", "Portfolio Company Investments"
- Bare industry labels: "Aerospace & Defense", "Healthcare", "Technology"
- Percentage patterns without company names: "85.2% Senior Secured First Lien"
- Contains "Total", "Subtotal", "Net Assets" without a company name
- Affiliation-level headers: "Non-Controlled Non-Affiliated Investments"
- Very short generic terms: "Cash", "Equity", "Warrants" (without company context)
- `n_funds` = 1 is common (leaked from a single filer's XBRL structure)

### 3. JV_SUBSIDIARY -- Joint Venture / Structured Vehicle
The entity name identifies a JV, co-investment vehicle, funding entity, or subsidiary SPV that is not an operating company but IS a legitimate position (not an aggregate header).

**Signals**: "JV", "Joint Venture", "Co-Invest", "Co-Investment", "Funding Vehicle", "Funding Entity", "Program", "Credit Facility", "Senior Loan Fund", "Warehouse", "Holding Vehicle". Often has a legal suffix (LLC) but web search reveals no operating business.

These should NOT be excluded from the pipeline -- they represent real holdings. The JV_SUBSIDIARY flag is informational only.

### 4. UNRESOLVABLE -- Cannot Determine
After searching, you cannot determine what this entity is. This includes:
- PE codenames with no public information (e.g., "Project Maple Bidco")
- Ambiguous names that could be a company or a vehicle
- Names that return no useful search results

## Triage Before Search

To save time, triage BEFORE doing web searches. Many entities can be classified on name alone:

**Immediately flag as AGGREGATE_HEADER (no search needed)**:
- Names that are bare instrument categories: "First Lien Senior Secured Term Loans"
- Names with "Total" + category: "Total Debt Investments", "Total First Lien"
- Bare industry labels matching known GICS sectors
- Affiliation-hierarchy headers: "Non-Controlled/Non-Affiliated Investments"
- Bare geographic labels: "United States", "Europe"

**Immediately flag as JV_SUBSIDIARY (no search needed)**:
- Names containing "JV", "Joint Venture", "Co-Invest", "Funding Vehicle"
- Names that are clearly SPVs: "[Company] Senior Loan Fund", "[Company] Credit Facility LLC"

**Search the rest** using the `search_name` column. Use web search to find what the company does, then classify into a GICS sub-industry.

## GICS Sub-Industry Reference

Use EXACTLY one of these names (spelling must match):

Oil & Gas Drilling, Oil & Gas Equipment & Services, Integrated Oil & Gas, Oil & Gas Exploration & Production, Oil & Gas Refining & Marketing, Oil & Gas Storage & Transportation, Coal & Consumable Fuels, Commodity Chemicals, Diversified Chemicals, Fertilizers & Agricultural Chemicals, Industrial Gases, Specialty Chemicals, Construction Materials, Metal, Glass & Plastic Containers, Paper & Plastic Packaging Products & Materials, Copper, Diversified Metals & Mining, Gold, Precious Metals & Minerals, Silver, Aluminum, Steel, Aerospace & Defense, Building Products, Construction & Engineering, Electrical Components & Equipment, Heavy Electrical Equipment, Industrial Conglomerates, Construction Machinery & Heavy Transportation Equipment, Agricultural & Farm Machinery, Industrial Machinery & Supplies & Components, Trading Companies & Distributors, Commercial Printing, Environmental & Facilities Services, Office Services & Supplies, Diversified Support Services, Security & Alarm Services, Human Resource & Employment Services, Research & Consulting Services, Data Processing & Outsourced Services, Air Freight & Logistics, Passenger Airlines, Marine Transportation, Rail Transportation, Cargo Ground Transportation, Passenger Ground Transportation, Airport Services, Highways & Railtracks, Marine Ports & Services, Automobile Parts & Equipment, Tires & Rubber, Automobile Manufacturers, Motorcycle Manufacturers, Consumer Electronics, Home Furnishings, Homebuilding, Household Appliances, Housewares & Specialties, Leisure Products, Apparel, Accessories & Luxury Goods, Footwear, Textiles, Casinos & Gaming, Hotels, Resorts & Cruise Lines, Leisure Facilities, Restaurants, Education Services, Specialized Consumer Services, Distributors, Broadline Retail, Specialty Stores, Apparel Retail, Computer & Electronics Retail, Home Improvement Retail, Automotive Retail, Homefurnishing Retail, Food Distributors, Food Retail, Consumer Staples Merchandise Retail, Drug Retail, Agricultural Products & Services, Packaged Foods & Meats, Tobacco, Soft Drinks & Non-alcoholic Beverages, Brewers, Distillers & Vintners, Household Products, Personal Care Products, Health Care Equipment, Health Care Supplies, Health Care Distributors, Health Care Services, Health Care Facilities, Managed Health Care, Health Care Technology, Biotechnology, Pharmaceuticals, Life Sciences Tools & Services, Diversified Banks, Regional Banks, Diversified Financial Services, Multi-Sector Holdings, Specialized Finance, Commercial & Residential Mortgage Finance, Transaction & Payment Processing Services, Consumer Finance, Asset Management & Custody Banks, Investment Banking & Brokerage, Diversified Capital Markets, Financial Exchanges & Data, Mortgage REITs, Insurance Brokers, Life & Health Insurance, Multi-line Insurance, Property & Casualty Insurance, Reinsurance, IT Consulting & Other Services, Internet Services & Infrastructure, Application Software, Systems Software, Communications Equipment, Technology Hardware, Storage & Peripherals, Electronic Equipment & Instruments, Electronic Components, Electronic Manufacturing Services, Technology Distributors, Semiconductor Materials & Equipment, Semiconductors, Alternative Carriers, Integrated Telecommunication Services, Wireless Telecommunication Services, Electric Utilities, Gas Utilities, Multi-Utilities, Water Utilities, Independent Power Producers & Energy Traders, Renewable Electricity, Diversified REITs, Industrial REITs, Hotel & Resort REITs, Office REITs, Health Care REITs, Residential REITs, Retail REITs, Specialized REITs, Other Specialized REITs, Timber REITs, Telecom Tower REITs, Data Center REITs, Self-Storage REITs, Real Estate Operating Companies, Real Estate Development, Real Estate Services, Diversified Real Estate Activities, Interactive Media & Services, Movies & Entertainment, Broadcasting, Cable & Satellite, Publishing, Advertising, Interactive Home Entertainment

## GICS Classification Rules

1. **Bidcos / acquisition vehicles**: Search for "[name] acquisition" or "[name] private equity" to find the target operating company. Classify by the target's industry.

2. **Goldman Sachs hierarchy names**: The `issuer_name_raw` may have an embedded industry prefix (e.g., "Software Acme Corp"). Use the company portion after the industry label.

3. **DBA / trade names**: If `search_name` differs from `issuer_name_raw`, the search name has the DBA extracted -- search using that.

4. **Multi-industry conglomerates**: Use the dominant revenue segment.

5. **Healthcare IT / fintech**: Classify by the PRIMARY customer -- health care IT companies go to "Health Care Technology", payment processors go to "Transaction & Payment Processing Services".

6. **Confidence threshold**: Only assign a GICS if you have reasonable evidence. "medium" confidence is fine. Do not guess without any signal.

## Recording Results

After processing each batch of ~20 entities, write results to both cache files:

### GICS verdicts -> `company_gics_cache.csv`

```python
import pandas as pd
from datetime import datetime, timezone

cache = pd.read_csv("data/output/company_gics_cache.csv")

new_gics = [
    {"company_name_norm": "acme software", "gics_sub_industry": "Application Software", "confidence": "high", "source": "cc_skill", "timestamp": datetime.now(timezone.utc).isoformat()},
    # ... more entries
]

new_df = pd.DataFrame(new_gics)
cache = cache[~cache["company_name_norm"].isin(new_df["company_name_norm"])]
cache = pd.concat([cache, new_df], ignore_index=True)
cache.to_csv("data/output/company_gics_cache.csv", index=False)
```

### Non-GICS verdicts -> `aggregate_header_flags.csv`

```python
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

flags_path = Path("data/output/aggregate_header_flags.csv")
COLUMNS = ["name_norm", "issuer_name_raw", "verdict", "confidence", "evidence",
           "total_fv", "n_positions", "reviewed_by", "reviewed_at", "batch_id"]

if flags_path.exists():
    flags = pd.read_csv(flags_path, dtype=str)
else:
    flags = pd.DataFrame(columns=COLUMNS)

new_flags = [
    {
        "name_norm": "senior secured first lien term loans",
        "issuer_name_raw": "Senior Secured First Lien Term Loans",
        "verdict": "AGGREGATE_HEADER",
        "confidence": "high",
        "evidence": "Bare instrument category label, no entity signals",
        "total_fv": "50000000",
        "n_positions": "12",
        "reviewed_by": "cc_skill",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": "001",
    },
    {
        "name_norm": "acme co-invest vehicle",
        "issuer_name_raw": "Acme Co-Invest Vehicle, LLC",
        "verdict": "JV_SUBSIDIARY",
        "confidence": "high",
        "evidence": "Co-investment SPV, no operating business found",
        "total_fv": "25000000",
        "n_positions": "4",
        "reviewed_by": "cc_skill",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "batch_id": "001",
    },
]

new_df = pd.DataFrame(new_flags)
flags = flags[~flags["name_norm"].isin(new_df["name_norm"])]
flags = pd.concat([flags, new_df], ignore_index=True)
flags.to_csv(flags_path, index=False)
```

### Update batch claim

After finishing your batch:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

claims_path = Path("data/output/gics_skill_claims.json")
claims = json.loads(claims_path.read_text()) if claims_path.exists() else {}
claims["NNN"] = {
    "status": "done",
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "n_gics": 45,
    "n_aggregate": 30,
    "n_jv": 15,
    "n_unresolvable": 10,
}
claims_path.write_text(json.dumps(claims, indent=2))
```

## Batch Processing Workflow

1. Load your batch CSV
2. Triage all entities by name (flag obvious aggregates and JVs without searching)
3. Web search the remaining entities (the real company candidates)
4. Record results in batches of ~20
5. Update the claim file when done
6. Report summary: N GICS, N AGGREGATE_HEADER, N JV_SUBSIDIARY, N UNRESOLVABLE, total FV covered

## Stopping Criteria

Stop when all entities in your assigned batch are processed.

## Integration

- GICS results in `company_gics_cache.csv` are automatically applied on the next `python -m pipeline.main --unified` run via the existing `classify_gics(cache_only=True)` path.
- AGGREGATE_HEADER flags in `aggregate_header_flags.csv` are applied during BDC staging in `staging_bdc.py` to exclude leaked rows.
- JV_SUBSIDIARY and UNRESOLVABLE flags are informational only -- they do not change pipeline behavior.
- After all batches are done, run `python scripts/gics_merge_results.py --validate --apply` to validate and rebuild.
