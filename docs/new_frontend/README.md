# Handoff: Metris Lens — private markets website

A design handoff package for the Metris Lens website — a data platform for US private markets covering BDCs, interval funds, and tender-offer funds, built from mandatory SEC filings.

---

## Overview

**Metris Lens** is a data product with three layers:

1. **Data** — universe statistics aggregated from mandatory SEC filings
2. **Indices** — three position-level benchmarks (Direct Lending, Preferred Equity, Common Equity)
3. **Research / analytics** — interpretive content layered on top

This bundle contains the **complete frontend design** as HTML/JSX prototypes covering every primary page of the product:

| Live route | Bundle file |
|---|---|
| `/` (homepage / fund universe) | `index.html` (loaded inside a design canvas) |
| `/indices/direct-lending` | `Index Detail - Direct Lending.html` |
| `/indices/preferred-equity` | `Index Detail - Preferred Equity.html` |
| `/indices/common-equity` | `Index Detail - Common Equity.html` |
| `/funds/<bdc>` | `Fund Detail v3 - BDC.html` (template — uses ARCC as example) |
| `/funds/<interval>` | `Fund Detail v3 - Interval.html` (template — uses CCLFX as example) |
| `/methodology` | `Methodology.html` |
| `/data` | `Data.html` (data-access request form) |
| `/about` | `About.html` |

---

## About the design files

**The files in this bundle are design references created in HTML/JSX — they are not production code.** They use plain `<script type="text/babel">` loading of inline React via Babel-standalone, and inline-style React for layout. This is intentionally fast-iteration prototype code, not the architecture you should ship.

**Your job is to recreate these designs in the target codebase's environment** — its real component library, routing system, styling solution (Tailwind / CSS modules / styled-components / whatever), and data layer — using the structural, content, and visual decisions documented in these files as input.

**If no codebase exists yet**, choose the framework you think best fits a data-heavy, server-rendered, SEO-friendly content site (Next.js is a reasonable default; the design works equally well in Remix, SvelteKit, etc.) and implement against that.

---

## Fidelity

These are **high-fidelity structural prototypes** with **intentionally flexible pixel values**. That distinction matters and is the single most important thing on this page:

### LOCKED — preserve in implementation

These are the design decisions to preserve as-is. They were debated, settled, and should not be re-litigated.

- **What's on each page, in what order.** Section ordering on every page is deliberate. Don't reflow into a different IA.
- **Information hierarchy.** Headlines, secondary metrics, captions — the relative weight of every number reflects a decision about what matters.
- **Copy / content.** All headlines, eyebrows, captions, callout titles, and labels. Re-write only when (a) using real data values, (b) the firm has different brand voice, or (c) you spot a factual error.
- **Net is the headline return; Gross is dim and small.** This pattern is enforced on every page that shows total return — the headline number is **Net**, and Gross is rendered smaller and dimmer, never with positive (green) color. Gross isn't "good," it's structural. (See Variant C of the return summary in `index-detail.jsx` / `v2-themed.jsx`.)
- **No green on Gross returns.** Color carries semantic meaning here. Green = positive performance investor sees. Gross is pre-fee and shouldn't get the green treatment.
- **No decorative eyebrows above hero headlines.** Don't add a "Welcome to Metris Lens" eyebrow above "The data platform for private markets." Eyebrows must add a category, audience, time, or live signal — not paraphrase the headline.
- **NAV per share is the headline of the Interval fund snapshot card.** It's the transaction price for an interval fund. Don't demote it to one tile in a 2×2 grid.
- **Top constituents are *positions*, not companies.** A single issuer can appear multiple times (e.g., Stripe Series I preferred + Stripe Series H preferred = two rows). Column header is "Position" and copy reflects this. Don't change "Position" back to "Company."
- **Coverage gaps are disclosed inline, never averaged away.** Where the metric has incomplete coverage (e.g., 64% of FV reports a spread), the coverage % is shown next to the metric. Don't quietly extrapolate.
- **Three callout types in Methodology.** ▸ Design choice (accent), ◇ Edge case (ink), ⚠ Limitation (amber). These three patterns carry meaning — don't merge them.
- **Three-tier data access pattern.** Tier 1 (Universe) + Tier 2 (Indices) are open; Tier 3 (Position-level) is reviewed. Visible upfront so retail visitors understand what they're requesting.
- **About-page team cards are intentionally name-less.** They're placeholder slots for real people — keep the placeholder pattern; don't fabricate names. The note in the People section explaining this is also intentional — remove only when the real roster lands.

