/* eslint-disable */
// Fund Detail v3 — Interval / tender-offer variant. CCLFX.
//
// Editorial brief: interval funds are NOT exchange-listed. There is no
// market price and therefore no NAV–price spread. The structural signals
// in this template are:
//   - Quartile rankings of NAV-based total return vs. interval-fund peers
//   - Distribution coverage ratio and rate
//   - Tender history (the liquidity equivalent of "spread")
//   - Standard deviation / max drawdown vs. peers (less rate-cycle exposed)
//
// Compared to the BDC template:
//   ✗ Price / NAV spread block      ✓ Liquidity-terms block
//   ✗ "Last Price" headline         ✓ NAV is the transaction price
//   ✗ 10-K / 10-Q filings           ✓ N-2, N-CSR, N-CSRS, N-PORT

const T = T_V3,SX = SX_V3;
const FI = FUND_INTERVAL;

// ── Identity ─────────────────────────────────────────────────────────────────
function IntervalIdentity() {
  const f = FI.identity;
  const R = PEER_UNIVERSE.ranks.CCLFX;

  const Stat = ({ label, value, sub, quartile, big = false, color }) =>
  <div style={{ borderTop: `1px solid ${T.rule2}`, paddingTop: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ ...SX.eyebrow, color: T.ink3 }}>{label}</div>
        {quartile &&
      <span style={{ fontSize: 9, fontWeight: 600, letterSpacing: "0.08em", color: quartile.q <= 2 ? T.accent : T.ink3 }}>
            Q{quartile.q} · {pq_ordinal(quartile.rank)} of {quartile.total}
          </span>
      }
      </div>
      <div style={{ ...SX.display, fontSize: big ? 36 : 28, color: color || T.ink, letterSpacing: "-0.02em", marginTop: 4, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: T.ink3, marginTop: 4 }}>{sub}</div>}
    </div>;


  return (
    <div style={{ padding: "32px 72px 40px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1.4fr", gap: 36, alignItems: "start" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
            <span style={{ padding: "3px 9px", background: T.navy, color: "#fff", ...SX.eyebrow, color: "#fff", fontSize: 10 }}>Interval Fund</span>
            <span style={{ padding: "3px 9px", border: `1px solid ${T.rule}`, ...SX.eyebrow, color: T.ink2, fontSize: 10 }}>Semi-Liquid · Quarterly Tender</span>
            <span style={{ padding: "3px 9px", border: `1px solid ${T.accent}`, color: T.accent, ...SX.eyebrow, color: T.accent, fontSize: 10 }}>Index member · Direct Lending</span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap" }}>
            <h1 style={{ ...SX.display, fontSize: 48, margin: 0, letterSpacing: "-0.025em", lineHeight: 1.04 }}>{f.name}</h1>
            <span style={{ ...SX.display, fontSize: 32, color: T.accent }}>({f.ticker})</span>
          </div>
          <div style={{ display: "flex", gap: 22, marginTop: 14, fontSize: 12, color: T.ink2, flexWrap: "wrap" }}>
            <span><span style={{ color: T.ink3 }}>CIK</span> &nbsp;<span style={{ ...SX.num }}>{f.cik}</span></span>
            <span><span style={{ color: T.ink3 }}>Manager</span> &nbsp;{f.manager}</span>
            <span><span style={{ color: T.ink3 }}>Inception</span> &nbsp;{f.inception}</span>
            <span><span style={{ color: T.ink3 }}>HQ</span> &nbsp;Marina del Rey, CA</span>
          </div>
          <p style={{ fontSize: 15, lineHeight: 1.55, color: T.ink2, maxWidth: 620, marginTop: 18 }}>
            The largest credit-focused interval fund by AUM. CCLFX is a continuously offered, daily-priced 1940 Act fund providing access to a broadly diversified portfolio of senior secured middle-market loans, originated through a network of more than 90 sub-managers.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 22, flexWrap: "wrap" }}>
            <span style={{ padding: "10px 18px", background: T.navy, color: "#fff", fontSize: 13, fontWeight: 500, letterSpacing: "0.04em" }}>+ Watchlist</span>
            <span style={{ padding: "10px 18px", border: `1px solid ${T.rule}`, color: T.ink, fontSize: 13, fontWeight: 500 }}>EDGAR filings ↗</span>
            <a href="Fund Detail v3 - BDC.html" style={{ padding: "10px 18px", border: `1px solid ${T.accent}`, color: T.accent, fontSize: 13, fontWeight: 500, textDecoration: "none" }}>View BDC template →</a>
          </div>
        </div>
        <div style={{ ...SX.card, padding: 36 }}>
          {/* HERO: NAV is the transaction price for an interval fund — make it the
              centerpiece of the card, with an explicit "as of" stamp. */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <span style={{ ...SX.eyebrowAccent }}>NAV per share · as of Dec 31, 2025</span>
            <span style={{ fontSize: 10, letterSpacing: "0.14em", textTransform: "uppercase", color: T.ink3 }}>{f.asOf}</span>
          </div>
          <div style={{ ...SX.display, ...SX.num, fontSize: 72, lineHeight: 1, color: T.ink, letterSpacing: "-0.03em", marginTop: 10, fontWeight: 600 }}>
            ${f.navPerShare.toFixed(2)}
          </div>
          <div style={{ fontSize: 12, color: T.ink3, marginTop: 8, maxWidth: 360 }}>
            Daily-struck transaction price — interval funds redeem and subscribe at NAV, not a market price.
          </div>

          {/* SUPPORTING STATS — three secondary numbers in a row, clearly lower in
              the visual hierarchy than the NAV headline. */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", columnGap: 22, marginTop: 28, paddingTop: 18, borderTop: `1px solid ${T.rule}` }}>
            <Stat label="AUM" value={"$" + f.aum.toFixed(1) + "B"} sub={`${f.sharesOut.toFixed(0)}M shares · Largest credit interval fund`} />
            <Stat
              label="Distribution"
              value={f.distRate.toFixed(2) + "%"}
              sub={`${f.distCadence}`}
              color={T.accent}
              quartile={{ q: pq_quartileOf(R.vsAll.dist.rank, R.vsAll.dist.total), rank: R.vsAll.dist.rank, total: R.vsAll.dist.total }} />
            <Stat
              label="YTD return"
              value={"+" + f.ytdReturn.toFixed(1) + "%"}
              sub="NAV total return"
              color={T.green} />
          </div>
          <div style={{ marginTop: 22, padding: "14px 16px", background: T.rule3, borderLeft: `2px solid ${T.accent}`, fontSize: 12, color: T.ink2, lineHeight: 1.5 }}>
            <strong style={{ color: T.ink }}>No market price.</strong> Interval funds transact at NAV, with redemption available only through periodic tender offers. The block we'd show for premium/discount is replaced with <a href="#liquidity" style={{ color: T.accent, textDecoration: "none" }}>tender history</a>.
          </div>
        </div>
      </div>
    </div>);

}

// ── Peer standing band — different metric set ────────────────────────────────
function PeerStandingInterval() {
  const U = PEER_UNIVERSE;
  const R = U.ranks.CCLFX;
  const all = U.creditAll;
  const ivs = U.intervalsTender;
  const items = [
  {
    key: "ret3y",
    label: "3Y total return (annlz.)",
    value: R.vsAll.ret3y.value,
    valueFmt: (v) => "+" + v.toFixed(1) + "%",
    rank: R.vsAll.ret3y.rank,
    total: R.vsAll.ret3y.total,
    totalLabel: "credit funds",
    direction: "higher",
    distribution: all.map((p) => p.ret3y)
  },
  {
    key: "distCov",
    label: "Distribution coverage",
    value: R.vsAll.distCov.value,
    valueFmt: (v) => v.toFixed(2) + "×",
    rank: R.vsAll.distCov.rank,
    total: R.vsAll.distCov.total,
    totalLabel: "credit funds",
    direction: "higher",
    distribution: all.map((p) => p.distCov)
  },
  {
    key: "drawdown",
    label: "Max drawdown · 3Y",
    value: R.vsInterval.drawdown.value,
    valueFmt: (v) => v.toFixed(1) + "%",
    rank: R.vsInterval.drawdown.rank,
    total: R.vsInterval.drawdown.total,
    totalLabel: "interval funds",
    direction: "higher",
    distribution: ivs.map((p) => p.drawdown)
  }];

  return (
    <PeerStandingBand
      items={items}
      T={T}
      ticker="CCLFX"
      eyebrow="Peer Standing · Q4 2025"
      title="How CCLFX ranks across the full universe."
      subtitle="NAV-based total return — interval funds have no market price, so we cannot rank by spread or by capital-account proxies. Returns and coverage are ranked across the full SEC-registered credit universe (~140 funds); drawdown is interval-only since BDC volatility is structurally different."
      footnote="Universe: 95 interval &amp; tender-offer funds + 47 traded BDCs. Data: SEC filings (N-CSR, N-PORT, 10-K, 10-Q)." />);


}

// ── Liquidity terms + tender history — replaces NAV-price spread ─────────────
function LiquidityTerms() {
  const t = FI.liquidity;
  const hist = FI.tenderHistory;
  const U = PEER_UNIVERSE;
  const ivs = U.intervalsTender;
  const R = U.ranks.CCLFX.vsInterval.prorata;
  const proDist = ivs.map((p) => p.prorata);

  // Bar chart of demand vs 5% cap
  const Bar = ({ tendered, offered, fulfilled, prorata, date }) => {
    const w = 100;
    const tenderedW = Math.min(tendered / 7, 1) * w; // scale to 7% max axis
    const offeredW = Math.min(offered / 7, 1) * w;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ position: "relative", height: 22, background: T.rule3, border: `1px solid ${T.rule2}` }}>
          {/* offered cap line */}
          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: offeredW + "%", background: T.rule2 }} />
          {/* tendered demand */}
          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: tenderedW + "%", background: prorata ? T.amber : T.accent, opacity: 0.85 }} />
          {/* offered marker */}
          <div style={{ position: "absolute", left: offeredW + "%", top: -2, bottom: -2, width: 2, background: T.ink }} />
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: T.ink3 }}>
          <span style={{ ...SX.num }}>{date.slice(2)}</span>
          <span style={{ ...SX.num, fontWeight: 600, color: prorata ? T.amber : T.ink }}>{tendered.toFixed(1)}% demand</span>
        </div>
      </div>);

  };

  return (
    <div id="liquidity" style={{ padding: "0 72px 56px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "28px 36px 18px", borderBottom: `1px solid ${T.rule2}` }}>
          <div>
            <div style={{ ...SX.eyebrowAccent }}>Liquidity terms · Interval-fund specific</div>
            <h2 style={{ ...SX.display, fontSize: 30, margin: "6px 0 0", letterSpacing: "-0.015em" }}>Redemption mechanics</h2>
            <div style={{ fontSize: 13, color: T.ink2, marginTop: 8, maxWidth: 760 }}>
              Interval funds offer shareholders periodic exits via tender offers — the 1940 Act allows repurchases of 5–25% of shares per offer. When tender demand exceeds the offer size, redemptions are pro-rated and shareholders wait a future window to exit fully. This is the closest analogue to a BDC's NAV–price spread: the marginal seller takes a haircut on timing rather than price.
            </div>
          </div>
        </div>

        <div style={{ display: "block" }}>
          {/* PRIMARY: tender history — promoted to full width per teammate feedback (the chart IS the story; structural terms are reference) */}
          <div style={{ padding: "28px 36px 24px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14 }}>
              <div style={{ ...SX.eyebrow, color: T.ink3 }}>Tender history · trailing 8 quarters</div>
              <div style={{ display: "flex", gap: 14, fontSize: 10, color: T.ink2 }}>
                <span><span style={{ display: "inline-block", width: 10, height: 8, background: T.accent, verticalAlign: "middle" }} /> &nbsp;Fully filled</span>
                <span><span style={{ display: "inline-block", width: 10, height: 8, background: T.amber, verticalAlign: "middle" }} /> &nbsp;Pro-rated</span>
                <span><span style={{ display: "inline-block", width: 2, height: 10, background: T.ink, verticalAlign: "middle" }} /> &nbsp;5% cap</span>
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(8, 1fr)", gap: 14 }}>
              {hist.map((h) =>
              <Bar key={h.date} tendered={h.tendered} offered={h.offered} fulfilled={h.fulfilled} prorata={h.prorata} date={h.date} />
              )}
            </div>

            {/* Peer context — moved out of the panel header so it sits next to the chart it contextualizes */}
            <div style={{ marginTop: 24, paddingTop: 18, borderTop: `1px solid ${T.rule2}`, display: "grid", gridTemplateColumns: "1fr auto", alignItems: "center", gap: 32 }}>
              <div>
                <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 6 }}>vs. peer interval funds</div>
                <div style={{ fontSize: 14, color: T.ink, lineHeight: 1.5, maxWidth: 420 }}>
                  CCLFX pro-rated <span style={{ ...SX.num, fontWeight: 700 }}>{R.value}</span> of the last 8 quarters — ranking <span style={{ ...SX.num, fontWeight: 700 }}>{R.rank}</span> of <span style={{ ...SX.num }}>{R.total}</span> interval funds. Higher pro-ration means more frequent rationing of exits.
                </div>
              </div>
              <QuartileBadge
                metric="Pro-rated tenders · last 8 qtrs"
                rank={R.rank}
                total={R.total}
                totalLabel="interval funds"
                value={R.value}
                valueFmt={(v) => v + (v === 1 ? " qtr" : " qtrs")}
                note="Higher = more rationing"
                direction="lower"
                distribution={proDist}
                ticker="CCLFX"
                T={T}
                densityW={280}
                densityH={64}
                compact />
            </div>

            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginTop: 22 }}>
              <thead>
                <tr style={{ borderTop: `1px solid ${T.rule2}`, borderBottom: `1px solid ${T.rule2}` }}>
                  <th style={{ ...SX.eyebrow, textAlign: "left", padding: "10px 12px", color: T.ink3 }}>Pricing Date</th>
                  <th style={{ ...SX.eyebrow, textAlign: "right", padding: "10px 12px", color: T.ink3 }}>Offered</th>
                  <th style={{ ...SX.eyebrow, textAlign: "right", padding: "10px 12px", color: T.ink3 }}>Tendered</th>
                  <th style={{ ...SX.eyebrow, textAlign: "right", padding: "10px 12px", color: T.ink3 }}>Fulfilled</th>
                  <th style={{ ...SX.eyebrow, textAlign: "right", padding: "10px 12px", color: T.ink3 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {hist.slice().reverse().slice(0, 4).map((h) =>
                <tr key={h.date} style={{ borderBottom: `1px solid ${T.rule2}` }}>
                    <td style={{ ...SX.num, padding: "10px 12px" }}>{h.date}</td>
                    <td style={{ ...SX.num, padding: "10px 12px", textAlign: "right" }}>{h.offered.toFixed(1)}%</td>
                    <td style={{ ...SX.num, padding: "10px 12px", textAlign: "right", color: h.prorata ? T.amber : T.ink, fontWeight: h.prorata ? 600 : 500 }}>{h.tendered.toFixed(1)}%</td>
                    <td style={{ ...SX.num, padding: "10px 12px", textAlign: "right" }}>{h.fulfilled}%</td>
                    <td style={{ padding: "10px 12px", textAlign: "right", color: h.prorata ? T.amber : T.green, fontSize: 11, fontWeight: 600 }}>{h.prorata ? "PRO-RATED" : "FULLY FILLED"}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {/* SECONDARY: structural terms — collapsible. Key redemption mechanics (frequency / size / notice / fee) stay visible inline because they're the chart's parameters; the rest hide behind a disclosure. */}
          <div style={{ padding: "20px 36px 28px", borderTop: `1px solid ${T.rule2}` }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 24, marginBottom: 4 }}>
              {[
              ["Tender frequency", t.tenderFrequency],
              ["Offer size", t.tenderSize],
              ["Notice window", t.tenderNotice],
              ["Early-redemption fee", t.earlyRedemptionFee]].
              map(([k, v]) =>
              <div key={k}>
                  <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 4 }}>{k}</div>
                  <div style={{ ...SX.num, fontSize: 15, color: T.ink, fontWeight: 600 }}>{v}</div>
                </div>
              )}
            </div>
            <details style={{ marginTop: 18 }}>
              <summary style={{ ...SX.eyebrow, color: T.ink3, cursor: "pointer", padding: "6px 0", listStyle: "none", display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 9 }}>▾</span> View all structural terms
              </summary>
              <div style={{ marginTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 36, rowGap: 0, maxWidth: 920 }}>
                {[
                ["Structure", t.structure],
                ["Listing", t.listing],
                ["Transaction price", t.transactionPrice],
                ["Tender frequency", t.tenderFrequency],
                ["Tender size", t.tenderSize],
                ["Notice window", t.tenderNotice],
                ["Early-redemption fee", t.earlyRedemptionFee],
                ["Minimum investment", t.minimumInvestment],
                ["Lock-up", t.lockup],
                ["Soft close", t.softClose]].
                map(([k, v], i) =>
                <div key={k} style={{ display: "grid", gridTemplateColumns: "150px 1fr", padding: "10px 0", borderTop: i < 2 ? "none" : `1px solid ${T.rule2}`, fontSize: 12 }}>
                    <span style={{ color: T.ink3 }}>{k}</span>
                    <span style={{ color: T.ink, fontWeight: 500 }}>{v}</span>
                  </div>
                )}
              </div>
            </details>
          </div>
        </div>
      </div>
    </div>);

}

