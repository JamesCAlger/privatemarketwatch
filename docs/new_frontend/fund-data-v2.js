/* eslint-disable */
// v2 additions: full peer set with quartile-able metrics, NAV-price spread
// history (BDC), and a complementary interval-fund record (Cliffwater CCLFX).
//
// Loads after fund-data.js; mutates FUND with extra peer columns and exposes
// FUND_INTERVAL on window.

// ─── BDC peer set: enriched columns for quartile analysis ─────────────────────
// All eight publics in our universe. For each: returns over multiple periods,
// distribution rate, current premium/discount and 3Y average, plus operating
// indicators we can rank on.
FUND.peersFull = [
  { ticker: "ARCC", name: "Ares Capital Corp",          aum: 31.2, nav: 19.94, last: 20.74, prem:  4.0, prem3yAvg:  5.8, ret1y: 12.6, ret3y: 11.8, ret5y: 10.4, dist:  9.6, distCov: 1.04, navGrowth5y: 3.1, leverage: 1.16, nonAccrual: 1.5, highlight: true },
  { ticker: "BXSL", name: "Blackstone Sec. Lending",    aum: 14.7, nav: 26.92, last: 27.79, prem:  3.2, prem3yAvg:  6.2, ret1y: 13.1, ret3y: 12.4, ret5y: null, dist: 11.4, distCov: 1.01, navGrowth5y: null, leverage: 1.12, nonAccrual: 0.4 },
  { ticker: "OBDC", name: "Blue Owl Capital Corp",      aum: 17.2, nav: 14.81, last: 15.04, prem:  1.6, prem3yAvg: -2.4, ret1y: 10.8, ret3y:  9.2, ret5y:  8.7, dist: 10.0, distCov: 1.02, navGrowth5y: 0.4, leverage: 1.21, nonAccrual: 1.8 },
  { ticker: "FSK",  name: "FS KKR Capital",             aum: 13.7, nav: 20.89, last: 19.42, prem: -7.0, prem3yAvg: -8.6, ret1y:  6.4, ret3y:  5.8, ret5y:  3.2, dist: 13.4, distCov: 0.97, navGrowth5y: -2.4, leverage: 1.18, nonAccrual: 3.6 },
  { ticker: "MAIN", name: "Main Street Capital",        aum:  5.7, nav: 33.33, last: 56.40, prem: 69.2, prem3yAvg: 56.4, ret1y: 18.4, ret3y: 16.2, ret5y: 15.4, dist: 12.7, distCov: 1.12, navGrowth5y: 4.8, leverage: 0.92, nonAccrual: 0.8 },
  { ticker: "GBDC", name: "Golub Capital BDC",          aum:  8.9, nav: 14.84, last: 14.92, prem:  0.5, prem3yAvg: -1.2, ret1y:  9.4, ret3y:  8.6, ret5y:  7.1, dist:  8.4, distCov: 1.05, navGrowth5y: -0.2, leverage: 1.24, nonAccrual: 1.2 },
  { ticker: "HTGC", name: "Hercules Capital",           aum:  4.6, nav: 12.13, last: 18.71, prem: 54.2, prem3yAvg: 42.8, ret1y: 14.2, ret3y: 13.6, ret5y: 12.8, dist: 15.5, distCov: 1.18, navGrowth5y: 1.4, leverage: 0.98, nonAccrual: 2.1 },
  { ticker: "BCSF", name: "Bain Capital Spec. Finance", aum:  2.7, nav: 17.23, last: 16.93, prem: -1.7, prem3yAvg: -3.1, ret1y:  8.6, ret3y:  7.4, ret5y:  6.2, dist: 13.9, distCov: 0.95, navGrowth5y: -1.6, leverage: 1.14, nonAccrual: 1.9 },
];

