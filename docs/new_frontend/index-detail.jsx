/* eslint-disable */
// Index Detail page — Direct Lending.
// Chassis is data-agnostic: pass any INDEX_DATA-shaped object and it renders.
// Reuses T_V3 / SX_V3 / FundHeader / FundFooter from fund-chrome.jsx.

// ─── Identity hero ────────────────────────────────────────────────────────────
function IndexIdentity({ T, SX, d }) {
  return (
    <div style={{ padding: "44px 72px 32px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)", gap: 56, alignItems: "start" }}>
        <div>
          <div style={{ ...SX.eyebrowAccent }}>PMW Index · Private Credit Benchmarks</div>
          <h1 style={{ ...SX.display, fontSize: 64, lineHeight: 1.02, margin: "10px 0 18px", letterSpacing: "-0.026em", color: T.ink }}>
            {d.name}
          </h1>
          <p style={{ fontSize: 16, lineHeight: 1.55, color: T.ink2, maxWidth: 600, margin: 0 }}>{d.tagline}</p>
          <div style={{ marginTop: 22, display: "flex", flexWrap: "wrap", gap: 18, alignItems: "baseline", color: T.ink3, fontSize: 12, letterSpacing: "0.04em" }}>
            <IdentityFact label="Inception"   value={d.inceptionDate} T={T} />
            <IdentityFact label="Rebalance"   value={d.rebalance} T={T} />
            <IdentityFact label="Currency"    value={d.currency} T={T} />
            <IdentityFact label="Return Type" value={d.returnTypes} T={T} />
            <IdentityFact label="Base Level"  value={`${d.baseLevel} (${d.inception})`} T={T} />
          </div>
        </div>
        <div style={{ ...SX.card, padding: 28 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={{ ...SX.eyebrowAccent }}>Level · {d.asOf}</span>
            <span style={{ ...SX.num, fontSize: 11, color: T.green, fontWeight: 600 }}>+{d.qoqReturn.toFixed(1)}% QoQ</span>
          </div>
          <div style={{ ...SX.num, ...SX.display, fontSize: 84, lineHeight: 1, marginTop: 6, color: T.ink, letterSpacing: "-0.03em", fontWeight: 600 }}>{d.level.toFixed(2)}</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, marginTop: 22, paddingTop: 16, borderTop: `1px solid ${T.rule2}` }}>
            <MiniStat label="1 Year"       value={`+${d.oneYearReturn.toFixed(1)}%`} accent T={T} SX={SX} />
            <MiniStat label="Since Incep." value={`+${d.sinceInceptionReturn.toFixed(2)}%`} T={T} SX={SX} />
            <MiniStat label="Constituents" value={d.holdingsCount.toLocaleString()} T={T} SX={SX} />
          </div>
        </div>
      </div>
    </div>
  );
}

function IdentityFact({ label, value, T }) {
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", color: T.ink3 }}>{label}</span>
      <span style={{ fontSize: 13, color: T.ink, letterSpacing: 0 }}>{value}</span>
    </span>
  );
}

function MiniStat({ label, value, accent, T, SX }) {
  return (
    <div>
      <div style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: T.ink3 }}>{label}</div>
      <div style={{ ...SX.num, fontSize: 19, color: accent ? T.accent : T.ink, fontWeight: 600, marginTop: 4 }}>{value}</div>
    </div>
  );
}