### FLEXIBLE — reset against your real design system

- **All pixel values.** Padding, gaps, line-heights, font sizes, border widths, shadow values. These were set by intuition during the prototype, not measured against tokens. **Reset every number against your design system's spacing/type/elevation scales.** Do not preserve them.
- **Typography family.** Currently IBM Plex (Sans / Serif / Mono). If your DS has different display + body + mono fonts, use those. The decision being made by the type pairing is "editorial serif display + neutral sans body + monospace numerals" — preserve the *pairing intent*, not the specific font.
- **Color values.** Hex codes given below are the prototype's working palette. Map them to your real design tokens. The decisions being made are: warm white background, navy ink, gold accent (warm not bright), and traffic-light semantics. Preserve those decisions; rewire the hexes.
- **Border / surface / elevation.** Cards are 1px ruled borders, no shadow, no radius (radius: 2px is rendered as basically square). This is editorial intent; if your DS uses 8px-rounded elevated cards, use that — the *card-as-content-container* pattern is what matters.
- **Charts.** Inline SVG primitives in `shared.jsx` are illustrative — every line/bar/donut should be rendered with your real charting library (Recharts, Visx, Highcharts, etc.). The chart *types* and *what they encode* are locked; the rendering library is flexible.

---

## Architecture & dependencies

The prototypes share a small system. Understanding it will save you time.

### Shared chrome

`fund-chrome.jsx` exports four things used by every detail page:

- `<FundHeader T SX navActive />` — top nav (dark navy bar + ticker for the funds page, plus a fund-lookup search bar). `navActive` prop controls which nav item is highlighted. Removed phantom "Research" item — current nav is **Funds, Indices, Methodology, Data, About**.
- `<Breadcrumb T items />` — breadcrumb with `[{label, href?}, …]`. Items without `href` render as plain text (current page).
- `<FundFooter T SX />` — dark navy footer with three columns: Indices, Resources, Data Sources.
- `T_V3` and `SX_V3` — the design tokens and shared style objects (see Design tokens below).

### Shared chart primitives

`shared.jsx` exports inline-SVG primitives used everywhere:

- `<PMWSparkline data w h stroke />` — small inline sparkline (used in ticker bar)
- `<PMWLineChart series labels w h />` — multi-series line chart with toggleable legend
- `<PMWStackedArea data palette />` — stacked area for AUM/composition
- `<PMWHBars items accent />` — horizontal bar list (sector exposures, yield leaderboards)
- `<PMWHistogram bins series palette />` — multi-series histogram
- `<PMWDonut items size thickness palette />` — donut for proportion breakdowns
- `<PMWPlaceholder label h />` — dashed-border placeholder for unrendered charts

All of these accept color via `currentColor` and explicit props — they should be replaced with your charting library calls 1:1 in the rebuild.

### Page chassis

| Page | Component file | Data file |
|---|---|---|
| Homepage | `v2-themed.jsx` exports `V2Home({ theme, returnVariant })` | `shared.jsx` (`PMW_DATA`) |
| Index Detail × 3 | `index-detail.jsx` exports `IndexDetailApp({ data })` | `index-data.js` (3 constants) |
| Methodology | `methodology.jsx` | content inline in file |
| Data | `data-access.jsx` | content inline in file |
| About | `about.jsx` | content inline in file |
| Fund Detail BDC | `fund-detail-v3-bdc.jsx` | `fund-data-v2.js` + `peer-universe.js` |
| Fund Detail Interval | `fund-detail-v3-interval.jsx` | `fund-data.js` + `peer-universe.js` |