// ─── ARCC's NAV-price spread history with peer cross-section ──────────────────
// Premium (+) / discount (−) to NAV, quarterly. Median + 25/75 are the cross-
// sectional figures across the eight-fund peer set in that quarter. The
// "premium peers" exclude MAIN and HTGC, which structurally trade at large
// premiums and would otherwise distort the band.
FUND.spreadHistory = {
  quarters: ["Q1 23","Q2 23","Q3 23","Q4 23","Q1 24","Q2 24","Q3 24","Q4 24","Q1 25","Q2 25","Q3 25","Q4 25"],
  arcc:    [ 1.8,  2.2,  3.4,  5.1,  4.2,  3.6,  4.8,  5.4,  4.9,  3.8,  3.2,  4.0],
  peerMed: [-2.4, -1.6, -0.4,  0.8,  1.4,  2.0,  2.4,  2.8,  2.6,  2.0,  1.6,  1.4],
  peerP25: [-7.6, -6.4, -4.2, -2.8, -2.0, -1.4, -0.6,  0.2, -0.4, -1.2, -1.8, -2.4],
  peerP75: [ 4.4,  5.2,  6.8,  7.6,  6.8,  6.2,  6.8,  7.4,  6.6,  5.6,  4.8,  5.8],
};

// ─── Quartile rank lookups (precomputed for clarity) ──────────────────────────
// "rank" is 1-best to N-worst by the convention of the metric.
//   ret/dist/distCov/navGrowth: higher = better (rank 1 = highest)
//   nonAccrual/leverage:         lower  = better (rank 1 = lowest)
//   prem (premium to NAV):       no canonical "better"; we just show position
FUND.quartiles = {
  ret1y:       { value: 12.6, rank: 4, total: 8, direction: "higher", peerLabel: "BDC peers" },
  ret3y:       { value: 11.8, rank: 4, total: 8, direction: "higher", peerLabel: "BDC peers" },
  ret5y:       { value: 10.4, rank: 3, total: 7, direction: "higher", peerLabel: "BDC peers" },
  dist:        { value:  9.6, rank: 8, total: 8, direction: "higher", peerLabel: "BDC peers" },
  distCov:     { value: 1.04, rank: 4, total: 8, direction: "higher", peerLabel: "BDC peers" },
  navGrowth5y: { value:  3.1, rank: 2, total: 6, direction: "higher", peerLabel: "BDC peers" },
  leverage:    { value: 1.16, rank: 4, total: 8, direction: "lower",  peerLabel: "BDC peers" },
  nonAccrual:  { value:  1.5, rank: 4, total: 8, direction: "lower",  peerLabel: "BDC peers" },
  prem:        { value:  4.0, rank: 4, total: 8, direction: "neutral",peerLabel: "BDC peers" },
};

// ────────────────────────────────────────────────────────────────────────────
// INTERVAL FUND record: Cliffwater Corporate Lending Fund (CCLFX)
// ────────────────────────────────────────────────────────────────────────────
// Interval funds: no exchange listing, no daily market price, periodic tender
// windows for redemption (typically quarterly, 5% of shares outstanding). NAV
// is the transaction price. So there is NO premium/discount — instead, the
// key liquidity signals are tender oversubscription history and pro-ration.

