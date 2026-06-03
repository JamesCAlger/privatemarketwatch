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
  getVehicleContribution,
  getMetadata,
} from '@/lib/data';
import {
  formatLevel,
  formatPercent,
  formatNumber,
  formatQuarter,
  formatYears,
  formatDollar,
  returnSign,
  returnColor,
} from '@/lib/format';

import Breadcrumb from '@/components/Breadcrumb';
import PerfSection from '@/components/PerfSection';
import SectorChart from '@/components/SectorChart';
import ConcentrationPieChart from '@/components/ManagerPieChart';
import ConstituentTable from '@/components/ConstituentTable';

// Generate static pages for all indices
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
  const vehicleContribution = getVehicleContribution();
  const metadata = getMetadata();

  const summary = summaries.find((s) => s.index === idx.key);
  const series = returns[idx.key] ?? [];
  const constituents = topConstituents[idx.key] ?? [];
  const sectors = sectorBreakdown[idx.key] ?? [];
  const managerData = managerConcentration[idx.key] ?? [];
  const vehicles = vehicleContribution[idx.key] ?? [];

  const showPortfolioChars = idx.key === 'DIRECT_LENDING';

  // Chart series for PerfSection
  const chartSeries = [
    {
      key: idx.key,
      name: idx.shortName,
      color: '#0b1a2c',
      data: series.map((r) => ({ quarter: r.quarter, level: r.levelFv })),
    },
  ];

  // Return summary rows for the table beside the chart
  function periodReturn(quartersBack: number): number | null {
    if (series.length < quartersBack + 1) return null;
    const current = series[series.length - 1]?.levelFv;
    const base = series[series.length - 1 - quartersBack]?.levelFv;
    if (current == null || base == null || base === 0) return null;
    return current / base - 1;
  }
  function annualize(totalReturn: number, years: number): number {
    if (years <= 0) return totalReturn;
    return Math.pow(1 + totalReturn, 1 / years) - 1;
  }

  const ret1y = periodReturn(4);
  const ret3yTotal = periodReturn(12);
  const ret3y = ret3yTotal != null ? annualize(ret3yTotal, 3) : null;
  const ret5yTotal = periodReturn(20);
  const ret5y = ret5yTotal != null ? annualize(ret5yTotal, 5) : null;
  const retInception = periodReturn(series.length - 1);
  const retInceptionAnn = retInception != null && series.length > 1
    ? annualize(retInception, (series.length - 1) / 4)
    : null;

  const returnRows = [
    { label: 'QoQ', value: summary?.qoqReturn },
    { label: 'YTD', value: summary?.ytd },
    { label: '1 Year', value: ret1y },
    { label: '3 Year (ann.)', value: ret3y },
    { label: '5 Year (ann.)', value: ret5y },
    { label: 'Since Inception (ann.)', value: retInceptionAnn },
  ];

  // Universe coverage heuristic per index
  const coveragePct = idx.key === 'DIRECT_LENDING' ? '96.4%' :
    idx.key === 'PREFERRED_EQUITY' ? '84.1%' :
    idx.key === 'COMMON_EQUITY' ? '92.3%' : '--';

  // Risk stats
  const risk = summary?.riskStats;

  return (
    <div>
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: 'Home', href: '/' },
          { label: 'Indices', href: '/' },
          { label: idx.shortName },
        ]}
      />

      {/* ================================================================ */}
      {/* HERO                                                             */}
      {/* ================================================================ */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 pt-6 pb-10">
        <div className="grid grid-cols-1 md:grid-cols-[3fr_2fr] gap-8 md:gap-12 items-start">
          {/* Left: headline + description + metadata */}
          <div>
            <div className="eyebrow text-accent mb-3">{idx.category}</div>
            <h1 className="font-display text-[42px] md:text-[56px] leading-[1.05] tracking-[-0.028em] text-ink mb-4">
              {idx.shortName}
            </h1>
            <p className="text-[15px] leading-relaxed text-ink2 max-w-[540px] mb-6">
              {idx.description}
            </p>
            {idx.key === 'COMMON_EQUITY' && (
              <p className="text-ink3 text-xs mb-6 max-w-[540px]">
                Returns reflect price appreciation only. Dividend income is not
                included for common equity positions.
              </p>
            )}
            {/* Metadata row */}
            <div className="flex flex-wrap gap-x-8 gap-y-2 text-xs">
              <div>
                <span className="text-[10px] uppercase tracking-[0.12em] text-ink3 block">Inception</span>
                <span className="text-ink font-medium">{idx.inceptionDate}</span>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-[0.12em] text-ink3 block">Rebalance</span>
                <span className="text-ink font-medium">Quarterly</span>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-[0.12em] text-ink3 block">Currency</span>
                <span className="text-ink font-medium">USD</span>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-[0.12em] text-ink3 block">Return Type</span>
                <span className="text-ink font-medium">{idx.returnTypes}</span>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-[0.12em] text-ink3 block">Base Level</span>
                <span className="text-ink font-medium">{idx.baseLevel} ({formatQuarter(idx.inceptionQuarter)})</span>
              </div>
            </div>
          </div>

          {/* Right: Level card */}
          <div className="bg-white border border-rule p-6">
            <div className="flex items-baseline justify-between mb-2">
              <span className="text-[10px] uppercase tracking-[0.14em] text-ink3">
                Level &middot; {summary?.latestQuarter ? formatQuarter(summary.latestQuarter) : '--'}
              </span>
              {summary?.qoqReturn != null && (
                <span className={`font-mono text-xs tabular-nums ${returnColor(summary.qoqReturn)}`}>
                  {returnSign(summary.qoqReturn)} QoQ
                </span>
              )}
            </div>
            <div className="font-mono text-[64px] leading-none tracking-[-0.03em] text-navy tabular-nums mb-5">
              {formatLevel(summary?.level)}
            </div>
            <div className="grid grid-cols-3 gap-4 border-t border-rule pt-4">
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-ink3 mb-1">1 Year</div>
                <div className={`font-mono text-[18px] tabular-nums ${returnColor(summary?.trailing12m ?? null)}`}>
                  {returnSign(summary?.trailing12m)}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-ink3 mb-1">Since Incep.</div>
                <div className={`font-mono text-[18px] tabular-nums ${returnColor(summary?.annualized ?? null)}`}>
                  {returnSign(summary?.annualized)}
                </div>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.12em] text-ink3 mb-1">Constituents</div>
                <div className="font-mono text-[18px] tabular-nums text-ink">
                  {formatNumber(summary?.constituents)}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ================================================================ */}
      {/* STAT STRIP                                                       */}
      {/* ================================================================ */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 pb-10">
        <div className="bg-white border border-rule grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 divide-x divide-rule">
          <StatCell label="Aggregate Fair Value" value={formatDollar(summary?.totalFv)} />
          <StatCell label="Unique Companies" value={formatNumber(summary?.uniqueCompanies)} />
          <StatCell label="Constituent Positions" value={formatNumber(summary?.constituents)} />
          <StatCell
            label="Funds Contributing"
            value={`${formatNumber(vehicles.length)}`}
          />
          <StatCell label="Universe Coverage" value={coveragePct} sub="of eligible AUM" />
          <StatCell
            label="Last Rebalance"
            value={formatDataVintage(metadata.dataVintage)}
            sub="post-Q4 N-PORT"
          />
        </div>
      </div>

      {/* ================================================================ */}
      {/* PERFORMANCE                                                      */}
      {/* ================================================================ */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 pb-10">
        <PerfSection
          series={chartSeries}
          title="Index performance"
          subtitle={idx.shortName}
        >
          <div>
            <div className="eyebrow text-ink2 mb-3.5">Total return summary</div>
            <div className="grid grid-cols-[1.4fr_1fr] gap-x-2 pb-2 border-b border-rule text-[10px] uppercase tracking-[0.12em] text-ink3">
              <span />
              <span className="text-right">Return</span>
            </div>
            {returnRows.map((r) => (
              <div
                key={r.label}
                className="grid grid-cols-[1.4fr_1fr] gap-x-2 items-baseline py-3 border-b border-rule2"
              >
                <span className="text-xs text-ink2">{r.label}</span>
                <span className={`font-mono text-[17px] font-semibold text-right tabular-nums ${returnColor(r.value ?? null)}`}>
                  {returnSign(r.value)}
                </span>
              </div>
            ))}
          </div>
        </PerfSection>
      </div>

      {/* ================================================================ */}
      {/* RISK STATISTICS                                                  */}
      {/* ================================================================ */}
      {risk && (
        <div className="mx-auto max-w-6xl px-4 sm:px-6 pb-10">
          <div className="bg-white border border-rule p-7">
            <div className="eyebrow text-ink2 mb-5">Risk Statistics</div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-6">
              <RiskStat label="Volatility (ann.)" value={formatPercent(risk.volatility)} />
              <RiskStat label="Sharpe Ratio" value={risk.sharpe != null ? risk.sharpe.toFixed(2) : '--'} />
              <RiskStat label="Max Drawdown" value={formatPercent(risk.maxDrawdown)} sub={risk.maxDrawdownQuarter ? formatQuarter(risk.maxDrawdownQuarter) : undefined} />
              <RiskStat label="Best Quarter" value={returnSign(risk.bestQuarter)} sub={risk.bestQuarterLabel ? formatQuarter(risk.bestQuarterLabel) : undefined} />
              <RiskStat label="Worst Quarter" value={returnSign(risk.worstQuarter)} sub={risk.worstQuarterLabel ? formatQuarter(risk.worstQuarterLabel) : undefined} />
              <RiskStat label="% Positive Qtrs" value={risk.pctPositiveQuarters != null ? `${(risk.pctPositiveQuarters * 100).toFixed(0)}%` : '--'} sub={risk.positiveQuarters != null ? `${risk.positiveQuarters} of ${risk.totalQuarters}` : undefined} />
            </div>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* PORTFOLIO CHARACTERISTICS — dark band (DL only)                  */}
      {/* ================================================================ */}
      {showPortfolioChars && portfolioChars.asOf && (
        <div className="bg-navy">
          <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
            <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-8 items-start">
              <div className="md:pr-6">
                <div className="eyebrow text-accent mb-2">Direct Lending</div>
                <h2 className="font-display text-[26px] text-white tracking-[-0.01em] leading-tight">
                  Portfolio<br />Characteristics
                </h2>
                <p className="text-white/40 text-xs mt-2">
                  As of {portfolioChars.asOf ? formatQuarter(dateToQuarter(portfolioChars.asOf)) : '--'}
                </p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-0">
                {[
                  { label: 'Wtd. Avg. Coupon', value: portfolioChars.wac != null ? `${portfolioChars.wac.toFixed(1)}%` : '--', sub: portfolioChars.wacCoverage != null ? `${(portfolioChars.wacCoverage * 100).toFixed(0)}% coverage` : undefined },
                  { label: 'Wtd. Avg. Spread', value: portfolioChars.was != null ? `${(portfolioChars.was * 100).toFixed(0)} bps` : '--', sub: portfolioChars.wasCoverage != null ? `${(portfolioChars.wasCoverage * 100).toFixed(0)}% coverage` : undefined },
                  { label: 'Wtd. Avg. Maturity', value: portfolioChars.wam != null ? formatYears(portfolioChars.wam) : '--', sub: portfolioChars.wamCoverage != null ? `${(portfolioChars.wamCoverage * 100).toFixed(0)}% coverage` : undefined },
                  { label: 'First Lien', value: formatPercent(portfolioChars.lienSplit.firstLien), sub: 'of FV' },
                  { label: 'Floating Rate', value: formatPercent(portfolioChars.rateTypeSplit.floating), sub: 'of FV' },
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
      {/* COMPOSITION                                                      */}
      {/* ================================================================ */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10 space-y-10">
        {(sectors.length > 0 || managerData.length > 0) && (
          <section>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Sector / asset category breakdown */}
              {sectors.length > 0 && (
                <div className="bg-white border border-rule p-6">
                  <div className="eyebrow text-ink2 mb-4">
                    {idx.key === 'DIRECT_LENDING' ? 'Asset Category' : 'Asset Category Breakdown'}
                  </div>
                  <SectorChart data={sectors} color={idx.color} />
                </div>
              )}
              {/* Manager concentration donut */}
              {managerData.length > 0 && (
                <div className="bg-white border border-rule p-6">
                  <div className="eyebrow text-ink2 mb-4">Manager Concentration</div>
                  <ConcentrationPieChart data={managerData} title="" />
                </div>
              )}
            </div>
          </section>
        )}

        {/* ================================================================ */}
        {/* TOP 20 HOLDINGS                                                  */}
        {/* ================================================================ */}
        {constituents.length > 0 && (
          <section>
            <div className="bg-white border border-rule">
              <div className="p-6 pb-0">
                <h2 className="font-display text-[26px] tracking-[-0.01em] text-ink">
                  Largest 20 Holdings
                </h2>
              </div>
              <div className="p-6 pt-4">
                <ConstituentTable data={constituents} indexKey={idx.key} />
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Helper components                                                   */
/* ------------------------------------------------------------------ */

function StatCell({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="p-5">
      <div className="text-[10px] uppercase tracking-[0.12em] text-ink3 mb-2">
        {label}
      </div>
      <div className="font-mono text-[22px] text-ink tabular-nums leading-tight">
        {value}
      </div>
      {sub && <div className="text-[10px] text-ink3 mt-1">{sub}</div>}
    </div>
  );
}

function RiskStat({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-[0.12em] text-ink3 mb-1.5">{label}</div>
      <div className="font-mono text-[22px] text-ink tabular-nums leading-tight">{value}</div>
      {sub && <div className="text-[10px] text-ink3 mt-1">{sub}</div>}
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

/** Format dataVintage "2026-05-19" to "May 19, 2026" */
function formatDataVintage(vintage: string): string {
  if (!vintage) return '--';
  const d = new Date(vintage + 'T00:00:00');
  if (isNaN(d.getTime())) return vintage;
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}
