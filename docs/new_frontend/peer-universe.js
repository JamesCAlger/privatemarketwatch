// ─────────────────────────────────────────────────────────────────────────────
// peer-universe.js
//
// Full-universe mock data for ranking fund metrics against ALL comparable
// funds, not a curated peer set. Three universes:
//
//   - bdcsTraded     ~47 publicly-traded BDCs
//   - intervalsTender ~95 interval + tender-offer registered funds
//   - creditAll      both combined (~140) — used for metrics that are
//                    comparable across both wrappers (returns, dist,
//                    coverage). Wrapper-specific metrics use only the
//                    relevant universe.
//
// Deterministic — seeded PRNG so values are stable across reloads. Focal
// funds (ARCC, CCLFX) are pinned to their canonical headline values; the
// rest are synthesized with realistic per-metric distributions.
//
// Each entry exposes only the fields meaningful for its wrapper:
//   BDC:      ret1y, ret3y, ret5y, dist, distCov, leverage, nonAccrual,
//             prem, navGrowth5y
//   Interval: ret1y, ret3y, ret5y, dist, distCov, stdev, drawdown, prorata
// ─────────────────────────────────────────────────────────────────────────────

(function () {
  // ── deterministic PRNG ────────────────────────────────────────────────────
  function rng(seed) {
    let s = seed | 0;
    return function () {
      s = (s + 0x6D2B79F5) | 0;
      let t = s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function gauss(r) {
    // Box–Muller. Clamp to avoid log(0).
    const u = Math.max(1e-9, r());
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
  }
  // Generate skewed-positive value via gamma-like sum
  function skewRight(r, scale) {
    return (Math.pow(r(), 1.6)) * scale;
  }
  function clip(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }
  function round(v, d) {
    const m = Math.pow(10, d);
    return Math.round(v * m) / m;
  }

  // ── pseudo-ticker generators ──────────────────────────────────────────────
  // Mix of real fund tickers + synthetic ones. Real tickers anchor the set
  // to recognizable names; synthetic ones (with realistic 4-5 letter form)
  // fill out the universe without overclaiming specific funds.
  const BDC_REAL = [
    ["ARCC", "Ares Capital Corp"],
    ["BXSL", "Blackstone Sec. Lending"],
    ["OBDC", "Blue Owl Capital Corp"],
    ["FSK",  "FS KKR Capital"],
    ["MAIN", "Main Street Capital"],
    ["GBDC", "Golub Capital BDC"],
    ["HTGC", "Hercules Capital"],
    ["BCSF", "Bain Capital Spec. Finance"],
    ["TSLX", "Sixth Street Specialty Lend."],
    ["PSEC", "Prospect Capital"],
    ["CGBD", "Carlyle Secured Lending"],
    ["CSWC", "Capital Southwest"],
    ["TCPC", "BlackRock TCP Capital"],
    ["NMFC", "New Mountain Finance"],
    ["PFLT", "PennantPark Floating Rate"],
    ["GLAD", "Gladstone Capital"],
    ["GAIN", "Gladstone Investment"],
    ["GSBD", "Goldman Sachs BDC"],
    ["SLRC", "SLR Investment Corp"],
    ["TPVG", "TriplePoint Venture Growth"],
    ["BBDC", "Barings BDC"],
    ["PNNT", "PennantPark Investment"],
    ["TRIN", "Trinity Capital"],
    ["HRZN", "Horizon Technology Finance"],
    ["MFIC", "MidCap Financial Investment"],
    ["OXSQ", "Oxford Square Capital"],
    ["WHF",  "WhiteHorse Finance"],
    ["SAR",  "Saratoga Investment"],
    ["OCSL", "Oaktree Specialty Lending"],
    ["CION", "CION Investment Corp"],
    ["RWAY", "Runway Growth Finance"],
    ["FDUS", "Fidus Investment"],
    ["SCM",  "Stellus Capital"],
    ["INCC", "Investcorp BDC"],
    ["MRCC", "Monroe Capital BDC"],
    ["LRFC", "Logan Ridge Finance"],
    ["PTMN", "Portman Ridge Finance"],
    ["KCAP", "Kennedy Capital"],
  ];

  const INTERVAL_REAL = [
    ["CCLFX", "Cliffwater Corporate Lending"],
    ["CELFX", "Cliffwater Enhanced Lending"],
    ["PFLEX", "PIMCO Flexible Credit Income"],
    ["BIICX", "Blackstone Private Credit Inc."],
    ["ARDBX", "Apollo Diversified Credit"],
    ["IFLEX", "Invesco Senior Floating Rate"],
    ["PRCFX", "Partners Capital Real Cr. Fund"],
    ["FCIRX", "First Eagle Credit Opps."],
    ["TPIIX", "T. Rowe Price OHA Select"],
    ["NICHX", "Nuveen Churchill Private Cap."],
    ["BDIB",  "BlackRock Direct Lending"],
    ["KKRCX", "KKR Credit Opps. Portfolio"],
    ["FCRD",  "First Eagle Credit Direct"],
    ["MSDLX", "Morgan Stanley Direct Lending"],
    ["LACOX", "Lord Abbett Credit Opps."],
    ["AICDX", "American Beacon Apollo Inc."],
    ["VCRDX", "Variant Alternative Inc."],
    ["GICOX", "Goldman Sachs Inc. Builder"],
    ["BICIX", "Brookfield Inc. Realty Tr."],
    ["FSCIX", "FS Credit Opportunities"],
    ["FCRIX", "FS Multi-Strategy Alternatives"],
    ["JOFAX", "Jasper Operations Fund"],
    ["MCRDX", "Mercer Private Credit"],
    ["OPCMX", "Optima Private Credit Master"],
    ["VPCCX", "Voya Senior Inc. Master"],
    ["ANGLX", "Angel Oak Strategic Credit"],
    ["AOSCX", "Angel Oak Multi-Strat Inc."],
    ["BPRCX", "Brookfield Real Asset Inc."],
    ["CRGCX", "Carey Diversified Credit"],
    ["CIPDX", "Crystal Capital Diversified"],
    ["MAVNX", "Mavik Real Estate Credit"],
    ["MFLDX", "Mercer Floating Direct Lend."],
    ["NMCIX", "Nuveen Multi-Asset Credit"],
    ["PCREX", "PIMCO Capital Solutions"],
    ["POLEX", "Pomona Investment Fund"],
    ["RICFX", "Resource Credit Inc."],
    ["SMIIX", "Stone Ridge Mortgage Cred."],
    ["TIIFX", "Thornburg Inc. Builder"],
    ["TYIIX", "Tortoise Tax-Advtg Soc. Inc."],
    ["VCRBX", "Variant Impact Fund"],
    ["WCRIX", "Western Asset Multi-Strat."],
  ];

  function syntheticTickers(prefix, n, rng) {
    // Generate believable-looking 4-5 char fund tickers
    const out = [];
    const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    const seen = new Set();
    while (out.length < n) {
      let t = prefix;
      const remaining = 4 - prefix.length + Math.floor(rng() * 2);
      for (let i = 0; i < remaining; i++) t += letters[Math.floor(rng() * 26)];
      if (!seen.has(t)) { seen.add(t); out.push(t); }
    }
    return out;
  }

  // ── BDC universe — 47 publicly-traded ─────────────────────────────────────
  const rb = rng(0xBDC247);
  const N_BDC = 47;
  const bdcsTraded = [];
  // Anchor with real BDCs first (38 of them — generate 9 synthetics to reach 47)
  const bdcNames = [...BDC_REAL];
  const bdcSyn = syntheticTickers("BD", N_BDC - bdcNames.length, rb);
  bdcSyn.forEach((t) => bdcNames.push([t, "Mid-size BDC"]));

  bdcNames.forEach(([ticker, name]) => {
    const highlight = ticker === "ARCC";
    const e = {
      ticker, name, highlight,
      // returns — normal around peer median, with some dispersion
      ret1y:   round(clip(8.5  + gauss(rb) * 3.8,  -4, 19), 1),
      ret3y:   round(clip(8.0  + gauss(rb) * 3.0,  -1, 17), 1),
      ret5y:   round(clip(7.2  + gauss(rb) * 2.6,   1, 15), 1),
      // distribution: BDCs typically pay 8-14%
      dist:    round(clip(10.2 + gauss(rb) * 2.0,   5, 16), 1),
      distCov: round(clip(1.00 + gauss(rb) * 0.09, 0.7, 1.25), 2),
      // leverage 0.7-1.4
      leverage:round(clip(1.10 + gauss(rb) * 0.18, 0.6, 1.5), 2),
      // non-accrual: right-skewed, mode near 1.5%
      nonAccrual: round(clip(0.6 + skewRight(rb, 4.5), 0.2, 6.5), 1),
      // premium to NAV: roughly normal around -2% with fat tails
      prem:    round(clip(-2.5 + gauss(rb) * 8, -32, 22), 1),
      navGrowth5y: round(clip(0.5 + gauss(rb) * 2.5, -6, 7), 1),
    };
    bdcsTraded.push(e);
  });

  // Pin focal-fund ARCC + key real BDCs (ensures the visualization shows
  // recognizable funds in their actual positions, not synthetic noise)
  const pin = (arr, ticker, fields) => {
    const e = arr.find((x) => x.ticker === ticker);
    if (e) Object.assign(e, fields);
  };
  pin(bdcsTraded, "ARCC", { ret1y: 12.6, ret3y: 11.8, ret5y: 10.4, dist:  9.6, distCov: 1.04, leverage: 1.16, nonAccrual: 1.5, prem:  4.0, navGrowth5y: 3.1, highlight: true });
  pin(bdcsTraded, "BXSL", { ret1y: 13.1, ret3y: 12.4, ret5y: null, dist: 11.4, distCov: 1.01, leverage: 1.12, nonAccrual: 0.4, prem:  3.2, navGrowth5y: null });
  pin(bdcsTraded, "OBDC", { ret1y: 10.8, ret3y:  9.2, ret5y:  8.7, dist: 10.0, distCov: 1.02, leverage: 1.21, nonAccrual: 1.8, prem:  1.6, navGrowth5y: 0.4 });
  pin(bdcsTraded, "FSK",  { ret1y:  6.4, ret3y:  5.8, ret5y:  3.2, dist: 13.4, distCov: 0.97, leverage: 1.18, nonAccrual: 3.6, prem: -7.0, navGrowth5y: -2.4 });
  pin(bdcsTraded, "MAIN", { ret1y: 18.4, ret3y: 16.2, ret5y: 15.4, dist: 12.7, distCov: 1.12, leverage: 0.92, nonAccrual: 0.8, prem: 69.2, navGrowth5y: 4.8 });
  pin(bdcsTraded, "GBDC", { ret1y:  9.4, ret3y:  8.6, ret5y:  7.1, dist:  8.4, distCov: 1.05, leverage: 1.24, nonAccrual: 1.2, prem:  0.5, navGrowth5y: -0.2 });
  pin(bdcsTraded, "HTGC", { ret1y: 14.2, ret3y: 13.6, ret5y: 12.8, dist: 15.5, distCov: 1.18, leverage: 0.98, nonAccrual: 2.1, prem: 54.2, navGrowth5y: 1.4 });
  pin(bdcsTraded, "BCSF", { ret1y:  8.6, ret3y:  7.4, ret5y:  6.2, dist: 13.9, distCov: 0.95, leverage: 1.14, nonAccrual: 1.9, prem: -1.7, navGrowth5y: -1.6 });

  // ── Interval / tender-offer universe — 95 funds ───────────────────────────
  const ri = rng(0x1FCB95);
  const N_INTERVAL = 95;
  const intervalsTender = [];
  const ivNames = [...INTERVAL_REAL];
  const ivSyn = syntheticTickers("I", N_INTERVAL - ivNames.length, ri);
  ivSyn.forEach((t) => ivNames.push([t, "Interval Fund"]));

  ivNames.forEach(([ticker, name]) => {
    const highlight = ticker === "CCLFX";
    // Pro-ration: heavily zero-skewed. Most intervals never pro-rate.
    // P(0)=0.62, P(1)=0.18, P(2)=0.10, P(3)=0.05, P(4)=0.03, P(5+)=0.02
    const u = ri();
    let prorata = 0;
    if      (u < 0.62) prorata = 0;
    else if (u < 0.80) prorata = 1;
    else if (u < 0.90) prorata = 2;
    else if (u < 0.95) prorata = 3;
    else if (u < 0.98) prorata = 4;
    else               prorata = 5 + Math.floor(ri() * 4); // 5-8
    const e = {
      ticker, name, highlight,
      // Intervals: total returns generally lower-vol than BDCs
      ret1y:   round(clip(7.5  + gauss(ri) * 3.2, -3, 16), 1),
      ret3y:   round(clip(7.0  + gauss(ri) * 2.4,  0, 14), 1),
      ret5y:   round(clip(6.2  + gauss(ri) * 2.0,  1, 12), 1),
      dist:    round(clip(8.6  + gauss(ri) * 1.7,  4, 13), 2),
      distCov: round(clip(0.98 + gauss(ri) * 0.08, 0.65, 1.18), 2),
      // realized vol: right-skewed
      stdev:   round(clip(2.8 + skewRight(ri, 5.5), 0.8, 9.0), 1),
      // max drawdown: left-skewed (mostly small magnitudes, some large)
      drawdown: round(-clip(2.0 + skewRight(ri, 13), 0.5, 18), 1),
      prorata,
    };
    intervalsTender.push(e);
  });
  pin(intervalsTender, "CCLFX", { ret1y: 11.4, ret3y: 10.7, ret5y:  9.8, dist:  9.85, distCov: 1.06, stdev: 1.8, drawdown: -2.4, prorata: 2, highlight: true });
  pin(intervalsTender, "CELFX", { ret1y: 12.6, ret3y: 11.4, ret5y: null, dist: 11.20, distCov: 1.02, stdev: 2.4, drawdown: -3.1, prorata: 1 });
  pin(intervalsTender, "PFLEX", { ret1y:  9.8, ret3y:  7.6, ret5y:  6.2, dist: 10.40, distCov: 0.98, stdev: 3.8, drawdown: -8.4, prorata: 4 });
  pin(intervalsTender, "BIICX", { ret1y: 10.2, ret3y:  9.6, ret5y:  8.4, dist:  9.40, distCov: 1.04, stdev: 1.9, drawdown: -2.8, prorata: 0 });
  pin(intervalsTender, "ARDBX", { ret1y:  8.4, ret3y:  6.8, ret5y:  5.4, dist:  8.60, distCov: 0.94, stdev: 4.2, drawdown: -9.2, prorata: 3 });
  pin(intervalsTender, "IFLEX", { ret1y:  7.8, ret3y:  5.4, ret5y:  4.6, dist:  8.10, distCov: 0.96, stdev: 5.1, drawdown: -11.6, prorata: 5 });
  pin(intervalsTender, "PRCFX", { ret1y:  9.4, ret3y:  8.8, ret5y:  7.6, dist:  9.20, distCov: 1.01, stdev: 2.6, drawdown: -3.8, prorata: 1 });
  pin(intervalsTender, "FCIRX", { ret1y:  9.8, ret3y:  8.4, ret5y:  7.2, dist:  9.60, distCov: 1.00, stdev: 2.3, drawdown: -3.4, prorata: 1 });

  // ── Combined credit universe (BDCs + intervals) ───────────────────────────
  // For metrics comparable across both wrappers: ret1y/3y/5y, dist, distCov.
  // We strip wrapper-specific fields so density viz can't pull them by mistake.
  const creditAll = [
    ...bdcsTraded.map((p) => ({ ticker: p.ticker, name: p.name, wrapper: "BDC",
      ret1y: p.ret1y, ret3y: p.ret3y, ret5y: p.ret5y, dist: p.dist, distCov: p.distCov,
      highlight: p.highlight })),
    ...intervalsTender.map((p) => ({ ticker: p.ticker, name: p.name, wrapper: "Interval",
      ret1y: p.ret1y, ret3y: p.ret3y, ret5y: p.ret5y, dist: p.dist, distCov: p.distCov,
      highlight: p.highlight })),
  ];

  // ── Rank helper ───────────────────────────────────────────────────────────
  // direction "higher": rank 1 = highest value; "lower": rank 1 = lowest.
  function rankIn(value, peers, key, direction) {
    if (value == null) return null;
    const vals = peers.map((p) => p[key]).filter((v) => v != null);
    const sortedDesc = direction === "lower"
      ? vals.slice().sort((a, b) => a - b)
      : vals.slice().sort((a, b) => b - a);
    // rank = 1-based position of value in sorted order
    const rank = sortedDesc.findIndex((v) => v === value) + 1;
    return { value, rank: rank || null, total: vals.length };
  }

  // Convenience: build rank meta for a fund in a universe
  function buildRanks(focal, universe, spec) {
    // spec: { metricKey: { direction, label } }
    const out = {};
    for (const [k, def] of Object.entries(spec)) {
      const r = rankIn(focal[k], universe, k, def.direction);
      if (r) out[k] = { ...r, direction: def.direction, label: def.label };
    }
    return out;
  }

  // ── Build precomputed rank tables for the two focal funds ────────────────
  const ARCC = bdcsTraded.find((p) => p.ticker === "ARCC");
  const CCLFX = intervalsTender.find((p) => p.ticker === "CCLFX");

  // BDC-specific rankings (vs traded BDCs only)
  const ARCC_vsBDC = buildRanks(ARCC, bdcsTraded, {
    prem:       { direction: "neutral", label: "Premium to NAV" },
    leverage:   { direction: "lower",   label: "Leverage" },
    nonAccrual: { direction: "lower",   label: "Non-accrual rate" },
    navGrowth5y:{ direction: "higher",  label: "5Y NAV growth" },
  });
  // Cross-wrapper rankings (returns, dist, coverage — vs ALL credit funds)
  const ARCC_vsAll = buildRanks(ARCC, creditAll, {
    ret1y:    { direction: "higher", label: "1Y total return" },
    ret3y:    { direction: "higher", label: "3Y total return" },
    ret5y:    { direction: "higher", label: "5Y total return" },
    dist:     { direction: "higher", label: "Distribution rate" },
    distCov:  { direction: "higher", label: "Dist coverage" },
  });

  // Interval-specific rankings
  const CCLFX_vsInterval = buildRanks(CCLFX, intervalsTender, {
    stdev:    { direction: "lower",  label: "Realized vol (3Y)" },
    drawdown: { direction: "higher", label: "Max drawdown (3Y)" }, // less negative = better
    prorata:  { direction: "lower",  label: "Pro-rated tenders" },
  });
  const CCLFX_vsAll = buildRanks(CCLFX, creditAll, {
    ret1y:    { direction: "higher", label: "1Y total return" },
    ret3y:    { direction: "higher", label: "3Y total return" },
    ret5y:    { direction: "higher", label: "5Y total return" },
    dist:     { direction: "higher", label: "Distribution rate" },
    distCov:  { direction: "higher", label: "Dist coverage" },
  });

  // ── Expose ────────────────────────────────────────────────────────────────
  window.PEER_UNIVERSE = {
    bdcsTraded,
    intervalsTender,
    creditAll,
    rankIn,
    ranks: {
      ARCC: { vsBDC: ARCC_vsBDC, vsAll: ARCC_vsAll },
      CCLFX: { vsInterval: CCLFX_vsInterval, vsAll: CCLFX_vsAll },
    },
  };
})();
