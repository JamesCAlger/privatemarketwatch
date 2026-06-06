/* eslint-disable */
// V2 — Refinements. Parameterized "Institutional Index" homepage.
// Five themes share the SAME layout/structure (dark ticker bar, card grid,
// bordered tables, dark portfolio-characteristics band) but explore different
// palettes and type pairings.

// ─── Themes ───────────────────────────────────────────────────────────────────
const V2_THEMES = {
  navyGold: {
    name: "Navy + Gold",
    label: "V2.1 · Navy + Gold (original)",
    note: "S&P/MSCI-classic. Deep navy header, restrained gold signal accent.",
    bg:       "#fbfaf7",
    surface:  "#ffffff",
    ink:      "#0b1a2c",
    ink2:     "#3b4a5b",
    ink3:     "#6b7280",
    rule:     "#dfe3ea",
    rule2:    "#eef0f4",
    headerBg: "#0b1a2c",
    tickerBg: "#06121f",
    onDarkInk:    "#ffffff",
    onDarkInk2:   "rgba(255,255,255,0.78)",
    onDarkInk3:   "rgba(255,255,255,0.55)",
    onDarkRule:   "rgba(255,255,255,0.06)",
    onDarkRule2:  "rgba(255,255,255,0.14)",
    accent:   "#c7a14a",
    panelBg:  "#0b1a2c",
    green:    "#1f7a4a",
    red:      "#a8362b",
    displayFont: '"IBM Plex Serif","Source Serif 4",Georgia,serif',
    bodyFont:    '"IBM Plex Sans","Inter",system-ui,sans-serif',
    monoFont:    '"IBM Plex Mono",ui-monospace,monospace',
    displayWeight: 500,
  },
  charcoalGold: {
    name: "Charcoal + Gold",
    label: "V2.2 · Charcoal + Gold",
    note: "Slightly warmer, less formal than navy. Same gold signal.",
    bg:       "#f6f4ef",
    surface:  "#ffffff",
    ink:      "#1c1c1a",
    ink2:     "#4a4a46",
    ink3:     "#7a7a73",
    rule:     "#e2dfd6",
    rule2:    "#edebe3",
    headerBg: "#1c1c1a",
    tickerBg: "#121211",
    onDarkInk:   "#ffffff",
    onDarkInk2:  "rgba(255,255,255,0.78)",
    onDarkInk3:  "rgba(255,255,255,0.55)",
    onDarkRule:  "rgba(255,255,255,0.06)",
    onDarkRule2: "rgba(255,255,255,0.14)",
    accent:   "#c7a14a",
    panelBg:  "#1c1c1a",
    green:    "#3e7a4e",
    red:      "#a8463a",
    displayFont: '"IBM Plex Serif","Source Serif 4",Georgia,serif',
    bodyFont:    '"IBM Plex Sans","Inter",system-ui,sans-serif',
    monoFont:    '"IBM Plex Mono",ui-monospace,monospace',
    displayWeight: 500,
  },
  navySage: {
    name: "Navy + Sage",
    label: "V2.3 · Navy + Sage",
    note: "V2 chassis, V4's sage. Calmer, less Wall-Street, more research-house.",
    bg:       "#f7f6f1",
    surface:  "#ffffff",
    ink:      "#0b1a2c",
    ink2:     "#3b4a5b",
    ink3:     "#6b7280",
    rule:     "#dfe1d8",
    rule2:    "#ecede5",
    headerBg: "#0b1a2c",
    tickerBg: "#06121f",
    onDarkInk:   "#ffffff",
    onDarkInk2:  "rgba(255,255,255,0.78)",
    onDarkInk3:  "rgba(255,255,255,0.55)",
    onDarkRule:  "rgba(255,255,255,0.06)",
    onDarkRule2: "rgba(255,255,255,0.14)",
    accent:   "#6e8a6a",
    panelBg:  "#0b1a2c",
    green:    "#3e7a4e",
    red:      "#a8362b",
    displayFont: '"IBM Plex Serif","Source Serif 4",Georgia,serif',
    bodyFont:    '"IBM Plex Sans","Inter",system-ui,sans-serif',
    monoFont:    '"IBM Plex Mono",ui-monospace,monospace',
    displayWeight: 500,
  },
  inkElectric: {
    name: "Ink + Electric Coral",
    label: "V2.4 · Ink + Electric Coral",
    note: "Modern, slightly airy. Near-black header, bright signal accent, Fraunces display.",
    bg:       "#f5f3ee",
    surface:  "#ffffff",
    ink:      "#15171a",
    ink2:     "#4a4d52",
    ink3:     "#7a7d83",
    rule:     "#e1ddd3",
    rule2:    "#ecead0",
    headerBg: "#15171a",
    tickerBg: "#0a0b0c",
    onDarkInk:   "#ffffff",
    onDarkInk2:  "rgba(255,255,255,0.78)",
    onDarkInk3:  "rgba(255,255,255,0.55)",
    onDarkRule:  "rgba(255,255,255,0.06)",
    onDarkRule2: "rgba(255,255,255,0.14)",
    accent:   "#d24a30",
    panelBg:  "#15171a",
    green:    "#2f7a4a",
    red:      "#d24a30",
    displayFont: '"Fraunces","Source Serif 4",Georgia,serif',
    bodyFont:    '"Manrope","Plus Jakarta Sans","Inter",sans-serif',
    monoFont:    '"IBM Plex Mono",ui-monospace,monospace',
    displayWeight: 400,
  },
  creamOxblood: {
    name: "Cream + Oxblood",
    label: "V2.5 · Cream + Oxblood",
    note: "Editorial. Paper cream body, warm-ink header, oxblood signal. Most magazine-feeling.",
    bg:       "#f1ecdf",
    surface:  "#fbf6e9",
    ink:      "#1a140d",
    ink2:     "#4a3f30",
    ink3:     "#7a6f5f",
    rule:     "#cfc4a8",
    rule2:    "#ddd3b9",
    headerBg: "#1a140d",
    tickerBg: "#100c07",
    onDarkInk:   "#f3ede0",
    onDarkInk2:  "rgba(243,237,224,0.85)",
    onDarkInk3:  "rgba(243,237,224,0.6)",
    onDarkRule:  "rgba(243,237,224,0.08)",
    onDarkRule2: "rgba(243,237,224,0.16)",
    accent:   "#9a3324",
    panelBg:  "#1a140d",
    green:    "#3e5a3a",
    red:      "#9a3324",
    displayFont: '"Source Serif 4","Newsreader",Georgia,serif',
    bodyFont:    '"Inter","IBM Plex Sans",system-ui,sans-serif',
    monoFont:    '"IBM Plex Mono",ui-monospace,monospace',
    displayWeight: 600,
  },
};

