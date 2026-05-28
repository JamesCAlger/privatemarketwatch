# Frontend Implementation Plan

## Three Plans

The frontend build is split into three sequential Claude Code sessions. Each is self-contained and produces a working, testable artifact.

---

### Plan 1: Postgres Schema + Loader -- COMPLETE (2026-04-06)

**Scope:** Pipeline-side only. No frontend code.

**Deliverables:**
- [x] Postgres schema (5 tables with `pmi_` prefix: `pmi_entities`, `pmi_holdings`, `pmi_position_matches`, `pmi_position_returns`, `pmi_index_returns`)
- [x] Python loader module (`pipeline/db.py`) that reads existing CSVs and bulk-inserts into Postgres via COPY FROM STDIN
- [x] `--load-db` flag added to `pipeline/main.py`
- [x] Indexes optimized for the queries the frontend will run (13 indexes total)
- [x] 5 materialized views: `pmi_mv_latest_quarter`, `pmi_mv_top_constituents`, `pmi_mv_sector_breakdown`, `pmi_mv_vehicle_contribution`, `pmi_mv_latest_holdings`
- [x] Tests that round-trip data through Postgres and verify row counts, types, NULL handling (`tests/test_db.py`, 10 tests, skip gracefully if no Postgres)
- [x] `DATABASE_URL` config via `.env` / env var
- [x] `psycopg2-binary` added to `requirements.txt`

**Database:** Neon (cloud Postgres, `ep-restless-base-am3yupm7.us-east-1.aws.neon.tech`), free tier.

**Data loaded (2026-04-06):**

| Table | Rows Loaded | Status |
|---|---|---|
| `pmi_entities` | 587 | Full |
| `pmi_holdings` | 835,324 | Full |
| `pmi_position_matches` | 1 | Stub -- needs `--returns` regeneration |
| `pmi_position_returns` | 1 | Stub -- needs `--returns` regeneration |
| `pmi_index_returns` | 0 | Empty -- needs `--returns` regeneration |
| 5 materialized views | Created | Will auto-populate when tables are full |

**Load time:** ~2 min 10s (mostly 835K holdings COPY over network).

**To fully populate:** Run `python -m pipeline.main --returns --load-db` to regenerate position matching + index returns CSVs and reload everything into Postgres. This will require Neon paid tier (~$19/mo, 10 GB) as the full dataset exceeds the 0.5 GB free tier.

**Fixes applied during load:**
- Removed `UNIQUE` constraint on `cik` in entities -- 69 CIKs legitimately appear twice (dual BDC + interval/tender classification)
- Added TEXT staging table for holdings load -- 3 rows had `"True"` in `basis_spread` numeric column; safely cast to NULL

**Why first:** The frontend cannot query anything until data is in Postgres. The schema also forces decisions about column types, naming, and relationships that affect every downstream query.

---

### Plan 2: Next.js Scaffolding + Homepage + Shared Components

**Scope:** Frontend project from zero to a working homepage.

**Deliverables:**
- Next.js App Router project with TypeScript
- Tailwind CSS configured with institutional design tokens (navy, teal, red, grey, Inter font, tabular figures)
- Postgres client (Prisma or Drizzle) connected via `DATABASE_URL`
- Shared layout: header with nav dropdown, footer with disclaimer
- Homepage:
  - 4 index cards (latest level, QoQ return, 12M return, sparkline)
  - Combined performance chart (all 4 indices, rebased to 100, toggle visibility, log/linear)
  - Latest quarter summary table
  - Brief description section
- Reusable components: IndexCard, SparklineChart, TimeSeriesChart, DataTable, StatValue

**Why second:** Establishes all visual patterns, DB query patterns, and component library that the detail pages reuse.

---

### Plan 3: Index Detail Pages + Methodology + About

**Scope:** All remaining pages.

