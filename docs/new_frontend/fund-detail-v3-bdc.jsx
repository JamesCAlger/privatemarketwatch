/* eslint-disable */
// Fund Detail v3 — BDC variant. ARCC.
//
// Editorial brief: the emphasis is "where does this fund stand against its
// peers?" — not "here are its absolute numbers." Every headline metric is
// paired with a quartile rank and a strip chart showing the full peer set.
// NAV–price spread (premium/discount) gets its own block because it only
// exists for publicly-traded BDCs.

const T = T_V3, SX = SX_V3;

// ── Identity band ────────────────────────────────────────────────────────────
function BDCIdentity() {
  const f = FUND.identity;
  const premium = (f.lastPrice - f.navPerShare) / f.navPerShare * 100;
  const R = PEER_UNIVERSE.ranks.ARCC;

  const Stat = ({ label, value, sub, quartile, big = false, color }) => (
    <div style={{ borderTop: `1px solid ${T.rule2}`, paddingTop: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ ...SX.eyebrow, color: T.ink3 }}>{label}</div>
        {quartile && (
          <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: "0.08em", color: quartile.q <= 2 ? T.accent : T.ink3 }}>
            Q{quartile.q} · {pq_ordinal(quartile.rank)} of {quartile.total}
          </span>
        )}
      </div>
      <div style={{ ...SX.display, fontSize: big ? 36 : 28, color: color || T.ink, letterSpacing: "-0.02em", marginTop: 4, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: T.ink3, marginTop: 4 }}>{sub}</div>}
    </div>
  );

  return (
    <div style={{ padding: "32px 72px 40px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1.4fr", gap: 36, alignItems: "start" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
            <span style={{ padding: "3px 9px", background: T.navy, color: "#fff", ...SX.eyebrow, color: "#fff", fontSize: 10 }}>BDC</span>
            <span style={{ padding: "3px 9px", border: `1px solid ${T.rule}`, ...SX.eyebrow, color: T.ink2, fontSize: 10 }}>Publicly Traded</span>
            <span style={{ padding: "3px 9px", border: `1px solid ${T.accent}`, color: T.accent, ...SX.eyebrow, color: T.accent, fontSize: 10 }}>Index member · Direct Lending</span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap" }}>
            <h1 style={{ ...SX.display, fontSize: 52, margin: 0, letterSpacing: "-0.025em", lineHeight: 1.02 }}>{f.name}</h1>
            <span style={{ ...SX.display, fontSize: 36, color: T.accent }}>({f.ticker})</span>
          </div>
          <div style={{ display: "flex", gap: 22, marginTop: 14, fontSize: 12, color: T.ink2, flexWrap: "wrap" }}>
            <span><span style={{ color: T.ink3 }}>CIK</span> &nbsp;<span style={{ ...SX.num }}>{f.cik}</span></span>
            <span><span style={{ color: T.ink3 }}>Manager</span> &nbsp;{f.manager}</span>
            <span><span style={{ color: T.ink3 }}>Inception</span> &nbsp;{f.inception}</span>
            <span><span style={{ color: T.ink3 }}>HQ</span> &nbsp;New York, NY</span>
          </div>
          <p style={{ fontSize: 15, lineHeight: 1.55, color: T.ink2, maxWidth: 620, marginTop: 18 }}>
            The largest publicly traded business development company by AUM. ARCC invests primarily in U.S. middle-market companies through first lien senior secured loans, second lien debt, and selective equity co-investments alongside Ares Management's broader credit platform.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 22 }}>
            <span style={{ padding: "10px 18px", background: T.navy, color: "#fff", fontSize: 13, fontWeight: 500, letterSpacing: "0.04em" }}>+ Watchlist</span>
            <span style={{ padding: "10px 18px", border: `1px solid ${T.rule}`, color: T.ink, fontSize: 13, fontWeight: 500 }}>EDGAR filings ↗</span>
            <a href="Fund Detail v3 — Interval.html" style={{ padding: "10px 18px", border: `1px solid ${T.accent}`, color: T.accent, fontSize: 13, fontWeight: 500, textDecoration: "none" }}>View interval-fund template →</a>
          </div>
        </div>
        <div style={{ ...SX.card, padding: 36 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 18 }}>
            <span style={{ ...SX.eyebrowAccent }}>Snapshot · {f.asOf}</span>
            <span style={{ fontSize: 11, color: T.ink3 }}>Ranks vs. full credit universe (~140 funds)</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", rowGap: 22, columnGap: 22 }}>
            <Stat label="AUM" value={"$" + f.aum.toFixed(1) + "B"} sub={`${f.sharesOut}M shares · Largest publicly-traded BDC`} big />
            <Stat label="NAV / Share" value={"$" + f.navPerShare.toFixed(2)} sub="GAAP, Q4 2025" big />
            <Stat
              label="Last Price"
              value={"$" + f.lastPrice.toFixed(2)}
              sub={`+${premium.toFixed(1)}% to NAV · See spread analysis below ↓`}
              big
            />
            <Stat
              label="Distribution"
              value={f.distRate.toFixed(1) + "%"}
              sub="Annualized rate"
              color={T.accent}
              big
              quartile={{ q: pq_quartileOf(R.vsAll.dist.rank, R.vsAll.dist.total), rank: R.vsAll.dist.rank, total: R.vsAll.dist.total }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Peer standing band (4 quartile cards) ────────────────────────────────────
function PeerStandingBDC() {
  const U = PEER_UNIVERSE;
  const R = U.ranks.ARCC;
  // Returns / dist / coverage compare across the full credit universe
  // (BDCs + intervals) — these metrics are wrapper-agnostic.
  const all = U.creditAll;
  const bdcs = U.bdcsTraded;
  const items = [
    {
      key: "ret1y",
      label: "1Y total return",
      value: R.vsAll.ret1y.value,
      valueFmt: (v) => "+" + v.toFixed(1) + "%",
      rank: R.vsAll.ret1y.rank,
      total: R.vsAll.ret1y.total,
      totalLabel: "credit funds",
      direction: "higher",
      distribution: all.map((p) => p.ret1y),
    },
    {
      key: "ret3y",
      label: "3Y total return (annlz.)",
      value: R.vsAll.ret3y.value,
      valueFmt: (v) => "+" + v.toFixed(1) + "%",
      rank: R.vsAll.ret3y.rank,
      total: R.vsAll.ret3y.total,
      totalLabel: "credit funds",
      direction: "higher",
      distribution: all.map((p) => p.ret3y),
    },
    {
      key: "distCov",
      label: "Distribution coverage (NII/dist)",
      value: R.vsAll.distCov.value,
      valueFmt: (v) => v.toFixed(2) + "×",
      rank: R.vsAll.distCov.rank,
      total: R.vsAll.distCov.total,
      totalLabel: "credit funds",
      direction: "higher",
      distribution: all.map((p) => p.distCov),
    },
    {
      key: "nonAccrual",
      label: "Non-accrual rate (by FV)",
      value: R.vsBDC.nonAccrual.value,
      valueFmt: (v) => v.toFixed(1) + "%",
      rank: R.vsBDC.nonAccrual.rank,
      total: R.vsBDC.nonAccrual.total,
      totalLabel: "traded BDCs",
      direction: "lower",
      distribution: bdcs.map((p) => p.nonAccrual),
    },
  ];

  return (
    <PeerStandingBand
      items={items}
      T={T}
      ticker="ARCC"
      eyebrow="Peer Standing · Q4 2025"
      title="How ARCC ranks across the full universe."
      subtitle="Each metric is ranked against every fund where the metric is meaningful — the full SEC-registered universe (~140 credit funds) for returns / coverage, and only the 47 publicly-traded BDCs for non-accrual. No curated peer set."
      footnote="Universe: 47 traded BDCs · 95 interval &amp; tender-offer funds. Data: SEC filings (10-K, 10-Q, N-CSR, N-PORT)." />
  );
}

// ── NAV-price spread analysis — the BDC-only block ──────────────────────────
function SpreadAnalysis() {
  const f = FUND.identity;
  const sh = FUND.spreadHistory;
  const currentSpread = sh.arcc[sh.arcc.length - 1];
  const avg3y = sh.arcc.reduce((a, b) => a + b, 0) / sh.arcc.length;
  const peerMedNow = sh.peerMed[sh.peerMed.length - 1];
  const max = Math.max(...sh.arcc), min = Math.min(...sh.arcc);

  // Rank ARCC's current premium across ALL publicly-traded BDCs (~47).
  // Premium is structurally a BDC-only signal — intervals transact at NAV.
  const U = PEER_UNIVERSE;
  const bdcs = U.bdcsTraded;
  const premDist = bdcs.map((p) => p.prem);
  // Higher premium = "richer," not necessarily "better." Use neutral
  // direction but rank by absolute richness for the badge headline.
  const sortedDesc = premDist.slice().sort((a, b) => b - a);
  const arccRank = sortedDesc.indexOf(currentSpread) + 1
    || sortedDesc.findIndex((v) => Math.abs(v - currentSpread) < 0.01) + 1
    || sortedDesc.findIndex((v) => v <= currentSpread) + 1;

  const Stat = ({ label, value, sub, color }) => (
    <div style={{ borderTop: `1px solid ${T.rule2}`, paddingTop: 12 }}>
      <div style={{ ...SX.eyebrow, color: T.ink3 }}>{label}</div>
      <div style={{ ...SX.display, fontSize: 26, color: color || T.ink, letterSpacing: "-0.02em", marginTop: 4, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: T.ink3, marginTop: 4 }}>{sub}</div>}
    </div>
  );

  return (
    <div style={{ padding: "0 72px 56px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "28px 36px 18px", borderBottom: `1px solid ${T.rule2}`, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <div style={{ ...SX.eyebrowAccent }}>NAV–price spread · BDC-specific</div>
            <h2 style={{ ...SX.display, fontSize: 30, margin: "6px 0 0", letterSpacing: "-0.015em" }}>ARCC has traded at a steady premium to NAV.</h2>
            <div style={{ fontSize: 13, color: T.ink2, marginTop: 8, maxWidth: 760 }}>
              The market price–NAV gap is a public-only signal — interval funds transact at NAV, so we rank only against the 47 publicly-traded BDCs. Investors are willing to pay {currentSpread.toFixed(1)}% over GAAP book value today, vs. a peer median of {peerMedNow > 0 ? "+" : ""}{peerMedNow.toFixed(1)}%. The shaded band shows the 25th–75th percentile across the BDC universe each quarter.
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6, minWidth: 240 }}>
            <QuartileBadge
              metric="Current spread vs. all traded BDCs"
              rank={arccRank}
              total={bdcs.length}
              totalLabel="traded BDCs"
              value={currentSpread}
              valueFmt={(v) => (v > 0 ? "+" : "") + v.toFixed(1) + "%"}
              note="Higher = richer (good for sellers, bad for buyers)"
              direction="higher"
              distribution={premDist}
              ticker="ARCC"
              T={T}
              densityW={260}
              densityH={62}
              compact
            />
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.8fr 1fr" }}>
          {/* LEFT: time series with peer band */}
          <div style={{ padding: "28px 36px", borderRight: `1px solid ${T.rule2}` }}>
            <div style={{ ...SX.eyebrow, color: T.ink3 }}>Quarterly spread to NAV · 3-year history</div>
            <div style={{ color: T.ink, marginTop: 14 }}>
              <SpreadBandChart
                labels={sh.quarters}
                fund={sh.arcc}
                peerMed={sh.peerMed}
                peerP25={sh.peerP25}
                peerP75={sh.peerP75}
                T={T}
                w={720} h={240}
              />
            </div>
            <div style={{ display: "flex", gap: 22, marginTop: 12, flexWrap: "wrap", fontSize: 11, color: T.ink2 }}>
              <span><span style={{ display: "inline-block", width: 14, height: 2.5, background: T.accent, verticalAlign: "middle" }} /> &nbsp;ARCC spread to NAV</span>
              <span><span style={{ display: "inline-block", width: 14, height: 2, background: T.ink2, opacity: 0.7, borderTop: `2px dashed ${T.ink2}`, verticalAlign: "middle" }} /> &nbsp;Peer median (47 traded BDCs)</span>
              <span><span style={{ display: "inline-block", width: 14, height: 8, background: T.ink2, opacity: 0.10, verticalAlign: "middle" }} /> &nbsp;Peer P25–P75 band</span>
            </div>
            <div style={{ fontSize: 11, color: T.ink3, marginTop: 14, fontStyle: "italic", lineHeight: 1.6, maxWidth: 700 }}>
              ARCC has traded above the peer median in every one of the past 12 quarters — a {avg3y.toFixed(1)}% average premium vs. a peer median that crossed parity only in Q3 2023. Range over the period: {min.toFixed(1)}% (Q1 2023) to +{max.toFixed(1)}% (Q4 2024).
            </div>
          </div>

          {/* RIGHT: spread summary + scatter */}
          <div style={{ padding: "28px 36px", display: "flex", flexDirection: "column", gap: 22 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>
              <Stat label="Current spread" value={(currentSpread > 0 ? "+" : "") + currentSpread.toFixed(1) + "%"} sub="vs. peer median +1.4%" color={T.accent} />
              <Stat label="3Y avg spread" value={(avg3y > 0 ? "+" : "") + avg3y.toFixed(1) + "%"} sub="Trailing 12 quarters" />
              <Stat label="3Y range" value={min.toFixed(1) + " to +" + max.toFixed(1) + "%"} sub="Persistently above zero" />
              <Stat label="Pct. above peer med." value="100%" sub="of trailing quarters" color={T.green} />
            </div>
            <div>
              <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 8 }}>Cross-section · Distribution rate vs. premium ({bdcs.length} traded BDCs)</div>
              <div style={{ color: T.ink }}>
                <PeerScatter
                  peers={bdcs.map((p) => ({ ticker: p.ticker, dist: p.dist, prem: p.prem,
                    highlight: p.highlight,
                    label: ["MAIN", "HTGC", "FSK"].includes(p.ticker) ? true : false }))}
                  xKey="dist" yKey="prem"
                  xLabel="Distribution rate (%)"
                  yLabel="Premium to NAV (%)"
                  T={T} w={360} h={220}
                />
              </div>
              <div style={{ fontSize: 10, color: T.ink3, marginTop: 6, fontStyle: "italic", lineHeight: 1.5 }}>
                Higher payouts don't earn richer premiums across the full BDC set — the cloud is weakly negative. MAIN and HTGC trade rich on track record, not headline yield.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Price / NAV chart — kept but downsized; reuses original PriceChart logic ─
function PriceChart() {
  const [tf, setTf] = React.useState("3Y");
  const h = FUND.history;
  const d = FUND.daily;
  const fmtMo = (dt) => ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][dt.getMonth()] + " '" + String(dt.getFullYear()).slice(2);
  const thinDateLabels = (dates, n = 7) => {
    if (dates.length <= n) return dates.map(fmtMo);
    return Array.from({ length: n }, (_, i) => fmtMo(dates[Math.round(i / (n - 1) * (dates.length - 1))]));
  };
  let labels, price, nav;
  if (tf === "SI") {
    labels = FUND.sinceInception.labels;
    const tr = FUND.sinceInception.totalReturn;
    price = tr.map((v) => v / tr[0] * 17);
    nav = tr.map((v) => v * 0.92 / tr[0] * 17);
  } else {
    const n = tf === "1Y" ? 252 : Math.min(d.dates.length, 750);
    price = d.prices.slice(-n);
    nav = d.navs.slice(-n);
    labels = thinDateLabels(d.dates.slice(-n), 7);
  }
  return (
    <div style={{ padding: "0 72px 56px" }}>
      <div style={{ ...SX.card, padding: 32 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14 }}>
          <div>
            <div style={{ ...SX.eyebrowAccent }}>Price &amp; NAV / share</div>
            <h3 style={{ ...SX.display, fontSize: 22, margin: "4px 0 0", letterSpacing: "-0.015em" }}>Daily close vs. quarterly NAV</h3>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {["1Y", "3Y", "SI"].map((p) =>
              <span key={p} onClick={() => setTf(p)} style={tf === p ? SX.pillActive : SX.pillInactive}>{p}</span>
            )}
          </div>
        </div>
        <div style={{ color: T.ink }}>
          <PMWLineChart
            w={1100} h={220}
            labels={labels}
            series={[
              { label: "Price (daily close)", data: price, color: T.navy, strokeWidth: 1.4 },
              { label: "NAV / share", data: nav, color: T.accent, strokeWidth: 1.8 }
            ]}
            yFmt={(v) => "$" + v.toFixed(0)}
          />
        </div>
      </div>
    </div>
  );
}

// ── Tabs ─────────────────────────────────────────────────────────────────────
function TabBar({ tabs, active, onChange }) {
  return (
    <div style={{ borderTop: `1px solid ${T.rule}`, borderBottom: `1px solid ${T.rule}`, background: T.surface, position: "sticky", top: 0, zIndex: 10 }}>
      <div style={{ padding: "0 72px", display: "flex", gap: 0 }}>
        {tabs.map((t) =>
          <span key={t.id} onClick={() => onChange(t.id)} style={{ padding: "14px 22px", borderBottom: active === t.id ? `2px solid ${T.accent}` : "2px solid transparent", color: active === t.id ? T.ink : T.ink2, fontSize: 13, fontWeight: active === t.id ? 600 : 500, cursor: "pointer", letterSpacing: "0.02em" }}>
            {t.label}
            {t.count != null && <span style={{ marginLeft: 6, fontSize: 11, color: T.ink3, ...SX.num }}>{t.count}</span>}
          </span>
        )}
      </div>
    </div>
  );
}

// Performance tab w/ quartile column
function PerformanceTab() {
  const QChip = ({ q }) => (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      minWidth: 32, padding: "2px 8px",
      background: q === 1 ? T.accent : q === 2 ? T.accentSoft : T.rule2,
      color: q === 1 ? "#fff" : q === 2 ? T.amber : T.ink2,
      fontSize: 11, fontWeight: 600, letterSpacing: "0.04em",
    }}>Q{q}</span>
  );
  // Per-period quartiles (mock, matches a mid-pack BDC profile)
  const quartiles = { "QTD": 2, "YTD": 2, "1 Year": 4, "3 Year (annlz.)": 4, "5 Year (annlz.)": 3, "10 Year (annlz.)": 2, "Since inception": 1 };

  return (
    <div style={{ padding: "56px 72px 40px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 24 }}>
        <div style={{ ...SX.card, padding: 36 }}>
          <div style={{ ...SX.eyebrowAccent }}>Total return · Since Inception (Oct 2004)</div>
          <h3 style={{ ...SX.display, fontSize: 26, margin: "4px 0 16px", letterSpacing: "-0.01em" }}>$100 invested at IPO is now $512</h3>
          <div style={{ color: T.ink }}>
            <PMWLineChart
              w={680} h={260}
              labels={FUND.sinceInception.labels}
              series={[
                { label: "ARCC total return", data: FUND.sinceInception.totalReturn, color: T.navy, strokeWidth: 2 },
                { label: "PMW BDC Index", data: [100, 130, 90, 160, 200, 225, 255, 290, 335, 388, 440], color: T.accent, strokeWidth: 2 },
                { label: "S&P 500 (total return)", data: [100, 120, 80, 135, 170, 205, 240, 285, 355, 415, 475], color: T.ink3, strokeWidth: 1.5, dash: "4 4" }
              ]}
              yFmt={(v) => "$" + v.toFixed(0)}
            />
          </div>
        </div>
        <div style={{ ...SX.card, padding: 36 }}>
          <div style={{ ...SX.eyebrowAccent }}>Total return · per period</div>
          <h3 style={{ ...SX.display, fontSize: 22, margin: "4px 0 4px", letterSpacing: "-0.01em" }}>Quartile vs. BDC universe</h3>
          <div style={{ fontSize: 12, color: T.ink3, marginBottom: 16 }}>Quartile is ARCC's rank across all {PEER_UNIVERSE.bdcsTraded.length} publicly-traded BDCs.</div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${T.rule}` }}>
                <th style={{ ...SX.eyebrow, textAlign: "left", padding: "8px 0", color: T.ink3 }}>Period</th>
                <th style={{ ...SX.eyebrow, textAlign: "right", padding: "8px 0", color: T.ink3 }}>ARCC</th>
                <th style={{ ...SX.eyebrow, textAlign: "right", padding: "8px 0", color: T.ink3 }}>Peer med</th>
                <th style={{ ...SX.eyebrow, textAlign: "right", padding: "8px 0", color: T.ink3 }}>Q</th>
              </tr>
            </thead>
            <tbody>
              {FUND.performance.rows.map((r) => (
                <tr key={r.k} style={{ borderBottom: `1px solid ${T.rule2}` }}>
                  <td style={{ padding: "12px 0", color: T.ink2 }}>{r.k}</td>
                  <td style={{ ...SX.num, padding: "12px 0", textAlign: "right", fontWeight: 600, color: T.navy }}>{r.arcc}</td>
                  <td style={{ ...SX.num, padding: "12px 0", textAlign: "right", color: T.ink3 }}>{r.bdcIdx}</td>
                  <td style={{ padding: "12px 0", textAlign: "right" }}><QChip q={quartiles[r.k] || 3} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// Other tabs reuse logic — slim placeholders importing from the original file.
// Holdings tab — re-implement compactly
function HoldingsTab() {
  const rows = FUND.topHoldings.slice(0, 12);
  return (
    <div style={{ padding: "56px 72px 40px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "28px 32px 12px" }}>
          <div style={{ ...SX.eyebrowAccent }}>Holdings · Q4 2025 N-PORT</div>
          <h3 style={{ ...SX.display, fontSize: 28, margin: "6px 0 0", letterSpacing: "-0.015em" }}>Top 12 of 332 positions</h3>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 14 }}>
          <thead>
            <tr style={{ background: T.rule3, borderTop: `1px solid ${T.rule}`, borderBottom: `1px solid ${T.rule}` }}>
              <th style={{ ...SX.eyebrow, textAlign: "left", padding: "12px 22px", color: T.ink2 }}>Portfolio Company</th>
              <th style={{ ...SX.eyebrow, textAlign: "left", padding: "12px 22px", color: T.ink2 }}>Industry</th>
              <th style={{ ...SX.eyebrow, textAlign: "left", padding: "12px 22px", color: T.ink2 }}>Position</th>
              <th style={{ ...SX.eyebrow, textAlign: "right", padding: "12px 22px", color: T.ink2 }}>Coupon</th>
              <th style={{ ...SX.eyebrow, textAlign: "right", padding: "12px 22px", color: T.ink2 }}>Maturity</th>
              <th style={{ ...SX.eyebrow, textAlign: "right", padding: "12px 22px", color: T.ink2 }}>Fair Value ($M)</th>
              <th style={{ ...SX.eyebrow, textAlign: "right", padding: "12px 22px", color: T.ink2 }}>% of NAV</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.name} style={{ borderBottom: `1px solid ${T.rule2}`, background: i % 2 ? T.rule3 : "transparent" }}>
                <td style={{ padding: "14px 22px", fontWeight: 500 }}>{r.name}</td>
                <td style={{ padding: "14px 22px", color: T.ink2, fontSize: 12 }}>{r.industry}</td>
                <td style={{ padding: "14px 22px" }}>
                  <span style={{ padding: "2px 8px", border: `1px solid ${T.rule}`, fontSize: 11, letterSpacing: "0.04em", color: T.ink2 }}>{r.type}</span>
                </td>
                <td style={{ ...SX.num, padding: "14px 22px", textAlign: "right" }}>{r.coupon != null ? r.coupon.toFixed(2) + "%" : "—"}</td>
                <td style={{ ...SX.num, padding: "14px 22px", textAlign: "right", color: T.ink2 }}>{r.maturity || "—"}</td>
                <td style={{ ...SX.num, padding: "14px 22px", textAlign: "right", fontWeight: 500 }}>{"$" + r.fv.toLocaleString()}</td>
                <td style={{ ...SX.num, padding: "14px 22px", textAlign: "right", color: T.accent, fontWeight: 600 }}>{r.pctNAV.toFixed(1) + "%"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding: "16px 28px", borderTop: `1px solid ${T.rule}`, fontSize: 12, color: T.ink3 }}>
          Top 12 shown · 320 additional positions in N-PORT &nbsp; · &nbsp;<span style={{ color: T.accent, fontWeight: 500 }}>View full N-PORT →</span>
        </div>
      </div>
    </div>
  );
}

function PortfolioTab() {
  return (
    <div style={{ padding: "56px 72px 40px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
        <div style={{ ...SX.card, padding: 36 }}>
          <div style={{ ...SX.eyebrowAccent }}>Industry exposure</div>
          <h3 style={{ ...SX.display, fontSize: 24, margin: "4px 0 16px", letterSpacing: "-0.01em" }}>By fair value</h3>
          <PMWHBars items={FUND.industries.map((s) => ({ name: s.sector, pct: s.pct }))} accent={T.accent} labelWidth={170} valueWidth={60} barHeight={10} gap={9} />
        </div>
        <div style={{ ...SX.card, padding: 36 }}>
          <div style={{ ...SX.eyebrowAccent }}>Position type mix</div>
          <h3 style={{ ...SX.display, fontSize: 24, margin: "4px 0 16px", letterSpacing: "-0.01em" }}>By fair value</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {FUND.positionTypes.map((p, i) => (
              <div key={p.type} style={{ display: "grid", gridTemplateColumns: "1fr 80px 60px", alignItems: "center", gap: 14, fontSize: 13 }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
                  <span style={{ width: 10, height: 10, background: [T.navy, T.navyMid, T.accent, T.accent2, T.ink3, T.ink4][i] }} />
                  {p.type}
                </span>
                <span style={{ position: "relative", height: 8, background: T.rule2 }}>
                  <span style={{ position: "absolute", left: 0, top: 0, height: "100%", width: `${p.pct}%`, background: [T.navy, T.navyMid, T.accent, T.accent2, T.ink3, T.ink4][i] }} />
                </span>
                <span style={{ ...SX.num, textAlign: "right", color: T.ink2 }}>{p.pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// Enhanced peer table — universe-ranked quartile chips.
// Rows are the largest BDCs by AUM (objective sort, not a curated peer set);
// Q-chips compute each fund's quartile within the full BDC universe.
function EnhancedPeerTable() {
  const peers = FUND.peersFull;
  const universe = PEER_UNIVERSE.bdcsTraded;

  // Compute quartile per column for each peer
  const cols = [
    { key: "aum",        label: "AUM ($B)",       fmt: (v) => "$" + v.toFixed(1) + "B", dir: "higher", rank: false },
    { key: "prem",       label: "Prem / Disc",    fmt: (v) => (v >= 0 ? "+" : "") + v.toFixed(1) + "%", dir: "neutral", color: (v) => v >= 0 ? T.green : T.red },
    { key: "prem3yAvg",  label: "3Y Avg Prem",    fmt: (v) => (v >= 0 ? "+" : "") + v.toFixed(1) + "%", dir: "neutral", color: (v) => v >= 0 ? T.green : T.red },
    { key: "ret1y",      label: "1Y Return",      fmt: (v) => "+" + v.toFixed(1) + "%", dir: "higher", rank: true },
    { key: "ret3y",      label: "3Y Return",      fmt: (v) => "+" + v.toFixed(1) + "%", dir: "higher", rank: true },
    { key: "dist",       label: "Dist. Rate",     fmt: (v) => v.toFixed(1) + "%", dir: "higher", color: () => T.accent },
    { key: "distCov",    label: "Cov.",           fmt: (v) => v.toFixed(2) + "×", dir: "higher", rank: true },
    { key: "nonAccrual", label: "Non-Accr.",      fmt: (v) => v.toFixed(1) + "%", dir: "lower", rank: true },
  ];

  // Rank each row against the full BDC universe, not the table set.
  function quartileMap(key, dir) {
    const values = universe.map((p) => p[key]).filter((v) => v != null);
    const sorted = [...values].sort((a, b) => dir === "higher" ? b - a : a - b);
    const map = {};
    peers.forEach((p) => {
      const v = p[key];
      if (v == null) { map[p.ticker] = null; return; }
      const rank = sorted.findIndex((x) => x === v) + 1
        || sorted.findIndex((x) => dir === "higher" ? x <= v : x >= v) + 1;
      const q = pq_quartileOf(rank, sorted.length);
      map[p.ticker] = q;
    });
    return map;
  }
  const qMaps = {};
  cols.forEach((c) => { if (c.rank) qMaps[c.key] = quartileMap(c.key, c.dir); });

  const QChip = ({ q }) => q == null ? <span style={{ color: T.ink4 }}>—</span> : (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: 22, height: 16, fontSize: 10, fontWeight: 600,
      background: q === 1 ? T.accent : q === 2 ? T.accentSoft : "transparent",
      color: q === 1 ? "#fff" : q === 2 ? T.amber : T.ink3,
      border: q >= 3 ? `1px solid ${T.rule}` : "none",
    }}>Q{q}</span>
  );

  return (
    <div style={{ padding: "0 72px 56px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "24px 32px 8px", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <div style={{ ...SX.eyebrowAccent }}>Largest BDCs · by AUM</div>
            <h3 style={{ ...SX.display, fontSize: 26, margin: "4px 0 0", letterSpacing: "-0.01em" }}>The largest publicly-traded BDCs, ranked against the full BDC universe.</h3>
            <div style={{ fontSize: 13, color: T.ink3, marginTop: 6 }}>Rows are the largest by AUM (objective sort, not a curated peer set). Q-chips show each fund's quartile within the full {PEER_UNIVERSE.bdcsTraded.length}-BDC universe — not within these eight rows.</div>
          </div>
          <span style={{ fontSize: 12, color: T.ink2 }}>View full screener →</span>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginTop: 14 }}>
          <thead>
            <tr style={{ background: T.rule3, borderTop: `1px solid ${T.rule}`, borderBottom: `1px solid ${T.rule}` }}>
              <th style={{ ...SX.eyebrow, textAlign: "left", padding: "12px 20px", color: T.ink2 }}>Fund</th>
              {cols.map((c) => (
                <th key={c.key} style={{ ...SX.eyebrow, textAlign: "right", padding: "12px 20px", color: T.ink2 }}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {peers.map((p) => (
              <tr key={p.ticker} style={{ borderBottom: `1px solid ${T.rule2}`, background: p.highlight ? T.accentSoft : "transparent" }}>
                <td style={{ padding: "14px 20px", fontWeight: p.highlight ? 700 : 600, color: T.ink }}>
                  {p.highlight && <span style={{ color: T.accent, marginRight: 6 }}>★</span>}
                  <span style={{ ...SX.num }}>{p.ticker}</span>
                  <span style={{ marginLeft: 10, color: T.ink2, fontWeight: 400 }}>{p.name}</span>
                </td>
                {cols.map((c) => {
                  const v = p[c.key];
                  const display = v == null ? "—" : c.fmt(v);
                  const col = c.color ? c.color(v) : T.ink;
                  return (
                    <td key={c.key} style={{ ...SX.num, padding: "14px 20px", textAlign: "right", color: col, fontWeight: 500 }}>
                      <div style={{ display: "inline-flex", alignItems: "center", gap: 8, justifyContent: "flex-end" }}>
                        <span>{display}</span>
                        {c.rank && <QChip q={qMaps[c.key][p.ticker]} />}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FilingsTab() {
  return (
    <div style={{ padding: "56px 72px 40px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "28px 32px 12px" }}>
          <div style={{ ...SX.eyebrowAccent }}>Recent filings · SEC EDGAR</div>
          <h3 style={{ ...SX.display, fontSize: 28, margin: "6px 0 0", letterSpacing: "-0.015em" }}>Source of all data on this page</h3>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 18 }}>
          <thead>
            <tr style={{ background: T.rule3, borderTop: `1px solid ${T.rule}`, borderBottom: `1px solid ${T.rule}` }}>
              <th style={{ ...SX.eyebrow, textAlign: "left", padding: "12px 32px", color: T.ink2 }}>Filing Date</th>
              <th style={{ ...SX.eyebrow, textAlign: "left", padding: "12px 32px", color: T.ink2 }}>Form</th>
              <th style={{ ...SX.eyebrow, textAlign: "left", padding: "12px 32px", color: T.ink2 }}>Period</th>
              <th style={{ ...SX.eyebrow, textAlign: "right", padding: "12px 32px", color: T.ink2 }}>Open</th>
            </tr>
          </thead>
          <tbody>
            {FUND.filings.map((f) => (
              <tr key={f.date + f.type} style={{ borderBottom: `1px solid ${T.rule2}` }}>
                <td style={{ ...SX.num, padding: "14px 32px" }}>{f.date}</td>
                <td style={{ padding: "14px 32px" }}><span style={{ padding: "2px 8px", border: `1px solid ${T.rule}`, fontSize: 11, letterSpacing: "0.06em", color: T.ink, fontWeight: 600 }}>{f.type}</span></td>
                <td style={{ padding: "14px 32px", color: T.ink2 }}>{f.period}</td>
                <td style={{ padding: "14px 32px", textAlign: "right", color: T.accent, fontSize: 12, fontWeight: 500 }}>EDGAR ↗</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// Overview = quick characteristics + risk flags + industries (compact)
function OverviewTab() {
  return (
    <div>
      <div style={{ padding: "56px 72px 40px" }}>
        <div style={{ background: T.navy, color: "#fff", padding: "36px 36px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 40, alignItems: "center" }}>
            <div>
              <div style={{ color: T.accent, ...SX.eyebrow, color: T.accent }}>Portfolio characteristics</div>
              <div style={{ ...SX.display, fontSize: 26, marginTop: 8, maxWidth: 220, lineHeight: 1.1 }}>The senior, floating-rate engine.</div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)" }}>
              {FUND.portfolioChars.slice(0, 5).map((p, i) =>
                <div key={p.k} style={{ borderLeft: `1px solid rgba(255,255,255,0.14)`, padding: "0 22px" }}>
                  <div style={{ fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.65)" }}>{p.k}</div>
                  <div style={{ ...SX.num, fontSize: 34, color: T.accent, fontWeight: 500, marginTop: 8 }}>{p.v}</div>
                  <div style={{ fontSize: 10, color: "rgba(255,255,255,0.55)" }}>{p.note}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      <div style={{ padding: "0 72px 56px" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 32 }}>
          <div style={{ ...SX.card, padding: 32 }}>
            <div style={{ ...SX.eyebrowAccent }}>Risk &amp; credit indicators</div>
            <h3 style={{ ...SX.display, fontSize: 24, margin: "6px 0 20px", letterSpacing: "-0.01em" }}>Credit health, glanced at.</h3>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <tbody>
                {FUND.riskFlags.slice(0, 5).map((r) => (
                  <tr key={r.k} style={{ borderBottom: `1px solid ${T.rule2}` }}>
                    <td style={{ padding: "14px 0", color: T.ink2 }}>
                      <span style={{ display: "inline-block", width: 8, height: 8, marginRight: 10, background: r.status === "ok" ? T.green : r.status === "warn" ? T.amber : T.red, borderRadius: 999 }} />
                      {r.k}
                    </td>
                    <td style={{ ...SX.num, padding: "14px 0", textAlign: "right", fontWeight: 600, fontSize: 15 }}>{r.v}</td>
                    <td style={{ padding: "14px 0", paddingLeft: 14, color: T.ink3, fontSize: 11, textAlign: "right", maxWidth: 220 }}>{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ ...SX.card, padding: 32 }}>
            <div style={{ ...SX.eyebrowAccent }}>Top industries</div>
            <h3 style={{ ...SX.display, fontSize: 24, margin: "6px 0 20px", letterSpacing: "-0.01em" }}>By fair value</h3>
            <PMWHBars items={FUND.industries.slice(0, 8).map((s) => ({ name: s.sector, pct: s.pct }))} accent={T.accent} labelWidth={170} valueWidth={56} barHeight={10} gap={12} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── App ──────────────────────────────────────────────────────────────────────
function FundDetailBDCApp() {
  const [tab, setTab] = React.useState("overview");
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "holdings", label: "Holdings", count: 332 },
    { id: "portfolio", label: "Portfolio breakdown" },
    { id: "performance", label: "Performance" },
    { id: "filings", label: "Filings", count: FUND.filings.length },
  ];
  const crumbs = [
    { label: "Home",  href: "index.html" },
    { label: "Funds", href: "index.html#universe" },
    { label: "Business Development Companies" },
    { label: "ARCC" },
  ];
  return (
    <div style={SX.root}>
      <FundHeader T={T} SX={SX} otherFundLink="Fund Detail v3 - Interval.html" otherFundLabel="Interval template" />
      <Breadcrumb T={T} items={crumbs} />
      <BDCIdentity />
      <PeerStandingBDC />
      <SpreadAnalysis />
      <PriceChart />
      <TabBar tabs={tabs} active={tab} onChange={setTab} />
      {tab === "overview" && <OverviewTab />}
      {tab === "holdings" && <HoldingsTab />}
      {tab === "portfolio" && <PortfolioTab />}
      {tab === "performance" && <PerformanceTab />}
      {tab === "filings" && <FilingsTab />}
      <EnhancedPeerTable />
      <FundFooter T={T} SX={SX} />
    </div>
  );
}

window.FundDetailBDCApp = FundDetailBDCApp;
