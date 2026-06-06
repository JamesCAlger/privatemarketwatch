/* eslint-disable */
// ARCC fund-detail mock data. Public details (ticker, NAV/sh, AUM, dist rate)
// match the Q4 2025 homepage table; holdings & breakdowns are illustrative
// placeholders that match the SHAPE of N-PORT data.

const FUND = {
  identity: {
    name: "Ares Capital Corp",
    ticker: "ARCC",
    cik: "0001287750",
    type: "BDC",
    liquidity: "Publicly Traded",
    inception: "Oct 2004",
    manager: "Ares Capital Management",
    address: "245 Park Avenue, 44th Fl, New York, NY",
    aum: 31.2,             // $B
    navPerShare: 19.94,
    lastPrice: 20.74,
    sharesOut: 627.4,      // M
    distRate: 9.6,         // %
    qoqReturn: 2.0,        // %
    ytdReturn: 8.4,
    asOf: "Q4 2025",
  },
  // Quarterly price + NAV history (mock; ~12 quarters, then 5 years for SI view)
  history: {
    quarters: ["Q1 22","Q2 22","Q3 22","Q4 22","Q1 23","Q2 23","Q3 23","Q4 23","Q1 24","Q2 24","Q3 24","Q4 24","Q1 25","Q2 25","Q3 25","Q4 25"],
    price:   [21.45,19.20,17.85,18.45,19.10,19.85,20.20,20.80,21.05,20.35,20.90,21.40,20.85,21.20,20.55,20.74],
    nav:     [19.04,18.81,18.50,18.40,18.55,18.80,19.05,19.25,19.40,19.55,19.70,19.80,19.85,19.90,19.92,19.94],
    distributions: [0.42,0.43,0.44,0.45,0.46,0.46,0.48,0.48,0.48,0.48,0.48,0.48,0.48,0.48,0.48,0.48],
  },
  // since-inception, sparse annual points
  sinceInception: {
    labels: ["'05","'07","'09","'11","'13","'15","'17","'19","'21","'23","'25"],
    totalReturn: [100,138,92,178,224,256,292,334,392,447,512],
  },
  performance: {
    rows: [
      { k: "QTD",                arcc: "+2.0%",  bdcIdx: "+1.7%", sp500: "+0.8%" },
      { k: "YTD",                arcc: "+8.4%",  bdcIdx: "+7.1%", sp500: "+5.2%" },
      { k: "1 Year",             arcc: "+12.6%", bdcIdx: "+10.4%",sp500: "+12.1%" },
      { k: "3 Year (annlz.)",    arcc: "+11.8%", bdcIdx: "+9.6%", sp500: "+9.4%" },
      { k: "5 Year (annlz.)",    arcc: "+10.4%", bdcIdx: "+8.1%", sp500: "+11.8%" },
      { k: "10 Year (annlz.)",   arcc: "+9.7%",  bdcIdx: "+7.8%", sp500: "+10.9%" },
      { k: "Since inception",    arcc: "+9.1%",  bdcIdx: "+6.4%", sp500: "+8.6%" },
    ],
  },
  // Portfolio characteristics — fund-specific
  portfolioChars: [
    { k: "Wtd. Avg. Coupon",  v: "9.4%",    note: "92% coverage" },
    { k: "Wtd. Avg. Spread",  v: "532 bps", note: "78% coverage" },
    { k: "Wtd. Avg. Maturity",v: "4.4 yrs", note: "71% coverage" },
    { k: "First Lien",        v: "78.4%",   note: "of FV" },
    { k: "Floating Rate",     v: "94.8%",   note: "of FV" },
    { k: "Non-Accrual",       v: "1.5%",    note: "by FV" },
  ],
  // Industry breakdown — illustrative but realistic for a senior-secured BDC
  industries: [
    { sector: "Software & Services",         pct: 17.4, fv: 5.43 },
    { sector: "Healthcare Equipment & Svcs.",pct: 13.1, fv: 4.09 },
    { sector: "Capital Goods",               pct: 11.6, fv: 3.62 },
    { sector: "Commercial & Prof. Services", pct:  9.8, fv: 3.06 },
    { sector: "Insurance",                   pct:  8.7, fv: 2.72 },
    { sector: "Diversified Financials",      pct:  7.4, fv: 2.31 },
    { sector: "Consumer Services",           pct:  6.9, fv: 2.15 },
    { sector: "Food, Bev. & Tobacco",        pct:  5.2, fv: 1.62 },
    { sector: "Pharma, Biotech & Life Sci.", pct:  4.7, fv: 1.47 },
    { sector: "Materials",                   pct:  4.1, fv: 1.28 },
    { sector: "Transportation",              pct:  3.6, fv: 1.12 },
    { sector: "Other / Unclassified",        pct:  7.5, fv: 2.34 },
  ],
  // Position type breakdown
  positionTypes: [
    { type: "First Lien Senior Secured",   pct: 78.4, fv: 24.46 },
    { type: "Second Lien Senior Secured",  pct:  6.2, fv:  1.93 },
    { type: "Subordinated Debt",           pct:  2.8, fv:  0.87 },
    { type: "Preferred Equity",            pct:  4.5, fv:  1.40 },
    { type: "Common Equity / Warrants",    pct:  6.1, fv:  1.90 },
    { type: "Other",                       pct:  2.0, fv:  0.62 },
  ],
  geography: [
    { region: "United States",     pct: 88.4 },
    { region: "Canada",            pct:  4.6 },
    { region: "United Kingdom",    pct:  3.1 },
    { region: "Western Europe",    pct:  2.8 },
    { region: "Other",             pct:  1.1 },
  ],
  // Top holdings table — sortable
  topHoldings: [
    { name: "Ivy Hill Asset Mgmt., L.P.",    industry: "Diversified Financials",        type: "Equity",       coupon: null,  maturity: null,      fv:  2480, pctNAV: 19.8 },
    { name: "Senior Direct Lending Program", industry: "Diversified Financials",        type: "First Lien",   coupon: 9.85,  maturity: "2028-04", fv:  1840, pctNAV: 14.7 },
    { name: "OPS Acquisitions HoldCo",       industry: "Commercial & Prof. Services",   type: "First Lien",   coupon: 10.20, maturity: "2029-09", fv:   612, pctNAV:  4.9 },
    { name: "Singerman Real Estate",         industry: "Diversified Financials",        type: "Preferred",    coupon: 12.50, maturity: "2027-12", fv:   504, pctNAV:  4.0 },
    { name: "Pluralsight Holdings",          industry: "Software & Services",           type: "First Lien",   coupon:  9.85, maturity: "2027-04", fv:   486, pctNAV:  3.9 },
    { name: "Therapy Brands Holdings",       industry: "Healthcare Equipment & Svcs.",  type: "Second Lien",  coupon: 11.55, maturity: "2029-05", fv:   422, pctNAV:  3.4 },
    { name: "PetVet Care Centers",           industry: "Consumer Services",             type: "First Lien",   coupon:  9.60, maturity: "2028-02", fv:   395, pctNAV:  3.2 },
    { name: "American Achievement Corp.",    industry: "Consumer Services",             type: "First Lien",   coupon: 10.05, maturity: "2028-08", fv:   362, pctNAV:  2.9 },
    { name: "Convey Health Solutions",       industry: "Healthcare Equipment & Svcs.",  type: "First Lien",   coupon:  9.75, maturity: "2028-11", fv:   348, pctNAV:  2.8 },
    { name: "Tank Holding Corp.",            industry: "Capital Goods",                 type: "First Lien",   coupon:  9.45, maturity: "2028-03", fv:   327, pctNAV:  2.6 },
    { name: "Atria Wealth Solutions",        industry: "Diversified Financials",        type: "First Lien",   coupon:  9.30, maturity: "2029-02", fv:   309, pctNAV:  2.5 },
    { name: "Aimbridge Hospitality",         industry: "Consumer Services",             type: "First Lien",   coupon: 10.80, maturity: "2027-10", fv:   297, pctNAV:  2.4 },
    { name: "PHM Health (Cordis)",           industry: "Healthcare Equipment & Svcs.",  type: "First Lien",   coupon:  9.55, maturity: "2028-12", fv:   286, pctNAV:  2.3 },
    { name: "K2 Pure Solutions",             industry: "Materials",                     type: "First Lien",   coupon:  9.20, maturity: "2028-06", fv:   272, pctNAV:  2.2 },
    { name: "Mavis Tire Express",            industry: "Consumer Services",             type: "First Lien",   coupon:  9.10, maturity: "2028-09", fv:   258, pctNAV:  2.1 },
    { name: "Sunrise Senior Living",         industry: "Healthcare Equipment & Svcs.",  type: "Second Lien",  coupon: 11.20, maturity: "2029-01", fv:   244, pctNAV:  2.0 },
    { name: "Galway Insurance Holdings",     industry: "Insurance",                     type: "First Lien",   coupon:  9.40, maturity: "2028-07", fv:   231, pctNAV:  1.8 },
    { name: "Tegra118 Wealth Solutions",     industry: "Software & Services",           type: "First Lien",   coupon:  9.65, maturity: "2028-04", fv:   218, pctNAV:  1.7 },
    { name: "Worldwise (Petmate)",           industry: "Consumer Services",             type: "First Lien",   coupon:  9.90, maturity: "2027-11", fv:   206, pctNAV:  1.6 },
    { name: "Heartland Veterinary Partners", industry: "Healthcare Equipment & Svcs.",  type: "First Lien",   coupon:  9.55, maturity: "2028-08", fv:   194, pctNAV:  1.5 },
  ],
  filings: [
    { date: "2026-02-12", type: "10-K",   period: "FY 2025",        url: "#" },
    { date: "2026-02-12", type: "N-CSR",  period: "FY 2025 annual", url: "#" },
    { date: "2026-01-28", type: "N-PORT", period: "Q4 2025",        url: "#" },
    { date: "2026-01-15", type: "8-K",    period: "Quarterly div.", url: "#" },
    { date: "2025-11-06", type: "10-Q",   period: "Q3 2025",        url: "#" },
    { date: "2025-10-28", type: "N-PORT", period: "Q3 2025",        url: "#" },
    { date: "2025-10-15", type: "8-K",    period: "Quarterly div.", url: "#" },
    { date: "2025-08-06", type: "10-Q",   period: "Q2 2025",        url: "#" },
    { date: "2025-07-28", type: "N-PORT", period: "Q2 2025",        url: "#" },
    { date: "2025-07-15", type: "8-K",    period: "Quarterly div.", url: "#" },
    { date: "2025-05-07", type: "10-Q",   period: "Q1 2025",        url: "#" },
    { date: "2025-04-28", type: "N-PORT", period: "Q1 2025",        url: "#" },
  ],
  // Peer comparison — large public BDCs
  peers: [
    { ticker: "ARCC", name: "Ares Capital Corp",          aum: 31.2, nav: 19.94, last: 20.74, prem:  4.0, dist: 9.6,  qoq: 2.0,  highlight: true },
    { ticker: "BXSL", name: "Blackstone Sec. Lending",    aum: 14.7, nav: 26.92, last: 27.79, prem:  3.2, dist: 11.4, qoq: 2.0 },
    { ticker: "OBDC", name: "Blue Owl Capital Corp",      aum: 17.2, nav: 14.81, last: 15.04, prem:  1.6, dist: 10.0, qoq: 2.8 },
    { ticker: "FSK",  name: "FS KKR Capital",             aum: 13.7, nav: 20.89, last: 19.42, prem: -7.0, dist: 13.4, qoq: -1.6 },
    { ticker: "MAIN", name: "Main Street Capital",        aum:  5.7, nav: 33.33, last: 56.40, prem: 69.2, dist: 12.7, qoq: 4.1 },
    { ticker: "GBDC", name: "Golub Capital BDC",          aum:  8.9, nav: 14.84, last: 14.92, prem:  0.5, dist:  8.4, qoq: 1.6 },
    { ticker: "HTGC", name: "Hercules Capital",           aum:  4.6, nav: 12.13, last: 18.71, prem: 54.2, dist: 15.5, qoq: 2.0 },
    { ticker: "BCSF", name: "Bain Capital Spec. Finance", aum:  2.7, nav: 17.23, last: 16.93, prem: -1.7, dist: 13.9, qoq: 2.5 },
  ],
  // Risk indicators
  riskFlags: [
    { k: "Non-Accruals (by FV)",       v: "1.5%",   status: "ok",   note: "vs. 2.1% peer median" },
    { k: "Non-Accruals (by count)",    v: "2.4%",   status: "ok",   note: "8 of 332 positions" },
    { k: "Marked Below Cost",          v: "4.2%",   status: "ok",   note: "vs. 4.4% peer median" },
    { k: "Leverage Ratio",             v: "1.16×",  status: "warn", note: "vs. 1.05× peer median" },
    { k: "PIK Income (% interest)",    v: "5.8%",   status: "ok" },
    { k: "Floating Rate Coverage",     v: "94.8%",  status: "ok" },
  ],
};