// ─── Themed homepage component ────────────────────────────────────────────────
function V2Home({ theme: t, returnVariant = "A" }) {
  const S = {
    root:    { background: t.bg, color: t.ink, fontFamily: t.bodyFont, fontSize: 14, width: "100%", minHeight: "100%" },
    display: { fontFamily: t.displayFont, fontWeight: t.displayWeight },
    num:     { fontFamily: t.monoFont, fontVariantNumeric: "tabular-nums" },
    eyebrow: { textTransform: "uppercase", letterSpacing: "0.18em", fontSize: 10, fontWeight: 600, color: t.ink2 },
    eyebrowOnDark: { textTransform: "uppercase", letterSpacing: "0.18em", fontSize: 10, fontWeight: 600, color: t.onDarkInk3 },
    card:    { background: t.surface, border: `1px solid ${t.rule}`, borderRadius: 2 },
  };
  return (
    <div style={S.root}>
      <V2Header t={t} S={S} />
      <V2Hero t={t} S={S} />
      <V2Performance t={t} S={S} returnVariant={returnVariant} />
      <V2AUMExposure t={t} S={S} />
      <V2Characteristics t={t} S={S} />
      <V2Movers t={t} S={S} />
      <V2ManagerDist t={t} S={S} />
      <V2Universe t={t} S={S} />
      <V2Footer t={t} S={S} />
    </div>
  );
}

