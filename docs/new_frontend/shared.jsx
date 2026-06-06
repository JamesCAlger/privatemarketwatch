/* eslint-disable */
// Shared data + tiny chart primitives used by every variation.
// Each variation re-skins these via CSS variables / props.

const PMW_DATA = {
  asOf: "Q4 2025",
  indices: [
  { id: "direct-lending", name: "Direct Lending", level: 137.55, ret: 11.2, holdings: 27261, fv: "$426.6B", spark: [100, 101.2, 103.8, 106.4, 109.1, 111.9, 116.4, 120.3, 124.6, 128.7, 132.5, 135.1, 137.55] },
  { id: "preferred-equity", name: "Preferred Equity", level: 103.69, ret: 21.1, holdings: 1267, fv: "$12.9B", spark: [100, 99.4, 97.8, 96.2, 95.1, 94.8, 96.7, 98.9, 100.4, 101.5, 102.3, 103.2, 103.69] },
  { id: "common-equity", name: "Common Equity", level: 241.14, ret: 8.8, holdings: 2938, fv: "$27.9B", spark: [100, 108, 115, 122, 138, 156, 178, 189, 201, 215, 224, 232, 241.14] }],

  topStats: [
  { label: "Indexed Fair Value", value: "$467.3B" },
  { label: "Registered Funds", value: "385" },
  { label: "CIKs with Holdings", value: "283" },
  { label: "Unique Companies", value: "28,378" }],

  perf: { // for Index Performance chart (gross vs net)
    labels: ["Q1'21", "Q3", "Q1'22", "Q3", "Q1'23", "Q3", "Q1'24", "Q3", "Q1'25", "Q3", "Q4'25"],
    gross: [100, 103, 107, 110, 113, 118, 122, 125, 129, 134, 137.55],
    net: [100, 102, 104, 105, 107, 110, 113, 115, 118, 121, 123.4]
  },
  aum: { // stacked area
    labels: ["'19", "'20", "'21", "'22", "'23", "'24", "'25"],
    bdc: [120, 150, 210, 290, 420, 560, 680],
    interval: [35, 50, 70, 95, 120, 140, 150],
    tender: [5, 6, 12, 22, 30, 40, 50]
  },
  // Credit Risk & Distress — quarterly stacked credit stress signals across the
  // BDC Direct Lending universe. Three series in ascending severity:
  //   markedBelowCost — fair value < 90% of cost (early warning)
  //   nonAccrual      — loan not paying interest
  //   deepDistress    — fair value < 80% of par (severe impairment)
  // Each value is % of cumulative portfolio (by fair value).
  creditDistress: {
    labels: ["Q4'22","Q1'23","Q2'23","Q3'23","Q4'23","Q1'24","Q2'24","Q3'24","Q4'24","Q1'25","Q2'25","Q3'25","Q4'25"],
    deepDistress:    [3.3, 2.9, 2.7, 2.4, 2.3, 2.1, 1.9, 1.8, 2.0, 2.1, 2.3, 2.6, 3.0],
    nonAccrual:      [0.5, 0.4, 0.5, 0.4, 0.6, 0.5, 0.7, 0.7, 0.6, 0.9, 1.0, 1.0, 0.8],
    markedBelowCost: [6.7, 5.5, 4.8, 4.2, 3.9, 3.8, 3.4, 3.4, 3.5, 3.5, 3.7, 4.0, 4.3],
  },
  // Median price-to-NAV delta across listed BDCs (same 13 quarters as creditDistress).
  // Positive = premium to NAV, negative = discount. The story: premium evaporated
  // in 2025 as credit stress signals climbed — the market repriced.
  navPriceDelta: {
    labels: ["Q4'22","Q1'23","Q2'23","Q3'23","Q4'23","Q1'24","Q2'24","Q3'24","Q4'24","Q1'25","Q2'25","Q3'25","Q4'25"],
    median: [-2.1, -1.8, 0.5, 2.4, 3.8, 5.2, 6.1, 5.4, 3.2, 1.5, -1.4, -4.6, -7.8],
  },
  // Cross-sectional distribution of premium/discount-to-NAV across listed BDCs, by quarter.
  // Each entry is one quarter's five-number summary used to draw a box-and-whisker:
  //   min  — lowest fund's delta (whisker bottom)
  //   q1   — 25th percentile (box bottom)
  //   med  — median (line through box; mirrors navPriceDelta.median above)
  //   q3   — 75th percentile (box top)
  //   max  — highest fund's delta (whisker top)
  // Story: tight cluster around zero in '22, premium era through '24, sharp re-widening
  // and downward drift in 2025 as credit stress repriced the universe.
  navPriceDeltaQuarterly: [
    { q: "Q4'22", min: -10, q1: -5,  med: -2.1, q3:  1, max:  5 },
    { q: "Q1'23", min:  -9, q1: -5,  med: -1.8, q3:  2, max:  6 },
    { q: "Q2'23", min:  -7, q1: -3,  med:  0.5, q3:  4, max:  8 },
    { q: "Q3'23", min:  -5, q1: -1,  med:  2.4, q3:  6, max:  9 },
    { q: "Q4'23", min:  -4, q1:  1,  med:  3.8, q3:  7, max: 10 },
    { q: "Q1'24", min:  -3, q1:  2,  med:  5.2, q3:  8, max: 11 },
    { q: "Q2'24", min:  -2, q1:  3,  med:  6.1, q3:  9, max: 12 },
    { q: "Q3'24", min:  -3, q1:  2,  med:  5.4, q3:  8, max: 11 },
    { q: "Q4'24", min:  -5, q1:  0,  med:  3.2, q3:  6, max: 10 },
    { q: "Q1'25", min:  -7, q1: -2,  med:  1.5, q3:  5, max:  9 },
    { q: "Q2'25", min: -10, q1: -5,  med: -1.4, q3:  2, max:  6 },
    { q: "Q3'25", min: -14, q1: -9,  med: -4.6, q3: -1, max:  4 },
    { q: "Q4'25", min: -18, q1: -13, med: -7.8, q3: -3, max:  5 },
  ],
  // Distribution of premium/discount-to-NAV across listed BDCs as of Q4 2025.
  // Each bin = 5pp wide. Bins below zero = discount (red); above = premium (gold).
  // Sum to 47 listed BDCs.
  navPriceDistribution: {
    bins: [
      { label: "≤−15%",  count: 4, side: "discount" },
      { label: "−15 to −10", count: 8, side: "discount" },
      { label: "−10 to −5",  count: 12, side: "discount" },
      { label: "−5 to 0",    count: 14, side: "discount" },
      { label: "0 to +5",    count: 6,  side: "premium" },
      { label: "+5 to +10",  count: 2,  side: "premium" },
      { label: ">+10%",     count: 1,  side: "premium" },
    ],
    median: -7.8,
    total: 47,
  },
  // Stress signals by GICS sector. shareAum = % of universe AUM in this sector;
  // stressPct = % of that sector flagged (marked < 90% of cost OR non-accrual).
  // Q4 2025. Healthcare and Software are the conventionally-watched outliers.
  sectorStress: [
    { sector: "Health Care",       shortLabel: "Healthcare", shareAum: 14, stressPct: 6.2 },
    { sector: "Information Tech.", shortLabel: "Software",   shareAum: 22, stressPct: 4.8 },
    { sector: "Real Estate",       shortLabel: "Real Estate", shareAum:  9, stressPct: 4.2 },
    { sector: "Consumer Discr.",   shortLabel: "Cons. Disc.", shareAum:  8, stressPct: 3.8 },
    { sector: "Energy",            shortLabel: "Energy",     shareAum:  4, stressPct: 3.5 },
    { sector: "Comm. Svcs.",       shortLabel: "Comms",      shareAum:  5, stressPct: 2.6 },
    { sector: "Industrials",       shortLabel: "Industrials",shareAum: 16, stressPct: 2.4 },
    { sector: "Financials",        shortLabel: "Financials", shareAum: 12, stressPct: 1.9 },
    { sector: "Materials",         shortLabel: "Materials",  shareAum:  4, stressPct: 1.8 },
    { sector: "Consumer Staples",  shortLabel: "Staples",    shareAum:  6, stressPct: 1.5 },
  ],
  industry: [// holdings-level industry classification
  { sector: "Financials", pct: 6.8, fv: "$47.2B" },
  { sector: "Real Estate", pct: 1.5, fv: "$10.5B" },
  { sector: "Industrials", pct: 1.4, fv: "$9.4B" },
  { sector: "Health Care", pct: 0.9, fv: "$5.9B" },
  { sector: "Information Tech.", pct: 0.7, fv: "$5.0B" },
  { sector: "Consumer Staples", pct: 0.3, fv: "$2.1B" },
  { sector: "Consumer Discr.", pct: 0.3, fv: "$2.0B" },
  { sector: "Communication Svcs.", pct: 0.3, fv: "$1.9B" },
  { sector: "Materials", pct: 0.1, fv: "$1.1B" },
  { sector: "Utilities, Energy", pct: 0.0, fv: "$0.2B" },
  { sector: "Unclassified", pct: 87.8, fv: "$611.5B" }],

  portfolio: [
  { k: "Wtd. Avg. Coupon", v: "8.8%", note: "86% coverage" },
  { k: "Wtd. Avg. Spread", v: "514 bps", note: "64% coverage" },
  { k: "Wtd. Avg. Maturity", v: "4.0 yrs", note: "59% coverage" },
  { k: "First Lien", v: "98.1%", note: "of FV" },
  { k: "Floating Rate", v: "92.2%", note: "of FV" }],

  managers: [
  { name: "Blackstone", pct: 19.1 },
  { name: "Blue Owl", pct: 9.8 },
  { name: "Ares", pct: 8.6 },
  { name: "Cliffwater", pct: 5.7 },
  { name: "HPS", pct: 5.5 },
  { name: "Apollo", pct: 4.3 },
  { name: "Golub Capital", pct: 3.7 },
  { name: "Goldman Sachs", pct: 2.8 },
  { name: "FS KKR", pct: 2.2 },
  { name: "Oaktree", pct: 2.2 },
  { name: "All Others", pct: 36.2 }],

  // Top premium/discount to NAV (mocked from QoQ + NAV signals — illustrative)
  topMovers: {
    premiums: [
    { ticker: "MAIN", name: "Main Street Capital", last: "$56.40", navPx: "$33.33", prem: 69.2 },
    { ticker: "HTGC", name: "Hercules Capital", last: "$18.71", navPx: "$12.13", prem: 54.2 },
    { ticker: "GAIN", name: "Gladstone Investment", last: "$15.41", navPx: "$14.95", prem: 3.1 },
    { ticker: "ARCC", name: "Ares Capital Corp", last: "$20.74", navPx: "$19.94", prem: 4.0 },
    { ticker: "BXSL", name: "Blackstone Sec. Lending", last: "$27.79", navPx: "$26.92", prem: 3.2 }],

    discounts: [
    { ticker: "PSEC", name: "Prospect Capital", last: "$3.85", navPx: "$6.21", disc: -38.0 },
    { ticker: "TPVG", name: "TriplePoint Venture", last: "$6.95", navPx: "$8.73", disc: -20.4 },
    { ticker: "PNNT", name: "PennantPark Investment", last: "$5.78", navPx: "$7.00", disc: -17.4 },
    { ticker: "OFS", name: "OFS Capital", last: "$7.69", navPx: "$9.19", disc: -16.3 },
    { ticker: "MRCC", name: "Monroe Capital", last: "$6.51", navPx: "$7.68", disc: -15.2 }]

  },
  yieldLeaders: [
  { ticker: "GSPM", name: "GS Private Middle Market II", rate: 33.8, type: "BDC" },
  { ticker: "OXSQ", name: "Oxford Square Capital", rate: 26.0, type: "BDC" },
  { ticker: "SXTH", name: "Sixth Street Lending Partners", rate: 25.0, type: "BDC" },
  { ticker: "BRGT", name: "Brightwood Capital I", rate: 24.7, type: "BDC" },
  { ticker: "TPGV", name: "TriplePoint Global Venture", rate: 21.5, type: "BDC" },
  { ticker: "NCBD", name: "Nuveen Churchill BDC V", rate: 20.9, type: "BDC" },
  { ticker: "WTC", name: "Willow Tree Capital", rate: 20.6, type: "BDC" },
  { ticker: "WTI", name: "WTI Fund X", rate: 19.7, type: "BDC" },
  { ticker: "FDPC", name: "Fidelity Private Credit Ctrl.", rate: 19.4, type: "BDC" },
  { ticker: "RAND", name: "Rand Capital", rate: 19.4, type: "BDC" }],

  // Top-10 fund universe sample
  funds: [
  { name: "Blackstone Private Credit Fund", type: "BDC", liq: "Publicly Traded", aum: "$86.0B", nav: "$24.79", dist: "—", qoq: "+1.7%" },
  { name: "Cliffwater Corporate Lending Fund", type: "Interval", liq: "Semi-Liquid", aum: "$56.3B", nav: "$10.83", dist: "—", qoq: "+2.1%" },
  { name: "Owl Rock Core Income Corp.", type: "BDC", liq: "Publicly Traded", aum: "$37.0B", nav: "—", dist: "—", qoq: "+1.6%" },
  { name: "Ares Capital Corp (ARCC)", type: "BDC", liq: "Publicly Traded", aum: "$31.2B", nav: "$19.94", dist: "9.6%", qoq: "+2.0%" },
  { name: "HPS Corporate Lending Fund", type: "BDC", liq: "Publicly Traded", aum: "$26.3B", nav: "$1000.00", dist: "—", qoq: "+2.4%" },
  { name: "Apollo Debt Solutions BDC", type: "BDC", liq: "Publicly Traded", aum: "$25.9B", nav: "—", dist: "—", qoq: "+1.7%" },
  { name: "Ares Strategic Income Fund", type: "BDC", liq: "Publicly Traded", aum: "$22.7B", nav: "$27.48", dist: "—", qoq: "+1.5%" },
  { name: "Victory Portfolios II", type: "Interval", liq: "Semi-Liquid", aum: "$21.6B", nav: "—", dist: "—", qoq: "+2.3%" },
  { name: "Owl Rock Capital Corp (OBDC)", type: "BDC", liq: "Publicly Traded", aum: "$17.2B", nav: "$14.81", dist: "10.0%", qoq: "+2.8%" },
  { name: "Partners Group PE Fund, LLC", type: "Interval", liq: "Semi-Liquid", aum: "$17.0B", nav: "$2.19", dist: "—", qoq: "+0.6%" }],

  // Distribution-rate histogram (approx, illustrative)
  distHist: { bins: ["0-4%", "4-6%", "6-8%", "8-10%", "10-12%", "12-15%", "15-20%", "20%+"], bdc: [8, 14, 22, 38, 30, 22, 14, 8], non: [4, 10, 14, 16, 10, 6, 3, 1] },
  // Leverage histogram
  levHist: { bins: ["0.0", "0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "0.7+"], bdc: [40, 55, 50, 40, 28, 18, 10, 4], non: [85, 55, 28, 16, 8, 5, 2, 1] },
  // Credit risk cumulative bars
  credit: { byCount: { deepDistress: 1.2, nonAccrual: 2.1, belowCost: 4.4 },
    byFV: { deepDistress: 0.8, nonAccrual: 1.5, belowCost: 3.2 } }
};

// ─── Chart primitives (SVG, take color from CSS currentColor + props) ─────────
function PMWSparkline({ data, w = 88, h = 28, stroke = "currentColor", strokeWidth = 1.25, fill = "none" }) {
  const min = Math.min(...data),max = Math.max(...data);
  const pts = data.map((v, i) => {
    const x = i / (data.length - 1) * w;
    const y = h - (v - min) / (max - min || 1) * h;
    return [x, y];
  });
  const d = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
  const dFill = fill !== "none" ? d + ` L ${w} ${h} L 0 ${h} Z` : null;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block", overflow: "visible" }}>
      {dFill && <path d={dFill} fill={fill} opacity="0.25" />}
      <path d={d} fill="none" stroke={stroke} strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round" />
    </svg>);

}

function PMWLineChart({ series, labels, w = 560, h = 220, padding = { t: 12, r: 10, b: 22, l: 36 }, gridColor = "currentColor", gridOpacity = 0.08, yTicks = 4, yFmt = (v) => v.toFixed(0), showLegend = true, legendInline = false }) {
  const all = series.flatMap((s) => s.data);
  const min = Math.min(...all),max = Math.max(...all);
  const pad = (max - min) * 0.1;
  const yMin = Math.floor((min - pad) / 5) * 5;
  const yMax = Math.ceil((max + pad) / 5) * 5;
  const cw = w - padding.l - padding.r;
  const ch = h - padding.t - padding.b;
  const xAt = (i, n) => padding.l + (n <= 1 ? cw / 2 : i / (n - 1) * cw);
  const yAt = (v) => padding.t + ch - (v - yMin) / (yMax - yMin || 1) * ch;
  const ticks = Array.from({ length: yTicks + 1 }, (_, i) => yMin + i / yTicks * (yMax - yMin));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block", fontFamily: "inherit" }}>
        {ticks.map((t, i) =>
        <g key={i}>
            <line x1={padding.l} x2={w - padding.r} y1={yAt(t)} y2={yAt(t)} stroke={gridColor} strokeOpacity={gridOpacity} strokeWidth="1" strokeDasharray={i === 0 ? "0" : "2 4"} />
            <text x={padding.l - 6} y={yAt(t) + 3} textAnchor="end" fontSize="9" fill="currentColor" opacity="0.55">{yFmt(t)}</text>
          </g>
        )}
        {labels.map((lab, i) =>
        <text key={lab + i} x={xAt(i, labels.length)} y={h - 6} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.55">{lab}</text>
        )}
        {series.map((s, si) => {
          const d = s.data.map((v, i) => (i ? "L" : "M") + xAt(i, s.data.length).toFixed(1) + " " + yAt(v).toFixed(1)).join(" ");
          return (
            <g key={si}>
              <path d={d} fill="none" stroke={s.color || "currentColor"} strokeWidth={s.strokeWidth || 1.5} strokeDasharray={s.dash || ""} strokeLinejoin="round" strokeLinecap="round" />
            </g>);

        })}
      </svg>
      {showLegend &&
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 11, opacity: 0.85 }}>
          {series.map((s, i) =>
        <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 14, height: 2, background: s.color || "currentColor", borderTop: s.dash ? `2px dashed ${s.color}` : "none" }} />
              {s.label}
            </span>
        )}
        </div>
      }
    </div>);

}