The **homepage** is wrapped in a `design-canvas.jsx` (pan/zoom canvas for design review) — that wrapper is part of the prototype review experience, not the product. The actual page to ship is the `V2Home` component itself, rendered without the canvas.

`V2Home` accepts a `theme` prop (one of 5 palette/type variants in `V2_THEMES`). **Default is `navyGold` (V2.1)** per CLAUDE.md — only build the navyGold variant unless instructed otherwise.

`IndexDetailApp` accepts a `data` prop (one of three index data constants in `index-data.js`). All three index pages render from the same chassis — your implementation should be one route component, parameterized by index slug.

### What's loaded on each HTML page

Each HTML file loads React, ReactDOM, and Babel-standalone from unpkg, then loads `.jsx` files via `<script type="text/babel" src="…">`. **Do not preserve this loading pattern** — convert each .jsx to a real module in your build system.

---

## Page-by-page reference

### Homepage (`index.html` → `v2-themed.jsx`)

**Purpose**: Landing page + fund universe browser. The "default destination" for any traffic that didn't come in via a deep link.

**Sections, top to bottom:**

1. **Header** — top utility bar (as-of + language + login), main logo + nav row, dark **ticker bar** showing the three index levels with sparkline + 1Y return. The three ticker items link to their index detail pages.
2. **Hero** (`V2Hero`) — left: "The data platform for private markets." headline + paragraph + two CTAs ("Browse the fund universe" anchors to `#universe`, "View methodology" → `Methodology.html`). Right: universe-coverage card with 4-stat grid + coverage progress bar.
3. **Performance** (`V2Performance`) — Direct Lending index level chart + Total Return Summary card. **The return summary uses Variant C** (Net headline, Gross dimmed, Fee drag muted). Three sibling variants of the return summary exist in `v2-themed.jsx` (A, B, C) — we shipped C; the others are for reference only.
4. **AUM & Exposure** (`V2AUMExposure`) — two stacked rows: (a) Industry exposure donut + Manager concentration donut, (b) Credit stress stacked-bar chart, (c) NAV premium/discount box-and-whisker chart + Stress-by-sector scatter.
5. **Portfolio characteristics** (`V2Characteristics`) — dark navy band. 5 metrics in gold: Wtd Avg Coupon, Wtd Avg Spread, Wtd Avg Maturity, First Lien %, Floating Rate %. Each with coverage caption underneath.
6. **Movers** (`V2Movers`) — three cards: Top Premiums to NAV (green), Top Discounts to NAV (red), Yield Leaderboard (gold). Used to surface where the action is right now.
7. **Distributions & Leverage** (`V2ManagerDist`) — two histograms side by side: distribution rate distribution + leverage ratio distribution, BDC vs non-BDC overlaid.
8. **Fund Universe** (`V2Universe`) — full fund table with type filters and search. Row links to fund detail (currently only ARCC is wired since we have one BDC template; in production, every row is a link).
9. **Footer** (`V2Footer`) — three columns of links + bottom disclaimer.

### Index Detail × 3 (`Index Detail - …`)

**Purpose**: Factsheet for one index. Single chassis, three data instantiations.

**Sections:**