function V2Header({ t, S }) {
  return (
    <div style={{ background: t.headerBg, color: t.onDarkInk2 }}>
      <div style={{ padding: "10px 56px", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: `1px solid ${t.onDarkRule}`, fontSize: 11, letterSpacing: "0.06em" }}>
        <span style={{ color: t.onDarkInk3 }}>As of Q4 2025 · Data derived from mandatory SEC filings</span>
        <div style={{ display: "flex", gap: 18, color: t.onDarkInk2 }}>
          <span>EN ▾</span>
          <span>For Advisors</span>
          <span>For Institutions</span>
          <span>Login</span>
        </div>
      </div>
      <div style={{ padding: "20px 56px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
          <div style={{ ...S.display, fontSize: 26, letterSpacing: "-0.005em", color: t.onDarkInk, fontWeight: 500 }}>Metris Lens</div>
          <div style={{ fontSize: 10, letterSpacing: "0.2em", textTransform: "uppercase", color: t.accent }}>Data · Indices · Research</div>
        </div>
        <div style={{ display: "flex", gap: 28, alignItems: "center", fontSize: 13, fontWeight: 500 }}>
          {[
            { label: "Funds",       href: "index.html" },
            { label: "Indices",     href: "Index Detail - Direct Lending.html" },
            { label: "Methodology", href: "Methodology.html" },
            { label: "About",       href: "About.html" },
            { label: "Data",        href: "Data.html" },
          ].map((m, i) => (
            <a key={m.label} href={m.href} style={{ textDecoration: "none", paddingBottom: 4, borderBottom: i === 0 ? `2px solid ${t.accent}` : "2px solid transparent", color: i === 0 ? t.onDarkInk : t.onDarkInk2 }}>{m.label}</a>
          ))}
          <a href="Data.html" style={{ padding: "8px 16px", border: `1px solid ${t.accent}`, color: t.accent, fontSize: 12, letterSpacing: "0.08em", textTransform: "uppercase", textDecoration: "none" }}>Subscribe →</a>
        </div>
      </div>
      {/* Ticker bar */}
      <div style={{ background: t.tickerBg, padding: "0 56px", display: "grid", gridTemplateColumns: "auto repeat(3, 1fr)", alignItems: "stretch", borderTop: `1px solid ${t.onDarkRule}` }}>
        <div style={{ padding: "10px 18px 10px 0", color: t.accent, ...S.eyebrowOnDark, color: t.accent, letterSpacing: "0.22em", display: "flex", alignItems: "center", borderRight: `1px solid ${t.onDarkRule2}` }}>
          PMW Indices
        </div>
        {PMW_DATA.indices.map((idx, i) => {
          const HREF = {
            "direct-lending":   "Index Detail - Direct Lending.html",
            "preferred-equity": "Index Detail - Preferred Equity.html",
            "common-equity":    "Index Detail - Common Equity.html",
          }[idx.id];
          return (
          <a key={idx.id} href={HREF} style={{ textDecoration: "none", padding: "10px 18px", borderRight: i < 2 ? `1px solid ${t.onDarkRule2}` : "none", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 14 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
              <span style={{ fontSize: 10, letterSpacing: "0.16em", textTransform: "uppercase", color: t.onDarkInk3 }}>{idx.name}</span>
              <span style={{ ...S.num, fontSize: 18, color: t.onDarkInk, fontWeight: 500 }}>{idx.level.toFixed(2)}</span>
            </div>
            <div style={{ color: idx.ret >= 0 ? "#7fd6a1" : "#e08c83", display: "flex", alignItems: "center", gap: 8 }}>
              <PMWSparkline data={idx.spark} w={66} h={20} stroke="currentColor" strokeWidth={1.25} />
              <span style={{ ...S.num, fontSize: 13, fontWeight: 600 }}>{idx.ret >= 0 ? "+" : ""}{idx.ret.toFixed(1)}%</span>
            </div>
          </a>
          );
        })}
      </div>
    </div>
  );
}

function V2Hero({ t, S }) {
  return (
    <div style={{ padding: "44px 56px 28px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 56, alignItems: "start" }}>
        <div>
          <h1 style={{ ...S.display, fontSize: 72, lineHeight: 1.02, margin: "0 0 22px", letterSpacing: "-0.028em", color: t.ink }}>
            The data platform <br/>
            for private markets.
          </h1>
          <p style={{ fontSize: 17, lineHeight: 1.55, color: t.ink2, maxWidth: 620, margin: 0 }}>
            The largest publicly available dataset of <strong style={{ color: t.ink }}>BDCs, interval funds, and tender offer funds</strong>. Covering the investor-accessible side of private credit and equity, built from mandatory SEC filings.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 24 }}>
            <a href="#universe" style={{ padding: "12px 22px", background: t.headerBg, color: t.onDarkInk, fontSize: 13, fontWeight: 500, letterSpacing: "0.06em", textDecoration: "none" }}>Browse the fund universe →</a>
            <a href="Methodology.html" style={{ padding: "12px 22px", border: `1px solid ${t.rule}`, color: t.ink, fontSize: 13, fontWeight: 500, letterSpacing: "0.06em", textDecoration: "none" }}>View methodology ↗</a>
          </div>
        </div>
        <div style={{ ...S.card, padding: 24, position: "relative" }}>
          <div style={{ ...S.eyebrow, color: t.accent, marginBottom: 12 }}>Universe coverage · Q4 2025</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", rowGap: 18, columnGap: 18 }}>
            {PMW_DATA.topStats.map((s, i) => (
              <div key={i} style={{ borderTop: `1px solid ${t.rule2}`, paddingTop: 10 }}>
                <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.12em", color: t.ink3 }}>{s.label}</div>
                <div style={{ ...S.display, fontSize: 30, color: t.ink, letterSpacing: "-0.02em", marginTop: 4 }}>{s.value}</div>
              </div>
            ))}
          </div>
          <div style={{ borderTop: `1px solid ${t.rule2}`, paddingTop: 12, marginTop: 16, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={{ fontSize: 11, color: t.ink3 }}>Universe coverage by AUM</span>
            <span style={{ ...S.num, fontSize: 13, color: t.green }}>96.4%</span>
          </div>
          <div style={{ height: 6, background: t.rule2, marginTop: 8, position: "relative" }}>
            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: "96%", background: t.accent }} />
          </div>
        </div>
      </div>
    </div>
  );
}

// Return summary table — three color/hierarchy variants share the same data + layout.
// Headers always sit at the top of the table.
//   A · Monochrome      — all ink, hierarchy via weight & size. Editorial.
//   B · Accent-led Net  — Net highlighted in theme accent (the headline number).
//   C · Headline + dim  — Net big & bold, Gross dimmed & smaller (strict hierarchy).
function V2ReturnSummary({ t, S, variant = "A", showCaption = true }) {
  const rows = [
    { k: "1 Year",              n: "+8.4%",  g: "+11.2%", d: "2.8 pp"  },
    { k: "3 Year (annualized)", n: "+7.6%",  g: "+9.8%",  d: "2.2 pp"  },
    { k: "5 Year (annualized)", n: "+5.7%",  g: "+7.6%",  d: "1.9 pp"  },
    { k: "Since inception",     n: "+23.40%",g: "+37.55%",d: "14.15 pp"},
  ];
  // Per-variant cell styles
  const V = {
    A: { // Monochrome
      netColor: t.ink,   netSize: 16, netWeight: 600,
      grsColor: t.ink2,  grsSize: 16, grsWeight: 400,
      feeColor: t.ink3,  feeSize: 13, feeWeight: 400,
      caption: "All ink — hierarchy via weight",
    },
    B: { // Accent-led Net
      netColor: t.accent, netSize: 16, netWeight: 600,
      grsColor: t.ink,    grsSize: 16, grsWeight: 400,
      feeColor: t.ink3,   feeSize: 13, feeWeight: 400,
      caption: "Net in brand accent — signals the headline",
    },
    C: { // Headline + dim
      netColor: t.ink,   netSize: 19, netWeight: 600,
      grsColor: t.ink3,  grsSize: 13, grsWeight: 400,
      feeColor: t.ink3,  feeSize: 12, feeWeight: 400,
      caption: "Strict hierarchy — Net is the answer",
    },
  }[variant];

  const cols = "1.4fr 1fr 1fr 0.9fr";

  return (
    <div>
      <div style={{ ...S.eyebrow }}>Total return summary</div>
      <div style={{ display: "flex", flexDirection: "column", marginTop: 14 }}>
        {/* Header row — ON TOP */}
        <div style={{
          display: "grid", gridTemplateColumns: cols, columnGap: 8,
          color: t.ink3, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.12em",
          paddingBottom: 8, borderBottom: `1px solid ${t.rule}`,
        }}>
          <span></span>
          <span style={{ textAlign: "right" }}>Net</span>
          <span style={{ textAlign: "right" }}>Gross</span>
          <span style={{ textAlign: "right" }}>Fee drag</span>
        </div>
        {rows.map(r => (
          <div key={r.k} style={{ display: "grid", gridTemplateColumns: cols, alignItems: "baseline", padding: "12px 0", borderBottom: `1px solid ${t.rule2}`, columnGap: 8 }}>
            <span style={{ fontSize: 12, color: t.ink2 }}>{r.k}</span>
            <span style={{ ...S.num, fontSize: V.netSize, color: V.netColor, fontWeight: V.netWeight, textAlign: "right" }}>{r.n}</span>
            <span style={{ ...S.num, fontSize: V.grsSize, color: V.grsColor, fontWeight: V.grsWeight, textAlign: "right" }}>{r.g}</span>
            <span style={{ ...S.num, fontSize: V.feeSize, color: V.feeColor, fontWeight: V.feeWeight, textAlign: "right" }}>−{r.d}</span>
          </div>
        ))}
        {showCaption && (
          <div style={{ marginTop: 10, fontSize: 10, color: t.ink3, textTransform: "uppercase", letterSpacing: "0.12em" }}>
            Variant {variant} · {V.caption}
          </div>
        )}
      </div>
    </div>
  );
}

function V2Performance({ t, S, returnVariant = "A" }) {
  return (
    <div style={{ padding: "8px 56px 32px" }}>
      <div style={{ ...S.card, padding: 28, display: "grid", gridTemplateColumns: "3fr 2fr", gap: 36 }}>
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <h2 style={{ ...S.display, fontSize: 28, margin: 0, letterSpacing: "-0.015em" }}>
              Index performance <span style={{ color: t.ink3, fontWeight: 400 }}>· Direct Lending</span>
            </h2>
            <div style={{ display: "flex", gap: 6, fontSize: 11, letterSpacing: "0.06em" }}>
              {["1Y","3Y","5Y","Since Incep."].map((tg, i) => (
                <span key={tg} style={{ padding: "6px 12px", border: `1px solid ${i === 3 ? t.ink : t.rule}`, color: i === 3 ? t.onDarkInk : t.ink2, background: i === 3 ? t.headerBg : "transparent" }}>{tg}</span>
              ))}
            </div>
          </div>
          <div style={{ color: t.ink, marginTop: 20 }}>
            <PMWLineChart
              w={620} h={240}
              labels={PMW_DATA.perf.labels}
              series={[
                { label: "Position-Level (Gross)", data: PMW_DATA.perf.gross, color: t.headerBg, strokeWidth: 2 },
                { label: "Fund-Level (Net)",        data: PMW_DATA.perf.net,   color: t.accent,   strokeWidth: 2 },
              ]}
            />
          </div>
        </div>
        <div style={{ borderLeft: `1px solid ${t.rule}`, paddingLeft: 28 }}>
          <V2ReturnSummary t={t} S={S} variant={returnVariant} showCaption={false} />
        </div>
      </div>
    </div>
  );
}

// Standalone artboard component for comparing the three return-summary variants.
function V2ReturnSummaryCard({ theme: t, variant }) {
  const S = {
    card: { background: t.surface, border: `1px solid ${t.rule}` },
    eyebrow: { fontFamily: t.bodyFont, fontSize: 10, fontWeight: 600, letterSpacing: "0.16em", textTransform: "uppercase", color: t.ink2 },
    num:     { fontFamily: t.monoFont, fontVariantNumeric: "tabular-nums" },
  };
  return (
    <div style={{ background: t.bg, color: t.ink, fontFamily: t.bodyFont, padding: 32, width: "100%", height: "100%", boxSizing: "border-box" }}>
      <div style={{ ...S.card, padding: 24 }}>
        <V2ReturnSummary t={t} S={S} variant={variant} showCaption />
      </div>
    </div>
  );
}

// Stacked-bar chart for the Credit Risk & Distress panel.
// Severity gradient (red → orange → gold). Order in `series` is bottom → top.
function V2StackedBars({ labels, series, w = 1080, h = 220, padding = { t: 14, r: 12, b: 26, l: 36 }, yMax, yTicks = 4, gridColor = "currentColor", gridOpacity = 0.08, barWidthFactor = 0.62, barMaxWidth = 64 }) {
  const n = labels.length;
  const totals = labels.map((_, i) => series.reduce((s, ser) => s + ser.data[i], 0));
  const max = yMax ?? Math.ceil(Math.max(...totals) * 1.15);
  const cw = w - padding.l - padding.r;
  const ch = h - padding.t - padding.b;
  const groupW = cw / n;
  const barW = Math.min(groupW * barWidthFactor, barMaxWidth);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block" }}>
      {/* Y gridlines + ticks */}
      {Array.from({ length: yTicks + 1 }, (_, i) => {
        const v = max * i / yTicks;
        const y = padding.t + ch - (v / max) * ch;
        return (
          <g key={i}>
            <line x1={padding.l} x2={padding.l + cw} y1={y} y2={y} stroke={gridColor} strokeOpacity={gridOpacity} />
            <text x={padding.l - 8} y={y + 3} textAnchor="end" fontSize="10" fill="currentColor" opacity="0.55">{v.toFixed(0)}%</text>
          </g>
        );
      })}
      {/* Stacked bars */}
      {labels.map((lab, i) => {
        const cx = padding.l + i * groupW + groupW / 2;
        let yCursor = padding.t + ch;
        return (
          <g key={lab}>
            {series.map((ser, si) => {
              const v = ser.data[i];
              const bh = (v / max) * ch;
              yCursor -= bh;
              return <rect key={si} x={cx - barW / 2} y={yCursor} width={barW} height={bh} fill={ser.color} />;
            })}
            <text x={cx} y={h - 8} textAnchor="middle" fontSize="10" fill="currentColor" opacity="0.6">{lab}</text>
          </g>
        );
      })}
    </svg>
  );
}

// Box-and-whisker per quarter. Each "candle" shows the cross-sectional distribution
// of premium/discount-to-NAV across the listed BDC universe at that quarter end.
//   whisker:  min → max
//   box:      Q1 → Q3 (IQR)
//   tick:     median
// A bold zero line cuts across the chart; the discount zone gets a subtle wash
// so above/below NAV reads instantly.
function V2NavBoxRange({ quarters, w = 520, h = 240, padding = { t: 22, r: 14, b: 32, l: 32 }, boxColor, medianColor, washColor, ruleColor }) {
  const allMin = Math.min(...quarters.map(q => q.min));
  const allMax = Math.max(...quarters.map(q => q.max));
  const yMin = Math.floor(allMin / 5) * 5;
  const yMax = Math.ceil(allMax / 5) * 5;
  const cw = w - padding.l - padding.r;
  const ch = h - padding.t - padding.b;
  const yAt = (v) => padding.t + ch - ((v - yMin) / (yMax - yMin)) * ch;
  const zeroY = yAt(0);
  const groupW = cw / quarters.length;
  const boxW = Math.min(groupW * 0.5, 22);
  const yTicks = [];
  for (let v = yMin; v <= yMax; v += 5) yTicks.push(v);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block" }}>
      {/* Discount-zone wash — "below water" */}
      <rect x={padding.l} y={zeroY} width={cw} height={padding.t + ch - zeroY} fill={washColor} />
      {/* Gridlines + y ticks */}
      {yTicks.map(v => (
        <g key={v}>
          <line x1={padding.l} x2={padding.l + cw} y1={yAt(v)} y2={yAt(v)} stroke="currentColor" strokeOpacity={v === 0 ? 0 : 0.06} />
          <text x={padding.l - 6} y={yAt(v) + 3} textAnchor="end" fontSize="10" fill="currentColor" opacity="0.55">{v > 0 ? `+${v}` : v}%</text>
        </g>
      ))}
      {/* Bold zero divider */}
      <line x1={padding.l} x2={padding.l + cw} y1={zeroY} y2={zeroY} stroke={ruleColor} strokeOpacity="0.9" strokeWidth="1.5" />
      <text x={padding.l + cw + 2} y={zeroY + 3} fontSize="10" fill={ruleColor} opacity="0.85" fontWeight="600">NAV</text>
      {/* Boxes */}
      {quarters.map((q, i) => {
        const cx = padding.l + i * groupW + groupW / 2;
        const yMaxV = yAt(q.max);
        const yMinV = yAt(q.min);
        const yQ3   = yAt(q.q3);
        const yQ1   = yAt(q.q1);
        const yMed  = yAt(q.med);
        return (
          <g key={q.q}>
            {/* Whisker line */}
            <line x1={cx} x2={cx} y1={yMaxV} y2={yMinV} stroke={boxColor} strokeOpacity="0.55" strokeWidth="1" />
            {/* Whisker caps */}
            <line x1={cx - boxW / 4} x2={cx + boxW / 4} y1={yMaxV} y2={yMaxV} stroke={boxColor} strokeOpacity="0.55" strokeWidth="1" />
            <line x1={cx - boxW / 4} x2={cx + boxW / 4} y1={yMinV} y2={yMinV} stroke={boxColor} strokeOpacity="0.55" strokeWidth="1" />
            {/* IQR box */}
            <rect x={cx - boxW / 2} y={yQ3} width={boxW} height={yQ1 - yQ3} fill={boxColor} fillOpacity="0.85" />
            {/* Median tick (accent color, sits across the box) */}
            <line x1={cx - boxW / 2 - 2} x2={cx + boxW / 2 + 2} y1={yMed} y2={yMed} stroke={medianColor} strokeWidth="2.5" />
            {/* Quarter label */}
            <text x={cx} y={h - 10} textAnchor="middle" fontSize="10" fill="currentColor" opacity="0.6">{q.q}</text>
          </g>
        );
      })}
    </svg>
  );
}

function V2NavPriceDelta({ t, S }) {
  const dist = PMW_DATA.navPriceDistribution;
  const quarters = PMW_DATA.navPriceDeltaQuarterly;
  const latest = quarters[quarters.length - 1];
  return (
    <div style={{ ...S.card, padding: 28 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 16 }}>
        <h3 style={{ ...S.display, fontSize: 22, margin: 0, letterSpacing: "-0.01em" }}>Premium / discount to NAV</h3>
        <div style={{ ...S.num, fontSize: 22, color: t.ink, fontWeight: 600, textAlign: "right" }}>
          {latest.med > 0 ? "+" : ""}{latest.med.toFixed(1)}%
          <div style={{ fontSize: 10, color: t.ink3, letterSpacing: "0.1em", textTransform: "uppercase", fontWeight: 400 }}>median, {latest.q}</div>
        </div>
      </div>
      <div style={{ fontSize: 12, color: t.ink3, marginTop: 8, marginBottom: 6 }}>Cross-sectional distribution of {dist.total} listed BDCs · 13-quarter history · box = IQR, whisker = range</div>
      <div style={{ color: t.ink2 }}>
        <V2NavBoxRange quarters={quarters} boxColor={t.ink} medianColor={t.accent} ruleColor={t.ink} washColor={`color-mix(in oklch, ${t.ink} 5%, ${t.surface})`} w={540} h={240} />
      </div>
    </div>
  );
}

// Scatter: sector AUM share (x) vs. stress rate (y).
function V2SectorScatter({ t, S, points, w = 520, h = 220, padding = { t: 18, r: 16, b: 36, l: 44 }, highlightColor, baseColor }) {
  const xs = points.map(p => p.shareAum);
  const ys = points.map(p => p.stressPct);
  const xMax = Math.ceil(Math.max(...xs) / 5) * 5 + 2;
  const yMax = Math.ceil(Math.max(...ys));
  const cw = w - padding.l - padding.r;
  const ch = h - padding.t - padding.b;
  const xAt = (v) => padding.l + (v / xMax) * cw;
  const yAt = (v) => padding.t + ch - (v / yMax) * ch;
  const xTicks = [0, xMax / 4, xMax / 2, (xMax / 4) * 3, xMax];
  const yTicks = Array.from({ length: 5 }, (_, i) => (yMax / 4) * i);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block" }}>
      {yTicks.map((v, i) => (
        <g key={"y" + i}>
          <line x1={padding.l} x2={padding.l + cw} y1={yAt(v)} y2={yAt(v)} stroke="currentColor" strokeOpacity="0.07" />
          <text x={padding.l - 8} y={yAt(v) + 3} textAnchor="end" fontSize="10" fill="currentColor" opacity="0.55">{v.toFixed(1)}%</text>
        </g>
      ))}
      {xTicks.map((v, i) => (
        <g key={"x" + i}>
          <line x1={xAt(v)} x2={xAt(v)} y1={padding.t} y2={padding.t + ch} stroke="currentColor" strokeOpacity="0.04" />
          <text x={xAt(v)} y={h - 18} textAnchor="middle" fontSize="10" fill="currentColor" opacity="0.55">{v.toFixed(0)}%</text>
        </g>
      ))}
      <text x={padding.l + cw / 2} y={h - 4} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.5" style={{ letterSpacing: "0.1em", textTransform: "uppercase" }}>Sector share of universe AUM →</text>
      <text x={12} y={padding.t + ch / 2} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.5" style={{ letterSpacing: "0.1em", textTransform: "uppercase" }} transform={`rotate(-90 12 ${padding.t + ch / 2})`}>↑ Stress rate</text>
      {points.map((p) => {
        const isHi = p.highlight;
        const color = isHi ? highlightColor : baseColor;
        const r = isHi ? 7 : 5;
        return (
          <g key={p.sector}>
            <circle cx={xAt(p.shareAum)} cy={yAt(p.stressPct)} r={r} fill={color} fillOpacity={isHi ? 0.85 : 0.55} stroke={color} strokeWidth={isHi ? 1.5 : 0.5} />
            <text x={xAt(p.shareAum) + r + 4} y={yAt(p.stressPct) + 3} fontSize="10" fill="currentColor" opacity={isHi ? 0.9 : 0.65} fontWeight={isHi ? 600 : 400}>{p.shortLabel}</text>
          </g>
        );
      })}
    </svg>
  );
}

function V2StressBySector({ t, S }) {
  const points = PMW_DATA.sectorStress.map(p => ({
    ...p,
    highlight: p.sector === "Health Care" || p.sector === "Information Tech.",
  }));
  return (
    <div style={{ ...S.card, padding: 28 }}>
      <h3 style={{ ...S.display, fontSize: 22, margin: 0, letterSpacing: "-0.01em" }}>Stress by sector</h3>
      <div style={{ fontSize: 12, color: t.ink3, marginTop: 8, marginBottom: 6 }}>% of holdings marked below cost or on non-accrual · Q4 2025</div>
      <div style={{ color: t.ink2 }}>
        <V2SectorScatter t={t} S={S} points={points} w={520} h={200} baseColor={t.ink2} highlightColor={t.accent} />
      </div>
    </div>
  );
}

function V2CreditDistress({ t, S }) {
  const cd = PMW_DATA.creditDistress;
  // Severity ramp in the ink family. Darkest = most severe (top of stack).
  // Single-hue value ramp is the textbook encoding for monotonic ordinal data;
  // keeps the chart on-palette and lets total stack height read first.
  const deepColor  = t.ink;
  const midColor   = `color-mix(in oklch, ${t.ink} 55%, ${t.surface})`;
  const lightColor = `color-mix(in oklch, ${t.ink} 22%, ${t.surface})`;
  const latest = cd.labels.length - 1;
  const yearAgo = latest - 4;
  const latestTotal = cd.deepDistress[latest] + cd.nonAccrual[latest] + cd.markedBelowCost[latest];
  const yearAgoTotal = cd.deepDistress[yearAgo] + cd.nonAccrual[yearAgo] + cd.markedBelowCost[yearAgo];
  const delta = latestTotal - yearAgoTotal;
  const series = [
    { label: "Deep Distress (<80% par)", data: cd.deepDistress,    color: deepColor },
    { label: "Non-Accrual",               data: cd.nonAccrual,      color: midColor },
    { label: "Marked Below Cost (<90%)",  data: cd.markedBelowCost, color: lightColor },
  ];
  return (
    <div style={{ ...S.card, padding: 28 }}>
      {/* Header row — title left, latest-quarter callout right (matches Performance / NAV panels) */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 24 }}>
        <h3 style={{ ...S.display, fontSize: 24, margin: 0, letterSpacing: "-0.01em" }}>Credit stress, by quarter</h3>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <div style={{ ...S.num, fontSize: 26, color: t.ink, fontWeight: 600, lineHeight: 1 }}>
            {latestTotal.toFixed(1)}%
          </div>
          <div style={{ fontSize: 10, color: t.ink3, letterSpacing: "0.1em", textTransform: "uppercase", marginTop: 6 }}>
            of fair value flagged · Q4'25
          </div>
          <div style={{ fontSize: 11, color: t.ink2, marginTop: 4, ...S.num }}>
            {delta > 0 ? "+" : "−"}{Math.abs(delta).toFixed(1)} pp YoY
          </div>
        </div>
      </div>
      {/* Legend row — sits between header and chart, like a sub-caption */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 16, marginBottom: 4 }}>
        <div style={{ fontSize: 12, color: t.ink3 }}>Cumulative % of fair value showing each signal · 13-quarter history</div>
        <div style={{ display: "flex", gap: 16, fontSize: 11, color: t.ink2 }}>
          {[...series].reverse().map(s => (
            <span key={s.label} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 9, height: 9, background: s.color, display: "inline-block", border: `1px solid ${t.rule}` }} />
              {s.label}
            </span>
          ))}
        </div>
      </div>
      {/* Chart */}
      <div style={{ color: t.ink2, marginTop: 8 }}>
        <V2StackedBars labels={cd.labels} series={series} w={1080} h={200} yMax={10} barWidthFactor={0.62} />
      </div>
      {/* Footnote — sourcing + universe context */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginTop: 6, paddingTop: 12, borderTop: `1px solid ${t.rule2}`, fontSize: 12, color: t.ink3 }}>
        <span>Universe AUM <span style={{ ...S.num, color: t.ink2 }}>$830.6B</span> (+18% YoY) across 47 listed and unlisted BDC vehicles.</span>
        <span>Source: SEC 10-K / 10-Q filings</span>
      </div>
    </div>
  );
}