// ─── Daily price + step-NAV series ────────────────────────────────────────────
// PMW's price coverage begins Q4 2022 (first full quarter under the current
// indexing methodology). Prior to that we only have data from quarterly filings.
// NAV remains a quarterly figure — it is repeated daily as a step function.
(function buildDaily() {
  const qPrices = FUND.history.price.slice(3); // Q4 22 onwards (13 quarters)
  const qNavs   = FUND.history.nav.slice(3);
  const qBoundaries = [
    new Date(2022, 9,  3), new Date(2023, 0, 2), new Date(2023, 3, 3), new Date(2023, 6, 3),
    new Date(2023, 9,  2), new Date(2024, 0, 2), new Date(2024, 3, 1), new Date(2024, 6, 1),
    new Date(2024, 9,  1), new Date(2025, 0, 2), new Date(2025, 3, 1), new Date(2025, 6, 1),
    new Date(2025, 9,  1), new Date(2025, 11, 31),
  ];
  const dates = [], prices = [], navs = [];
  // Deterministic LCG for reproducible noise
  let seed = 1729;
  const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };

  const cur = new Date(qBoundaries[0]);
  const end = qBoundaries[qBoundaries.length - 1];
  let lastPrice = qPrices[0];

  while (cur <= end) {
    const dow = cur.getDay();
    if (dow !== 0 && dow !== 6) {
      // Which quarter index are we in?
      let qIdx = qPrices.length - 1;
      for (let i = 0; i < qBoundaries.length - 1; i++) {
        if (cur >= qBoundaries[i] && cur < qBoundaries[i + 1]) { qIdx = Math.min(i, qPrices.length - 1); break; }
      }
      const qStart = qBoundaries[qIdx];
      const qEnd   = qBoundaries[qIdx + 1] || qBoundaries[qBoundaries.length - 1];
      const totalDays = (qEnd - qStart) / 86400000;
      const elapsed   = (cur  - qStart) / 86400000;
      const t = totalDays > 0 ? elapsed / totalDays : 0;
      const startPrice = qIdx === 0 ? qPrices[0] : qPrices[qIdx - 1];
      const endPrice   = qPrices[qIdx];
      const trend = startPrice + (endPrice - startPrice) * t;
      // Mean-reverting random walk around the trend
      const noise = (rnd() - 0.5) * 0.42;
      const mr = 0.86;
      lastPrice = lastPrice * mr + trend * (1 - mr) + noise;
      const p = Math.round(lastPrice * 100) / 100;

      dates.push(new Date(cur));
      prices.push(p);
      navs.push(qNavs[qIdx]);
    }
    cur.setDate(cur.getDate() + 1);
  }
  FUND.daily = { dates, prices, navs };
})();

window.FUND = FUND;