1. **Breadcrumb** — Home › Indices › <Index name>. "Indices" crumb is plain text (no overview page).
2. **Identity hero** — eyebrow + huge serif name + tagline + fact row (Inception, Rebalance, Currency, Return Type, Base Level) + large level callout card on right with 1Y / SI / Constituents mini-stats.
3. **Stat strip** — 6-stat horizontal grid: Aggregate FV, Unique Companies, Constituent Positions, Funds Contributing (N of M), Universe Coverage %, Last Rebalance date.
4. **Performance** — index level chart (Gross + Net + benchmark) with time-range pills + return summary table (Variant C) on the right.
5. **Risk & return statistics** — 6 cols: Volatility, Sharpe, Max Drawdown, Best Q, Worst Q, % positive quarters. Computed since inception, on Net.
6. **Portfolio characteristics** — dark navy band, 5 metrics. *Content varies per index*: Direct Lending shows Coupon/Spread/Maturity/First Lien/Floating; Preferred Equity shows Stated Div/Cumulative/PIK/Redeemable/Perpetual; Common Equity shows Hold Period/Sponsor-Backed/Co-Invest/Realized LTM/Top-10 Concentration. The metrics list comes from each index's `portfolio` array in `index-data.js`.
7. **Composition** — two donuts: Sector composition + Manager contribution. Center stat shows "Top 5" share.
8. **Top constituents** — table of 25 largest position-level exposures. Columns: #, Position, Sector, Funds holding, Aggregate FV, Weight (with bar). **Each row is one security — not one company.** Footer: "Top 25 of N positions across M unique issuers".
9. **Structural composition** — two cards driven from `data.seniority` and `data.rateDistribution`. *Content varies per index*: Direct Lending = Lien position bars + Spread-over-SOFR histogram; Preferred Equity = Preferred seniority bars + Stated div rate histogram; Common Equity = Position type bars + Vintage year histogram. Titles, subtitles, and footnotes are all in the data file, not hardcoded.
10. **Top funds contributing** — table of top 10 vehicles holding the most index FV. ARCC row links to BDC fund detail.
11. **Methodology summary** — short-form recap of construction + eligibility rules, with link to full methodology page.
12. **Footer**.

### Methodology (`Methodology.html` → `methodology.jsx`)

**Purpose**: Canonical document explaining how the universe, indices, and analytics are constructed. The credibility document — the single most important page for institutional readers.

**Layout**: Editorial. Single document with a sticky left-side TOC.

**Sections:**

1. **Hero** — large serif "Methodology" + lede + meta row (Version, Last updated, Maintainer, Format) + CTA row (Read methodology, Download PDF, Change log).
2. **Sticky TOC sidebar** (220px) + content column (max 760px).
3. **§1 Universe** — eligible vehicle types, add/remove rules, survivorship.
4. **§2 Data pipeline** — 4-stage horizontal diagram (Ingest → Reconcile → Aggregate → Publish), then source-form inventory table, reconciliation rules, cadence.
5. **§3 Index construction** — shared parameter table, then per-index eligibility tables (3.2 Direct Lending, 3.3 Preferred Equity, 3.4 Common Equity).
6. **§4 Return calculation** — quarterly return formula in dark navy block with symbol gloss, then compounding rules.
7. **§5 Universe analytics** — AUM aggregation, industry classification, coverage logic.
8. **§6 Limitations & versioning** — numbered limitations list + version history table.

**Editorial callouts** — three styles used throughout:

- **▸ Design choice** (accent left-border) — why a decision was made. Example: "Why fair-value-weighted: …"
- **◇ Edge case** (ink left-border) — tricky scenarios. Example: "IPO conversion: when a portfolio company goes public, …"
- **⚠ Limitation** (amber left-border) — structural compromises stated honestly.

These three types carry distinct meaning. Preserve all three; don't merge.

### Data (`Data.html` → `data-access.jsx`)

**Purpose**: Data-access request landing page. Replaces the "Data Quality" page from the live site — this product surfaces data access as a primary action.

**Sections:**

1. **Hero** (two-column): left — pitch with three checked bullets (three tiers, quarterly cadence, versioned/reproducible). Right — **form card** with three required fields.
2. **Form** with three required fields:
   - **Email** (required, email-format validation)
   - **Role** (required dropdown, 11 options: Asset allocator, Investment adviser / RIA, Wealth manager, Fund manager, Equity/credit analyst, Academic researcher, Journalist, Policy researcher, Retail investor, Student, Other)
   - **How will you use the data?** (required textarea, min 20 chars)
