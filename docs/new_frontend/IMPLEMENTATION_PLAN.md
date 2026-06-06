# Metris Lens Frontend Implementation Plan

## Scope Assessment

The new design is a complete visual and structural overhaul. The current frontend (`privatemarketwatch.com` style) shares the same Next.js/Tailwind/Recharts stack but has a completely different visual language: dashboard-style cards, teal+navy palette, Libre Franklin font, shadowed cards. The new design is editorial: warm white backgrounds, IBM Plex type family (serif/sans/mono), ruled borders, generous spacing, navy+gold palette.

**Current codebase:** 28 components, 8 routes, ~4,500 lines of TSX. The data layer (`types.ts`, `data.ts`, `format.ts`) and data files (`public/data/`) are reusable. The visual components are not -- they need full rewrites to match the new design language.

**Prototype reference:** ~7,300 lines of JSX/JS across 15 files. This is the structural/content spec, not code to port.

**This must be split into multiple implementation phases.** Each phase produces a working, buildable site. The phases follow the README's suggested build order.

---

## Phase 1: Foundation + Chrome + Design Tokens

**Goal:** Replace the visual foundation. Every page should render the new header, footer, and typography. Existing pages will look broken until rebuilt, but the chrome will be correct.

### Changes

1. **Tailwind config** — Replace color palette, add IBM Plex font families, update spacing scale, remove old shadows/add ruled-border utilities. Map all tokens from README:
   - `bg: #fbfaf7`, `surface: #ffffff`, `ink: #0b1a2c`, `ink2: #3b4a5b`, `ink3: #6b7280`, `ink4: #9aa1ab`
   - `rule: #dfe3ea`, `rule2: #eef0f4`, `rule3: #f5f7fa`
   - `navy: #0b1a2c`, `navyDeep: #06121f`
   - `accent: #c7a14a`, `accent2: #e2bb66`, `accentSoft: #f3e6c0`
   - `green: #1f7a4a`, `red: #a8362b`, `amber: #b07827`

2. **Fonts** — Add IBM Plex Serif, IBM Plex Sans, IBM Plex Mono via `next/font/google`. Define `font-display`, `font-body`, `font-mono` utility classes.

3. **Root layout** — Update `layout.tsx`: new fonts, warm white background, metadata rename to "Metris Lens".

4. **Header** (`Header.tsx`) — Full rewrite:
   - Top utility bar: as-of date + language + login links
   - Main nav: Metris Lens logo + "DATA - INDICES - RESEARCH" tagline + nav items (Indices, Funds, Methodology, Data, About) + Subscribe CTA
   - Search bar: "Search N funds by ticker, name, manager, or CIK..."
   - Ticker bar: three index levels with sparklines + 1Y return (dark navy strip)

5. **Footer** (`Footer.tsx`) — Full rewrite: dark navy, three columns (Indices, Resources, Data Sources), disclaimer.

6. **Breadcrumb** — New component for detail pages.

7. **globals.css** — Reset base styles: warm white bg, navy ink, tabular-nums for mono.

8. **constants.ts** — Update `SITE_NAME` to "Metris Lens", update index colors to accent gold.

### Files touched
- `tailwind.config.ts` (rewrite)
- `src/app/layout.tsx` (rewrite)
- `src/app/globals.css` (rewrite)
- `src/components/Header.tsx` (rewrite)
- `src/components/Footer.tsx` (rewrite)
- `src/components/Breadcrumb.tsx` (new)
- `src/lib/constants.ts` (update)
- `src/lib/format.ts` (update return color logic: green only for net positive)

### Verification
- `npm run build` passes
- Dev server shows new header/footer/typography on all routes
- No TypeScript errors

---

## Phase 2: Chart Primitives

**Goal:** Rebuild all chart components against the new design language. These are used by every data page.

### Changes

1. **SparklineChart** — Thin inline sparkline for ticker bar (navy bg, gold or green stroke).
2. **TimeSeriesChart** — Multi-series line chart with time-range pills (1Y/3Y/5Y/SI). Gross = dimmed line, Net = bold.
3. **StackedAreaChart** — AUM composition by vehicle type over time.
4. **DonutChart** — New component for sector/manager composition donuts. Center stat.
5. **HorizontalBarChart** — New component for sector exposures, yield leaderboards, lien splits.
6. **HistogramChart** — Multi-series histogram (BDC vs non-BDC overlay). Distribution + leverage.
7. **DistressBarChart** — Stacked bar for credit stress over time.

All charts use the new color palette. Recharts remains the library.

