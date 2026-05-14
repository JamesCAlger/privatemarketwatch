import {
  getFundList,
  getFundSummary,
  getIndexReturns,
  getIndexSummary,
  getMetadata,
  getPortfolioCharacteristics,
  getManagerConcentration,
  getFundIndexReturns,
  getAumTimeSeries,
  getGicsSectorBreakdown,
  getCreditRisk,
  getDistributionHistogram,
  getLeverageHistogram,
} from '@/lib/data';
import { INDICES } from '@/lib/constants';
import { formatDollar, formatNumber, formatLevel, formatQuarter, formatPercent, formatYears, returnSign } from '@/lib/format';
import { combineConcentration } from '@/lib/data';
import Link from 'next/link';
import FundTable from '@/components/FundTable';
import HomepageSparkline from '@/components/HomepageSparkline';
import TimeSeriesChart from '@/components/TimeSeriesChart';
import StackedAreaChart from '@/components/StackedAreaChart';
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
  const aumTimeSeries = getAumTimeSeries();
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
      color: '#2A9D8F',
      data: rebaseSeries(
        dlPositionSeries.map((r) => ({ quarter: r.quarter, level: r.levelFv })),
        PERF_START_QUARTER,
      ),
    },
    {
      key: 'fundNet',
      name: 'Fund-Level (Net)',
      color: '#E76F51',
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
      <div className="hero-gradient-home hero-pattern">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 pt-14 pb-12 md:pt-20 md:pb-16">
          {/* Tagline + value prop */}
          <div className="max-w-3xl">
            <p className="text-teal text-xs font-semibold uppercase tracking-[0.15em] mb-4">
              Independent Benchmarks
            </p>
            <h1 className="text-display-sm md:text-display-lg text-white mb-5 leading-tight">
              Transparent indices for{' '}
              <span className="text-teal">private markets</span>
            </h1>
            <p className="text-white/55 text-base md:text-lg leading-relaxed max-w-2xl mb-10">
              Rules-based total return indices tracking{' '}
              {formatNumber(dlSummary?.constituents)} direct loans,{' '}
              equity co-investments, and fund allocations across{' '}
              {formatNumber(summary.totalFunds)} SEC-registered vehicles.
              Built entirely from mandatory regulatory filings.
            </p>
          </div>

          {/* Index ticker strip */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 md:gap-5">
            {INDICES.map((idx) => {
              const s = indexSummaries.find((x) => x.index === idx.key);
              if (!s) return null;
              const isPositive = (s.trailing12m ?? 0) >= 0;
              return (
                <Link
                  key={idx.key}
                  href={`/indices/${idx.slug}`}
                  className="group flex items-center gap-4 bg-white/[0.04] border border-white/[0.06] px-5 py-4 hover:bg-white/[0.07] hover:border-white/[0.12] transition-all"
                >
                  {/* Left: color pip + name + level */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: idx.color }}
                      />
                      <span className="text-white/60 text-xs font-medium uppercase tracking-wider truncate">
                        {idx.shortName}
                      </span>
                    </div>
                    <div className="flex items-baseline gap-3">
                      <span className="text-white text-xl font-bold tabular-nums">
                        {formatLevel(s.level)}
                      </span>
                      <span
                        className={`text-sm font-semibold tabular-nums ${
                          isPositive ? 'text-teal-light' : 'text-red'
                        }`}
                      >
                        {returnSign(s.trailing12m)}
                      </span>
                    </div>
                  </div>

                  {/* Right: sparkline */}
                  {s.sparkline && s.sparkline.length >= 2 && (
                    <HomepageSparkline
                      data={s.sparkline}
                      color={isPositive ? '#3DB8A9' : '#E63946'}
                      width={96}
                      height={28}
                    />
                  )}
                </Link>
              );
            })}
          </div>
        </div>
      </div>

      {/* ================================================================ */}
      {/* DATA HIGHLIGHTS BAR                                              */}
      {/* ================================================================ */}
      <div className="bg-navy-900/50 border-b border-white/[0.06]" style={{ backgroundColor: '#0A1118' }}>
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-4">
          <div className="flex flex-wrap justify-between gap-x-8 gap-y-2 text-xs">
            <DataHighlight label="Indexed Fair Value" value={formatDollar(totalIndexFv)} />
            <DataHighlight label="Registered Funds" value={formatNumber(summary.totalFunds)} />
            <DataHighlight label="CIKs with Holdings" value={formatNumber(metadata.cikCount)} />
            <DataHighlight label="Unique Companies" value={formatNumber(metadata.uniqueIssuers)} />
            <DataHighlight
              label="As Of"
              value={metadata.asOfQuarter ? formatQuarter(metadata.asOfQuarter) : '--'}
            />
          </div>
        </div>
      </div>

      {/* ================================================================ */}
      {/* MAIN CONTENT                                                     */}
      {/* ================================================================ */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10 space-y-14">

        {/* 3. Index Performance */}
        {perfSeries.some((s) => s.data.length > 0) && (
          <section>
            <div className="flex items-baseline justify-between mb-6">
              <h2 className="text-xl font-semibold text-navy flex items-center gap-3">
                <span className="w-1 h-5 bg-teal" />
                Index Performance
              </h2>
              <span className="text-xs text-muted">
                Position-level gross return vs. fund-level net return (Direct Lending)
              </span>
            </div>
            <div className="bg-white shadow-card p-5">
              <TimeSeriesChart series={perfSeries} />
            </div>
          </section>
        )}

        {/* 4. AUM Growth */}
        {aumTimeSeries.length > 0 && (
          <section>
            <div className="flex items-baseline justify-between mb-6">
              <h2 className="text-xl font-semibold text-navy flex items-center gap-3">
                <span className="w-1 h-5 bg-teal" />
                AUM Growth
              </h2>
              <span className="text-xs text-muted">
                Total assets by vehicle type
              </span>
            </div>
            <div className="bg-white shadow-card p-5">
              <StackedAreaChart data={aumTimeSeries} />
            </div>
          </section>
        )}

        {/* 5. GICS Sectors */}
        {gicsSectorBreakdown.length > 0 && (
          <section>
            <div className="flex items-baseline justify-between mb-6">
              <h2 className="text-xl font-semibold text-navy flex items-center gap-3">
                <span className="w-1 h-5 bg-teal" />
                Industry Exposure
              </h2>
              <span className="text-xs text-muted">
                BDC XBRL industry-axis data (latest quarter)
              </span>
            </div>
            <div className="bg-white shadow-card p-5">
              <GicsSectorChart data={gicsSectorBreakdown} />
            </div>
          </section>
        )}

        {/* 6. Portfolio Characteristics */}
        {hasPC && (
          <section>
            <div className="flex items-baseline justify-between mb-6">
              <h2 className="text-xl font-semibold text-navy flex items-center gap-3">
                <span className="w-1 h-5 bg-teal" />
                Portfolio Characteristics
              </h2>
              <span className="text-xs text-muted">
                Direct Lending positions as of {pc.asOf ? formatQuarter(dateToQuarter(pc.asOf)) : '--'}
              </span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
              <StatCard
                label="Wtd. Avg. Coupon"
                value={pc.wac != null ? `${pc.wac.toFixed(1)}%` : '--'}
                sub={pc.wacCoverage != null ? `${(pc.wacCoverage * 100).toFixed(0)}% coverage` : undefined}
              />
              <StatCard
                label="Wtd. Avg. Spread"
                value={pc.was != null ? `${(pc.was * 100).toFixed(0)} bps` : '--'}
                sub={pc.wasCoverage != null ? `${(pc.wasCoverage * 100).toFixed(0)}% coverage` : undefined}
              />
              <StatCard
                label="Wtd. Avg. Maturity"
                value={pc.wam != null ? formatYears(pc.wam) : '--'}
                sub={pc.wamCoverage != null ? `${(pc.wamCoverage * 100).toFixed(0)}% coverage` : undefined}
              />
              <StatCard
                label="First Lien"
                value={formatPercent(pc.lienSplit.firstLien)}
                sub="of FV"
              />
              <StatCard
                label="Floating Rate"
                value={formatPercent(pc.rateTypeSplit.floating)}
                sub="of FV"
              />
            </div>
          </section>
        )}

        {/* 7. Credit Risk */}
        {creditRisk.length > 0 && (
          <section>
            <div className="flex items-baseline justify-between mb-6">
              <h2 className="text-xl font-semibold text-navy flex items-center gap-3">
                <span className="w-1 h-5 bg-teal" />
                Credit Risk &amp; Distress
              </h2>
              <span className="text-xs text-muted">
                Direct Lending: % of positions by stress tier
              </span>
            </div>
            <div className="bg-white shadow-card p-5">
              <DistressBarChart data={creditRisk} />
            </div>
          </section>
        )}

        {/* 8. Distributions & Leverage */}
        {(distHistogram || levHistogram) && (
          <section>
            <h2 className="text-xl font-semibold text-navy mb-6 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              Distributions &amp; Leverage
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {distHistogram && (
                <div className="bg-white shadow-card p-5">
                  <HistogramChart
                    data={distHistogram}
                    title="Distribution Rate"
                    medianLabel={`Median: ${formatPercent(distHistogram.median)}`}
                  />
                </div>
              )}
              {levHistogram && (
                <div className="bg-white shadow-card p-5">
                  <HistogramChart
                    data={levHistogram}
                    title="Leverage Ratio"
                    medianLabel={`Median: ${levHistogram.median.toFixed(2)}x`}
                  />
                </div>
              )}
            </div>
          </section>
        )}

        {/* 9. Manager Concentration */}
        {combinedManagers.length > 0 && (
          <section>
            <h2 className="text-xl font-semibold text-navy mb-6 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              Manager Concentration
            </h2>
            <div className="bg-white shadow-card p-5 max-w-md mx-auto">
              <ConcentrationPieChart data={combinedManagers} title="Combined Indices" />
            </div>
          </section>
        )}

        {/* 10. Fund Universe */}
        <section>
          <div className="flex items-baseline justify-between mb-6">
            <h2 className="text-xl font-semibold text-navy flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              Fund Universe
            </h2>
            <span className="text-xs text-muted">
              {formatNumber(summary.totalFunds)} funds &middot;{' '}
              {formatDollar(summary.totalAum)} AUM
            </span>
          </div>
          <FundTable funds={funds} />
        </section>

        {/* 11. Index Detail Cards */}
        {visibleSummaries.length > 0 && (
          <section>
            <h2 className="text-xl font-semibold text-navy mb-6 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              Index Detail
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
              {INDICES.map((idx) => {
                const s = indexSummaries.find((x) => x.index === idx.key);
                return (
                  <Link
                    key={idx.key}
                    href={`/indices/${idx.slug}`}
                    className="group relative overflow-hidden bg-white p-6 transition-all hover:shadow-panel shadow-card flex flex-col"
                  >
                    <div
                      className="absolute top-0 left-0 h-1 w-full"
                      style={{ backgroundColor: idx.color }}
                    />
                    <h3 className="text-lg font-semibold mb-1 text-navy">
                      {idx.shortName}
                    </h3>
                    <p className="text-sm text-muted mb-3 flex-1">{idx.description}</p>
                    {s && (
                      <div className="flex items-baseline gap-4 text-xs text-muted mb-3">
                        <span>
                          Level{' '}
                          <span className="font-semibold text-navy tabular-nums">
                            {s.level?.toFixed(1)}
                          </span>
                        </span>
                        <span className="text-surface-muted">|</span>
                        <span>{formatNumber(s.constituents)} holdings</span>
                        <span className="text-surface-muted">|</span>
                        <span>{formatDollar(s.totalFv)} FV</span>
                      </div>
                    )}
                    <span className="inline-flex items-center gap-1 text-sm font-medium text-teal group-hover:text-teal-dark transition-colors">
                      View index
                      <svg
                        className="w-4 h-4 transition-transform group-hover:translate-x-0.5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M9 5l7 7-7 7"
                        />
                      </svg>
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function DataHighlight({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-white/35 uppercase tracking-wider">{label}</span>
      <span className="text-white/80 font-semibold tabular-nums">{value}</span>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="bg-white shadow-card p-4">
      <p className="text-xs text-muted uppercase tracking-wider mb-1">{label}</p>
      <p className="text-xl font-bold text-navy tabular-nums">{value}</p>
      {sub && <p className="text-xs text-muted mt-0.5">{sub}</p>}
    </div>
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