function V2AUMExposure({ t, S }) {
  const sectors = PMW_DATA.industry.filter(s => s.sector !== "Unclassified");
  const top5Share = (arr) => {
    const total = arr.reduce((s, x) => s + x.pct, 0);
    const top5 = [...arr].sort((a, b) => b.pct - a.pct).slice(0, 5).reduce((s, x) => s + x.pct, 0);
    return total ? (top5 / total) * 100 : 0;
  };
  const sectorTop5 = top5Share(sectors);
  const managerTop5 = top5Share(PMW_DATA.managers);
  return (
    <div style={{ padding: "0 56px 32px", display: "grid", gap: 24 }}>
      {/* AUM composition pair — sits directly under returns so universe scale + concentration are seen before credit stress drilldowns */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 24 }}>
        <div style={{ ...S.card, padding: 28 }}>
          <h3 style={{ ...S.display, fontSize: 22, margin: 0, letterSpacing: "-0.01em" }}>Industry exposure</h3>
          <div style={{ fontSize: 12, color: t.ink3, marginTop: 8, marginBottom: 12 }}>{sectors.length} GICS sectors · share of holdings AUM</div>
          <V2ProportionDonut items={sectors} labelKey="sector" label="Sectors" centerStat={{ label: "Top 5", value: sectorTop5.toFixed(0) + "%", note: "of holdings" }} t={t} S={S} />
          <div style={{ marginTop: 16, paddingTop: 12, borderTop: `1px solid ${t.rule2}`, fontSize: 11, color: t.ink3 }}>Reconciled BDC filings + holdings-level N-PORT.</div>
        </div>
        <div style={{ ...S.card, padding: 28 }}>
          <h3 style={{ ...S.display, fontSize: 22, margin: 0, letterSpacing: "-0.01em" }}>Manager concentration</h3>
          <div style={{ fontSize: 12, color: t.ink3, marginTop: 8, marginBottom: 12 }}>Top 10 managers · share of universe AUM</div>
          <V2ProportionDonut items={PMW_DATA.managers} labelKey="name" label="Managers" centerStat={{ label: "Top 5", value: managerTop5.toFixed(0) + "%", note: "of universe AUM" }} t={t} S={S} />
          <div style={{ marginTop: 16, paddingTop: 12, borderTop: `1px solid ${t.rule2}`, fontSize: 11, color: t.ink3 }}>Combined indices · top 10 managers.</div>
        </div>
      </div>
      <V2CreditDistress t={t} S={S} />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 24 }}>
        <V2NavPriceDelta t={t} S={S} />
        <V2StressBySector t={t} S={S} />
      </div>
    </div>
  );
}