3. **Submit** transitions the card to a **thank-you state** echoing email + role and the SLA (Tier 1+2: 2 business days, Tier 3: 5 business days). Includes a "Submit another" link for repeated requests.
4. **Three dataset cards** (Tier 1 Universe / Tier 2 Indices / Tier 3 Position-level). Tier 3 has an accent border + a "Reviewed — role and use case determine eligibility" footer so retail visitors understand the gating up front.
5. **Delivery & terms strip** — three cells: Format, Update cadence, Citation requirements.

**Form behavior**: purely client-side, no backend. The submit handler is where you wire the real endpoint + bot protection (captcha, honeypot, rate limit).

### About (`About.html` → `about.jsx`)

**Purpose**: Mission, manifesto, principles, team, contact.

**Sections:**

1. **Hero** — "Making private markets observable." + supporting paragraph.
2. **Manifesto** — 3-paragraph "why this exists" editorial (the gap → the SEC mandate → the principle).
3. **Principles** — four-card strip: 01 Independent, 02 Rules-based, 03 Transparent, 04 Reproducible. Each card has a short body.
4. **People** — 4 founding-team cards + 4 advisor cards. **All cards are placeholder slots — no names** (the section has an inline note explaining this is intentional). The structural decision being shown is the 4+4 pattern.
5. **Contact** — dark navy card with 4 inboxes: `press@`, `data@`, `partnerships@`, `hello@`. Plus bottom strip with links to Methodology, Data, Universe homepage.

### Fund Detail templates (`Fund Detail v3 - …`)

**Purpose**: One page per fund. Two templates shipped: BDC (uses ARCC as the example) and Interval (uses CCLFX). Each illustrative fund's data lives in `fund-data.js` / `fund-data-v2.js`.

These are templates — in production every fund in the universe table links to one of these templates parameterized by its data. The structural difference between BDC and Interval is real:

- **BDC** has a market price → NAV–price spread is the headline signal
- **Interval** has no market price → NAV is the transaction price; the headline signal is **liquidity terms** (tender history, pro-ration rate, redemption frequency)

The two templates encode this difference deliberately. The BDC variant has a price chart + spread analysis; the Interval variant has a tender-history bar chart + a liquidity-terms table replacing those blocks.

These two pages are the most data-shaped in the bundle — `fund-data.js` and `fund-data-v2.js` are large. In production, these should be database-backed.

---

## Design tokens

The prototype palette is in `fund-chrome.jsx` (`T_V3`). Map these to your real design tokens; **do not preserve the hex codes**.

### Colors

| Token | Hex | Use |
|---|---|---|
| `bg` | `#fbfaf7` | Page background (warm white) |
| `surface` | `#ffffff` | Card surface |
| `ink` | `#0b1a2c` | Primary text (navy) |
| `ink2` | `#3b4a5b` | Secondary text |
| `ink3` | `#6b7280` | Tertiary text / captions |
| `ink4` | `#9aa1ab` | Quaternary (rarely used) |
| `rule` | `#dfe3ea` | Primary rule / border |
| `rule2` | `#eef0f4` | Soft rule (table dividers) |
| `rule3` | `#f5f7fa` | Subtle row stripe / pill background |
| `navy` | `#0b1a2c` | Same as ink — used semantically for dark surfaces |
| `navyDeep` | `#06121f` | Header ticker bar (darker navy) |
| `navyMid` | `#16273c` | (Variant, currently unused on shipped pages) |
| `accent` | `#c7a14a` | Warm gold — primary accent |
| `accent2` | `#e2bb66` | Lighter gold variant |
| `accentSoft` | `#f3e6c0` | Soft gold (chip backgrounds, Q2 indicators) |
| `green` | `#1f7a4a` | Positive / "fully filled" / earned |
| `red` | `#a8362b` | Negative / impaired |
| `amber` | `#b07827` | Warning / pro-rated / under-earned |