// ─── Stat strip ───────────────────────────────────────────────────────────────
function IndexStatStrip({ T, SX, d }) {
  const stats = [
    { label: "Aggregate Fair Value", value: d.aggregateFV },
    { label: "Unique Companies",     value: d.uniqueCompanies.toLocaleString() },
    { label: "Constituent Positions",value: d.holdingsCount.toLocaleString() },
    { label: "Funds Contributing",   value: `${d.fundsContributing} of ${d.fundsEligible}` },
    { label: "Universe Coverage",    value: `${d.universeCoverage.toFixed(1)}%`, note: "of eligible AUM" },
    { label: "Last Rebalance",       value: "Feb 15, 2026", note: "post-Q4 N-PORT" },
  ];
  return (
    <div style={{ padding: "0 72px 32px" }}>
      <div style={{ ...SX.card, display: "grid", gridTemplateColumns: `repeat(${stats.length}, 1fr)` }}>
        {stats.map((s, i) => (
          <div key={s.label} style={{ padding: "20px 22px", borderLeft: i === 0 ? "none" : `1px solid ${T.rule2}` }}>
            <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 8 }}>{s.label}</div>
            <div style={{ ...SX.num, fontSize: 22, color: T.ink, fontWeight: 600, letterSpacing: "-0.005em" }}>{s.value}</div>
            {s.note && <div style={{ fontSize: 11, color: T.ink3, marginTop: 3 }}>{s.note}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Performance + Return Summary ─────────────────────────────────────────────
function IndexPerformance({ T, SX, d }) {
  return (
    <div style={{ padding: "0 72px 32px" }}>
      <div style={{ ...SX.card, padding: 28, display: "grid", gridTemplateColumns: "minmax(0, 3fr) minmax(0, 2fr)", gap: 36 }}>
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <h2 style={{ ...SX.display, fontSize: 26, margin: 0, letterSpacing: "-0.015em" }}>
              Index level · <span style={{ color: T.ink3, fontWeight: 400 }}>since inception</span>
            </h2>
            <div style={{ display: "flex", gap: 6, fontSize: 11, letterSpacing: "0.06em" }}>
              {["1Y","3Y","5Y","SI"].map((tg, i) => (
                <span key={tg} style={{ padding: "6px 12px", border: `1px solid ${i === 3 ? T.ink : T.rule}`, color: i === 3 ? "#fff" : T.ink2, background: i === 3 ? T.navy : "transparent" }}>{tg}</span>
              ))}
            </div>
          </div>
          <div style={{ color: T.ink, marginTop: 18 }}>
            <PMWLineChart
              w={680} h={260}
              labels={d.perf.labels}
              series={[
                { label: `${d.name} (Gross)`,       data: d.perf.gross,     color: T.navy,   strokeWidth: 2 },
                { label: `${d.name} (Net)`,         data: d.perf.net,       color: T.accent, strokeWidth: 2 },
                { label: d.perf.benchmarkLabel,     data: d.perf.benchmark, color: T.ink3,   strokeWidth: 1.5, dash: "4 3" },
              ]}
            />
          </div>
        </div>
        <div style={{ borderLeft: `1px solid ${T.rule}`, paddingLeft: 28 }}>
          <ReturnSummaryTable T={T} SX={SX} rows={d.returnSummary} />
        </div>
      </div>
    </div>
  );
}

// Return summary — variant C (Net headline, Gross dim, Fee drag muted).
// Same hierarchy decision already locked in for the homepage.
function ReturnSummaryTable({ T, SX, rows }) {
  const cols = "1.4fr 1fr 1fr 0.9fr";
  return (
    <div>
      <div style={{ ...SX.eyebrow }}>Total return summary</div>
      <div style={{ display: "flex", flexDirection: "column", marginTop: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: cols, columnGap: 8, color: T.ink3, fontSize: 10, textTransform: "uppercase", letterSpacing: "0.12em", paddingBottom: 8, borderBottom: `1px solid ${T.rule}` }}>
          <span></span>
          <span style={{ textAlign: "right" }}>Net</span>
          <span style={{ textAlign: "right" }}>Gross</span>
          <span style={{ textAlign: "right" }}>Fee drag</span>
        </div>
        {rows.map(r => (
          <div key={r.period} style={{ display: "grid", gridTemplateColumns: cols, alignItems: "baseline", padding: "12px 0", borderBottom: `1px solid ${T.rule2}`, columnGap: 8 }}>
            <span style={{ fontSize: 12, color: T.ink2 }}>{r.period}</span>
            <span style={{ ...SX.num, fontSize: 19, color: T.ink,  fontWeight: 600, textAlign: "right" }}>{r.net}</span>
            <span style={{ ...SX.num, fontSize: 13, color: T.ink3, fontWeight: 400, textAlign: "right" }}>{r.gross}</span>
            <span style={{ ...SX.num, fontSize: 12, color: T.ink3, fontWeight: 400, textAlign: "right" }}>−{r.drag}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Risk & return statistics ─────────────────────────────────────────────────
function IndexRiskStats({ T, SX, d }) {
  return (
    <div style={{ padding: "0 72px 32px" }}>
      <div style={{ ...SX.card, padding: 28 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 18 }}>
          <h3 style={{ ...SX.display, fontSize: 22, margin: 0, letterSpacing: "-0.01em" }}>Risk &amp; return statistics</h3>
          <span style={{ fontSize: 11, color: T.ink3, letterSpacing: "0.04em" }}>Since inception · computed on Net unless noted</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", borderTop: `1px solid ${T.rule2}` }}>
          {d.riskStats.map((s, i) => (
            <div key={s.label} style={{ padding: "18px 18px 4px", borderLeft: i === 0 ? "none" : `1px solid ${T.rule2}` }}>
              <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 8 }}>{s.label}</div>
              <div style={{ ...SX.num, fontSize: 26, color: T.ink, fontWeight: 600, letterSpacing: "-0.01em" }}>{s.value}</div>
              <div style={{ fontSize: 11, color: T.ink3, marginTop: 4 }}>{s.note}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Portfolio characteristics (dark band — matches homepage) ────────────────
function IndexCharacteristics({ T, SX, d }) {
  return (
    <div style={{ padding: "0 72px 32px" }}>
      <div style={{ background: T.navy, color: "#fff", padding: "32px 28px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 32, alignItems: "center" }}>
          <div>
            <div style={{ ...SX.eyebrowAccent }}>Portfolio Characteristics</div>
            <div style={{ ...SX.display, fontSize: 26, marginTop: 6, maxWidth: 260, lineHeight: 1.1 }}>{d.name} positions as of {d.asOf}.</div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: `repeat(${d.portfolio.length},1fr)` }}>
            {d.portfolio.map((p) => (
              <div key={p.k} style={{ borderLeft: "1px solid rgba(255,255,255,0.14)", padding: "0 20px" }}>
                <div style={{ fontSize: 11, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.78)" }}>{p.k}</div>
                <div style={{ ...SX.num, fontSize: 36, color: T.accent, fontWeight: 500, marginTop: 6 }}>{p.v}</div>
                <div style={{ fontSize: 11, color: "rgba(255,255,255,0.55)" }}>{p.note}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Composition donuts (Sector + Manager) ───────────────────────────────────
function IndexComposition({ T, SX, d }) {
  return (
    <div style={{ padding: "0 72px 32px", display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 24 }}>
      <CompositionCard T={T} SX={SX}
        title="Sector composition"
        sub={`${d.sectors.filter(s => !s.sector.includes("Unclassified")).length} GICS sectors · share of index FV`}
        items={d.sectors}
        labelKey="sector"
        centerStat={{ label: "Top 5", value: topNShare(d.sectors, 5).toFixed(0) + "%", note: "of index FV" }}
        footnote="Reconciled BDC sector filings + holdings-level N-PORT." />
      <CompositionCard T={T} SX={SX}
        title="Manager contribution"
        sub={`Top 10 managers · share of index FV`}
        items={d.managers}
        labelKey="name"
        centerStat={{ label: "Top 5", value: topNShare(d.managers, 5).toFixed(0) + "%", note: "of index FV" }}
        footnote="Reflects manager whose vehicle reports the position; co-investments counted once." />
    </div>
  );
}

function topNShare(arr, n) {
  return [...arr].sort((a, b) => b.pct - a.pct).slice(0, n).reduce((s, x) => s + x.pct, 0);
}

function CompositionCard({ T, SX, title, sub, items, labelKey, centerStat, footnote }) {
  return (
    <div style={{ ...SX.card, padding: 28 }}>
      <h3 style={{ ...SX.display, fontSize: 22, margin: 0, letterSpacing: "-0.01em" }}>{title}</h3>
      <div style={{ fontSize: 12, color: T.ink3, marginTop: 8, marginBottom: 12 }}>{sub}</div>
      <ProportionDonut items={items} labelKey={labelKey} centerStat={centerStat} T={T} SX={SX} />
      <div style={{ marginTop: 16, paddingTop: 12, borderTop: `1px solid ${T.rule2}`, fontSize: 11, color: T.ink3 }}>{footnote}</div>
    </div>
  );
}

// Donut + legend (same as homepage but as a free function, since fund-chrome doesn't expose it)
function ProportionDonut({ items, labelKey, centerStat, T, SX }) {
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
    const baseColor = i % 2 === 0 ? T.accent : T.navy;
    const step = Math.floor(i / 2);
    const opacity = Math.max(1 - step * 0.16, 0.34);
    return { d, color: baseColor, opacity };
  });
  return (
    <div style={{ display: "grid", gridTemplateColumns: `${size}px minmax(0, 1fr)`, gap: 24, alignItems: "center" }}>
      <div style={{ position: "relative", width: size, height: size }}>
        <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} style={{ display: "block" }}>
          <circle cx={cx} cy={cy} r={r} fill="none" stroke={T.rule2} strokeWidth={thickness} />
          {arcs.map((a, i) => (
            <path key={i} d={a.d} stroke={a.color} strokeOpacity={a.opacity} strokeWidth={thickness} fill="none" strokeLinecap="butt" />
          ))}
        </svg>
        {centerStat && (
          <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", padding: 12 }}>
            <div style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", color: T.ink3 }}>{centerStat.label}</div>
            <div style={{ ...SX.num, fontSize: 30, color: T.ink, letterSpacing: "-0.01em", marginTop: 2, fontWeight: 600 }}>{centerStat.value}</div>
            {centerStat.note && <div style={{ fontSize: 10, color: T.ink3, marginTop: 4, lineHeight: 1.3 }}>{centerStat.note}</div>}
          </div>
        )}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", columnGap: 18, rowGap: 6 }}>
        {arcs.map((a, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: T.ink2, borderBottom: `1px solid ${T.rule2}`, padding: "4px 0" }}>
            <span style={{ width: 9, height: 9, background: a.color, opacity: a.opacity, flexShrink: 0 }} />
            <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{items[i][labelKey]}</span>
            <span style={{ ...SX.num, color: T.ink, fontWeight: 500 }}>{items[i].pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Top constituents table ──────────────────────────────────────────────────
function IndexTopConstituents({ T, SX, d }) {
  return (
    <div style={{ padding: "0 72px 32px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "24px 28px 18px", display: "flex", justifyContent: "space-between", alignItems: "baseline", borderBottom: `1px solid ${T.rule}` }}>
          <div>
            <h3 style={{ ...SX.display, fontSize: 24, margin: 0, letterSpacing: "-0.01em" }}>Top constituents</h3>
            <div style={{ fontSize: 12, color: T.ink3, marginTop: 6 }}>
              Largest position-level exposures across the index · each row is one security; an issuer with multiple instruments will appear multiple times
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
            {["Top 25", "Top 100", `All ${d.holdingsCount.toLocaleString()}`].map((tg, i) => (
              <span key={tg} style={{ padding: "6px 14px", border: `1px solid ${T.rule}`, background: i === 0 ? T.navy : "transparent", color: i === 0 ? "#fff" : T.ink2, letterSpacing: "0.06em" }}>{tg}</span>
            ))}
            <span style={{ marginLeft: 10, color: T.ink3, fontSize: 12 }}>Search ⌕</span>
          </div>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: T.rule3 }}>
              {[
                { h: "#",            align: "right", w: 48 },
                { h: "Position",     align: "left" },
                { h: "Sector",       align: "left" },
                { h: "Funds holding",align: "right" },
                { h: "Aggregate FV", align: "right" },
                { h: "Weight",       align: "right" },
              ].map((c, i) => (
                <th key={c.h} style={{ ...SX.eyebrow, color: T.ink2, textAlign: c.align, padding: "10px 22px", width: c.w }}>{c.h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.topConstituents.map((c, i) => (
              <tr key={c.rank} style={{ borderBottom: `1px solid ${T.rule2}` }}>
                <td style={{ ...SX.num, padding: "11px 22px", textAlign: "right", color: T.ink3 }}>{c.rank}</td>
                <td style={{ padding: "11px 22px", fontWeight: 500, color: T.ink }}>{c.company}</td>
                <td style={{ padding: "11px 22px", color: T.ink2, fontSize: 12 }}>{c.sector}</td>
                <td style={{ ...SX.num, padding: "11px 22px", textAlign: "right", color: T.ink2 }}>{c.funds}</td>
                <td style={{ ...SX.num, padding: "11px 22px", textAlign: "right", color: T.ink }}>{c.fv}</td>
                <td style={{ padding: "11px 22px", textAlign: "right" }}>
                  <WeightBar pct={c.weight} maxPct={d.topConstituents[0].weight} T={T} SX={SX} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding: "16px 28px", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, color: T.ink3, borderTop: `1px solid ${T.rule}` }}>
          <span>
            Top 25 of <span style={{ ...SX.num, color: T.ink }}>{d.holdingsCount.toLocaleString()}</span> positions across <span style={{ ...SX.num, color: T.ink }}>{d.uniqueCompanies.toLocaleString()}</span> unique issuers · combined weight {' '}
            <span style={{ ...SX.num, color: T.ink }}>
              {d.topConstituents.reduce((s, x) => s + x.weight, 0).toFixed(2)}%
            </span> of index
          </span>
          <a href="#" style={{ color: T.ink, fontWeight: 500, textDecoration: "none", borderBottom: `1px solid ${T.accent}`, paddingBottom: 2 }}>View full constituent list →</a>
        </div>
      </div>
    </div>
  );
}

function WeightBar({ pct, maxPct, T, SX }) {
  return (
    <div style={{ display: "inline-grid", gridTemplateColumns: "1fr auto", alignItems: "center", gap: 10, minWidth: 130 }}>
      <span style={{ height: 6, background: T.rule2, position: "relative", display: "block" }}>
        <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(pct / maxPct) * 100}%`, background: T.accent }} />
      </span>
      <span style={{ ...SX.num, fontSize: 12, color: T.ink, fontWeight: 500, textAlign: "right" }}>{pct.toFixed(2)}%</span>
    </div>
  );
}

// ─── Structural composition: Seniority bars + Rate/Vintage distribution ───────
// Generic — Direct Lending fills in lien position + spread, Preferred fills in
// pref seniority + dividend rate, Common Equity fills in position type + vintage.
function IndexStructuralComposition({ T, SX, d }) {
  const s = d.seniority;
  const r = d.rateDistribution;
  return (
    <div style={{ padding: "0 72px 32px", display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 24 }}>
      {/* Seniority / Position-type bars */}
      <div style={{ ...SX.card, padding: 28 }}>
        <h3 style={{ ...SX.display, fontSize: 22, margin: 0, letterSpacing: "-0.01em" }}>{s.title}</h3>
        <div style={{ fontSize: 12, color: T.ink3, marginTop: 8, marginBottom: 18 }}>{s.subtitle}</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {s.items.map((l, i) => (
            <div key={l.label} style={{ display: "grid", gridTemplateColumns: "minmax(0, 200px) 1fr 90px 70px", alignItems: "center", gap: 14, fontSize: 13 }}>
              <span style={{ color: T.ink, fontWeight: i === 0 ? 600 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.label}</span>
              <span style={{ height: 12, background: T.rule2, position: "relative" }}>
                <span style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${l.pct}%`, background: i === 0 ? T.navy : T.accent, opacity: i === 0 ? 1 : Math.max(0.85 - i * 0.14, 0.35) }} />
              </span>
              <span style={{ ...SX.num, color: T.ink2, fontSize: 12, textAlign: "right" }}>{l.fv}</span>
              <span style={{ ...SX.num, color: T.ink, fontWeight: 600, textAlign: "right" }}>{l.pct.toFixed(1)}%</span>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 18, paddingTop: 12, borderTop: `1px solid ${T.rule2}`, fontSize: 11, color: T.ink3, lineHeight: 1.55 }}>
          {s.footnote}
        </div>
      </div>

      {/* Rate / Vintage distribution */}
      <div style={{ ...SX.card, padding: 28 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 16 }}>
          <div>
            <h3 style={{ ...SX.display, fontSize: 22, margin: 0, letterSpacing: "-0.01em" }}>{r.title}</h3>
            <div style={{ fontSize: 12, color: T.ink3, marginTop: 8 }}>{r.subtitle}</div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ ...SX.num, fontSize: 26, color: T.ink, fontWeight: 600 }}>{r.headline}</div>
            <div style={{ fontSize: 10, color: T.ink3, letterSpacing: "0.12em", textTransform: "uppercase", marginTop: 4 }}>{r.headlineLabel}</div>
          </div>
        </div>
        <div style={{ color: T.ink2, marginTop: 16 }}>
          <RateHistogram T={T} bins={r.bins} pcts={r.pct} xAxisLabel={r.xAxisLabel} />
        </div>
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: `1px solid ${T.rule2}`, fontSize: 11, color: T.ink3 }}>
          {r.footnote}
        </div>
      </div>
    </div>
  );
}

function RateHistogram({ T, bins, pcts, xAxisLabel, h = 160 }) {
  const w = 540, padding = { t: 14, r: 8, b: 28, l: 32 };
  const cw = w - padding.l - padding.r;
  const ch = h - padding.t - padding.b;
  const max = Math.max(...pcts);
  const bw = cw / bins.length;
  const yTicks = 4;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" style={{ display: "block" }}>
      {Array.from({ length: yTicks + 1 }, (_, i) => {
        const v = (max * i) / yTicks;
        const y = padding.t + ch - (v / max) * ch;
        return (
          <g key={i}>
            <line x1={padding.l} x2={padding.l + cw} y1={y} y2={y} stroke="currentColor" strokeOpacity={0.08} />
            <text x={padding.l - 6} y={y + 3} textAnchor="end" fontSize="10" fill="currentColor" opacity="0.55">{v.toFixed(0)}%</text>
          </g>
        );
      })}
      {bins.map((b, i) => {
        const bh = (pcts[i] / max) * ch;
        const x = padding.l + i * bw + 4;
        const isPeak = pcts[i] === max;
        return (
          <g key={b}>
            <rect x={x} y={padding.t + ch - bh} width={bw - 8} height={bh} fill={isPeak ? T.accent : T.navy} opacity={isPeak ? 1 : 0.78} />
            <text x={x + (bw - 8) / 2} y={padding.t + ch - bh - 6} textAnchor="middle" fontSize="10" fill={T.ink} fontWeight={isPeak ? 600 : 400}>{pcts[i].toFixed(1)}</text>
            <text x={x + (bw - 8) / 2} y={h - 10} textAnchor="middle" fontSize="10" fill="currentColor" opacity="0.6">{b}</text>
          </g>
        );
      })}
      <text x={padding.l + cw / 2} y={h - 0} textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.5" style={{ letterSpacing: "0.1em", textTransform: "uppercase" }}>{xAxisLabel}</text>
    </svg>
  );
}

// ─── Top funds contributing to the index ─────────────────────────────────────
function IndexTopFunds({ T, SX, d }) {
  const top = d.topFundsContributing;
  const totalTop = top.reduce((s, x) => s + x.pctOfIndex, 0);
  return (
    <div style={{ padding: "0 72px 32px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "24px 28px 18px", display: "flex", justifyContent: "space-between", alignItems: "baseline", borderBottom: `1px solid ${T.rule}` }}>
          <div>
            <h3 style={{ ...SX.display, fontSize: 24, margin: 0, letterSpacing: "-0.01em" }}>Top funds contributing</h3>
            <div style={{ fontSize: 12, color: T.ink3, marginTop: 6 }}>
              Vehicles holding the largest dollar exposure to constituent positions
            </div>
          </div>
          <span style={{ fontSize: 12, color: T.ink3 }}>
            Top 10 of <span style={{ ...SX.num, color: T.ink }}>{d.fundsContributing}</span> contributing funds
          </span>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: T.rule3 }}>
              {[
                { h: "Fund",         align: "left"  },
                { h: "Manager",      align: "left"  },
                { h: "Positions",    align: "right" },
                { h: "FV in index",  align: "right" },
                { h: "% of index",   align: "right" },
              ].map(c => (
                <th key={c.h} style={{ ...SX.eyebrow, color: T.ink2, textAlign: c.align, padding: "10px 22px" }}>{c.h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {top.map((f, i) => {
              const isArcc = f.ticker === "ARCC";
              return (
                <tr key={f.name} style={{ borderBottom: `1px solid ${T.rule2}`, background: isArcc ? "rgba(199,161,74,0.04)" : "transparent" }}>
                  <td style={{ padding: "12px 22px", fontWeight: 500 }}>
                    {isArcc ? (
                      <a href="Fund Detail v3 - BDC.html" style={{ color: T.ink, textDecoration: "none", borderBottom: `1px solid ${T.accent}`, paddingBottom: 1 }}>
                        {f.name} {f.ticker && <span style={{ color: T.ink3, marginLeft: 6, fontSize: 11, ...SX.num }}>{f.ticker}</span>}
                        <span style={{ color: T.accent, marginLeft: 6 }}>↗</span>
                      </a>
                    ) : (
                      <span>{f.name}{f.ticker && <span style={{ color: T.ink3, marginLeft: 6, fontSize: 11, ...SX.num }}>{f.ticker}</span>}</span>
                    )}
                  </td>
                  <td style={{ padding: "12px 22px", color: T.ink2 }}>{f.manager}</td>
                  <td style={{ ...SX.num, padding: "12px 22px", textAlign: "right", color: T.ink2 }}>{f.positions.toLocaleString()}</td>
                  <td style={{ ...SX.num, padding: "12px 22px", textAlign: "right", color: T.ink, fontWeight: 500 }}>{f.fvContrib}</td>
                  <td style={{ ...SX.num, padding: "12px 22px", textAlign: "right", color: T.ink, fontWeight: 600 }}>{f.pctOfIndex.toFixed(1)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div style={{ padding: "16px 28px", display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 12, color: T.ink3, borderTop: `1px solid ${T.rule}` }}>
          <span>Top 10 funds account for <span style={{ ...SX.num, color: T.ink }}>{totalTop.toFixed(1)}%</span> of index FV</span>
          <a href="#" style={{ color: T.ink, fontWeight: 500, textDecoration: "none", borderBottom: `1px solid ${T.accent}`, paddingBottom: 2 }}>View all {d.fundsContributing} funds →</a>
        </div>
      </div>
    </div>
  );
}

// ─── Methodology summary ─────────────────────────────────────────────────────
function IndexMethodologySummary({ T, SX, d }) {
  return (
    <div style={{ padding: "0 72px 56px" }}>
      <div style={{ ...SX.card, padding: 32, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 36 }}>
        <div>
          <div style={{ ...SX.eyebrowAccent }}>Methodology · summary</div>
          <h3 style={{ ...SX.display, fontSize: 26, margin: "10px 0 14px", letterSpacing: "-0.015em" }}>How the index is built</h3>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: T.ink2, margin: 0 }}>
            {d.methodology.construction}
          </p>
          <p style={{ fontSize: 13, lineHeight: 1.6, color: T.ink3, margin: "14px 0 0" }}>
            {d.methodology.rebalanceNote}
          </p>
          <a href="#" style={{ display: "inline-block", marginTop: 22, padding: "10px 18px", background: T.navy, color: "#fff", fontSize: 12, letterSpacing: "0.06em", textDecoration: "none" }}>
            Read full methodology →
          </a>
        </div>
        <div>
          <div style={{ ...SX.eyebrow, color: T.ink2 }}>Eligibility rules</div>
          <ol style={{ margin: "14px 0 0", padding: 0, listStyle: "none", counterReset: "rule" }}>
            {d.methodology.eligibility.map((rule, i) => (
              <li key={i} style={{ display: "grid", gridTemplateColumns: "32px 1fr", gap: 0, padding: "12px 0", borderTop: `1px solid ${T.rule2}`, fontSize: 13, lineHeight: 1.5, color: T.ink2 }}>
                <span style={{ ...SX.num, color: T.accent, fontWeight: 600 }}>{String(i + 1).padStart(2, "0")}</span>
                <span>{rule}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}

// ─── App shell ────────────────────────────────────────────────────────────────
function IndexDetailApp({ data }) {
  const d = data || window.INDEX_DATA_DIRECT_LENDING;
  const T = window.T_V3, SX = window.SX_V3;
  return (
    <div style={SX.root} data-screen-label={`Index Detail · ${d.name}`}>
      <FundHeader T={T} SX={SX} navActive="Indices" />
      <Breadcrumb T={T} items={[
        { label: "Home",   href: "index.html" },
        { label: "Indices" },
        { label: d.name },
      ]} />
      <IndexIdentity           T={T} SX={SX} d={d} />
      <IndexStatStrip          T={T} SX={SX} d={d} />
      <IndexPerformance        T={T} SX={SX} d={d} />
      <IndexRiskStats          T={T} SX={SX} d={d} />
      <IndexCharacteristics    T={T} SX={SX} d={d} />
      <IndexComposition        T={T} SX={SX} d={d} />
      <IndexTopConstituents    T={T} SX={SX} d={d} />
      <IndexStructuralComposition T={T} SX={SX} d={d} />
      <IndexTopFunds           T={T} SX={SX} d={d} />
      <IndexMethodologySummary T={T} SX={SX} d={d} />
      <FundFooter T={T} SX={SX} />
    </div>
  );
}

window.IndexDetailApp = IndexDetailApp;