function V2Characteristics({ t, S }) {
  return (
    <div style={{ padding: "0 56px 32px" }}>
      <div style={{ background: t.panelBg, color: t.onDarkInk, padding: "32px 28px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 32, alignItems: "center" }}>
          <div>
            <div style={{ color: t.accent, textTransform: "uppercase", letterSpacing: "0.18em", fontSize: 10, fontWeight: 600 }}>Portfolio Characteristics</div>
            <div style={{ ...S.display, fontSize: 26, marginTop: 6, maxWidth: 240, lineHeight: 1.1 }}>Direct Lending positions as of Q4 2025.</div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)" }}>
            {PMW_DATA.portfolio.map((p, i) => (
              <div key={p.k} style={{ borderLeft: `1px solid ${t.onDarkRule2}`, padding: "0 20px" }}>
                <div style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: t.onDarkInk2 }}>{p.k}</div>
                <div style={{ ...S.num, fontSize: 36, color: t.accent, fontWeight: 500, marginTop: 6 }}>{p.v}</div>
                <div style={{ fontSize: 11, color: t.onDarkInk3 }}>{p.note}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function V2Movers({ t, S }) {
  const Cell = ({ heading, color, items, valFn }) => (
    <div style={{ ...S.card, padding: 24 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <span style={{ width: 8, height: 8, background: color, display: "inline-block" }} />
        <span style={{ ...S.eyebrow, color: t.ink }}>{heading}</span>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${t.rule}` }}>
            <th style={{ ...S.eyebrow, textAlign: "left", padding: "8px 14px 8px 0", color: t.ink3 }}>Ticker</th>
            <th style={{ ...S.eyebrow, textAlign: "left", padding: "8px 18px 8px 0", color: t.ink3 }}>Name</th>
            <th style={{ ...S.eyebrow, textAlign: "right", padding: "8px 18px 8px 0", color: t.ink3 }}>Last</th>
            <th style={{ ...S.eyebrow, textAlign: "right", padding: "8px 18px 8px 0", color: t.ink3 }}>NAV</th>
            <th style={{ ...S.eyebrow, textAlign: "right", padding: "8px 0", color: t.ink3 }}>± NAV</th>
          </tr>
        </thead>
        <tbody>
          {items.map((m, i) => (
            <tr key={m.ticker} style={{ borderBottom: `1px solid ${t.rule2}` }}>
              <td style={{ padding: "14px 14px 14px 0", fontWeight: 600, ...S.num }}>{m.ticker}</td>
              <td style={{ padding: "14px 18px 14px 0", color: t.ink2 }}>{m.name}</td>
              <td style={{ ...S.num, padding: "14px 18px 14px 0", textAlign: "right" }}>{m.last}</td>
              <td style={{ ...S.num, padding: "14px 18px 14px 0", textAlign: "right" }}>{m.navPx}</td>
              <td style={{ ...S.num, padding: "14px 0", textAlign: "right", color, fontWeight: 600 }}>{valFn(m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
  return (
    <div style={{ padding: "0 56px 32px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 24 }}>
        <Cell heading="Top Premiums to NAV" color={t.green} items={PMW_DATA.topMovers.premiums} valFn={m => `+${m.prem.toFixed(1)}%`} />
        <Cell heading="Top Discounts to NAV" color={t.red}   items={PMW_DATA.topMovers.discounts} valFn={m => `${m.disc.toFixed(1)}%`} />
        <div style={{ ...S.card, padding: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <span style={{ width: 8, height: 8, background: t.accent }} />
            <span style={{ ...S.eyebrow }}>Yield Leaderboard</span>
          </div>
          <PMWHBars
            items={PMW_DATA.yieldLeaders.slice(0, 8).map(y => ({ name: y.name.length > 24 ? y.name.slice(0, 22) + "…" : y.name, pct: y.rate }))}
            accent={t.accent}
            labelWidth={140}
            valueWidth={56}
            barHeight={9}
            gap={9}
          />
        </div>
      </div>
    </div>
  );
}

function V2ManagerDist({ t, S }) {
  return (
    <div style={{ padding: "0 56px 32px" }}>
      <div style={{ ...S.card, padding: 28 }}>
        <h3 style={{ ...S.display, fontSize: 24, margin: 0, letterSpacing: "-0.01em" }}>Distributions &amp; leverage</h3>
        <div style={{ fontSize: 12, color: t.ink3, marginTop: 8, marginBottom: 14 }}>Liquid (listed BDCs) vs. semi-liquid (interval + tender) · medians shown.</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 28 }}>
          <div>
            <div style={{ ...S.eyebrow, color: t.ink2 }}>Distribution rate</div>
            <div style={{ ...S.num, fontSize: 22, color: t.ink }}>9.9%<span style={{ fontSize: 11, color: t.ink3, marginLeft: 6 }}>median, 149 funds</span></div>
            <div style={{ color: t.ink, marginTop: 10 }}>
              <PMWHistogram bins={PMW_DATA.distHist.bins} series={[{ label: "Liquid", data: PMW_DATA.distHist.bdc }, { label: "Semi-liquid", data: PMW_DATA.distHist.non }]} palette={[t.headerBg, t.accent]} h={140} />
            </div>
          </div>
          <div>
            <div style={{ ...S.eyebrow, color: t.ink2 }}>Leverage ratio</div>
            <div style={{ ...S.num, fontSize: 22, color: t.ink }}>0.16×<span style={{ fontSize: 11, color: t.ink3, marginLeft: 6 }}>median, 365 funds</span></div>
            <div style={{ color: t.ink, marginTop: 10 }}>
              <PMWHistogram bins={PMW_DATA.levHist.bins} series={[{ label: "Liquid", data: PMW_DATA.levHist.bdc }, { label: "Semi-liquid", data: PMW_DATA.levHist.non }]} palette={[t.headerBg, t.accent]} h={140} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function V2Universe({ t, S }) {
  return (
    <div id="universe" style={{ padding: "0 56px 32px" }}>
      <div style={{ ...S.card, padding: 0 }}>
        <div style={{ padding: "24px 28px 0", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <h3 style={{ ...S.display, fontSize: 26, margin: 0, letterSpacing: "-0.01em" }}>
            Fund universe <span style={{ color: t.ink3, fontWeight: 400 }}>· 385 funds · $830.6B</span>
          </h3>
          <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
            {["All","BDC","Interval","Tender"].map((tg, i) => (
              <span key={tg} style={{ padding: "6px 14px", border: `1px solid ${t.rule}`, background: i === 0 ? t.headerBg : "transparent", color: i === 0 ? t.onDarkInk : t.ink2, letterSpacing: "0.06em" }}>{tg}</span>
            ))}
            <span style={{ marginLeft: 10, color: t.ink3, fontSize: 12 }}>Search ⌕</span>
          </div>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 20 }}>
          <thead>
            <tr style={{ background: t.rule2 }}>
              {["Fund","Type","Liquidity","AUM","NAV / Sh","Dist Rate","QoQ"].map((h, i) => (
                <th key={h} style={{ ...S.eyebrow, textAlign: i >= 3 ? "right" : "left", padding: "10px 22px", color: t.ink2 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PMW_DATA.funds.map((f, i) => {
              const isArcc = f.name.includes("Ares Capital Corp");
              const RowTag = isArcc ? "a" : "tr";
              return (
              <tr key={f.name} style={{ borderBottom: `1px solid ${t.rule2}`, cursor: isArcc ? "pointer" : "default", background: isArcc ? "rgba(199,161,74,0.04)" : "transparent" }}
                  onClick={isArcc ? () => { window.location.href = "Fund Detail v3 - BDC.html"; } : undefined}>
                <td style={{ padding: "12px 22px", fontWeight: 500 }}>
                  {isArcc ? <a href="Fund Detail v3 - BDC.html" style={{ color: t.ink, textDecoration: "none", borderBottom: `1px solid ${t.accent}`, paddingBottom: 1 }}>{f.name} <span style={{ color: t.accent, marginLeft: 4 }}>↗</span></a> : f.name}
                </td>
                <td style={{ padding: "12px 22px", color: t.ink2 }}>
                  <span style={{ padding: "2px 8px", border: `1px solid ${t.rule}`, fontSize: 11, letterSpacing: "0.06em" }}>{f.type.toUpperCase()}</span>
                </td>
                <td style={{ padding: "12px 22px", color: t.ink2, fontSize: 12 }}>{f.liq}</td>
                <td style={{ ...S.num, padding: "12px 22px", textAlign: "right" }}>{f.aum}</td>
                <td style={{ ...S.num, padding: "12px 22px", textAlign: "right" }}>{f.nav}</td>
                <td style={{ ...S.num, padding: "12px 22px", textAlign: "right" }}>{f.dist}</td>
                <td style={{ ...S.num, padding: "12px 22px", textAlign: "right", color: f.qoq.startsWith("-") ? t.red : t.green, fontWeight: 600 }}>{f.qoq}</td>
              </tr>
              );
            })}
          </tbody>
        </table>
        <div style={{ padding: "16px 28px", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, color: t.ink3, borderTop: `1px solid ${t.rule}` }}>
          <span>Showing 10 of 385</span>
          <span style={{ color: t.ink, fontWeight: 500 }}>View all 385 →</span>
        </div>
      </div>
    </div>
  );
}

function V2Footer({ t, S }) {
  return (
    <div style={{ background: t.headerBg, color: t.onDarkInk2, padding: "44px 56px 28px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 28 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ ...S.display, fontSize: 18, color: t.onDarkInk }}>Metris Lens</span>
          </div>
          <p style={{ fontSize: 12, lineHeight: 1.6, marginTop: 12, maxWidth: 320 }}>
            Fund data, portfolio analytics, and position-level indices for private credit and equity markets, built from mandatory SEC filings. Does not constitute investment advice. Past performance is not indicative of future results.
          </p>
        </div>
        {(() => {
          const HREFS = {
            "Direct Lending":   "Index Detail - Direct Lending.html",
            "Preferred Equity": "Index Detail - Preferred Equity.html",
            "Common Equity":    "Index Detail - Common Equity.html",
            "Home":             "index.html",
            "Methodology":      "Methodology.html",
            "About":            "About.html",
            "Data access":      "Data.html",
          };
          return [
            ["Indices",      ["Direct Lending", "Preferred Equity", "Common Equity"]],
            ["Resources",    ["Home", "Methodology", "About", "Data access"]],
            ["Data Sources", ["SEC EDGAR · BDC XBRL (10-K/10-Q)", "SEC EDGAR · N-PORT (quarterly TSV)", "SEC EDGAR · N-CEN / N-2 (universe)"]],
          ].map(([h, items]) => (
            <div key={h}>
              <div style={{ ...S.eyebrow, color: t.accent, marginBottom: 10 }}>{h}</div>
              {items.map(it => HREFS[it]
                ? <a key={it} href={HREFS[it]} style={{ display: "block", fontSize: 12, padding: "4px 0", color: "inherit", textDecoration: "none" }}>{it}</a>
                : <div key={it} style={{ fontSize: 12, padding: "4px 0" }}>{it}</div>
              )}
            </div>
          ));
        })()}
      </div>
      <div style={{ borderTop: `1px solid ${t.onDarkRule2}`, marginTop: 28, paddingTop: 14, fontSize: 11, color: t.onDarkInk3, display: "flex", justifyContent: "space-between" }}>
        <span>© 2026 Metris Lens · All data derived from mandatory SEC regulatory filings.</span>
        <span>BDCs · Interval Funds · Tender Offer Funds</span>
      </div>
    </div>
  );
}

function V2ProportionDonut({ items, label, labelKey = "label", centerStat, t, S }) {
  const total = items.reduce((s, x) => s + x.pct, 0);
  const size = 196, thickness = 26;
  const cx = size / 2, cy = size / 2, r = (size - thickness) / 2;
  let acc = 0;
  const arcs = items.map((it, i) => {
    const start = acc / total * Math.PI * 2 - Math.PI / 2;
    acc += it.pct;
    const end = acc / total * Math.PI * 2 - Math.PI / 2;
    const large = end - start > Math.PI ? 1 : 0;
    const x1 = cx + r * Math.cos(start), y1 = cy + r * Math.sin(start);
    const x2 = cx + r * Math.cos(end), y2 = cy + r * Math.sin(end);
    const d = `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
    // Alternate between accent and headerBg with stepped opacity for a clean monochrome ramp.
    const baseColor = i % 2 === 0 ? t.accent : t.headerBg;
    const step = Math.floor(i / 2);
    const opacity = Math.max(1 - step * 0.16, 0.34);
    return { d, color: baseColor, opacity };
  });
  return (
    <div style={{ display: "grid", gridTemplateColumns: `${size}px minmax(0, 1fr)`, gap: 24, alignItems: "center" }}>
      <div style={{ position: "relative", width: size, height: size }}>
        <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} style={{ display: "block" }}>
          <circle cx={cx} cy={cy} r={r} fill="none" stroke={t.rule2} strokeWidth={thickness} />
          {arcs.map((a, i) => (
            <path key={i} d={a.d} stroke={a.color} strokeOpacity={a.opacity} strokeWidth={thickness} fill="none" strokeLinecap="butt" />
          ))}
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: 12 }}>
          {centerStat ? (
            <>
              <div style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", color: t.ink3 }}>{centerStat.label}</div>
              <div style={{ ...S.num, fontSize: 30, color: t.ink, letterSpacing: "-0.01em", marginTop: 2, fontWeight: 600 }}>{centerStat.value}</div>
              {centerStat.note && <div style={{ fontSize: 10, color: t.ink3, marginTop: 4, lineHeight: 1.3 }}>{centerStat.note}</div>}
            </>
          ) : (
            <>
              <div style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", color: t.ink3 }}>{label}</div>
              <div style={{ ...S.display, fontSize: 28, color: t.ink, letterSpacing: "-0.02em", marginTop: 2 }}>{items.length}</div>
            </>
          )}
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", columnGap: 18, rowGap: 6 }}>
        {arcs.map((a, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: t.ink2, borderBottom: `1px solid ${t.rule2}`, padding: "4px 0" }}>
            <span style={{ width: 9, height: 9, background: a.color, opacity: a.opacity, flexShrink: 0 }} />
            <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{items[i][labelKey]}</span>
            <span style={{ ...S.num, color: t.ink, fontWeight: 500 }}>{items[i].pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { V2Home, V2_THEMES, V2ReturnSummaryCard });