### Files touched
- `src/components/SparklineChart.tsx` (rewrite)
- `src/components/TimeSeriesChart.tsx` (rewrite)
- `src/components/StackedAreaChart.tsx` (rewrite)
- `src/components/DonutChart.tsx` (new)
- `src/components/HorizontalBarChart.tsx` (new)
- `src/components/HistogramChart.tsx` (rewrite)
- `src/components/DistressBarChart.tsx` (rewrite)

### Verification
- Components render in isolation (Storybook-style or inline test page)
- `npm run build` passes

---

## Phase 3: Index Detail Page (Spine Page)

**Goal:** Build the Direct Lending index detail page end-to-end. This exercises most design patterns and validates the data contract.

### Sections (per README)
1. Breadcrumb
2. Identity hero — serif name, tagline, fact row, level callout card
3. Stat strip — 6 metrics
4. Performance — line chart + Variant C return summary table (Net headline, Gross dimmed)
5. Risk & return statistics — 6-col grid (vol, Sharpe, drawdown, best/worst Q, % positive)
6. Portfolio characteristics — dark navy band, 5 gold metrics with coverage captions
7. Composition — two donuts (sector + manager)
8. Top constituents — position-level table (25 rows, with bar-width for weight)
9. Structural composition — lien bars + spread histogram
10. Top funds contributing — table of top 10 vehicles
11. Methodology summary — short form + link
12. Footer

### Data requirements
- `index_summary.json` already has level, returns, constituents, sparkline, riskStats
- `index_returns.json` has quarterly series
- `top_constituents.json` has position-level top holdings
- `sector_breakdown.json` has sector composition
- `vehicle_contribution.json` has top funds
- `portfolio_characteristics.json` has WAC/WAS/WAM/lien/rate splits
- `concentration_curve.json` has pie brackets

### Files touched
- `src/app/indices/[slug]/page.tsx` (rewrite)
- `src/components/IndexHero.tsx` (new)
- `src/components/StatStrip.tsx` (new)
- `src/components/ReturnSummaryTable.tsx` (new — Variant C)
- `src/components/PortfolioCharacteristics.tsx` (new — dark band)
- `src/components/ConstituentTable.tsx` (rewrite)
- `src/components/VehicleTable.tsx` (rewrite)

### Verification
- `/indices/direct-lending` renders all 12 sections
- `/indices/preferred-equity` and `/indices/common-equity` render from same chassis
- Return summary shows Net as headline (bold), Gross dimmed, no green on Gross
- `npm run build` passes

---

## Phase 4: Homepage

**Goal:** Rebuild the homepage per the V2 navyGold design.

### Sections (per README)
1. Header (already done in Phase 1)
2. Hero — headline + CTAs + universe-coverage card (4-stat grid + coverage bar)
3. Performance — DL index level chart + Total Return Summary (Variant C)
4. AUM & Exposure — industry donut + manager donut + credit stress chart + NAV premium/discount
5. Portfolio characteristics — dark navy band (reuse component from Phase 3)
6. Movers — 3 cards: top premiums (green), top discounts (red), yield leaderboard (gold)
7. Distributions & Leverage — two histograms side by side
8. Fund Universe — full table with type filter pills + search
9. Footer (already done in Phase 1)

### New data needed
- Movers (top premiums/discounts/yields): derivable from `fund_list.json` sorting
- NAV premium/discount chart: now available from the listed prices work

### Files touched
- `src/app/page.tsx` (rewrite)
- `src/components/HeroSection.tsx` (new)
- `src/components/UniverseCoverageCard.tsx` (new)
- `src/components/MoversCards.tsx` (new)
- `src/components/FundTable.tsx` (rewrite — add type filter pills + search)

### Verification
- Homepage renders all 9 sections
- Type filter pills work (All/BDC/Interval/Tender)
- Fund table search works
- `npm run build` passes

---

## Phase 5: Fund Detail Pages

**Goal:** Build BDC and Interval fund detail templates.

### BDC template (from `fund-detail-v3-bdc.jsx`)
- Vehicle type badges (BDC, PUBLICLY TRADED, INDEX MEMBER)
- Identity hero — name, ticker, CIK, manager, inception, HQ
- Snapshot card — AUM, NAV/Share, Last Price, Distribution rate
- Peer standing — quartile rank cards across all metrics
- Tab bar: Overview / Holdings / Portfolio breakdown / Performance / Filings
- Overview: portfolio characteristics, top holdings, asset breakdown
- Holdings: full holdings table
- Performance: quarterly return chart + table, NAV-price spread chart
- Filings: link to EDGAR