const FUND_INTERVAL = {
  identity: {
    name: "Cliffwater Corporate Lending Fund",
    ticker: "CCLFX",
    cik: "0001719812",
    type: "Interval",
    liquidity: "Semi-Liquid · Quarterly Tender",
    inception: "Mar 2019",
    manager: "Cliffwater LLC",
    address: "4640 Admiralty Way, Marina del Rey, CA",
    aum: 56.3,
    navPerShare: 10.83,
    sharesOut: 5198.5,         // M
    distRate: 9.85,            // % annualized, paid monthly
    distCadence: "Monthly",
    qoqReturn: 2.1,
    ytdReturn: 8.7,
    asOf: "Q4 2025",
  },

  // Liquidity / tender terms — the BDC equivalent of NAV-price spread.
  liquidity: {
    structure: "Closed-end interval fund (1940 Act)",
    listing: "Not exchange-listed",
    transactionPrice: "Daily NAV",
    tenderFrequency: "Quarterly",
    tenderSize: "5.0% of shares outstanding (per Rule 23c-3)",
    tenderNotice: "21–42 days before pricing date",
    earlyRedemptionFee: "2.00% if redeemed within 365 days of purchase",
    minimumInvestment: "$50,000 (Class I)",
    lockup: "None",
    softClose: "Open to new investors",
  },

  // Tender history — past 8 quarters. fulfilled = % of tendered shares
  // actually repurchased. < 100% means the offer was oversubscribed and
  // shareholders were pro-rated.
  tenderHistory: [
    { date: "2024-03-15", offered: 5.0, tendered: 1.9, fulfilled: 100, prorata: false },
    { date: "2024-06-14", offered: 5.0, tendered: 2.4, fulfilled: 100, prorata: false },
    { date: "2024-09-13", offered: 5.0, tendered: 3.1, fulfilled: 100, prorata: false },
    { date: "2024-12-13", offered: 5.0, tendered: 4.2, fulfilled: 100, prorata: false },
    { date: "2025-03-14", offered: 5.0, tendered: 4.8, fulfilled: 100, prorata: false },
    { date: "2025-06-13", offered: 5.0, tendered: 5.6, fulfilled:  89, prorata: true  },
    { date: "2025-09-12", offered: 5.0, tendered: 5.2, fulfilled:  96, prorata: true  },
    { date: "2025-12-12", offered: 5.0, tendered: 4.5, fulfilled: 100, prorata: false },
  ],

  // NAV history (quarterly) and total-return reconstruction
  history: {
    quarters: ["Q1 23","Q2 23","Q3 23","Q4 23","Q1 24","Q2 24","Q3 24","Q4 24","Q1 25","Q2 25","Q3 25","Q4 25"],
    nav:     [10.46, 10.48, 10.51, 10.54, 10.58, 10.62, 10.66, 10.71, 10.76, 10.79, 10.81, 10.83],
    // Monthly distributions per share — sum over the quarter
    distQ:   [ 0.25,  0.26,  0.26,  0.27,  0.27,  0.27,  0.27,  0.27,  0.27,  0.27,  0.27,  0.27],
    // Net total-return index (NAV + reinvested distributions)
    tr:      [100.0, 102.9, 105.5, 108.4, 111.5, 114.5, 117.5, 120.7, 123.8, 126.5, 129.0, 131.6],
  },

  sinceInception: {
    labels: ["'19","'20","'21","'22","'23","'24","'25"],
    totalReturn: [100, 107, 117, 125, 135, 148, 162],
  },

  performance: {
    rows: [
      { k: "QTD",                fund: "+2.1%",  peerMed: "+1.8%", quartile: 2 },
      { k: "YTD",                fund: "+8.7%",  peerMed: "+7.6%", quartile: 1 },
      { k: "1 Year",             fund: "+11.4%", peerMed: "+9.8%", quartile: 1 },
      { k: "3 Year (annlz.)",    fund: "+10.7%", peerMed: "+8.4%", quartile: 1 },
      { k: "5 Year (annlz.)",    fund: "+ 9.8%", peerMed: "+7.6%", quartile: 1 },
      { k: "Since inception",    fund: "+ 8.4%", peerMed: "+6.8%", quartile: 1 },
    ],
  },

  portfolioChars: [
    { k: "Wtd. Avg. Coupon",   v: "10.1%",   note: "94% coverage" },
    { k: "Wtd. Avg. Spread",   v: "584 bps", note: "82% coverage" },
    { k: "Wtd. Avg. Maturity", v: "3.9 yrs", note: "76% coverage" },
    { k: "First Lien",         v: "92.6%",   note: "of FV" },
    { k: "Floating Rate",      v: "97.1%",   note: "of FV" },
    { k: "Non-Accrual",        v: "0.7%",    note: "by FV" },
  ],

  industries: [
    { sector: "Software & Services",          pct: 19.2, fv: 10.81 },
    { sector: "Healthcare Equipment & Svcs.", pct: 14.8, fv:  8.33 },
    { sector: "Commercial & Prof. Services",  pct: 12.1, fv:  6.81 },
    { sector: "Capital Goods",                pct: 10.4, fv:  5.86 },
    { sector: "Insurance",                    pct:  8.2, fv:  4.62 },
    { sector: "Consumer Services",            pct:  7.6, fv:  4.28 },
    { sector: "Diversified Financials",       pct:  6.4, fv:  3.60 },
    { sector: "Food, Bev. & Tobacco",         pct:  5.9, fv:  3.32 },
    { sector: "Pharma, Biotech & Life Sci.",  pct:  5.1, fv:  2.87 },
    { sector: "Materials",                    pct:  3.8, fv:  2.14 },
    { sector: "Other / Unclassified",         pct:  6.5, fv:  3.66 },
  ],

  positionTypes: [
    { type: "First Lien Senior Secured",  pct: 92.6, fv: 52.13 },
    { type: "Second Lien Senior Secured", pct:  3.4, fv:  1.91 },
    { type: "Subordinated Debt",          pct:  1.1, fv:  0.62 },
    { type: "Preferred Equity",           pct:  1.6, fv:  0.90 },
    { type: "Common Equity / Warrants",   pct:  0.7, fv:  0.39 },
    { type: "Other",                      pct:  0.6, fv:  0.34 },
  ],

  // Top holdings — only a few; for interval funds, position-level disclosure
  // is less granular (semi-annual N-CSR rather than quarterly N-PORT for some).
  topHoldings: [
    { name: "Cliffwater Direct Lending Fund (master)", industry: "Diversified Financials",     type: "Underlying Fund", fv: 8120, pctNAV: 14.4 },
    { name: "Galway Insurance Holdings",               industry: "Insurance",                  type: "First Lien", coupon: 9.40, maturity: "2028-07", fv: 612, pctNAV: 1.1 },
    { name: "Therapy Brands Holdings",                 industry: "Healthcare Equipment & Svcs.",type: "First Lien", coupon: 9.85, maturity: "2029-05", fv: 581, pctNAV: 1.0 },
    { name: "Pluralsight Holdings",                    industry: "Software & Services",        type: "First Lien", coupon: 9.65, maturity: "2027-04", fv: 524, pctNAV: 0.9 },
    { name: "PetVet Care Centers",                     industry: "Consumer Services",          type: "First Lien", coupon: 9.40, maturity: "2028-02", fv: 498, pctNAV: 0.9 },
    { name: "Convey Health Solutions",                 industry: "Healthcare Equipment & Svcs.",type: "First Lien", coupon: 9.55, maturity: "2028-11", fv: 461, pctNAV: 0.8 },
    { name: "Tank Holding Corp.",                      industry: "Capital Goods",              type: "First Lien", coupon: 9.25, maturity: "2028-03", fv: 437, pctNAV: 0.8 },
    { name: "Atria Wealth Solutions",                  industry: "Diversified Financials",     type: "First Lien", coupon: 9.10, maturity: "2029-02", fv: 410, pctNAV: 0.7 },
  ],

  riskFlags: [
    { k: "Non-Accruals (by FV)",     v: "0.7%",  status: "ok",   note: "vs. 1.4% peer median" },
    { k: "Marked Below Cost",        v: "2.8%",  status: "ok",   note: "vs. 3.6% peer median" },
    { k: "Leverage Ratio",           v: "0.34×", status: "ok",   note: "vs. 0.45× peer median" },
    { k: "Tender Pro-Ration",        v: "2 / 8", status: "warn" },
    { k: "Cash & Undrawn Liquidity", v: "8.4%",  status: "ok",   note: "of NAV" },
    { k: "Floating Rate Coverage",   v: "97.1%", status: "ok" },
  ],

  filings: [
    { date: "2026-02-18", type: "N-CSR",  period: "FY 2025 annual" },
    { date: "2026-02-12", type: "N-PX",   period: "Proxy voting" },
    { date: "2026-01-28", type: "N-PORT", period: "Q4 2025" },
    { date: "2025-10-28", type: "N-PORT", period: "Q3 2025" },
    { date: "2025-08-22", type: "N-CSRS", period: "Semi-annual" },
    { date: "2025-07-28", type: "N-PORT", period: "Q2 2025" },
    { date: "2025-04-28", type: "N-PORT", period: "Q1 2025" },
    { date: "2025-03-22", type: "N-2/A",  period: "Registration amendment" },
  ],

  // Interval-fund peer set — large credit-focused interval funds
  peersFull: [
    { ticker: "CCLFX", name: "Cliffwater Corporate Lending",   aum: 56.3, nav: 10.83, dist:  9.85, distCov: 1.06, ret1y: 11.4, ret3y: 10.7, ret5y:  9.8, stdev: 1.8, drawdown: -2.4, prorata: 2, highlight: true },
    { ticker: "CELFX", name: "Cliffwater Enhanced Lending",    aum: 12.8, nav: 10.41, dist: 11.20, distCov: 1.02, ret1y: 12.6, ret3y: 11.4, ret5y: null, stdev: 2.4, drawdown: -3.1, prorata: 1 },
    { ticker: "PFLEX", name: "PIMCO Flexible Credit Income",   aum: 13.4, nav:  8.94, dist: 10.40, distCov: 0.98, ret1y:  9.8, ret3y:  7.6, ret5y:  6.2, stdev: 3.8, drawdown: -8.4, prorata: 4 },
    { ticker: "BIICX", name: "Blackstone Private Credit Inc.", aum:  9.7, nav: 10.12, dist:  9.40, distCov: 1.04, ret1y: 10.2, ret3y:  9.6, ret5y:  8.4, stdev: 1.9, drawdown: -2.8, prorata: 0 },
    { ticker: "ARDBX", name: "Apollo Diversified Credit",      aum:  7.2, nav:  8.81, dist:  8.60, distCov: 0.94, ret1y:  8.4, ret3y:  6.8, ret5y:  5.4, stdev: 4.2, drawdown: -9.2, prorata: 3 },
    { ticker: "IFLEX", name: "Invesco Senior Floating Rate",   aum:  4.8, nav:  6.42, dist:  8.10, distCov: 0.96, ret1y:  7.8, ret3y:  5.4, ret5y:  4.6, stdev: 5.1, drawdown: -11.6, prorata: 5 },
    { ticker: "PRCFX", name: "Partners Capital Real Cr. Fund", aum:  3.4, nav:  9.95, dist:  9.20, distCov: 1.01, ret1y:  9.4, ret3y:  8.8, ret5y:  7.6, stdev: 2.6, drawdown: -3.8, prorata: 1 },
    { ticker: "FCIRX", name: "First Eagle Credit Opps.",       aum:  2.8, nav: 10.21, dist:  9.60, distCov: 1.00, ret1y:  9.8, ret3y:  8.4, ret5y:  7.2, stdev: 2.3, drawdown: -3.4, prorata: 1 },
  ],

  quartiles: {
    ret1y:    { value: 11.4, rank: 2, total: 8, direction: "higher", peerLabel: "Interval-fund peers" },
    ret3y:    { value: 10.7, rank: 2, total: 8, direction: "higher", peerLabel: "Interval-fund peers" },
    ret5y:    { value:  9.8, rank: 1, total: 7, direction: "higher", peerLabel: "Interval-fund peers" },
    dist:     { value:  9.85,rank: 4, total: 8, direction: "higher", peerLabel: "Interval-fund peers" },
    distCov:  { value: 1.06, rank: 1, total: 8, direction: "higher", peerLabel: "Interval-fund peers" },
    stdev:    { value:  1.8, rank: 1, total: 8, direction: "lower",  peerLabel: "Interval-fund peers" },
    drawdown: { value: -2.4, rank: 1, total: 8, direction: "higher", peerLabel: "Interval-fund peers" },
    prorata:  { value:  2,   rank: 5, total: 8, direction: "lower",  peerLabel: "Interval-fund peers" },
  },
};

window.FUND_INTERVAL = FUND_INTERVAL;
