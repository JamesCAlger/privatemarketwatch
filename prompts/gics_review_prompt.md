# GICS Review Queue — Claude Code Prompt

You are reviewing companies that an automated classifier could not assign to a GICS sub-industry. Your job is to research each company using web search and classify it into exactly one of the 161 GICS sub-industries, or confirm "Other" if the company truly cannot be classified.

## Setup

The review queue is at `data/output/gics_review_queue.csv`. Load it and process companies in order (highest FV first).

```python
import pandas as pd
queue = pd.read_csv("data/output/gics_review_queue.csv")
```

Each row has:
- `company_name_norm`: Normalized company name (this is the cache key)
- `search_name`: Best search term (use this for web searches)
- `evidence`: What the previous classifier found (may say "Unable to find...")
- `sources`: URLs found during previous search (may be empty)
- `context`: Position type and fund name (e.g., "DIRECT_LENDING; held by Blackstone Private Credit Fund")
- `total_fv`: Total fair value in dollars (priority signal)
- `n_positions`: Number of holdings positions affected

## Your Workflow

For each company in the queue:

1. **Search** using `search_name`. If the previous `evidence` already describes the business, skip to step 3.
2. **Read** the top result if needed to understand what the company does.
3. **Classify** into exactly one GICS sub-industry from this list:

<gics_list>
Oil & Gas Drilling, Oil & Gas Equipment & Services, Integrated Oil & Gas, Oil & Gas Exploration & Production, Oil & Gas Refining & Marketing, Oil & Gas Storage & Transportation, Coal & Consumable Fuels, Commodity Chemicals, Diversified Chemicals, Fertilizers & Agricultural Chemicals, Industrial Gases, Specialty Chemicals, Construction Materials, Metal, Glass & Plastic Containers, Paper & Plastic Packaging Products & Materials, Aluminum, Copper, Diversified Metals & Mining, Gold, Precious Metals & Minerals, Silver, Steel, Paper Products, Forest Products, Aerospace & Defense, Building Products, Construction & Engineering, Electrical Components & Equipment, Heavy Electrical Equipment, Industrial Conglomerates, Industrial Machinery & Supplies & Components, Trading Companies & Distributors, Commercial Printing, Environmental & Facilities Services, Office Services & Supplies, Diversified Support Services, Security & Alarm Services, Human Resource & Employment Services, Research & Consulting Services, Data Processing & Outsourced Services, Air Freight & Logistics, Passenger Airlines, Marine Transportation, Railroads, Cargo Ground Transportation, Airport Services, Highways & Railtracks, Marine Ports & Services, Automobile Parts & Equipment, Tires & Rubber, Automobile Manufacturers, Motorcycle Manufacturers, Consumer Electronics, Home Furnishings, Homebuilding, Household Appliances, Housewares & Specialties, Leisure Products, Apparel, Accessories & Luxury Goods, Footwear, Textiles, Casinos & Gaming, Hotels, Resorts & Cruise Lines, Leisure Facilities, Restaurants, Education Services, Specialized Consumer Services, Distributors, Broadline Retail, Specialty Stores, Consumer Staples Merchandise Retail, Drug Retail, Food Distributors, Food Retail, Brewers, Distillers & Vintners, Soft Drinks & Non-alcoholic Beverages, Agricultural Products & Services, Packaged Foods & Meats, Tobacco, Household Products, Personal Care Products, Health Care Equipment, Health Care Supplies, Health Care Distributors, Health Care Services, Health Care Facilities, Managed Health Care, Health Care Technology, Biotechnology, Pharmaceuticals, Life Sciences Tools & Services, Diversified Banks, Regional Banks, Diversified Financial Services, Multi-Sector Holdings, Consumer Finance, Specialized Finance, Transaction & Payment Processing Services, Insurance Brokers, Financial Exchanges & Data, Life & Health Insurance, Multi-line Insurance, Property & Casualty Insurance, Reinsurance, IT Consulting & Other Services, Internet Services & Infrastructure, Application Software, Systems Software, Communications Equipment, Technology Hardware, Storage & Peripherals, Electronic Equipment & Instruments, Electronic Components, Electronic Manufacturing Services, Technology Distributors, Semiconductors, Semiconductor Materials & Equipment, Diversified Telecommunication Services, Integrated Telecommunication Services, Wireless Telecommunication Services, Alternative Carriers, Electric Utilities, Gas Utilities, Multi-Utilities, Water Utilities, Independent Power Producers & Energy Traders, Renewable Electricity, Diversified REITs, Industrial REITs, Hotel & Resort REITs, Office REITs, Health Care REITs, Multi-Family Residential REITs, Single-Family Residential REITs, Retail REITs, Other Specialized REITs, Self-Storage REITs, Timber REITs, Telecom Tower REITs, Data Center REITs, Real Estate Operating Companies, Real Estate Development, Real Estate Services, Diversified Real Estate Activities, Interactive Media & Services, Movies & Entertainment, Broadcasting, Cable & Satellite, Publishing, Advertising, Interactive Home Entertainment
</gics_list>