**Semantic decisions** (preserve):
- Green is reserved for **positive performance the investor experiences** (Net returns, fully-filled tenders, full distribution coverage). **Never apply green to Gross returns.**
- Amber is for **warnings / partial outcomes** (pro-rated tenders, under-earned distributions, limitation callouts).
- Red is for **negative outcomes** (discounts to NAV, drawdowns).
- Gold accent is for **brand emphasis** (active nav, primary CTAs, headline numbers in selected variants, callout titles).

### Type

| Role | Family | Use |
|---|---|---|
| Display | IBM Plex Serif | Page titles, section headings, large numbers |
| Body | IBM Plex Sans | Paragraphs, UI labels, table cells |
| Mono | IBM Plex Mono | Numerical values, section numbers (§1), code, filing IDs |

**Decisions** (preserve):
- Numerical values are **always rendered in IBM Plex Mono** with `font-variant-numeric: tabular-nums`. Even when small. Tabular numerals matter for column alignment.
- Display serif is used for the **page headline and section headings**, never for body text.
- Eyebrows are **uppercase, monospace-ish letterspacing** (0.12–0.18em).

### Spacing

The prototype uses ad-hoc spacing values that should be **fully reset** against your design system's spacing scale. Don't pull pixel values from the prototype.

The structural decisions to preserve are:
- **72px (or your DS equivalent) horizontal page margin** on detail pages — gives content room to breathe at 1280px.
- **24px (or 16-24-32 scale) gaps between sibling cards.**
- **Cards have generous internal padding** (28–36px) — they're meant to feel like reading-page chapters, not dense cells.
- **Generous section spacing on long-form pages** (Methodology has 60px between sections) — this is editorial spacing, not dashboard density.

---

## Interactions & state

Most pages are **static reads** — no client state beyond hover effects.

**Stateful pages:**

1. **Homepage Index Performance card** — has time-range pills (1Y/3Y/5Y/SI). Currently pills are visual-only; in production each should switch the chart's series data.
2. **Universe table filters** — All / BDC / Interval / Tender pills. Currently visual; should filter the table rows.
3. **Index Detail performance chart** — same time-range pill pattern.
4. **Index Detail Top Constituents pills** — Top 25 / Top 100 / All N pills. Should filter the table.
5. **Methodology TOC** — anchor links via `<a href="#section-id">`. CSS `scroll-behavior: smooth` applied at the page level. Active-section highlighting in the TOC is **not** currently implemented (the `active` prop in the TOC component is hardcoded to "universe") — implement a scroll-spy if you want it.
6. **Data page form** — full client-side state (email, role, useCase, touched, submitted). Validation: email format, role non-empty, useCase ≥ 20 chars. Submit transitions to thank-you state. Reset button returns to the form. **No backend wired.**
7. **Fund Detail (BDC)** — tab bar (Overview / Holdings / Portfolio breakdown / Performance / Filings). Tabs use local state.
8. **Fund Detail (Interval)** — same tab pattern + LTM/3Y toggle on the Return Composition card.

---

## What we deliberately did NOT build

These pages exist on the live site (privatemarketwatch.com) but were **deliberately omitted** from this design doc, by user decision:

- **Indices overview page** (`/indices`). Folded into the homepage's index ticker bar + the per-index detail pages. Nav "Indices" routes to the Direct Lending detail page (the flagship).
- **Data Quality page** (`/data-quality`). Replaced by the Data access request page. The Methodology page's §6 Limitations covers most of what a Data Quality page would have said.

If the firm wants these pages added later, both are small lifts using existing patterns.

---

## Caveats — what to expect to be inaccurate

The bundle is a structural prototype, so the data values are illustrative. Specifically:

