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
  getSectorBreakdown,
  getDistributionHistogram,
  getLeverageHistogram,
  getCreditRisk,
  getTopConstituents,
  getConcentrationCurve,
  getSpreadTimeSeries,
  getSpreadByFundSize,
} from '@/lib/data';
import { INDICES } from '@/lib/constants';
import { formatDollar, formatNumber, formatQuarter, formatPercent, formatYears } from '@/lib/format';
import { combineConcentration } from '@/lib/data';
import Link from 'next/link';
import FundTable from '@/components/FundTable';
import PerfSection from '@/components/PerfSection';
import ReturnSummaryTable from '@/components/ReturnSummaryTable';
import ProportionDonut from '@/components/ProportionDonut';
import HistogramChart from '@/components/HistogramChart';
import CreditStressChart from '@/components/CreditStressChart';
import SpreadTimeChart from '@/components/SpreadTimeChart';
import SpreadByFundSizeChart from '@/components/SpreadByFundSizeChart';
import { formatDisplayName } from '@/lib/nameFormat';
import StatStrip from '@/components/StatStrip';

export default function HomePage() {
  const funds = getFundList();
  const summary = getFundSummary();
  const indexSummaries = getIndexSummary();
  const metadata = getMetadata();
  const indexReturns = getIndexReturns();
  const fundIndexReturns = getFundIndexReturns();
  const gicsSectorBreakdown = getGicsSectorBreakdown();
  const portfolioCharacteristics = getPortfolioCharacteristics();
  const distHistogram = getDistributionHistogram();
  const levHistogram = getLeverageHistogram();
  const managerConcentration = getManagerConcentration();
  const creditRisk = getCreditRisk();
  const spreadTimeSeries = getSpreadTimeSeries();
  const spreadByFundSize = getSpreadByFundSize();
  const sectorBreakdown = getSectorBreakdown();
  const topConstituents = getTopConstituents();
  const concentrationCurve = getConcentrationCurve();

  const dlSummary = indexSummaries.find((s) => s.index === 'DIRECT_LENDING');
  const visibleKeys = new Set(INDICES.map((i) => i.key));
  const visibleSummaries = indexSummaries.filter((s) => visibleKeys.has(s.index));
  const totalIndexFv = visibleSummaries.reduce((sum, s) => sum + (s.totalFv ?? 0), 0);

  // Build index performance series: position-level gross + fund-level net
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

  // Donut items for Industry Exposure + Manager Concentration
  const sectorItems = gicsSectorBreakdown.map((s) => ({
    label: s.sector,
    pct: s.pctOfTotal * 100,
  }));
  const managerItems = combinedManagers.map((m) => ({
    label: formatDisplayName(m.name, { kind: 'manager' }),
    pct: m.pctOfIndex * 100,
  }));
  function top5Share(items: { pct: number }[]): number {
    const total = items.reduce((s, x) => s + x.pct, 0);
    const top5Sum = [...items].sort((a, b) => b.pct - a.pct).slice(0, 5).reduce((s, x) => s + x.pct, 0);
    return total > 0 ? (top5Sum / total) * 100 : 0;
  }
  const sectorCenterStat = { label: 'Top 5', value: top5Share(sectorItems).toFixed(0) + '%', note: 'of holdings' };
  const managerCenterStat = { label: 'Top 5', value: top5Share(managerItems).toFixed(0) + '%', note: 'of universe AUM' };

  // Instrument type donut — split direct lending by lien, then other classifications
  const dlFv = (sectorBreakdown['DIRECT_LENDING'] ?? []).reduce((s, r) => s + r.totalFv, 0);
  const lien = portfolioCharacteristics?.lienSplit;
  const instrumentRaw: { label: string; fv: number }[] = [
    { label: 'First Lien Senior Loans', fv: lien ? dlFv * lien.firstLien : dlFv },
    { label: 'Second Lien Loans', fv: lien ? dlFv * lien.secondLien : 0 },
    { label: 'Unsecured Loans', fv: lien ? dlFv * lien.unsecured : 0 },
    { label: 'Structured Credit', fv: (sectorBreakdown['STRUCTURED_CREDIT'] ?? []).reduce((s, r) => s + r.totalFv, 0) },
    { label: 'Preferred Equity', fv: (sectorBreakdown['PREFERRED_EQUITY'] ?? []).reduce((s, r) => s + r.totalFv, 0) },
    { label: 'Common Equity', fv: (sectorBreakdown['COMMON_EQUITY'] ?? []).reduce((s, r) => s + r.totalFv, 0) },
    {
      label: 'Other',
      fv: ['DIRECT_REAL_ESTATE', 'PRIVATE_CREDIT_FUND', 'PRIVATE_EQUITY_FUND', 'UNCLASSIFIED']
        .reduce((sum, k) => sum + (sectorBreakdown[k] ?? []).reduce((s, r) => s + r.totalFv, 0), 0),
    },
  ].filter((x) => x.fv > 0);
  const instrumentTotal = instrumentRaw.reduce((s, x) => s + x.fv, 0);
  const instrumentDonutItems = instrumentRaw.map((x) => ({
    label: x.label,
    pct: instrumentTotal > 0 ? (x.fv / instrumentTotal) * 100 : 0,
  }));
  const firstLienPct = instrumentDonutItems.find((x) => x.label === 'First Lien Senior Loans')?.pct ?? 0;
  const instrumentCenterStat = { label: 'First Lien', value: firstLienPct.toFixed(0) + '%', note: 'of fair value' };

  // Portfolio characteristics stats
  const pc = portfolioCharacteristics;
  const hasPC = pc && pc.positionCount > 0;

  // Return summary rows
  const returnRows = buildReturnRows(indexReturns, fundIndexReturns);

  // Movers data
  const topLeverage = buildTopLeverage(funds);
  const largestNavMoves = buildLargestNavMoves(funds);
  const topYield = buildTopYield(funds);

  return (
    <div>
      {/* ================================================================ */}
      {/* HERO                                                             */}
      {/* ================================================================ */}
      <div className="border-b border-rule pt-6 pb-8">
        <div className="px-4 md:px-[120px]">
          <h1 className="font-display text-[56px] md:text-[80px] leading-[1.08] tracking-[-0.028em] text-ink mb-2 font-medium max-w-[920px]">
            Private fund holdings.
          </h1>
          <h1 className="font-display text-[56px] md:text-[80px] leading-[1.08] tracking-[-0.028em] text-ink3 mb-5 font-medium">
            Loan by loan.
          </h1>
          <p className="text-[22px] leading-relaxed text-ink3 max-w-[720px] mb-6">
            Browse individual loans, equity stakes, and credit facilities held by
            semi-liquid funds. Updated quarterly.
          </p>
          <div className="flex flex-wrap gap-3 mb-8">
            <Link
              href="#universe"
              className="inline-block px-[22px] py-3 bg-navy text-white text-[13px] font-medium tracking-[0.06em] no-underline hover:bg-navy/90 transition-colors"
            >
              Browse the fund universe &rarr;
            </Link>
            <Link
              href="/methodology"
              className="inline-block px-[22px] py-3 border border-rule text-ink2 text-[13px] font-medium tracking-[0.06em] no-underline hover:bg-surface/50 transition-colors"
            >
              View methodology &#x2197;
            </Link>
          </div>

          {/* Stat strip */}
          <StatStrip
            totalFv={totalIndexFv}
            holdingsCount={metadata.holdingsCount}
            totalFunds={summary.totalFunds}
            avgSpread={portfolioCharacteristics?.was ?? null}
            quarters={dlPositionSeries.length}
          />
        </div>
      </div>

      {/* ================================================================ */}
      {/* MAIN CONTENT                                                     */}
      {/* ================================================================ */}
      <div className="px-4 md:px-[120px] py-7 space-y-14">

        {/* Industry Exposure + Manager Concentration (two-column donuts) */}
        {/* Instrument Type + Industry Exposure (top row) */}
        {(instrumentDonutItems.length > 0 || sectorItems.length > 0) && (
          <section>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {instrumentDonutItems.length > 0 && (
                <div className="bg-white border border-rule p-7">
                  <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Instrument type</h3>
                  <p className="text-xs text-ink3 mt-2 mb-3">{instrumentDonutItems.length} categories &middot; share of indexed fair value</p>
                  <ProportionDonut items={instrumentDonutItems} centerStat={instrumentCenterStat} />
                  <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                    Other includes real estate holdings, indirect exposure via credit and equity fund vehicles, and opaque SPVs such as co-investment JVs and feeder funds.
                  </div>
                </div>
              )}
              {sectorItems.length > 0 && (
                <div className="bg-white border border-rule p-7">
                  <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Industry exposure</h3>
                  <p className="text-xs text-ink3 mt-2 mb-3">{sectorItems.length} GICS sectors &middot; share of holdings AUM</p>
                  <ProportionDonut items={sectorItems} centerStat={sectorCenterStat} />
                  <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                    Unknown sector positions lack GICS classification in the source filing or could not be reconciled.
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* Manager Concentration (full width below) */}
        {managerItems.length > 0 && (
          <section>
            <div className="bg-white border border-rule p-7">
              <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Manager concentration</h3>
              <p className="text-xs text-ink3 mt-2 mb-3">Top {managerItems.length} managers &middot; share of universe AUM</p>
              <ProportionDonut items={managerItems} centerStat={managerCenterStat} />
              <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                Combined indices &middot; top {managerItems.length} managers.
              </div>
            </div>
          </section>
        )}

        {/* Index Performance -- chart + return summary side by side */}
        {perfSeries.some((s) => s.data.length > 0) && (
          <section>
            <PerfSection series={perfSeries}>
              <ReturnSummaryTable rows={returnRows} showGross={true} />
            </PerfSection>
          </section>
        )}

        {/* Spread Analysis */}
        {spreadTimeSeries.length > 1 && (() => {
          const latest = spreadTimeSeries[spreadTimeSeries.length - 1];
          const latestBps = Math.round(latest.was * 100);
          const peak = Math.max(...spreadTimeSeries.map((d) => d.was));
          const peakBps = Math.round(peak * 100);
          return (
            <section>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Spread over time */}
                <div className="bg-white border border-rule p-7">
                  <div className="flex flex-wrap items-baseline justify-between gap-4 mb-1">
                    <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Spread analysis</h3>
                    <div className="text-right">
                      <span className="font-mono text-[18px] text-ink font-semibold tabular-nums">
                        {latestBps} bps
                      </span>
                      <span className="text-[11px] text-ink3 ml-1.5 font-mono tabular-nums">
                        from {peakBps} peak
                      </span>
                    </div>
                  </div>
                  <p className="text-xs text-ink3 mb-4">
                    FV-weighted average credit spread over base rate &middot; {spreadTimeSeries.length}-quarter history
                  </p>
                  <SpreadTimeChart data={spreadTimeSeries} />
                  <div className="border-t border-rule2 pt-3 mt-2 text-[11px] text-ink3">
                    Direct lending positions &middot; {latest.positionCount.toLocaleString()} positions &middot; {formatDollar(latest.totalFv)} FV
                  </div>
                </div>

                {/* Spread by fund size */}
                {spreadByFundSize.length > 0 && (
                  <div className="bg-white border border-rule p-7">
                    <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Spread by fund size</h3>
                    <p className="text-xs text-ink3 mt-2 mb-3">
                      Fund total assets tercile &middot; latest quarter
                    </p>
                    <SpreadByFundSizeChart data={spreadByFundSize} />
                    <div className="border-t border-rule2 pt-3 mt-2 text-[11px] text-ink3">
                      {spreadByFundSize.reduce((s, d) => s + d.fundCount, 0)} funds with spread data.
                      Small-fund premium: {Math.round((spreadByFundSize[0]?.was ?? 0) * 100) - Math.round((spreadByFundSize[spreadByFundSize.length - 1]?.was ?? 0) * 100)} bps over large.
                    </div>
                  </div>
                )}
              </div>
            </section>
          );
        })()}

        {/* Credit Stress */}
        {creditRisk.length > 1 && (() => {
          const latest = creditRisk[creditRisk.length - 1];
          const latestTotal = latest.byFv.deepDistress + latest.byFv.nonAccrual + latest.byFv.markedBelowCost;
          const yearAgoIdx = creditRisk.length - 5;
          const yearAgo = yearAgoIdx >= 0 ? creditRisk[yearAgoIdx] : null;
          const yearAgoTotal = yearAgo
            ? yearAgo.byFv.deepDistress + yearAgo.byFv.nonAccrual + yearAgo.byFv.markedBelowCost
            : null;
          const delta = yearAgoTotal != null ? latestTotal - yearAgoTotal : null;
          return (
            <section>
              <div className="bg-white border border-rule p-7">
                <div className="flex flex-wrap items-baseline justify-between gap-4 mb-1">
                  <h3 className="font-display text-[24px] tracking-[-0.01em] text-ink">Credit stress, by quarter</h3>
                  <div className="text-right">
                    <span className="font-mono text-[26px] text-ink font-semibold tabular-nums leading-none">
                      {(latestTotal * 100).toFixed(1)}%
                    </span>
                    <div className="text-[10px] text-ink3 uppercase tracking-[0.1em] mt-1">
                      of fair value flagged &middot; {formatQuarter(latest.quarter)}
                    </div>
                    {delta != null && (
                      <div className="text-[11px] text-ink2 font-mono tabular-nums mt-1">
                        {delta > 0 ? '+' : ''}{(delta * 100).toFixed(1)} pp YoY
                      </div>
                    )}
                  </div>
                </div>
                <p className="text-xs text-ink3 mb-2">
                  Cumulative % of fair value showing each signal &middot; {creditRisk.length}-quarter history
                </p>
                <CreditStressChart data={creditRisk} />
                <div className="flex flex-wrap justify-between items-baseline mt-2 pt-3 border-t border-rule2 text-xs text-ink3">
                  <span>
                    Universe AUM{' '}
                    <span className="font-mono text-ink2 tabular-nums">{formatDollar(latest.totalFv)}</span>
                    {' '}across {formatNumber(latest.totalPositions)} positions.
                  </span>
                  <span>Source: SEC 10-K / 10-Q filings</span>
                </div>
              </div>
            </section>
          );
        })()}

        {/* Top Positions + Concentration Curve (two-column) */}
        {(() => {
          // Flatten top constituents across DIRECT_LENDING only (largest category)
          const dlPositions = topConstituents['DIRECT_LENDING'] ?? [];
          const topPositions = dlPositions.slice(0, 15);
          const combinedCurve = concentrationCurve['COMBINED']?.position ?? [];

          if (topPositions.length === 0 && combinedCurve.length === 0) return null;
          return (
            <section>
              <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-6">
                {/* Top Positions Table */}
                {topPositions.length > 0 && (
                  <div className="bg-white border border-rule p-7">
                    <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Largest positions</h3>
                    <p className="text-xs text-ink3 mt-2 mb-4">Top {topPositions.length} direct lending positions by fair value</p>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-rule text-[10px] uppercase tracking-[0.12em] text-ink3">
                            <th className="text-left py-2 pr-3 font-medium">Issuer</th>
                            <th className="text-left py-2 pr-3 font-medium">Fund</th>
                            <th className="text-right py-2 pr-3 font-medium">Fair Value</th>
                            <th className="text-right py-2 pr-3 font-medium">Unreal. G/L</th>
                            <th className="text-right py-2 font-medium">Rate</th>
                          </tr>
                        </thead>
                        <tbody>
                          {topPositions.map((p, i) => {
                            // Clean up issuer name — strip trailing ",1" or description suffixes
                            const cleanName = p.issuerName.replace(/,\s*\d+$/, '').replace(/,\s*(CP|LLC|Inc\.|Ltd\.)?\s*$/, '$1').trim();
                            const shortName = cleanName.length > 32 ? cleanName.slice(0, 30) + '...' : cleanName;
                            const shortFund = p.vehicleName.length > 22 ? p.vehicleName.slice(0, 20) + '...' : p.vehicleName;
                            return (
                              <tr key={i} className="border-b border-rule2 hover:bg-surface/30">
                                <td className="py-2 pr-3 text-ink font-medium truncate max-w-[200px]" title={cleanName}>
                                  {shortName}
                                </td>
                                <td className="py-2 pr-3 text-ink3 truncate max-w-[160px]" title={p.vehicleName}>
                                  {shortFund}
                                </td>
                                <td className="py-2 pr-3 text-right font-mono tabular-nums text-ink">
                                  {formatDollar(p.fairValue ?? 0)}
                                </td>
                                <td className={`py-2 pr-3 text-right font-mono tabular-nums ${
                                  p.unrealizedGlPct != null
                                    ? p.unrealizedGlPct >= 0 ? 'text-green' : 'text-red'
                                    : 'text-ink3'
                                }`}>
                                  {p.unrealizedGlPct != null
                                    ? `${p.unrealizedGlPct >= 0 ? '+' : ''}${p.unrealizedGlPct.toFixed(1)}%`
                                    : '--'}
                                </td>
                                <td className="py-2 text-right text-ink3">
                                  {p.rateType ?? '--'}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <div className="border-t border-rule2 pt-3 mt-2 text-[11px] text-ink3">
                      {dlPositions.length} direct lending positions across the indexed universe.
                    </div>
                  </div>
                )}

                {/* Concentration Curve */}
                {combinedCurve.length > 0 && (
                  <div className="bg-white border border-rule p-7">
                    <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Position concentration</h3>
                    <p className="text-xs text-ink3 mt-2 mb-4">
                      Share of fair value by position quantile &middot; {combinedCurve[0]?.totalCount?.toLocaleString()} total positions
                    </p>
                    <div className="space-y-2">
                      {combinedCurve.map((b, i) => {
                        const pct = b.fvPct * 100;
                        return (
                          <div key={i}>
                            <div className="flex justify-between items-baseline text-xs mb-1">
                              <span className="text-ink2">{b.label}</span>
                              <span className="font-mono tabular-nums text-ink font-medium">
                                {pct.toFixed(1)}%
                                <span className="text-ink3 font-normal ml-1.5">({b.count.toLocaleString()})</span>
                              </span>
                            </div>
                            <div className="h-5 bg-rule2 relative">
                              <div
                                className="absolute left-0 top-0 bottom-0"
                                style={{
                                  width: `${pct}%`,
                                  backgroundColor: i === 0 ? '#0b1a2c' : i === 1 ? '#2a3f55' : i === 2 ? '#4a6178' : '#8a9bab',
                                }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    <div className="border-t border-rule2 pt-3 mt-4 text-[11px] text-ink3">
                      Top 5% of positions hold{' '}
                      <span className="font-mono text-ink tabular-nums font-medium">
                        {((combinedCurve[0]?.fvPct ?? 0) * 100 + (combinedCurve[1]?.fvPct ?? 0) * 100).toFixed(1)}%
                      </span>{' '}
                      of total indexed fair value.
                    </div>
                  </div>
                )}
              </div>
            </section>
          );
        })()}
      </div>

      {/* ================================================================ */}
      {/* PORTFOLIO CHARACTERISTICS -- dark band                            */}
      {/* ================================================================ */}
      {hasPC && (
        <div className="bg-navy mt-14">
          <div className="px-4 md:px-[120px] py-10">
            <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-8 items-start">
              <div className="md:pr-6">
                <div className="eyebrow text-accent mb-2">Private Credit</div>
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
      {/* MOVERS                                                           */}
      {/* ================================================================ */}
      <div className="px-4 md:px-[120px] py-10 space-y-14">
        {(topLeverage.length > 0 || largestNavMoves.length > 0 || topYield.length > 0) && (
          <section>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Top Leverage */}
              {topLeverage.length > 0 && (
                <MoversCard
                  title="Top Leverage"
                  dotColor="bg-red"
                  items={topLeverage}
                  maxVal={topLeverage[0]?.value ?? 1}
                  barColor="bg-red/60"
                  valueFmt={(v) => `${v.toFixed(2)}x`}
                />
              )}

              {/* Largest NAV Moves */}
              {largestNavMoves.length > 0 && (
                <MoversCard
                  title="Largest NAV Moves"
                  dotColor="bg-navy"
                  items={largestNavMoves}
                  maxVal={Math.max(...largestNavMoves.map((m) => Math.abs(m.value)))}
                  barColor="bg-navy/40"
                  valueFmt={(v) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`}
                />
              )}

              {/* Yield Leaderboard */}
              {topYield.length > 0 && (
                <MoversCard
                  title="Yield Leaderboard"
                  dotColor="bg-accent"
                  items={topYield}
                  maxVal={topYield[0]?.value ?? 1}
                  barColor="bg-accent"
                  valueFmt={(v) => `${v.toFixed(1)}%`}
                />
              )}
            </div>
          </section>
        )}

        {/* 7. Distributions & Leverage (single card, two-column) */}
        {(distHistogram || levHistogram) && (
          <section>
            <div className="bg-white border border-rule p-7">
              <h3 className="font-display text-[24px] tracking-[-0.01em] text-ink">Distributions &amp; leverage</h3>
              <p className="text-xs text-ink3 mt-2 mb-4">Cross-sectional distribution &middot; medians shown</p>
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
            <div className="p-7 pb-0">
              <h2 className="font-display text-[26px] tracking-[-0.01em] text-ink">
                Fund universe{' '}
                <span className="text-ink3 font-normal">
                  &middot; {formatNumber(summary.totalFunds)} funds &middot; {formatDollar(summary.totalAum)}
                </span>
              </h2>
            </div>
            <div className="p-7 pt-4">
              <FundTable funds={funds} />
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Movers card                                                         */
/* ------------------------------------------------------------------ */

interface MoverItem {
  name: string;
  cik: string;
  value: number;
}

function MoversCard({
  title,
  dotColor,
  items,
  maxVal,
  barColor,
  valueFmt,
}: {
  title: string;
  dotColor: string;
  items: MoverItem[];
  maxVal: number;
  barColor: string;
  valueFmt: (v: number) => string;
}) {
  return (
    <div className="bg-white border border-rule p-6">
      <div className="flex items-center gap-2 mb-4">
        <span className={`w-2 h-2 rounded-full ${dotColor}`} />
        <span className="eyebrow text-ink2">{title}</span>
      </div>
      <div className="space-y-2.5">
        {items.map((item) => {
          const barW = maxVal > 0 ? (Math.abs(item.value) / maxVal) * 100 : 0;
          return (
            <div key={item.cik}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-ink2 truncate pr-2">{item.name}</span>
                <span className="font-mono tabular-nums text-ink font-semibold shrink-0">
                  {valueFmt(item.value)}
                </span>
              </div>
              <div className="h-2 bg-rule2 relative">
                <div
                  className={`absolute left-0 top-0 bottom-0 ${barColor}`}
                  style={{ width: `${barW}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Data builders                                                       */
/* ------------------------------------------------------------------ */

function buildReturnRows(
  indexReturns: import('@/lib/types').IndexReturnsData,
  fundIndexReturns: import('@/lib/types').FundIndexReturnsData,
) {
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

  const gross1y = periodReturn(dlSeries.map((r) => ({ level: r.levelFv })), 4);
  const gross3yTotal = periodReturn(dlSeries.map((r) => ({ level: r.levelFv })), 12);
  const gross3y = gross3yTotal != null ? annualize(gross3yTotal, 3) : null;
  const gross5yTotal = periodReturn(dlSeries.map((r) => ({ level: r.levelFv })), 20);
  const gross5y = gross5yTotal != null ? annualize(gross5yTotal, 5) : null;
  const grossInception = periodReturn(dlSeries.map((r) => ({ level: r.levelFv })), dlSeries.length - 1);

  const net1y = periodReturn(fundSeries, 4);
  const net3yTotal = periodReturn(fundSeries, 12);
  const net3y = net3yTotal != null ? annualize(net3yTotal, 3) : null;
  const net5yTotal = periodReturn(fundSeries, 20);
  const net5y = net5yTotal != null ? annualize(net5yTotal, 5) : null;
  const netInception = periodReturn(fundSeries, fundSeries.length - 1);

  return [
    { label: '1 Year', gross: gross1y, net: net1y },
    { label: '3 Year (annualized)', gross: gross3y, net: net3y },
    { label: '5 Year (annualized)', gross: gross5y, net: net5y },
    { label: 'Since inception', gross: grossInception, net: netInception },
  ];
}

function shortName(f: import('@/lib/types').FundListItem): string {
  let n = f.name
    .replace(/\s*\(CIK\s+\d+\)\s*$/, '')
    .replace(/\s*\([A-Z]{1,5}(?:,\s*[A-Z]{1,5})*\)\s*/, ' ')
    .trim();
  if (n.length > 28) n = n.slice(0, 27) + '\u2026';
  return n;
}

function buildTopLeverage(funds: import('@/lib/types').FundListItem[]): MoverItem[] {
  return [...funds]
    .filter((f) => f.leverageRatio != null && f.leverageRatio > 0)
    .sort((a, b) => (b.leverageRatio ?? 0) - (a.leverageRatio ?? 0))
    .slice(0, 8)
    .map((f) => ({ name: shortName(f), cik: f.cik, value: f.leverageRatio! }));
}

function buildLargestNavMoves(funds: import('@/lib/types').FundListItem[]): MoverItem[] {
  return [...funds]
    .filter((f) => f.quarterlyReturn != null)
    .sort((a, b) => Math.abs(b.quarterlyReturn ?? 0) - Math.abs(a.quarterlyReturn ?? 0))
    .slice(0, 8)
    .map((f) => ({ name: shortName(f), cik: f.cik, value: f.quarterlyReturn! }));
}

function buildTopYield(funds: import('@/lib/types').FundListItem[]): MoverItem[] {
  return [...funds]
    .filter((f) => f.distributionRate != null && f.distributionRate > 0)
    .sort((a, b) => (b.distributionRate ?? 0) - (a.distributionRate ?? 0))
    .slice(0, 8)
    .map((f) => ({ name: shortName(f), cik: f.cik, value: f.distributionRate! }));
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