**Deliverables:**
- 4 index detail pages (`/indices/[slug]`):
  - Single-index time series chart with optional benchmark overlay
  - Quarterly return bar chart (positive/negative coloring)
  - Statistics panel (annualized return, volatility, Sharpe, max drawdown, best/worst quarter)
  - Portfolio characteristics panel (DL-specific: WAC, WAS, WAM, lien split, rate type split)
  - Sector/classification breakdown (horizontal bar chart + table)
  - Top 20 constituents table
  - Vehicle contribution table
- Methodology page (long-form MDX with sticky TOC sidebar, PDF download link)
- About page (static content)
- SEO: meta tags, OpenGraph, sitemap.xml, JSON-LD

**Why third:** These pages are repetitive variations of the same layout with different data queries. The component library from Plan 2 makes this fast.

---

## Technology Decisions

### Why Next.js?

MSCI (msci.com) — the most relevant comparable — uses **Next.js with React Server Components**. This is confirmed from their page source. Other index providers:

| Provider | Stack | Notes |
|---|---|---|
| MSCI | Next.js (React) | SSR + hydration, most modern in the group |
| S&P Global | React + legacy jQuery | Migrating to React/Node.js |
| FTSE Russell | Vanilla JS + AEM | Enterprise CMS, conservative |
| ICE | React (custom CMS) | SSR + hydration |
| Morningstar | Vue + Web Components | Proprietary design system |
| Bloomberg | Backbone.js + React | Legacy + newer products |
| Cliffwater | Angular / AngularJS | SPA, data-dense dashboard style |

Next.js is the clear modern choice for a new project with no legacy constraints. It gives us SSR for SEO, API routes for Postgres queries, and the React ecosystem for charts and tables.

### Why Postgres over static JSON?

The original spec called for static JSON files generated at build time. Postgres is better because:

1. **Query flexibility**: The frontend needs ~15 different query shapes (top constituents, sector breakdown, vehicle contribution, stats aggregations). Pre-generating all permutations as JSON is brittle and wasteful.
2. **Phase 2 readiness**: Vehicle pages (`/vehicles/[cik]`) need per-CIK queries. That's 588 JSON files to pre-generate vs one parameterized query.
3. **Incremental updates**: Load new quarterly data without rebuilding every JSON file.
4. **Materialized views**: Pre-compute expensive aggregations (index composition, quarterly fund performance) and refresh on pipeline run.

835K rows in Postgres is trivial — queries return in <50ms with proper indexes.

### Charting

| Library | Used By | Cost | Recommendation |
|---|---|---|---|
| Highcharts Stock | Fortune 500 finance | $590/dev | Best institutional look out of the box |
| Apache ECharts | High-traffic analytics | Free | Best free option for large datasets |
| Recharts | React ecosystem | Free | Simple React integration, good for basic charts |

Recharts for v1 (simple, fast, React-native). Upgrade to Highcharts or ECharts if we need more polish.

### Hosting

- **App**: Vercel (built for Next.js, free tier, auto-deploy on push)
- **Database**: Neon Postgres (cloud, free tier for development; Launch plan $19/mo for production with full dataset)

---

## Current Status & Next Steps

### What's done
- **Plan 1 complete.** Schema, loader, materialized views, tests all working. Entities + holdings loaded into Neon.

### What's in the database now
- 587 entities and 835K holdings -- enough to build and test the full frontend (homepage, index pages, entity pages, charts).
- Position matches, position returns, and index returns are stubs (1, 1, and 0 rows). These are the time-series and return data that power the performance charts and statistics panels.

### Before starting Plan 2 (Next.js frontend)
Nothing blocking. The entities and holdings tables are sufficient to build and test most frontend components. Performance charts will show empty/placeholder states until the returns data is loaded.

### Before going live
1. **Regenerate returns data:** `python -m pipeline.main --returns` (~10 min, regenerates position_matches.csv, position_returns.csv, index_returns.csv with full data)
2. **Upgrade Neon to paid tier** ($19/mo Launch plan, 10 GB) -- full dataset exceeds 0.5 GB free tier
3. **Reload into Postgres:** `python -m pipeline.main --load-db` (~2-3 min)
4. Verify all tables populated: entities 587, holdings ~835K, position_matches ~560K, position_returns ~560K, index_returns ~100