// ── Return composition — cash distributed vs. NAV change, with TR as reference ──
// Replaces the old single-line "$100 grew to $X" view, which baked in a
// reinvest-at-NAV assumption most income investors don't actually follow.
// Decomposition makes the cash-vs-NAV trade-off visible.
function NAVChart() {
  // Default to LTM — "trailing 12 months" is the natural basis for an income figure
  // (yield-equivalent). 3Y stays available for the multi-year cumulative view.
  const [tf, setTf] = React.useState("LTM");
  const slice = tf === "LTM" ? -4 : -12;
  const quarters = FI.history.quarters.slice(slice);
  const navs = FI.history.nav.slice(slice);
  const distQ = FI.history.distQ.slice(slice);
  const startNav = navs[0];
  const startShares = 100 / startNav;
  // Cumulative cash distributed per $100 invested (NOT reinvested)
  let runningCash = 0;
  const cumCash = distQ.map(d => (runningCash += startShares * d));
  // NAV value of those original shares per $100 invested
  const navVal = navs.map(nav => startShares * nav);

  const cashEnd = cumCash[cumCash.length - 1];
  const navEnd = navVal[navVal.length - 1];
  const navChangePct = ((navEnd - 100) / 100) * 100;

  // Distribution coverage figure (static from data file, but framed here)
  const distCoverage = 1.06;

  return (
    <div style={{ padding: "0 72px 56px" }}>
      <div style={{ ...SX.card, padding: 32 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 18 }}>
          <div>
            <div style={{ ...SX.eyebrowAccent }}>Return composition</div>
            <h3 style={{ ...SX.display, fontSize: 24, margin: "4px 0 0", letterSpacing: "-0.01em" }}>Where the return came from</h3>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            {["LTM", "3Y"].map((p) =>
            <span key={p} onClick={() => setTf(p)} style={tf === p ? SX.pillActive : SX.pillInactive}>{p}</span>
            )}
          </div>
        </div>

        {/* KPI strip — cash distributed + NAV change as the two unambiguous components of
            no-reinvestment return. A reinvested-TR figure is intentionally omitted: it lives
            on a different basis (compounded back into the fund) and would mix accounting
            conventions inside one card. Total return with reinvestment lives in the
            performance table elsewhere on the page. */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 0, borderTop: `1px solid ${T.rule2}`, borderBottom: `1px solid ${T.rule2}` }}>
          {[
            {
              label: tf === "LTM" ? "Cash distributed · LTM" : "Cash distributed · 3Y cumulative",
              value: "$" + cashEnd.toFixed(2),
              caption: `per $100 invested, ${tf === "LTM" ? "trailing 12 months" : "summed over 3 years"}`,
              color: T.accent,
            },
            {
              label: tf === "LTM" ? "NAV change · LTM" : "NAV change · 3Y",
              value: (navChangePct >= 0 ? "+" : "") + navChangePct.toFixed(1) + "%",
              caption: `original shares now worth $${navEnd.toFixed(2)}`,
              color: T.ink,
            },
          ].map((k, i) => (
            <div key={k.label} style={{ padding: "18px 22px", borderRight: i < 1 ? `1px solid ${T.rule2}` : "none" }}>
              <div style={{ ...SX.eyebrow, color: T.ink3, marginBottom: 6 }}>{k.label}</div>
              <div style={{ ...SX.num, fontSize: 26, fontWeight: 600, color: k.color, lineHeight: 1 }}>{k.value}</div>
              <div style={{ fontSize: 11, color: T.ink3, marginTop: 6 }}>{k.caption}</div>
            </div>
          ))}
        </div>

        {/* Attribution bar — what fraction of total return came from cash vs. NAV change.
            Replaces the old stacked-area chart, which for an interval fund was visually two
            near-parallel lines: NAV is structurally flat, cash accumulates ~linearly, so the
            chart added noise without insight. A single split bar answers the question an
            income investor actually has — "is this an income story or a price story?" */}
        {(() => {
          // Components of total return, in percentage points of starting capital.
          // cashEnd is already $/$100, which equals % contribution to return.
          const cashContrib = cashEnd;
          const navContrib = navChangePct;
          const grossContrib = Math.abs(cashContrib) + Math.abs(navContrib);
          const cashW = grossContrib > 0 ? (Math.abs(cashContrib) / grossContrib) * 100 : 50;
          const navW = 100 - cashW;
          const cashShare = Math.round(cashW);
          const navShare = 100 - cashShare;
          const navIsNeg = navContrib < 0;
          return (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 10 }}>
                <span style={{ ...SX.eyebrow, color: T.ink3 }}>Return attribution · {tf}</span>
                <span style={{ fontSize: 11, color: T.ink3 }}>
                  Of every dollar of return, <span style={{ ...SX.num, color: T.ink, fontWeight: 600 }}>{cashShare}¢</span> came from cash income, <span style={{ ...SX.num, color: T.ink, fontWeight: 600 }}>{navShare}¢</span> from NAV change.
                </span>
              </div>
              <div style={{ display: "flex", height: 32, width: "100%", border: `1px solid ${T.rule2}` }}>
                <div style={{ width: `${cashW}%`, background: T.accent, display: "flex", alignItems: "center", justifyContent: "flex-start", padding: "0 12px", color: "#fff", overflow: "hidden", whiteSpace: "nowrap" }}>
                  {cashW > 22 && (
                    <span style={{ ...SX.num, fontSize: 12, fontWeight: 600 }}>
                      Cash income&nbsp;&nbsp;+{cashContrib.toFixed(1)}%
                    </span>
                  )}
                </div>
                <div style={{ width: `${navW}%`, background: navIsNeg ? T.ink3 : T.ink, display: "flex", alignItems: "center", justifyContent: "flex-start", padding: "0 12px", color: "#fff", overflow: "hidden", whiteSpace: "nowrap" }}>
                  {navW > 22 && (
                    <span style={{ ...SX.num, fontSize: 12, fontWeight: 600 }}>
                      NAV change&nbsp;&nbsp;{navContrib >= 0 ? "+" : ""}{navContrib.toFixed(1)}%
                    </span>
                  )}
                </div>
              </div>
              {/* Inline labels for any segment too narrow to hold its text inside the bar */}
              {(cashW <= 22 || navW <= 22) && (
                <div style={{ display: "flex", marginTop: 6, fontSize: 11, color: T.ink2 }}>
                  {cashW <= 22 && (
                    <span style={{ width: `${cashW}%` }}>
                      <span style={{ display: "inline-block", width: 8, height: 8, background: T.accent, marginRight: 6, verticalAlign: "middle" }} />
                      <span style={{ ...SX.num }}>Cash +{cashContrib.toFixed(1)}%</span>
                    </span>
                  )}
                  {navW <= 22 && (
                    <span style={{ width: `${navW}%`, marginLeft: cashW <= 22 ? 0 : `${cashW}%` }}>
                      <span style={{ display: "inline-block", width: 8, height: 8, background: navIsNeg ? T.ink3 : T.ink, marginRight: 6, verticalAlign: "middle" }} />
                      <span style={{ ...SX.num }}>NAV {navContrib >= 0 ? "+" : ""}{navContrib.toFixed(1)}%</span>
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })()}

        {/* Distribution coverage — the sustainability check that an income investor cares about most */}
        <div style={{ marginTop: 20, paddingTop: 16, borderTop: `1px solid ${T.rule2}`, display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 24, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
            <span style={{ ...SX.eyebrow, color: T.ink3 }}>Distribution coverage</span>
            <span style={{ ...SX.num, fontSize: 22, color: T.ink, fontWeight: 600 }}>{distCoverage.toFixed(2)}×</span>
            <span style={{ fontSize: 11, color: distCoverage >= 1 ? T.green : T.amber, textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600 }}>
              {distCoverage >= 1 ? "Fully earned" : "Under-earned"}
            </span>
          </div>
          <span style={{ fontSize: 12, color: T.ink3, fontStyle: "italic" }}>
            Net investment income / distributions paid. &gt;1.0× means distributions are funded from earnings, not capital.
          </span>
        </div>
      </div>
    </div>);
}

// ── Tab bar ──────────────────────────────────────────────────────────────────
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
    </div>);

}

function OverviewTab() {
  return (
    <div>
      <div style={{ padding: "56px 72px 40px" }}>
        <div style={{ background: T.navy, color: "#fff", padding: "36px 36px" }}>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 40, alignItems: "center" }}>
            <div>
              <div style={{ color: T.accent, ...SX.eyebrow, color: T.accent }}>Portfolio characteristics</div>
              <div style={{ ...SX.display, fontSize: 26, marginTop: 8, maxWidth: 220, lineHeight: 1.1 }}>92% first-lien, daily-priced.</div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)" }}>
              {FI.portfolioChars.slice(0, 5).map((p) =>
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
            <div style={{ ...SX.eyebrowAccent }}>Risk &amp; liquidity indicators</div>
            <h3 style={{ ...SX.display, fontSize: 24, margin: "6px 0 20px", letterSpacing: "-0.01em" }}>Credit health and tender headroom.</h3>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <tbody>
                {FI.riskFlags.map((r) =>
                <tr key={r.k} style={{ borderBottom: `1px solid ${T.rule2}` }}>
                    <td style={{ padding: "14px 0", color: T.ink2 }}>
                      <span style={{ display: "inline-block", width: 8, height: 8, marginRight: 10, background: r.status === "ok" ? T.green : r.status === "warn" ? T.amber : T.red, borderRadius: 999 }} />
                      {r.k}
                    </td>
                    <td style={{ ...SX.num, padding: "14px 0", textAlign: "right", fontWeight: 600, fontSize: 15 }}>{r.v}</td>
                    <td style={{ padding: "14px 0", paddingLeft: 14, color: T.ink3, fontSize: 11, textAlign: "right", maxWidth: 220 }}>{r.note}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div style={{ ...SX.card, padding: 32 }}>
            <div style={{ ...SX.eyebrowAccent }}>Top industries</div>
            <h3 style={{ ...SX.display, fontSize: 24, margin: "6px 0 20px", letterSpacing: "-0.01em" }}>By fair value</h3>
            <PMWHBars items={FI.industries.slice(0, 8).map((s) => ({ name: s.sector, pct: s.pct }))} accent={T.accent} labelWidth={170} valueWidth={56} barHeight={10} gap={12} />
          </div>
        </div>
      </div>
    </div>);

}

function HoldingsTab() {
  const rows = FI.topHoldings;
  return (
    <div style={{ padding: "56px 72px 40px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "28px 32px 12px" }}>
          <div style={{ ...SX.eyebrowAccent }}>Holdings · Q4 2025 N-PORT</div>
          <h3 style={{ ...SX.display, fontSize: 28, margin: "6px 0 0", letterSpacing: "-0.015em" }}>Top {rows.length} of 1,247 positions</h3>
          <div style={{ fontSize: 12, color: T.ink3, marginTop: 6, fontStyle: "italic" }}>Interval funds disclose at the same N-PORT cadence as BDCs, but position concentration is much lower — the largest holding is 14.4% (a feeder structure); all others are sub-1.5%.</div>
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
            {rows.map((r, i) =>
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
            )}
          </tbody>
        </table>
        <div style={{ padding: "16px 28px", borderTop: `1px solid ${T.rule}`, fontSize: 12, color: T.ink3 }}>
          Top 8 shown · 1,239 additional positions · <span style={{ color: T.accent, fontWeight: 500 }}>View full N-PORT →</span>
        </div>
      </div>
    </div>);

}

function PortfolioTab() {
  return (
    <div style={{ padding: "56px 72px 40px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
        <div style={{ ...SX.card, padding: 36 }}>
          <div style={{ ...SX.eyebrowAccent }}>Industry exposure</div>
          <h3 style={{ ...SX.display, fontSize: 24, margin: "4px 0 16px", letterSpacing: "-0.01em" }}>By fair value</h3>
          <PMWHBars items={FI.industries.map((s) => ({ name: s.sector, pct: s.pct }))} accent={T.accent} labelWidth={170} valueWidth={60} barHeight={10} gap={9} />
        </div>
        <div style={{ ...SX.card, padding: 36 }}>
          <div style={{ ...SX.eyebrowAccent }}>Position type mix</div>
          <h3 style={{ ...SX.display, fontSize: 24, margin: "4px 0 16px", letterSpacing: "-0.01em" }}>By fair value</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {FI.positionTypes.map((p, i) =>
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
            )}
          </div>
        </div>
      </div>
    </div>);

}

function PerformanceTab() {
  const QChip = ({ q }) =>
  <span style={{
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    minWidth: 32, padding: "2px 8px",
    background: q === 1 ? T.accent : q === 2 ? T.accentSoft : T.rule2,
    color: q === 1 ? "#fff" : q === 2 ? T.amber : T.ink2,
    fontSize: 11, fontWeight: 600, letterSpacing: "0.04em"
  }}>Q{q}</span>;

  return (
    <div style={{ padding: "56px 72px 40px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 24 }}>
        <div style={{ ...SX.card, padding: 36 }}>
          <div style={{ ...SX.eyebrowAccent }}>Total return · Since Inception (Mar 2019)</div>
          <h3 style={{ ...SX.display, fontSize: 26, margin: "4px 0 16px", letterSpacing: "-0.01em" }}>$100 invested at launch is now ${FI.sinceInception.totalReturn[FI.sinceInception.totalReturn.length - 1]}</h3>
          <div style={{ color: T.ink }}>
            <PMWLineChart
              w={680} h={260}
              labels={FI.sinceInception.labels}
              series={[
              { label: "CCLFX (NAV TR)", data: FI.sinceInception.totalReturn, color: T.navy, strokeWidth: 2 },
              { label: "Interval-fund universe median", data: [100, 105, 113, 120, 128, 138, 149], color: T.accent, strokeWidth: 1.8 },
              { label: "PMW Direct Lending Index", data: [100, 108, 117, 125, 134, 143, 152], color: T.ink3, strokeWidth: 1.4, dash: "4 4" }]
              }
              yFmt={(v) => "$" + v.toFixed(0)} />
            
          </div>
        </div>
        <div style={{ ...SX.card, padding: 36 }}>
          <div style={{ ...SX.eyebrowAccent }}>Total return · per period</div>
          <h3 style={{ ...SX.display, fontSize: 22, margin: "4px 0 4px", letterSpacing: "-0.01em" }}>Quartile vs. credit universe</h3>
          <div style={{ fontSize: 12, color: T.ink3, marginBottom: 16 }}>Quartile is CCLFX's NAV-based rank across the full credit universe (~140 SEC-registered BDCs &amp; interval funds).</div>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${T.rule}` }}>
                <th style={{ ...SX.eyebrow, textAlign: "left", padding: "8px 0", color: T.ink3 }}>Period</th>
                <th style={{ ...SX.eyebrow, textAlign: "right", padding: "8px 0", color: T.ink3 }}>CCLFX</th>
                <th style={{ ...SX.eyebrow, textAlign: "right", padding: "8px 0", color: T.ink3 }}>Univ. med</th>
                <th style={{ ...SX.eyebrow, textAlign: "right", padding: "8px 0", color: T.ink3 }}>Q</th>
              </tr>
            </thead>
            <tbody>
              {FI.performance.rows.map((r) =>
              <tr key={r.k} style={{ borderBottom: `1px solid ${T.rule2}` }}>
                  <td style={{ padding: "12px 0", color: T.ink2 }}>{r.k}</td>
                  <td style={{ ...SX.num, padding: "12px 0", textAlign: "right", fontWeight: 600, color: T.navy }}>{r.fund}</td>
                  <td style={{ ...SX.num, padding: "12px 0", textAlign: "right", color: T.ink3 }}>{r.peerMed}</td>
                  <td style={{ padding: "12px 0", textAlign: "right" }}><QChip q={r.quartile} /></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>);

}

function FilingsTab() {
  return (
    <div style={{ padding: "56px 72px 40px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "28px 32px 12px" }}>
          <div style={{ ...SX.eyebrowAccent }}>Recent filings · SEC EDGAR</div>
          <h3 style={{ ...SX.display, fontSize: 28, margin: "6px 0 0", letterSpacing: "-0.015em" }}>Source of all data on this page</h3>
          <div style={{ fontSize: 13, color: T.ink3, marginTop: 6, maxWidth: 540 }}>Interval funds file under the closed-end fund regime: N-2 for registration, N-CSR/N-CSRS for periodic reports, N-PORT for monthly portfolios.</div>
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
            {FI.filings.map((f) =>
            <tr key={f.date + f.type} style={{ borderBottom: `1px solid ${T.rule2}` }}>
                <td style={{ ...SX.num, padding: "14px 32px" }}>{f.date}</td>
                <td style={{ padding: "14px 32px" }}><span style={{ padding: "2px 8px", border: `1px solid ${T.rule}`, fontSize: 11, letterSpacing: "0.06em", color: T.ink, fontWeight: 600 }}>{f.type}</span></td>
                <td style={{ padding: "14px 32px", color: T.ink2 }}>{f.period}</td>
                <td style={{ padding: "14px 32px", textAlign: "right", color: T.accent, fontSize: 12, fontWeight: 500 }}>EDGAR ↗</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>);

}

// Enhanced peer comparison — table of the largest-by-AUM credit interval funds.
// Quartile chips are computed against the FULL interval-fund universe, not
// the table's own row set, so the chips reflect universe rank — not an
// artificial in-table rank.
function EnhancedPeerTable() {
  const peers = FI.peersFull;
  const universe = PEER_UNIVERSE.intervalsTender;
  const cols = [
  { key: "aum", label: "AUM ($B)", fmt: (v) => "$" + v.toFixed(1) + "B", dir: "higher", rank: false },
  { key: "ret1y", label: "1Y NAV TR", fmt: (v) => "+" + v.toFixed(1) + "%", dir: "higher", rank: true },
  { key: "ret3y", label: "3Y NAV TR", fmt: (v) => "+" + v.toFixed(1) + "%", dir: "higher", rank: true },
  { key: "dist", label: "Dist. Rate", fmt: (v) => v.toFixed(2) + "%", dir: "higher", color: () => T.accent },
  { key: "distCov", label: "Cov.", fmt: (v) => v.toFixed(2) + "×", dir: "higher", rank: true },
  { key: "stdev", label: "Stdev", fmt: (v) => v.toFixed(1) + "%", dir: "lower", rank: true },
  { key: "drawdown", label: "Max DD", fmt: (v) => v.toFixed(1) + "%", dir: "higher", rank: true, color: () => T.red },
  { key: "prorata", label: "Prorated", fmt: (v) => v + (v === 1 ? " qtr" : " qtrs"), dir: "lower", rank: true }];


  function quartileMap(key, dir) {
    // Rank each row against the FULL interval-fund universe, not the table set.
    const values = universe.map((p) => p[key]).filter((v) => v != null);
    const sorted = [...values].sort((a, b) => dir === "higher" ? b - a : a - b);
    const map = {};
    peers.forEach((p) => {
      const v = p[key];
      if (v == null) { map[p.ticker] = null; return; }
      const rank = sorted.findIndex((x) => x === v) + 1 || sorted.findIndex((x) => dir === "higher" ? x <= v : x >= v) + 1;
      map[p.ticker] = pq_quartileOf(rank, sorted.length);
    });
    return map;
  }
  const qMaps = {};
  cols.forEach((c) => {if (c.rank) qMaps[c.key] = quartileMap(c.key, c.dir);});

  const QChip = ({ q }) => q == null ? <span style={{ color: T.ink4 }}>—</span> :
  <span style={{
    display: "inline-flex", alignItems: "center", justifyContent: "center",
    width: 22, height: 16, fontSize: 10, fontWeight: 600,
    background: q === 1 ? T.accent : q === 2 ? T.accentSoft : "transparent",
    color: q === 1 ? "#fff" : q === 2 ? T.amber : T.ink3,
    border: q >= 3 ? `1px solid ${T.rule}` : "none"
  }}>Q{q}</span>;


  return (
    <div style={{ padding: "0 72px 56px" }}>
      <div style={{ ...SX.card, padding: 0 }}>
        <div style={{ padding: "24px 32px 8px", display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <div style={{ ...SX.eyebrowAccent }}>Largest credit interval funds · by AUM</div>
            <h3 style={{ ...SX.display, fontSize: 26, margin: "4px 0 0", letterSpacing: "-0.01em" }}>The largest credit interval funds by AUM, ranked against the full universe.</h3>
            <div style={{ fontSize: 13, color: T.ink3, marginTop: 6 }}>No premium/discount column — these funds don't trade on an exchange. Rows are the largest by AUM (objective sort, not a curated peer set). Q-chips show quartile within the full {PEER_UNIVERSE.intervalsTender.length}-fund interval universe.</div>
          </div>
          <span style={{ fontSize: 12, color: T.ink2 }}>View full screener →</span>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, marginTop: 14 }}>
          <thead>
            <tr style={{ background: T.rule3, borderTop: `1px solid ${T.rule}`, borderBottom: `1px solid ${T.rule}` }}>
              <th style={{ ...SX.eyebrow, textAlign: "left", padding: "12px 20px", color: T.ink2 }}>Fund</th>
              {cols.map((c) =>
              <th key={c.key} style={{ ...SX.eyebrow, textAlign: "right", padding: "12px 20px", color: T.ink2 }}>{c.label}</th>
              )}
            </tr>
          </thead>
          <tbody>
            {peers.map((p) =>
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
                    </td>);

              })}
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>);

}

// ── App ──────────────────────────────────────────────────────────────────────
function FundDetailIntervalApp() {
  const [tab, setTab] = React.useState("overview");
  const tabs = [
  { id: "overview", label: "Overview" },
  { id: "holdings", label: "Holdings", count: 1247 },
  { id: "portfolio", label: "Portfolio breakdown" },
  { id: "performance", label: "Performance" },
  { id: "filings", label: "Filings", count: FI.filings.length }];

  const crumbs = [
    { label: "Home",  href: "index.html" },
    { label: "Funds", href: "index.html#universe" },
    { label: "Interval Funds" },
    { label: "CCLFX" },
  ];
  return (
    <div style={SX.root}>
      <FundHeader T={T} SX={SX} otherFundLink="Fund Detail v3 - BDC.html" otherFundLabel="BDC template" />
      <Breadcrumb T={T} items={crumbs} />
      <IntervalIdentity />
      <PeerStandingInterval />
      <LiquidityTerms />
      <NAVChart />
      <TabBar tabs={tabs} active={tab} onChange={setTab} />
      {tab === "overview" && <OverviewTab />}
      {tab === "holdings" && <HoldingsTab />}
      {tab === "portfolio" && <PortfolioTab />}
      {tab === "performance" && <PerformanceTab />}
      {tab === "filings" && <FilingsTab />}
      <EnhancedPeerTable />
      <FundFooter T={T} SX={SX} />
    </div>);

}

window.FundDetailIntervalApp = FundDetailIntervalApp;