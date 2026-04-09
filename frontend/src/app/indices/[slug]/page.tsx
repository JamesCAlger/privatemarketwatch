import { notFound } from 'next/navigation';
import { Metadata } from 'next';
import { INDICES, getIndexBySlug } from '@/lib/constants';
import {
  getIndexReturns,
  getIndexSummary,
  getTopConstituents,
  getSectorBreakdown,
  getPortfolioCharacteristics,
  getManagerConcentration,
  getConcentrationCurve,
} from '@/lib/data';
import {
  formatLevel,
  formatPercent,
  formatNumber,
  formatQuarter,
  formatYears,
  returnSign,
} from '@/lib/format';

import TimeSeriesChart from '@/components/TimeSeriesChart';
import QuarterlyBarChart from '@/components/QuarterlyBarChart';
import StatPanel from '@/components/StatPanel';
import SectorChart from '@/components/SectorChart';
import ConcentrationPieChart, { COLORS_TEAL_RAMP } from '@/components/ManagerPieChart';
import ConcentrationCurve from '@/components/ConcentrationCurve';
import ConstituentTable from '@/components/ConstituentTable';

// Generate static pages for all 4 indices
export function generateStaticParams() {
  return INDICES.map((idx) => ({ slug: idx.slug }));
}

export function generateMetadata({
  params,
}: {
  params: { slug: string };
}): Metadata {
  const idx = getIndexBySlug(params.slug);
  if (!idx) return {};
  return {
    title: idx.name,
    description: idx.description,
  };
}