function PMWStackedArea({ data, w = 560, h = 200, palette = ["#7a3b34", "#b88a5a", "#3f4a3a"], labels, padding = { t: 8, r: 8, b: 22, l: 36 }, yFmt = (v) => `$${Math.round(v)}B` }) {
  const n = data[0].values.length;
  const totals = Array.from({ length: n }, (_, i) => data.reduce((s, d) => s + d.values[i], 0));
  const max = Math.max(...totals);
  const cw = w - padding.l - padding.r,ch = h - padding.t - padding.b;
  const xAt = (i) => padding.l + i / (n - 1) * cw;
  const yAt = (v) => padding.t + ch - v / max * ch;
  // Build cumulative paths
  let cum = Array(n).fill(0);
  const paths = data.map((d, di) => {
    const top = d.values.map((v, i) => cum[i] + v);
    const bottom = cum.slice();
    const path = [
    ...top.map((v, i) => (i ? "L" : "M") + xAt(i).toFixed(1) + " " + yAt(v).toFixed(1)),
    ...bottom.slice().reverse().map((v, i) => "L" + xAt(n - 1 - i).toFixed(1) + " " + yAt(v).toFixed(1)),
    "Z"].
    join(" ");
    cum = top;
    return { d: path, color: palette[di % palette.length], label: d.label };
  });
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block" }}>
        {[0, 0.25, 0.5, 0.75, 1].map((t, i) =>
        <line key={i} x1={padding.l} x2={w - padding.r} y1={padding.t + ch * t} y2={padding.t + ch * t} stroke="currentColor" strokeOpacity="0.08" />
        )}
        {paths.map((p, i) => <path key={i} d={p.d} fill={p.color} opacity="0.85" />)}
        {labels.map((lab, i) =>
        <text key={i} x={xAt(i)} y={h - 6} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.55">{lab}</text>
        )}
        {/* y axis labels */}
        {[0, 0.5, 1].map((t, i) =>
        <text key={i} x={padding.l - 6} y={padding.t + ch * (1 - t) + 3} textAnchor="end" fontSize="9" fill="currentColor" opacity="0.55">
            {yFmt(max * t)}
          </text>
        )}
      </svg>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 11, opacity: 0.85 }}>
        {paths.map((p, i) =>
        <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 10, height: 10, background: p.color }} />{p.label}
          </span>
        )}
      </div>
    </div>);

}

