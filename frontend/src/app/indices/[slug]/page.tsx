import { notFound } from 'next/navigation';
import { Metadata } from 'next';
import Link from 'next/link';
import { INDICES, getIndexBySlug, INDEX_METHODOLOGY } from '@/lib/constants';
import {
  getIndexReturns,
  getIndexSummary,
  getTopConstituents,
  getSectorBreakdown,
  getPortfolioCharacteristics,
  getManagerConcentration,
  getVehicleContribution,
  getMetadata,
  getFundIndexReturns,
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
import ReturnSummaryTable from '@/components/ReturnSummaryTable';
import SectorChart from '@/components/SectorChart';
import ConcentrationPieChart from '@/components/ManagerPieChart';
import ConstituentTable from '@/components/ConstituentTable';
import HorizontalStackedBar from '@/components/HorizontalStackedBar';

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
  const fundIndexReturns = getFundIndexReturns();

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

  // Compute multi-period returns
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

  // Gross (position-level) returns
  const gross1y = periodReturn(4);
  const gross3yTotal = periodReturn(12);
  const gross3y = gross3yTotal != null ? annualize(gross3yTotal, 3) : null;
  const gross5yTotal = periodReturn(20);
  const gross5y = gross5yTotal != null ? annualize(gross5yTotal, 5) : null;
  const grossInception = periodReturn(series.length - 1);
  const grossInceptionAnn = grossInception != null && series.length > 1
    ? annualize(grossInception, (series.length - 1) / 4)
    : null;

  // Net (fund-level) returns
  const fundSeries = fundIndexReturns['combined'] ?? [];
  function fundPeriodReturn(quartersBack: number): number | null {
    if (fundSeries.length < quartersBack + 1) return null;
    const current = fundSeries[fundSeries.length - 1]?.level;
    const base = fundSeries[fundSeries.length - 1 - quartersBack]?.level;
    if (current == null || base == null || base === 0) return null;
    return current / base - 1;
  }
  const net1y = fundPeriodReturn(4);
  const net3yTotal = fundPeriodReturn(12);
  const net3y = net3yTotal != null ? annualize(net3yTotal, 3) : null;
  const net5yTotal = fundPeriodReturn(20);
  const net5y = net5yTotal != null ? annualize(net5yTotal, 5) : null;
  const netInception = fundPeriodReturn(fundSeries.length - 1);
  const netInceptionAnn = netInception != null && fundSeries.length > 1
    ? annualize(netInception, (fundSeries.length - 1) / 4)
    : null;

  const returnRows = [
    { label: 'QoQ', net: summary?.qoqReturn ?? null, gross: summary?.qoqReturn ?? null },
    { label: '1 Year', net: net1y, gross: gross1y },
    { label: '3 Year (ann.)', net: net3y, gross: gross3y },
    { label: '5 Year (ann.)', net: net5y, gross: gross5y },
    { label: 'Since Inception (ann.)', net: netInceptionAnn, gross: grossInceptionAnn },
  ];

  // Universe coverage heuristic per index
  const coveragePct = idx.key === 'DIRECT_LENDING' ? '96.4%' :
    idx.key === 'COMMON_EQUITY' ? '92.3%' : '--';

  // Risk stats
  const risk = summary?.riskStats;

  // Lien split for structural composition
  const lienItems = showPortfolioChars && portfolioChars ? [
    { label: 'First Lien', pct: portfolioChars.lienSplit.firstLien },
    { label: 'Second Lien', pct: portfolioChars.lienSplit.secondLien },
    { label: 'Unsecured', pct: portfolioChars.lienSplit.unsecured },
  ] : [];

  // Top 25 constituents
  const top25 = constituents.slice(0, 25);

  // Methodology content
  const methodology = INDEX_METHODOLOGY[idx.key];

  return (
    <div>
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: 'Home', href: '/' },
          { label: 'Indices' },
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
            sub="post-Q4 BDC XBRL"
          />
        </div>
      </div>

      {/* ================================================================ */}
      {/* PERFORMANCE + RETURN SUMMARY                                     */}
      {/* ================================================================ */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 pb-10">
        <PerfSection
          series={chartSeries}
          title="Index performance"
          subtitle={idx.shortName}
        >
          <ReturnSummaryTable rows={returnRows} showGross={true} />
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
                <div className="eyebrow text-accent mb-2">Private Credit</div>
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

      {/* CE portfolio characteristics — different metrics */}
      {idx.key === 'COMMON_EQUITY' && summary && (
        <div className="bg-navy">
          <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
            <div className="grid grid-cols-1 md:grid-cols-[auto_1fr] gap-8 items-start">
              <div className="md:pr-6">
                <div className="eyebrow text-accent mb-2">Private Equity</div>
                <h2 className="font-display text-[26px] text-white tracking-[-0.01em] leading-tight">
                  Portfolio<br />Characteristics
                </h2>
                <p className="text-white/40 text-xs mt-2">
                  As of {summary.latestQuarter ? formatQuarter(summary.latestQuarter) : '--'}
                </p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-0">
                <div className="py-4 px-5">
                  <div className="text-[10px] uppercase tracking-[0.14em] text-white/40 mb-2">
                    Constituent Positions
                  </div>
                  <div className="font-mono text-[36px] text-accent tabular-nums leading-none">
                    {formatNumber(summary.constituents)}
                  </div>
                </div>
                <div className="py-4 px-5 md:border-l md:border-white/[0.08]">
                  <div className="text-[10px] uppercase tracking-[0.14em] text-white/40 mb-2">
                    Unique Companies
                  </div>
                  <div className="font-mono text-[36px] text-accent tabular-nums leading-none">
                    {formatNumber(summary.uniqueCompanies)}
                  </div>
                </div>
                <div className="py-4 px-5 md:border-l md:border-white/[0.08]">
                  <div className="text-[10px] uppercase tracking-[0.14em] text-white/40 mb-2">
                    Aggregate Fair Value
                  </div>
                  <div className="font-mono text-[36px] text-accent tabular-nums leading-none">
                    {formatDollar(summary.totalFv)}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* STRUCTURAL COMPOSITION (DL only)                                 */}
      {/* ================================================================ */}
      {showPortfolioChars && lienItems.length > 0 && (
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
          <div className="bg-white border border-rule p-7">
            <div className="eyebrow text-ink2 mb-5">Structural Composition</div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              <div>
                <p className="text-xs text-ink2 mb-3">Lien Position</p>
                <HorizontalStackedBar
                  items={lienItems}
                  footnote="Percentage of total indexed fair value"
                />
              </div>
              <div>
                <p className="text-xs text-ink2 mb-3">Rate Type</p>
                <HorizontalStackedBar
                  items={[
                    { label: 'Floating', pct: portfolioChars.rateTypeSplit.floating },
                    { label: 'Fixed', pct: portfolioChars.rateTypeSplit.fixed },
                  ]}
                  footnote="Percentage of total indexed fair value"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================ */}
      {/* COMPOSITION DONUTS                                               */}
      {/* ================================================================ */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 pb-10 space-y-10">
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
        {/* TOP 25 HOLDINGS                                                 */}
        {/* ================================================================ */}
        {top25.length > 0 && (
          <section>
            <div className="bg-white border border-rule">
              <div className="p-6 pb-0">
                <h2 className="font-display text-[26px] tracking-[-0.01em] text-ink">
                  Largest 25 Holdings
                </h2>
              </div>
              <div className="p-6 pt-4">
                <ConstituentTable data={top25} indexKey={idx.key} />
                <p className="text-xs text-ink3 mt-3">
                  Top 25 of {formatNumber(summary?.constituents)} positions
                  across {formatNumber(summary?.uniqueCompanies)} issuers
                </p>
              </div>
            </div>
          </section>
        )}

        {/* ================================================================ */}
        {/* TOP FUNDS CONTRIBUTING                                          */}
        {/* ================================================================ */}
        {vehicles.length > 0 && (
          <section>
            <div className="bg-white border border-rule">
              <div className="p-6 pb-0">
                <h2 className="font-display text-[26px] tracking-[-0.01em] text-ink">
                  Top Funds Contributing
                </h2>
              </div>
              <div className="p-6 pt-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-navy">
                      <th className="py-3 px-4 text-left text-xs font-medium text-white/70 uppercase tracking-wider">
                        Fund
                      </th>
                      <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                        Positions
                      </th>
                      <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                        Fair Value
                      </th>
                      <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                        % of Index
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {vehicles.slice(0, 10).map((v, i) => (
                      <tr
                        key={String(v.cik)}
                        className={`border-b border-surface last:border-0 hover:bg-surface/50 transition-colors ${
                          i % 2 === 1 ? 'bg-surface/30' : ''
                        }`}
                      >
                        <td className="py-3 px-4 font-medium text-navy">
                          <Link
                            href={`/funds/${v.cik}`}
                            className="hover:text-teal transition-colors"
                          >
                            {v.entityName}
                          </Link>
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">
                          {formatNumber(v.positionCount)}
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">
                          {formatDollar(v.totalFv)}
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">
                          {formatPercent(v.pctOfIndex)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </section>
        )}

        {/* ================================================================ */}
        {/* METHODOLOGY SUMMARY                                             */}
        {/* ================================================================ */}
        {methodology && (
          <section>
            <div className="bg-white border border-rule p-7">
              <div className="eyebrow text-ink2 mb-4">Methodology</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm text-ink2 leading-relaxed">
                <div>
                  <p className="text-xs font-semibold text-ink mb-2 uppercase tracking-[0.08em]">
                    Eligibility
                  </p>
                  <p>{methodology.eligibility}</p>
                </div>
                <div>
                  <p className="text-xs font-semibold text-ink mb-2 uppercase tracking-[0.08em]">
                    Construction
                  </p>
                  <p>{methodology.construction}</p>
                </div>
              </div>
              <div className="mt-5 pt-4 border-t border-rule">
                <Link
                  href="/methodology"
                  className="text-teal text-sm font-medium hover:underline inline-flex items-center gap-1"
                >
                  Full methodology
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                </Link>
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