- **All fund returns, AUM figures, position counts, sector breakdowns, manager shares, and benchmark series are illustrative.** Plausible but not real. Wire your real data layer; the *structure* and *which metrics are shown* is the real artifact.
- **All names in the About page People section are blank placeholders** — fill with the real roster.
- **All press / contact emails are illustrative.** Replace with real inboxes.
- **All version history dates / change-log entries on the Methodology page are illustrative.** Replace with real version history.
- **All top-constituent company names** (Stripe, SpaceX, Anthropic, etc.) are illustrative for the equity indices. In production, these are derived from the position-level dataset.
- **Form submit has no backend.** Wire to your real endpoint.
- **Subscribe → buttons** route to Data.html — confirm that matches your funnel intent.
- **Roadmap.html** (linked from `For Advisors / For Institutions / Login` in the top utility bar) is a placeholder page not included in this bundle. Decide what those links should actually do.

---

## Files in this bundle

### HTML entries (one per route)
- `index.html` — homepage (wrapped in design canvas for review; ship `V2Home` rendered standalone)
- `Index Detail - Direct Lending.html`
- `Index Detail - Preferred Equity.html`
- `Index Detail - Common Equity.html`
- `Fund Detail v3 - BDC.html`
- `Fund Detail v3 - Interval.html`
- `Methodology.html`
- `Data.html`
- `About.html`

### Page components (JSX)
- `v2-themed.jsx` — homepage chassis + 5 palette variants (`V2_THEMES`). Ship the `navyGold` theme.
- `index-detail.jsx` — index detail chassis (data-driven via `data` prop)
- `methodology.jsx` — methodology document
- `data-access.jsx` — data request landing + form
- `about.jsx` — about page
- `fund-detail-v3-bdc.jsx` — BDC fund detail template (ARCC example)
- `fund-detail-v3-interval.jsx` — Interval fund detail template (CCLFX example)
- `peer-quartile.jsx` — peer-comparison primitives used by the fund-detail pages

### Shared chrome
- `fund-chrome.jsx` — FundHeader, Breadcrumb, FundFooter, T_V3 tokens, SX_V3 style primitives

### Shared chart primitives + universe data
- `shared.jsx` — PMWSparkline, PMWLineChart, PMWStackedArea, PMWHBars, PMWHistogram, PMWDonut, plus the universe-level `PMW_DATA` constant used by the homepage

### Data files (illustrative)
- `index-data.js` — three index data constants (one per index)
- `fund-data.js` — Interval fund (CCLFX) data
- `fund-data-v2.js` — BDC (ARCC) data
- `peer-universe.js` — peer-comparison universe data for fund-detail pages

### Other
- `design-canvas.jsx` — pan/zoom canvas component used to view homepage variants side-by-side during design review. **Not part of the production app — discard this in the rebuild.**
- `CLAUDE.md` — the design-time working context with the project owner. Read it for additional commentary on design decisions, especially the "Hard design rules" section.
- `screenshots/` — hero-frame PNG of each page (01–09) for quick visual reference. The page render was scaled to fit a single capture; for accurate pixel reference run the HTML.

---

## Suggested implementation order

If you're starting from scratch, this is the order that minimizes rework:

1. **Set up the project** with your chosen framework. Define the spacing, color, and type tokens in your DS. Build the typography primitives.
2. **Build the chrome** first (`FundHeader`, `Breadcrumb`, `FundFooter`) — they're shared by every page, and any layout decisions you make here propagate everywhere.
3. **Build chart primitives** with your real charting library (line, sparkline, histogram, donut, stacked bar). These are used everywhere.
4. **Pick a "spine" page** to validate the chassis. **Recommended: Index Detail — Direct Lending.** It exercises most patterns (hero, stat strip, performance chart, return summary, dark band, composition donuts, constituents table, structural composition, top funds, methodology summary) and is the cleanest data shape.
5. **Then build the homepage** (`V2Home`) — uses the same chart primitives + the universe table.
6. **Then the other two index pages** — same chassis, swap data.
7. **Then the two fund-detail templates.**
8. **Then Methodology** (long-form, different layout pattern — sticky TOC + 1-col content).
9. **Then Data + About** — simpler pages, mostly typography + a working form.

The Methodology page is structurally different from everything else (editorial document, not dashboard) — leave it for after you've gotten the dashboard chassis right.