function PMWHBars({ items, max, w = 320, barHeight = 10, gap = 8, accent = "currentColor", labelWidth = 96, valueWidth = 56, valueFmt = (v) => v.toFixed(1) + "%" }) {
  const mx = max ?? Math.max(...items.map((i) => i.pct));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap }}>
      {items.map((it, i) =>
      <div key={i} style={{ display: "grid", gridTemplateColumns: `${labelWidth}px 1fr ${valueWidth}px`, alignItems: "center", gap: 10, fontSize: 12 }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name || it.sector}</span>
          <span style={{ height: barHeight, background: "currentColor", opacity: 0.08, position: "relative", borderRadius: 0 }}>
            <span style={{ position: "absolute", left: 0, top: 0, height: "100%", width: `${it.pct / mx * 100}%`, background: accent }} />
          </span>
          <span style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{valueFmt(it.pct)}</span>
        </div>
      )}
    </div>);

}

function PMWHistogram({ bins, series, w = 320, h = 130, palette = ["#7a3b34", "#b88a5a"], gap = 2, axis = true, showLegend = true }) {
  const max = Math.max(...series.flatMap((s) => s.data));
  const padding = { t: 8, r: 4, b: axis ? 20 : 4, l: 4 };
  const cw = w - padding.l - padding.r,ch = h - padding.t - padding.b;
  const bw = cw / bins.length;
  const sw = (bw - gap * 2) / series.length;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block" }}>
        {series.map((s, si) => s.data.map((v, bi) => {
          const x = padding.l + bi * bw + gap + si * sw;
          const bh = v / max * ch;
          return <rect key={si + "-" + bi} x={x} y={padding.t + ch - bh} width={Math.max(1, sw - 1)} height={bh} fill={palette[si % palette.length]} opacity="0.9" />;
        }))}
        {axis && bins.map((b, i) =>
        <text key={i} x={padding.l + i * bw + bw / 2} y={h - 6} textAnchor="middle" fontSize="8" fill="currentColor" opacity="0.55">{b}</text>
        )}
      </svg>
      {showLegend &&
      <div style={{ display: "flex", gap: 12, fontSize: 11, opacity: 0.85 }}>
          {series.map((s, i) =>
        <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
              <span style={{ width: 9, height: 9, background: palette[i] }} />{s.label}
            </span>
        )}
        </div>
      }
    </div>);

}