export default function IndexDetailPage({
  params,
}: {
  params: { slug: string };
}) {
  const idx = getIndexBySlug(params.slug);
  if (!idx) notFound();

  const returns = getIndexReturns();
  const summaries = getIndexSummary();
  const topConstituents = getTopConstituents();
  const sectorBreakdown = getSectorBreakdown();
  const portfolioChars = getPortfolioCharacteristics();
  const managerConcentration = getManagerConcentration();
  const concentrationCurve = getConcentrationCurve();

  const summary = summaries.find((s) => s.index === idx.key);
  const series = returns[idx.key] ?? [];
  const constituents = topConstituents[idx.key] ?? [];
  const sectors = sectorBreakdown[idx.key] ?? [];
  const managerData = managerConcentration[idx.key] ?? [];
  const investeeCurve = concentrationCurve[idx.key]?.investee ?? [];
  const positionCurve = concentrationCurve[idx.key]?.position ?? [];

  // Stats panel
  const stats = [
    {
      label: 'Index Level',
      value: formatLevel(summary?.level),
    },
    {
      label: 'QoQ Return',
      value: returnSign(summary?.qoqReturn),
      delta: summary?.qoqReturn,
    },
    {
      label: 'Trailing 12M',
      value: returnSign(summary?.trailing12m),
      delta: summary?.trailing12m,
    },
    {
      label: 'Since Inception',
      value: returnSign(summary?.annualized),
      delta: summary?.annualized,
    },
    {
      label: 'Index Holdings',
      value: formatNumber(summary?.constituents),
    },
    {
      label: 'Unique Companies',
      value: formatNumber(summary?.uniqueCompanies),
    },
  ];

  // Chart data
  const chartSeries = [
    {
      key: idx.key,
      name: idx.shortName,
      color: idx.color,
      data: series.map((r) => ({ quarter: r.quarter, level: r.levelFv })),
    },
  ];

  const quarterlyReturns = series.map((r) => ({
    quarter: r.quarter,
    return: r.fvReturn,
  }));

  // Show portfolio characteristics for Direct Lending
  const showPortfolioChars = idx.key === 'DIRECT_LENDING';

  return (
    <div>
      {/* Hero Banner */}
      <div className="hero-gradient hero-pattern relative overflow-hidden">
        {/* Accent color bar at top */}
        <div className="h-1" style={{ backgroundColor: idx.color }} />
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12 md:py-16 relative z-10">
          <h1 className="text-display-sm md:text-display-lg text-white mb-4">{idx.name}</h1>
          <p className="text-white/60 max-w-2xl text-lg">
            {idx.description}
          </p>
          {idx.key === 'DIRECT_EQUITY' && (
            <p className="text-white/35 text-sm mt-3 max-w-2xl">
              Returns reflect price appreciation only. Dividend income is not
              included except for preferred equity positions where the stated rate
              is disclosed.
            </p>
          )}
        </div>
        {/* Decorative chevron */}
        <div className="absolute right-0 top-1/2 -translate-y-1/2 opacity-[0.04]">
          <svg width="300" height="300" viewBox="0 0 300 300" fill="none">
            <path d="M100 50L200 150L100 250" stroke="white" strokeWidth="40" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M160 50L260 150L160 250" stroke="white" strokeWidth="40" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        {/* Stats Panel */}
        <section className="py-10">
          <StatPanel stats={stats} accentColor={idx.color} />
        </section>

        {/* Performance Chart */}
        <section className="mb-14">
          <div className="bg-white rounded-lg p-4 sm:p-6 shadow-card">
            <TimeSeriesChart series={chartSeries} />
          </div>
        </section>

        {/* Quarterly Returns */}
        <section className="mb-14">
          <SectionHeading>Quarterly Returns</SectionHeading>
          <div className="bg-white rounded-lg p-4 sm:p-6 shadow-card">
            <QuarterlyBarChart data={quarterlyReturns} />
          </div>
        </section>

        {/* Concentration Charts */}
        {(managerData.length > 0 || investeeCurve.length > 0 || positionCurve.length > 0) && (
          <section className="mb-14">
            <SectionHeading>Concentration</SectionHeading>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {managerData.length > 0 && (
                <div className="bg-white rounded-lg p-5 shadow-card">
                  <ConcentrationPieChart data={managerData} title="By Manager" colors={COLORS_TEAL_RAMP} />
                </div>
              )}
              {investeeCurve.length > 0 && (
                <div className="bg-white rounded-lg p-5 shadow-card">
                  <ConcentrationCurve data={investeeCurve} title="By Company" />
                </div>
              )}
              {positionCurve.length > 0 && (
                <div className="bg-white rounded-lg p-5 shadow-card">
                  <ConcentrationCurve data={positionCurve} title="By Holding" />
                </div>
              )}
            </div>
          </section>
        )}

        {/* Portfolio Characteristics (DL only) */}
        {showPortfolioChars && portfolioChars.asOf && (
          <section className="mb-14">
            <SectionHeading>Portfolio Characteristics</SectionHeading>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-white rounded-lg p-5 shadow-card">
                <h3 className="text-sm font-medium text-navy mb-3">
                  Key Metrics
                </h3>
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <p className="text-xs text-muted">Weighted Avg Coupon</p>
                    <p className="text-lg font-bold text-navy tabular-nums">
                      {portfolioChars.wac != null
                        ? `${portfolioChars.wac.toFixed(1)}%`
                        : '--'}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted">Weighted Avg Spread</p>
                    <p className="text-lg font-bold text-navy tabular-nums">
                      {portfolioChars.was != null
                        ? `${(portfolioChars.was * 100).toFixed(0)} bps`
                        : '--'}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted">Weighted Avg Maturity</p>
                    <p className="text-lg font-bold text-navy tabular-nums">
                      {formatYears(portfolioChars.wam)}
                    </p>
                  </div>
                </div>
              </div>
              <div className="bg-white rounded-lg p-5 shadow-card">
                <h3 className="text-sm font-medium text-navy mb-3">
                  Rate Type Split
                </h3>
                <div className="space-y-2 mb-6">
                  <SplitBar
                    label="Floating"
                    pct={portfolioChars.rateTypeSplit.floating}
                    color={idx.color}
                  />
                  <SplitBar
                    label="Fixed"
                    pct={portfolioChars.rateTypeSplit.fixed}
                    color="#6C757D"
                  />
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Sector Breakdown (skip for DL -- nearly 100% LOAN is not informative) */}
        {sectors.length > 0 && idx.key !== 'DIRECT_LENDING' && (
          <section className="mb-14">
            <SectionHeading>Asset Category Breakdown</SectionHeading>
            <div className="bg-white rounded-lg p-5 shadow-card">
              <SectorChart data={sectors} color={idx.color} />
            </div>
          </section>
        )}

        {/* Top Constituents */}
        {constituents.length > 0 && (
          <section className="mb-14">
            <SectionHeading>Largest 20 Holdings</SectionHeading>
            <div className="bg-white rounded-lg p-1 shadow-card">
              <ConstituentTable data={constituents} indexKey={idx.key} />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-2xl font-semibold text-navy mb-8 flex items-center gap-3">
      <span className="w-1 h-5 bg-teal rounded-full" />
      {children}
    </h2>
  );
}

function SplitBar({
  label,
  pct,
  color,
}: {
  label: string;
  pct: number;
  color: string;
}) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-0.5">
        <span className="text-navy">{label}</span>
        <span className="text-muted tabular-nums">{formatPercent(pct)}</span>
      </div>
      <div className="h-1.5 bg-surface-muted rounded-full overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct * 100}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}