### Interval template (from `fund-detail-v3-interval.jsx`)
- Same structure but: NAV per share is headline (no market price)
- Liquidity terms block replaces price spread (data gap: placeholder for now)
- Tender history chart replaces price chart (data gap: placeholder for now)
- LTM/3Y toggle on return composition

### Files touched
- `src/app/funds/[cik]/page.tsx` (rewrite)
- `src/components/FundHero.tsx` (new)
- `src/components/FundSnapshotCard.tsx` (new)
- `src/components/PeerQuartile.tsx` (new)
- `src/components/FundTabBar.tsx` (new — client component)
- `src/components/FundOverviewTab.tsx` (new)
- `src/components/FundHoldingsTab.tsx` (new)
- `src/components/FundPerformanceTab.tsx` (new)
- `src/components/FundFilingsTab.tsx` (new)
- `src/components/FundTopHoldings.tsx` (rewrite)
- `src/components/FundPerformanceTable.tsx` (rewrite)

### Verification
- BDC fund page renders (e.g., `/funds/0001287750` for ARCC)
- Interval fund page renders with NAV headline, no price chart
- Tab switching works
- `npm run build` passes

---

## Phase 6: Methodology, Data, About

**Goal:** Build the three static/editorial pages.

### Methodology
- Editorial layout: sticky TOC sidebar (220px) + content column (760px)
- 6 sections with scroll-spy active highlighting
- Three callout styles: Design choice (accent border), Edge case (ink border), Limitation (amber border)
- Hero with meta row (Version, Last updated, Maintainer, Format)
- Content is inline (from `methodology.jsx`)

### Data (replaces Data Quality)
- Two-column hero: pitch bullets left, form card right
- Form: email + role dropdown + textarea, client-side validation
- Submit -> thank-you state with SLA
- Three dataset tier cards below
- Delivery & terms strip

### About
- Hero: "Making private markets observable."
- Manifesto: 3 paragraphs
- Principles: 4 cards
- People: 4+4 placeholder slots
- Contact: dark navy card with 4 inboxes

### Files touched
- `src/app/methodology/page.tsx` (rewrite)
- `src/app/data/page.tsx` (new route, replaces `/data-quality`)
- `src/app/about/page.tsx` (rewrite)
- `src/components/MethodologyTOC.tsx` (new — client component for scroll-spy)
- `src/components/DataRequestForm.tsx` (new — client component)
- `src/components/CalloutBox.tsx` (new — three variants)

### Verification
- Methodology page has working sticky TOC
- Data form validates and shows thank-you state
- About page renders all sections
- `npm run build` passes

---

## Phase 7: Polish + Cleanup

**Goal:** Remove old components, verify build, visual QA against screenshots.

### Changes
- Delete unused old components (IndexCard, StatPanel, StatValue, AnimatedNumber, ExposureSection, HeroStats, etc.)
- Update sitemap.ts for new routes
- Update not-found.tsx to match new design
- Visual comparison against all 9 screenshots
- Verify all inter-page links work
- Remove `/data-quality` route, redirect to `/data`
- Remove `/indices` overview redirect (nav "Indices" -> `/indices/direct-lending`)
- Run `npm run build` for final static export

---

## Dependency Notes

- **Phases 1-2** are foundation work with no data dependencies
- **Phase 3** validates the full data contract; any missing JSON fields surface here
- **Phase 4** depends on Phase 1-3 (reuses chrome + charts + ReturnSummary + PortfolioCharacteristics)
- **Phase 5** depends on Phase 1-2 (chrome + charts); fund data already exists
- **Phase 6** is independent of data pipeline (static content)
- **Phase 7** is cleanup after all pages exist

Phases 3-5 can be reordered if needed, but the README recommends Index Detail first because it exercises the most patterns.

## Data Gaps to Acknowledge

These design elements will render as placeholders or be omitted until pipeline work provides the data:

| Item | Phase affected | Workaround |
|---|---|---|
| External benchmarks (S&P LSTA, etc.) | Phase 3 (index perf chart) | Show only Gross + Net lines, no benchmark |
| Interval fund liquidity terms | Phase 5 | Show "Coming soon" in liquidity block |
| Tender offer history | Phase 5 | Show "Coming soon" in tender history block |
| Fund address | Phase 5 | Omit HQ field when null |
| Peer ranking engine | Phase 5 | Compute percentile ranks client-side from fund_list.json |