function PMWDonut({ items, size = 180, thickness = 22, palette }) {
  const total = items.reduce((s, i) => s + i.pct, 0);
  const cx = size / 2,cy = size / 2,r = (size - thickness) / 2;
  let acc = 0;
  const arcs = items.map((it, i) => {
    const start = acc / total * Math.PI * 2 - Math.PI / 2;
    acc += it.pct;
    const end = acc / total * Math.PI * 2 - Math.PI / 2;
    const large = end - start > Math.PI ? 1 : 0;
    const x1 = cx + r * Math.cos(start),y1 = cy + r * Math.sin(start);
    const x2 = cx + r * Math.cos(end),y2 = cy + r * Math.sin(end);
    const d = `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
    return { d, color: (palette || ["currentColor"])[i % (palette ? palette.length : 1)] };
  });
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
      <circle cx={cx} cy={cy} r={r} fill="none" stroke="currentColor" strokeOpacity="0.08" strokeWidth={thickness} />
      {arcs.map((a, i) => <path key={i} d={a.d} stroke={a.color} strokeWidth={thickness} fill="none" strokeLinecap="butt" />)}
    </svg>);

}

// Image-slot-ish placeholder for charts we don't render
function PMWPlaceholder({ label, h = 200, lineColor = "currentColor", bg = "transparent" }) {
  return (
    <div style={{ position: "relative", height: h, background: bg, border: `1px dashed ${lineColor}`, borderOpacity: 0.3, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "ui-monospace, SFMono-Regular, monospace", fontSize: 11, opacity: 0.65, letterSpacing: "0.06em", textTransform: "uppercase" }}>
      {label}
    </div>);

}

Object.assign(window, { PMW_DATA, PMWSparkline, PMWLineChart, PMWStackedArea, PMWHBars, PMWHistogram, PMWDonut, PMWPlaceholder });