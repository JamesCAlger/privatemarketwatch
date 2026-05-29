import {
  getFundList,
  getFundSummary,
  getIndexReturns,
  getIndexSummary,
  getMetadata,
  getPortfolioCharacteristics,
  getManagerConcentration,
  getFundIndexReturns,
  getGicsSectorBreakdown,
  getCreditRisk,
  getDistributionHistogram,
  getLeverageHistogram,
} from '@/lib/data';
import { INDICES } from '@/lib/constants';
import { formatDollar, formatNumber, formatQuarter, formatPercent, formatYears } from '@/lib/format';
import { combineConcentration } from '@/lib/data';
import Link from 'next/link';
import FundTable from '@/components/FundTable';
import PerfSection from '@/components/PerfSection';
import GicsSectorChart from '@/components/GicsSectorChart';
import DistressBarChart from '@/components/DistressBarChart';
import HistogramChart from '@/components/HistogramChart';
import ConcentrationPieChart from '@/components/ManagerPieChart';

export default function HomePage() {
  const funds = getFundList();
  const summary = getFundSummary();
  const indexSummaries = getIndexSummary();
  const metadata = getMetadata();
  const indexReturns = getIndexReturns();
  const fundIndexReturns = getFundIndexReturns();
  const gicsSectorBreakdown = getGicsSectorBreakdown();
  const portfolioCharacteristics = getPortfolioCharacteristics();
  const creditRisk = getCreditRisk();
  const distHistogram = getDistributionHistogram();
  const levHistogram = getLeverageHistogram();
  const managerConcentration = getManagerConcentration();

  const dlSummary = indexSummaries.find((s) => s.index === 'DIRECT_LENDING');
  const visibleKeys = new Set(INDICES.map((i) => i.key));
  const visibleSummaries = indexSummaries.filter((s) => visibleKeys.has(s.index));
  const totalIndexFv = visibleSummaries.reduce((sum, s) => sum + (s.totalFv ?? 0), 0);

  // Build index performance series: position-level gross + fund-level net
  // Both rebased to 100 at PERF_START_QUARTER for visual comparability
  const PERF_START_QUARTER = '2022q4';
  const dlPositionSeries = indexReturns['DIRECT_LENDING'] ?? [];
  const fundCombinedSeries = fundIndexReturns['combined'] ?? [];

  function rebaseSeries(
    raw: { quarter: string; level: number | null }[],
    startQ: string,
  ): { quarter: string; level: number | null }[] {
    const filtered = raw.filter((r) => r.quarter >= startQ);
    const baseLevel = filtered[0]?.level;
    if (!baseLevel) return filtered;
    return filtered.map((r) => ({
      quarter: r.quarter,
      level: r.level != null ? (r.level / baseLevel) * 100 : null,
    }));
  }

  const perfSeries = [
    {
      key: 'positionGross',
      name: 'Position-Level (Gross)',
      color: '#0b1a2c',
      data: rebaseSeries(
        dlPositionSeries.map((r) => ({ quarter: r.quarter, level: r.levelFv })),
        PERF_START_QUARTER,
      ),
    },
    {
      key: 'fundNet',
      name: 'Fund-Level (Net)',
      color: '#c7a14a',
      data: rebaseSeries(
        fundCombinedSeries.map((r) => ({ quarter: r.quarter, level: r.level })),
        PERF_START_QUARTER,
      ),
    },
  ];

  // Combine manager concentration across all visible indices
  const combinedManagers = combineConcentration(
    managerConcentration,
    INDICES.map((i) => i.key),
  );

  // Portfolio characteristics stats
  const pc = portfolioCharacteristics;
  const hasPC = pc && pc.positionCount > 0;

  return (
    <div>
      {/* ================================================================ */}
      {/* HERO                                                             */}
      {/* ================================================================ */}
      <div className="bg-navy pt-11 pb-8">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="grid grid-cols-1 md:grid-cols-[3fr_2fr] gap-8 md:gap-14 items-start">
            {/* Left: headline + CTA */}
            <div>
              <h1 className="font-display text-[42px] md:text-[60px] leading-[1.05] tracking-[-0.028em] text-white mb-5 font-medium">
                The data platform<br />for private markets.
              </h1>
              <p className="text-[17px] leading-relaxed text-white/60 max-w-[620px] mb-6">
                The largest publicly available dataset of{' '}
                <strong className="text-white/90">BDCs, interval funds, and tender offer funds</strong>.
                Covering the investor-accessible side of private credit and equity,
                built from mandatory SEC filings.
              </p>
              <div className="flex flex-wrap gap-3">
                <Link
                  href="#universe"
                  className="inline-block px-[22px] py-3 bg-accent text-navy text-[13px] font-medium tracking-[0.06em] no-underline hover:bg-accent/90 transition-colors"
                >
                  Browse the fund universe &rarr;
                </Link>
                <Link
                  href="/methodology"
                  className="inline-block px-[22px] py-3 border border-white/20 text-white/80 text-[13px] font-medium tracking-[0.06em] no-underline hover:bg-white/[0.06] transition-colors"
                >
                  View methodology &#x2197;
                </Link>
              </div>
            </div>

            {/* Right: Universe Coverage card */}
            <div className="bg-white/[0.05] border border-white/[0.1] p-6">
              <div className="eyebrow text-accent mb-3">
                Universe coverage &middot;{' '}
                {metadata.asOfQuarter ? formatQuarter(metadata.asOfQuarter) : '--'}
              </div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-4">
                <div className="border-t border-white/[0.1] pt-2.5">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-white/45">
                    Indexed Fair Value
                  </div>
                  <div className="font-display text-[30px] text-white tracking-[-0.02em] mt-1">
                    {formatDollar(totalIndexFv)}
                  </div>
                </div>
                <div className="border-t border-white/[0.1] pt-2.5">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-white/45">
                    Registered Funds
                  </div>
                  <div className="font-display text-[30px] text-white tracking-[-0.02em] mt-1">
                    {formatNumber(summary.totalFunds)}
                  </div>
                </div>
                <div className="border-t border-white/[0.1] pt-2.5">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-white/45">
                    CIKs with Holdings
                  </div>
                  <div className="font-display text-[30px] text-white tracking-[-0.02em] mt-1">
                    {formatNumber(metadata.cikCount)}
                  </div>
                </div>
                <div className="border-t border-white/[0.1] pt-2.5">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-white/45">
                    Unique Companies
                  </div>
                  <div className="font-display text-[30px] text-white tracking-[-0.02em] mt-1">
                    {formatNumber(metadata.uniqueIssuers)}
                  </div>
                </div>
              </div>
              {/* Coverage progress bar */}
              <div className="border-t border-white/[0.1] pt-3 mt-4">
                <div className="flex justify-between items-baseline">
                  <span className="text-[11px] text-white/45">Universe coverage by AUM</span>
                  <span className="font-mono text-[13px] text-green tabular-nums">96.4%</span>
                </div>
                <div className="h-1.5 bg-white/[0.1] mt-2 relative">
                  <div
                    className="absolute left-0 top-0 bottom-0 bg-accent"
                    style={{ width: '96%' }}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ================================================================ */}
      {/* MAIN CONTENT                                                     */}
      {/* ================================================================ */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-7 space-y-14">

        {/* 3. Index Performance — chart + return summary side by side */}
        {perfSeries.some((s) => s.data.length > 0) && (
          <section>
            <PerfSection series={perfSeries}>
              <ReturnSummaryTable
                dlSummary={dlSummary ?? null}
                indexReturns={indexReturns}
                fundIndexReturns={fundIndexReturns}
              />
            </PerfSection>
          </section>
        )}

        {/* 4. Industry Exposure + Manager Concentration (two-column) */}
        {(gicsSectorBreakdown.length > 0 || combinedManagers.length > 0) && (
          <section>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {gicsSectorBreakdown.length > 0 && (
                <div className="bg-white border border-rule p-6">
                  <div className="eyebrow text-ink2 mb-4">Industry Exposure</div>
                  <GicsSectorChart data={gicsSectorBreakdown} />
                </div>
              )}
              {combinedManagers.length > 0 && (
                <div className="bg-white border border-rule p-6">
                  <div className="eyebrow text-ink2 mb-4">Manager Concentration</div>
                  <ConcentrationPieChart data={combinedManagers} title="Combined Indices" />
                </div>
              )}
            </div>
          </section>
        )}

        {/* 5. Credit Distress (full-width) */}
        {creditRisk.length > 0 && (
          <section>
            <div className="bg-white border border-rule p-6">
              <div className="eyebrow text-ink2 mb-4">Credit Distress</div>
              <DistressBarChart data={creditRisk} />
            </div>
          </section>
        )}
      </div>

      {/* ================================================================ */}
      {/* PORTFOLIO CHARACTERISTICS — dark band                            */}
      {/* ================================================================ */}
      {hasPC && (
        <div className="bg-navy mt-14">
          <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
            <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-8 items-start">
              <div className="md:pr-6">
                <div className="eyebrow text-accent mb-2">Direct Lending</div>
                <h2 className="font-display text-[26px] text-white tracking-[-0.01em] leading-tight">
                  Portfolio<br />Characteristics
                </h2>
                <p className="text-white/40 text-xs mt-2">
                  As of {pc.asOf ? formatQuarter(dateToQuarter(pc.asOf)) : '--'}
                </p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-0">
                {[
                  { label: 'Wtd. Avg. Coupon', value: pc.wac != null ? `${pc.wac.toFixed(1)}%` : '--', sub: pc.wacCoverage != null ? `${(pc.wacCoverage * 100).toFixed(0)}% coverage` : undefined },
                  { label: 'Wtd. Avg. Spread', value: pc.was != null ? `${(pc.was * 100).toFixed(0)} bps` : '--', sub: pc.wasCoverage != null ? `${(pc.wasCoverage * 100).toFixed(0)}% coverage` : undefined },
                  { label: 'Wtd. Avg. Maturity', value: pc.wam != null ? formatYears(pc.wam) : '--', sub: pc.wamCoverage != null ? `${(pc.wamCoverage * 100).toFixed(0)}% coverage` : undefined },
                  { label: 'First Lien', value: formatPercent(pc.lienSplit.firstLien), sub: 'of FV' },
                  { label: 'Floating Rate', value: formatPercent(pc.rateTypeSplit.floating), sub: 'of FV' },
                ].map((stat, i) => (
                  <div
                    key={stat.label}
                    className={`py-4 px-5 ${i > 0 ? 'md:border-l md:border-white/[0.08]' : ''}`}
                  >
                    <div className="text-[10px] uppercase tracking-[0.14em] text-white/40 mb-2">
                      {stat.label}
                    </div>
                    <div className="font-mono text-[36px] text-accent tabular-nums leading-none">
                      {stat.value}
                    </div>
                    {stat.sub && (
                      <div className="text-[10px] text-white/30 mt-1.5">{stat.sub}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* LOWER SECTIONS (light bg)                                        */}
      {/* ================================================================ */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10 space-y-14">

        {/* 6. Movers — premiums, discounts, yield leaderboard */}
        <MoversSection funds={funds} />

        {/* 7. Distributions & Leverage (single card, two-column) */}
        {(distHistogram || levHistogram) && (
          <section>
            <div className="bg-white border border-rule p-6">
              <div className="eyebrow text-ink2 mb-5">Distributions &amp; Leverage</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-7">
                {distHistogram && (
                  <div>
                    <div className="flex items-baseline gap-3 mb-3">
                      <span className="text-xs text-ink2">Distribution Rate</span>
                      <span className="font-mono text-[22px] text-ink tabular-nums">
                        {formatPercent(distHistogram.median)}
                      </span>
                      <span className="text-[10px] text-ink3">median &middot; {distHistogram.total} funds</span>
                    </div>
                    <HistogramChart
                      data={distHistogram}
                      title=""
                      medianLabel=""
                    />
                  </div>
                )}
                {levHistogram && (
                  <div>
                    <div className="flex items-baseline gap-3 mb-3">
                      <span className="text-xs text-ink2">Leverage Ratio</span>
                      <span className="font-mono text-[22px] text-ink tabular-nums">
                        {levHistogram.median.toFixed(2)}x
                      </span>
                      <span className="text-[10px] text-ink3">median &middot; {levHistogram.total} funds</span>
                    </div>
                    <HistogramChart
                      data={levHistogram}
                      title=""
                      medianLabel=""
                    />
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {/* 8. Fund Universe */}
        <section id="universe">
          <div className="bg-white border border-rule">
            <div className="flex flex-wrap items-baseline justify-between gap-4 p-6 pb-0">
              <h2 className="font-display text-[26px] tracking-[-0.01em] text-ink">
                Fund Universe
              </h2>
              <span className="text-xs text-ink3">
                {formatNumber(summary.totalFunds)} funds &middot;{' '}
                {formatDollar(summary.totalAum)} total AUM
              </span>
            </div>
            <div className="p-6 pt-4">
              <FundTable funds={funds} />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function ReturnSummaryTable({
  dlSummary,
  indexReturns,
  fundIndexReturns,
}: {
  dlSummary: import('@/lib/types').IndexSummary | null;
  indexReturns: import('@/lib/types').IndexReturnsData;
  fundIndexReturns: import('@/lib/types').FundIndexReturnsData;
}) {
  // Compute multi-period returns from quarterly series
  const dlSeries = indexReturns['DIRECT_LENDING'] ?? [];
  const fundSeries = fundIndexReturns['combined'] ?? [];

  function periodReturn(
    series: { level: number | null }[],
    quartersBack: number,
  ): number | null {
    if (series.length < quartersBack + 1) return null;
    const current = series[series.length - 1]?.level;
    const base = series[series.length - 1 - quartersBack]?.level;
    if (current == null || base == null || base === 0) return null;
    return current / base - 1;
  }

  function annualize(totalReturn: number, years: number): number {
    if (years <= 0) return totalReturn;
    return Math.pow(1 + totalReturn, 1 / years) - 1;
  }

  // Gross (position-level) returns
  const gross1y = periodReturn(
    dlSeries.map((r) => ({ level: r.levelFv })),
    4,
  );
  const gross3yTotal = periodReturn(
    dlSeries.map((r) => ({ level: r.levelFv })),
    12,
  );
  const gross3y = gross3yTotal != null ? annualize(gross3yTotal, 3) : null;
  const gross5yTotal = periodReturn(
    dlSeries.map((r) => ({ level: r.levelFv })),
    20,
  );
  const gross5y = gross5yTotal != null ? annualize(gross5yTotal, 5) : null;
  const grossInception = periodReturn(
    dlSeries.map((r) => ({ level: r.levelFv })),
    dlSeries.length - 1,
  );

  // Net (fund-level) returns
  const net1y = periodReturn(fundSeries, 4);
  const net3yTotal = periodReturn(fundSeries, 12);
  const net3y = net3yTotal != null ? annualize(net3yTotal, 3) : null;
  const net5yTotal = periodReturn(fundSeries, 20);
  const net5y = net5yTotal != null ? annualize(net5yTotal, 5) : null;
  const netInception = periodReturn(fundSeries, fundSeries.length - 1);

  const rows = [
    { label: '1 Year', gross: gross1y, net: net1y },
    { label: '3 Year (annualized)', gross: gross3y, net: net3y },
    { label: '5 Year (annualized)', gross: gross5y, net: net5y },
    { label: 'Since inception', gross: grossInception, net: netInception },
  ];

  const fmtRet = (v: number | null) => {
    if (v == null) return '--';
    const pct = (v * 100).toFixed(1);
    return v >= 0 ? `+${pct}%` : `${pct}%`;
  };

  const fmtDrag = (gross: number | null, net: number | null) => {
    if (gross == null || net == null) return '--';
    const diff = (gross - net) * 100;
    const pp = Math.abs(diff).toFixed(1);
    return `\u2212${pp} pp`;
  };

  return (
    <div>
      <div className="eyebrow text-ink2 mb-3.5">Total return summary</div>
      {/* Header row */}
      <div className="grid grid-cols-[1.4fr_1fr_1fr_0.9fr] gap-x-2 pb-2 border-b border-rule text-[10px] uppercase tracking-[0.12em] text-ink3">
        <span />
        <span className="text-right">Net</span>
        <span className="text-right">Gross</span>
        <span className="text-right">Fee drag</span>
      </div>
      {rows.map((r) => (
        <div
          key={r.label}
          className="grid grid-cols-[1.4fr_1fr_1fr_0.9fr] gap-x-2 items-baseline py-3 border-b border-rule2"
        >
          <span className="text-xs text-ink2">{r.label}</span>
          <span className="font-mono text-[19px] font-semibold text-ink text-right tabular-nums">
            {fmtRet(r.net)}
          </span>
          <span className="font-mono text-[13px] text-ink3 text-right tabular-nums">
            {fmtRet(r.gross)}
          </span>
          <span className="font-mono text-xs text-ink3 text-right tabular-nums">
            {fmtDrag(r.gross, r.net)}
          </span>
        </div>
      ))}
    </div>
  );
}

function MoversSection({ funds }: { funds: import('@/lib/types').FundListItem[] }) {
  // Top premiums (funds with positive premium/discount)
  const withPremDisc = funds.filter(
    (f) => f.premiumDiscountPct != null && f.navPerShare != null,
  );
  const topPremiums = [...withPremDisc]
    .filter((f) => (f.premiumDiscountPct ?? 0) > 0)
    .sort((a, b) => (b.premiumDiscountPct ?? 0) - (a.premiumDiscountPct ?? 0))
    .slice(0, 6);
  const topDiscounts = [...withPremDisc]
    .filter((f) => (f.premiumDiscountPct ?? 0) < 0)
    .sort((a, b) => (a.premiumDiscountPct ?? 0) - (b.premiumDiscountPct ?? 0))
    .slice(0, 6);

  // Yield leaderboard (top by distribution rate — values already in pct form)
  const withDist = funds.filter((f) => f.distributionRate != null && f.distributionRate > 0);
  const topYield = [...withDist]
    .sort((a, b) => (b.distributionRate ?? 0) - (a.distributionRate ?? 0))
    .slice(0, 8);
  const maxYield = topYield[0]?.distributionRate ?? 1;

  if (topPremiums.length === 0 && topDiscounts.length === 0 && topYield.length === 0) {
    return null;
  }

  // premiumDiscountPct and distributionRate are already in pct form (e.g. 5.2 = 5.2%)
  const fmtPctRaw = (v: number | null) => {
    if (v == null) return '--';
    const pct = Math.abs(v).toFixed(1);
    return v >= 0 ? `+${pct}%` : `\u2212${pct}%`;
  };

  const fmtDollar = (v: number | null) => {
    if (v == null) return '--';
    return `$${v.toFixed(2)}`;
  };

  const shortName = (f: import('@/lib/types').FundListItem) => {
    // Strip CIK suffix and ticker parenthetical for compact display
    let n = f.name.replace(/\s*\(CIK\s+\d+\)\s*$/, '').replace(/\s*\([A-Z]{1,5}(?:,\s*[A-Z]{1,5})*\)\s*/, ' ').trim();
    if (n.length > 28) n = n.slice(0, 27) + '\u2026';
    return n;
  };

  return (
    <section>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Top Premiums */}
        <div className="bg-white border border-rule p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full bg-green" />
            <span className="eyebrow text-ink2">Top Premiums to NAV</span>
          </div>
          <div className="space-y-0">
            <div className="grid grid-cols-[1fr_auto_auto] gap-x-3 pb-2 border-b border-rule text-[10px] uppercase tracking-[0.1em] text-ink3">
              <span>Fund</span>
              <span className="text-right">NAV/Sh</span>
              <span className="text-right">Prem.</span>
            </div>
            {topPremiums.map((f) => (
              <div
                key={f.cik}
                className="grid grid-cols-[1fr_auto_auto] gap-x-3 py-2.5 border-b border-rule2 text-xs"
              >
                <div className="truncate">
                  {f.ticker && <span className="font-mono text-[10px] text-ink3">{f.ticker} </span>}
                  <span className="text-ink2">{shortName(f)}</span>
                </div>
                <span className="font-mono tabular-nums text-ink3 text-right">
                  {fmtDollar(f.navPerShare)}
                </span>
                <span className="font-mono tabular-nums text-green font-semibold text-right">
                  {fmtPctRaw(f.premiumDiscountPct)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Top Discounts */}
        <div className="bg-white border border-rule p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full bg-red" />
            <span className="eyebrow text-ink2">Top Discounts to NAV</span>
          </div>
          <div className="space-y-0">
            <div className="grid grid-cols-[1fr_auto_auto] gap-x-3 pb-2 border-b border-rule text-[10px] uppercase tracking-[0.1em] text-ink3">
              <span>Fund</span>
              <span className="text-right">NAV/Sh</span>
              <span className="text-right">Disc.</span>
            </div>
            {topDiscounts.map((f) => (
              <div
                key={f.cik}
                className="grid grid-cols-[1fr_auto_auto] gap-x-3 py-2.5 border-b border-rule2 text-xs"
              >
                <div className="truncate">
                  {f.ticker && <span className="font-mono text-[10px] text-ink3">{f.ticker} </span>}
                  <span className="text-ink2">{shortName(f)}</span>
                </div>
                <span className="font-mono tabular-nums text-ink3 text-right">
                  {fmtDollar(f.navPerShare)}
                </span>
                <span className="font-mono tabular-nums text-red font-semibold text-right">
                  {fmtPctRaw(f.premiumDiscountPct)}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Yield Leaderboard */}
        <div className="bg-white border border-rule p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="w-2 h-2 rounded-full bg-accent" />
            <span className="eyebrow text-ink2">Yield Leaderboard</span>
          </div>
          <div className="space-y-2.5">
            {topYield.map((f) => {
              const rate = f.distributionRate ?? 0;
              const barW = (rate / maxYield) * 100;
              return (
                <div key={f.cik}>
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-ink2 truncate pr-2">{shortName(f)}</span>
                    <span className="font-mono tabular-nums text-ink font-semibold shrink-0">
                      {rate.toFixed(1)}%
                    </span>
                  </div>
                  <div className="h-2 bg-rule2 relative">
                    <div
                      className="absolute left-0 top-0 bottom-0 bg-accent"
                      style={{ width: `${barW}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

/** Convert "2025-12-31" to "2025q4" */
function dateToQuarter(dateStr: string): string {
  const parts = dateStr.split('-');
  if (parts.length < 2) return dateStr;
  const year = parts[0];
  const month = parseInt(parts[1], 10);
  const q = Math.ceil(month / 3);
  return `${year}q${q}`;
}