4. **Record** your classification. After processing a batch, update the cache:

```python
import pandas as pd
from datetime import datetime, timezone

# Load existing cache
cache = pd.read_csv("data/output/company_gics_cache.csv")

# Your classifications (append to this list as you go)
new_entries = [
    {"company_name_norm": "snoopy bidco", "gics_sub_industry": "Other", "confidence": "low", "source": "cc_review", "timestamp": datetime.now(timezone.utc).isoformat()},
    {"company_name_norm": "aventiv technologies, llc, third out super priority first lien term loan", "gics_sub_industry": "Integrated Telecommunication Services", "confidence": "high", "source": "cc_review", "timestamp": datetime.now(timezone.utc).isoformat()},
]

# Update cache (overwrite existing entries for these names)
new_df = pd.DataFrame(new_entries)
cache = cache[~cache["company_name_norm"].isin(new_df["company_name_norm"])]
cache = pd.concat([cache, new_df], ignore_index=True)
cache.to_csv("data/output/company_gics_cache.csv", index=False)
```

## Classification Rules

1. **PE codenames** (Snoopy Bidco, Project Maple, etc.): Search anyway. Sometimes the acquisition target is known. If you find it, classify the target company. If not, "Other".

2. **Bidcos / acquisition vehicles**: These are SPVs created for leveraged buyouts. The operating company is the target. Search for "[bidco name] acquisition" or "[bidco name] private equity" to find the target.

3. **Fund names** (Cortland Growth Fund, Clarion Properties): If it's clearly an investment fund or real estate fund, use "Diversified Financial Services" or the appropriate Real Estate GICS. If it's a PE/VC fund with no operating business, "Other".

4. **Companies found but hard to classify**: Use the dominant revenue segment. When in doubt, prefer the more specific GICS over a broad one. E.g., "Health Care Technology" over "Application Software" for healthtech companies.

5. **Evidence from context**: The `context` field tells you position type and fund. If held by a healthcare-focused BDC, that's a signal. If the position is COMMON_EQUITY in a real estate fund, it's likely real estate.

6. **Threshold**: Only classify as non-Other if you have reasonable confidence. "medium" confidence is fine — you don't need certainty. But don't guess without any evidence.

## Batch Processing

Process 10-20 companies at a time. After each batch:
1. Save your results to the cache (as shown above)
2. Report what you classified and what remained "Other"
3. Move to the next batch

## Stopping Criteria

Stop when:
- You've processed all companies in the queue, OR
- The remaining companies are all genuinely unclassifiable (no info found after search), OR
- The user tells you to stop

## Output

After finishing, report:
- How many companies you classified (non-Other)
- How many remained "Other" (with brief reason: codename, fund, no info found)
- Total FV covered by your classifications
