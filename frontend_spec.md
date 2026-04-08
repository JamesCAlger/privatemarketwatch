# Private Markets Index: Frontend Specification

## Overview

A static, data-driven website presenting four free private market indices derived from SEC regulatory filings. The site targets institutional allocators, fund managers, and researchers. It must look credible enough to appear in an investment committee deck and be simple enough to maintain with quarterly data updates.

### Design Philosophy

Institutional, not startup. Think MSCI index pages, FTSE Russell, S&P Dow Jones — not fintech landing pages. Dense with data, sparse with decoration. Every element earns its place by communicating something useful. No hero images, no gradients, no animated counters.

Typography-led. A single high-quality sans-serif font family (Inter or IBM Plex Sans) at multiple weights carries the entire design. Numbers use tabular figures so columns of data align properly.

Colour is functional, not decorative. A dark navy (#0F1B2D or similar) for headers and primary text. A single accent colour (teal or deep blue) for interactive elements and positive returns. Red for negative returns. Grey for secondary information. White and off-white (#F8F9FA) backgrounds. No colour that doesn't encode information.

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | Next.js (App Router) | SSG for static pages, API routes for dynamic queries. Vercel serverless functions for Postgres access. |
| Hosting | Vercel free tier | Custom domain, HTTPS, global CDN, auto-deploy on push. |
| Styling | Tailwind CSS | Utility-first, keeps bundle small, easy to maintain consistent spacing and typography. |
| Charts | Recharts for standard charts, D3 for custom visualisations | Recharts covers 80% of needs (time series, bar, area). D3 for anything bespoke (waterfall, heatmap). |
| Database | PostgreSQL | Pipeline loads data into Postgres. Frontend queries at build time (SSG) or request time (SSR/API routes). |
| Methodology PDF | Static PDF in /public/ | Generated separately, linked from methodology page. |

### Build and Deploy

The data pipeline (Python) runs after each quarterly filing cycle and loads results into PostgreSQL:
- `index_returns` — quarterly index levels for all four indices
- `unified_holdings` — 835K+ position-level holdings with classification
- `position_matches` — matched position pairs across quarters
- `position_returns` — position-level returns (capital, income, total)
- `universe` — full vehicle universe with metadata

The frontend queries Postgres at build time (for static pages via `getStaticProps` / `generateStaticParams`) or at request time (for dynamic data via API routes). Vercel rebuilds on push; the pipeline triggers a rebuild after loading new data.

---

## Site Structure

```
/                           Homepage
/indices/direct-lending     Index 1 detail page
/indices/direct-equity      Index 2 detail page
/indices/credit-funds       Index 3 detail page
/indices/equity-funds       Index 4 detail page
/methodology                Methodology overview + PDF download
/about                      About the project
/vehicles/[cik]             Individual vehicle page (Phase 2, not in v1)
```

---

## Page Specifications

### Homepage: /

The homepage must establish credibility within three seconds. A first-time visitor — an allocator who received the link from a colleague — should immediately understand: what the indices measure, what the current values are, and that this is serious.

**Header bar**
- Project name (left-aligned, wordmark, no logo needed for v1)
- Navigation: Indices (dropdown to four index pages), Methodology, About
- Clean, minimal. No search bar, no login, no hamburger menu on desktop.

**Hero section (not a hero image — a hero data panel)**
- Four cards in a row, one per index
- Each card shows:
  - Index name (e.g., "Direct Lending Index")
  - Latest index level (large, prominent number)
  - Quarter-over-quarter return (with directional colour: green/teal for positive, red for negative)
  - Trailing 12-month return
  - Small sparkline showing last 8 quarters
- Below the cards: a single line stating the as-of date and total AUM covered across all vehicles

**Performance chart**
- A single time series chart showing all four indices on the same axes, rebased to 100 at inception
- Toggle to show/hide individual indices
- Toggle between linear and log scale
- Quarterly data points connected by lines
- Clean gridlines, no excessive labelling
- Time axis shows quarter labels (Q1 2023, Q2 2023, etc.)

**Latest quarter summary**
- A compact data table showing for each index:
  - Quarterly return
  - YTD return
  - Trailing 12-month return
  - Annualised return since inception
  - Number of constituents
  - Total fair value (AUM)
  - Weighted average spread (direct lending only)

**Brief description**
- 2-3 paragraphs explaining what these indices are and that they're derived from public SEC filings
- Link to methodology page

**Footer**
- "Derived from public SEC filings. Not investment advice."
- Disclaimer text (brief)
- Link to GitHub repo
- Link to methodology PDF

### Index Detail Page: /indices/[slug]

One page per index, identical structure, populated with different data.

**Page header**
- Index name
- Latest value, quarterly return, 12-month return (same as homepage card but larger)
- As-of date

**Performance section**
- Time series chart (larger than homepage version, single index)
  - Option to overlay a public benchmark for comparison:
    - Direct Lending: Morningstar LSTA US Leveraged Loan Index
    - Direct Equity: Russell 2000 Value
    - Credit Funds: Cliffwater Direct Lending Index (if publicly available data points exist)
    - Equity Funds: Cambridge PE Index (if publicly available data points exist)
  - Both series rebased to 100
- Quarterly return bar chart below the time series
  - Bars coloured by sign (positive/negative)
  - This makes seasonal patterns and drawdowns visually obvious

**Statistics panel**
- Two-column layout
- Left column: Return statistics
  - Annualised return
  - Annualised volatility (of quarterly returns, annualised)
  - Sharpe ratio (vs risk-free rate)
  - Maximum drawdown
  - Best quarter / worst quarter
  - % positive quarters
- Right column: Portfolio characteristics (latest quarter)
  - Number of unique investees (Indices 1, 2) or funds (Indices 3, 4)
  - Number of vehicles in the universe contributing data
  - Total fair value
  - Total cost basis
  - Aggregate unrealised gain/loss (%)
  - For Direct Lending specifically:
    - Weighted average coupon
    - Weighted average spread over reference rate
    - Weighted average maturity (years)
    - % first lien / second lien / unsecured
    - % floating rate / fixed rate

**Sector / classification breakdown**
- Horizontal bar chart showing fair value allocation by:
  - Industry sector (for Indices 1, 2)
  - Fund strategy sub-type (for Indices 3, 4)
- Table below with exact percentages and fair values

**Top constituents**
- Table showing top 20 investees (Indices 1, 2) or funds (Indices 3, 4) by aggregate fair value
- Columns: Name, Industry/Strategy, Aggregate Fair Value, Aggregate Cost, Unrealised Gain/Loss (%), Number of Vehicles Holding, Lien Position (Index 1 only)
- Note stating that these represent deduplicated investees after entity resolution

**Vehicle contribution**
- Table showing which BDCs / interval funds contribute data to this index
- Columns: Vehicle Name, Vehicle Type (BDC/Interval/Tender Offer), Number of Positions in Index, Total Fair Value Contributed, As-Of Date
- This establishes the breadth and credibility of the index

### Methodology Page: /methodology

**Structure**
- Rendered as a long-form document page with a sticky table of contents sidebar
- Sections:
  1. Overview and objectives
  2. Universe definition
     - How BDCs are identified (multi-method approach from the spec)
     - How interval/tender offer funds are identified
     - Inclusion and exclusion criteria
  3. Data sources
     - BDC XBRL filings (10-K, 10-Q)
     - N-PORT filings
     - How each source is parsed
     - Known data quality issues and how they're handled
  4. Index classification
     - How holdings are classified into the four indices
     - N-PORT assetCat and issuerCat logic
     - BDC XBRL taxonomy axis logic
     - Treatment of ambiguous positions (preferred equity, mezzanine, convertibles)
  5. Entity resolution
     - How investees are deduplicated across vehicles
     - Fuzzy matching approach
     - LLM-assisted classification
     - Known limitations
  6. Return calculation
     - Fair value change methodology
     - Income estimation from stated coupon (Index 1)
     - Cost basis change interpretation (deployment, repayment, write-off signals)
     - NAV return methodology (Indices 3, 4)
  7. Weighting and construction
     - Fair-value weighting methodology
     - Chain-linking quarterly returns
     - Treatment of entries and exits
     - Rebalancing
  8. Sub-indices
     - By lien position, by industry, by instrument type
  9. PME comparators
     - Methodology for public market equivalent calculations
  10. Limitations and known biases
      - ASC 820 Level 3 valuation subjectivity
      - BDC-flavoured universe (mostly US middle-market, mostly floating rate)
      - Survivorship bias from vehicle mergers and deregistrations
      - Reporting lag (60+ days after quarter-end)
      - XBRL tagging inconsistency across filers
  11. Change log
      - Version history of methodology changes

- Download link for the full methodology as a PDF (formatted for print, with page numbers, proper citations)

### About Page: /about

Brief and factual.

- What this project is: a free, open-source set of private market indices derived from public SEC filings
- Why it exists: no free investee-level benchmark for private credit and equity currently exists
- Data provenance: all data comes from EDGAR (BDC XBRL filings, N-PORT XML filings, N-CEN annual reports)
- Open source: link to GitHub repo with the full data pipeline
- Contact: email address for methodology questions, data issues, or collaboration
- Not investment advice disclaimer
- Acknowledgment of SEC DERA for publishing the BDC Data Sets and N-PORT Data Sets

No team bios, no company description, no investor logos. The project's credibility comes from the methodology transparency and data quality, not from who's behind it.

---

## Phase 2: Individual Vehicle Pages (future, not v1)

### Vehicle Page: /vehicles/[cik]

One page per BDC or interval/tender offer fund. Shows:

- Vehicle name, type, CIK, filing history
- Total portfolio fair value over time (chart)
- Portfolio composition breakdown (by index classification: what % is direct lending, direct equity, fund investments)
- Top holdings with fair values
- Link to source filings on EDGAR
- Historical quarterly data table

These pages are valuable because they let fund managers see how their own fund's holdings appear in the index, and let allocators drill into individual vehicles. The data structure (data/vehicles/[cik].json) should be built from v1 so pages can be generated later without pipeline changes.

---

## Responsive Design

The site must work on desktop, tablet, and mobile, but desktop is the primary experience. Institutional users are overwhelmingly on desktop or laptop screens.

- Desktop (>1024px): full layout, side-by-side panels, wide data tables
- Tablet (768-1024px): stacked layout, tables scroll horizontally
- Mobile (<768px): simplified layout, charts resize, tables become scrollable cards

Charts should be responsive but maintain a minimum height that keeps them readable. Data tables with many columns should scroll horizontally on small screens rather than wrapping.

---

## Performance Targets

- Lighthouse score >90 on all categories
- First contentful paint <1.5s
- Total page weight <500KB for homepage (excluding chart data loaded on interaction)
- Database queries cached aggressively (data only changes quarterly); use Next.js ISR or long cache headers

---

## Accessibility

- WCAG 2.1 AA compliance
- Colour choices must work for colour-blind users (don't rely solely on red/green — use directional arrows or +/- symbols alongside colour)
- All charts must have text alternatives (summary statistics in tables below charts)
- Data tables must use proper semantic HTML (thead, tbody, th with scope)
- Skip navigation link
- Sufficient contrast ratios (especially for the grey secondary text against white backgrounds)

---

## SEO and Discoverability

- Clean URL structure (/indices/direct-lending not /index?id=1)
- Proper meta titles and descriptions per page
- OpenGraph tags for social sharing (when someone shares the direct lending index page on LinkedIn, it should show the index name, latest return, and a clean preview)
- Structured data (JSON-LD) for index pages
- Sitemap.xml generated at build time
- Canonical URLs

---

## Content Tone

Write all site copy as if writing for the Financial Times or Institutional Investor — factual, precise, no superlatives, no marketing language. Never say "revolutionary" or "disrupting" or "powered by AI." The entity resolution uses LLMs but the site doesn't need to advertise that.

Specific language guidance:
- "Derived from public SEC filings" not "AI-powered index"
- "Covers N vehicles with $Xbn in aggregate portfolio fair value" not "massive dataset"
- "Quarterly returns are computed as..." not "we use a proprietary methodology"
- "Known limitation: ASC 820 Level 3 valuations are model-based" not "our cutting-edge approach handles..."

The methodology document can be technical. The homepage and about page should be accessible to someone who knows what a BDC is but hasn't read the XBRL spec.
