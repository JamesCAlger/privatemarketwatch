import { notFound } from 'next/navigation';
import { getFundDetail, getFundDetailCiks } from '@/lib/data';
import { formatDollar, formatPercent, formatNumber, formatYears, formatQuarter } from '@/lib/format';
import { formatDisplayName, getFundNameParts } from '@/lib/nameFormat';
import type { FundSeriesEntry, FundExposure } from '@/lib/types';
import VehicleTypeBadge from '@/components/VehicleTypeBadge';
import FundPerformanceTable, { getQuarterlyReturns } from '@/components/FundPerformanceTable';
import FundTopHoldings from '@/components/FundTopHoldings';
import ExposureSection from '@/components/ExposureSection';
import TotalReturnChart from '@/components/TotalReturnChart';

export function generateStaticParams() {
  return getFundDetailCiks().map((cik) => ({ cik }));
}

export function generateMetadata({ params }: { params: { cik: string } }) {
  const fund = getFundDetail(params.cik);
  if (!fund) return { title: 'Fund Not Found' };
  const fundName = getFundNameParts(fund.name, fund.ticker).displayName;
  return {
    title: `${fundName} | Metris Lens`,
    description: `Fund one-pager for ${fundName} (${fund.vehicleType}).`,
  };
}

// ---------------------------------------------------------------------------
// Chart data builders
// ---------------------------------------------------------------------------

/** Build a total return index by chaining quarterly or monthly returns. */
function buildTotalReturnIndex(series: FundSeriesEntry[]): { quarter: string; level: number }[] {
  let level = 100;
  const result: { quarter: string; level: number }[] = [];

  for (const s of series) {
    if (typeof s.quarterly_return === 'number') {
      level *= 1 + s.quarterly_return / 100;
      result.push({ quarter: s.quarter, level: Math.round(level * 100) / 100 });
      continue;
    }

    const months = [s.monthly_return_1, s.monthly_return_2, s.monthly_return_3];
    if (months.every((m) => typeof m === 'number')) {
      for (const m of months) {
        level *= 1 + (m as number) / 100;
      }
      result.push({ quarter: s.quarter, level: Math.round(level * 100) / 100 });
    }
  }

  return result;
}

/** Build NAV/share series from quarterly snapshots. */
function buildNavSeries(series: FundSeriesEntry[]): { quarter: string; level: number }[] {
  return series
    .filter((s) => s.nav_per_share != null)
    .map((s) => ({ quarter: s.quarter, level: s.nav_per_share as number }));
}

/**
 * Pick the best line chart to show:
 * - Fund rows with quarterly or monthly returns: total return index
 * - Fallback: NAV/share index when return data is unavailable
 * - Fallback: whichever has more data points
 */
function pickLineChart(series: FundSeriesEntry[], vehicleType: string) {
  const trIndex = buildTotalReturnIndex(series);
  const navIndex = buildNavSeries(series);

  // Count distinct NAV values to detect carried-forward annual snapshots
  const distinctNavs = new Set(navIndex.map((d) => d.level)).size;
  const navIsGenuineQuarterly = distinctNavs >= navIndex.length * 0.5;

  if (vehicleType === 'bdc') {
    if (trIndex.length >= 2) {
      return { data: trIndex, label: 'Total Return', key: 'tr' };
    }
    if (navIndex.length >= 2) {
      return { data: navIndex, label: 'NAV/Share Index', key: 'nav' };
    }
  } else {
    if (trIndex.length >= 2) {
      return { data: trIndex, label: 'Total Return', key: 'tr' };
    }
    if (navIndex.length >= 2 && navIsGenuineQuarterly) {
      return { data: navIndex, label: 'NAV/Share Index', key: 'nav' };
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Maturity bar chart (simple CSS bars)
// ---------------------------------------------------------------------------

// Teal ramp from light (short maturity) to dark (long maturity)
const MATURITY_COLORS = [
  '#B8ECE7', '#99DDD6', '#7ACEC5', '#5BBFB4',
  '#3DB0A3', '#2A9D8F', '#1F7268', '#1A5F56',
];

function MaturityChart({ buckets, coverage, embedded = false }: {
  buckets: { label: string; pct: number }[];
  coverage: number;
  embedded?: boolean;
}) {
  const nonZero = buckets.filter((b) => b.pct > 0);
  if (nonZero.length === 0) return null;
  const maxPct = Math.max(...buckets.map((b) => b.pct));

  return (
    <div className={embedded ? '' : 'bg-white shadow-card p-5'}>
      <div className="flex items-baseline justify-between mb-5">
        <p className="text-sm font-medium text-navy">Maturity Profile</p>
        <p className="text-[10px] text-muted">
          {(coverage * 100).toFixed(0)}% coverage
        </p>
      </div>
      <div className="flex items-end gap-1.5" style={{ height: '140px' }}>
        {buckets.map((b, i) => {
          const barH = maxPct > 0 ? (b.pct / maxPct) * 100 : 0;
          const color = MATURITY_COLORS[i % MATURITY_COLORS.length];
          return (
            <div key={b.label} className="flex-1 flex flex-col items-center h-full justify-end">
              {b.pct > 0 && (
                <span className="text-[10px] text-navy font-medium tabular-nums mb-1">
                  {(b.pct * 100).toFixed(0)}%
                </span>
              )}
              <div
                className="w-full transition-all"
                style={{
                  height: `${barH}%`,
                  minHeight: b.pct > 0 ? '3px' : '0px',
                  backgroundColor: color,
                }}
              />
            </div>
          );
        })}
      </div>
      {/* Baseline */}
      <div className="h-px bg-surface-muted" />
      {/* X-axis labels */}
      <div className="flex gap-1.5 mt-1.5">
        {buckets.map((b) => (
          <div key={b.label} className="flex-1 text-center">
            <span className="text-[10px] text-muted">{b.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Portfolio Analytics section
// ---------------------------------------------------------------------------

function PortfolioAnalytics({ exposure, embedded = false }: { exposure: FundExposure; embedded?: boolean }) {
  const { wac, wacCoverage, was, wam, wamCoverage, maturityBuckets, concentration, pikExposure, creditFlags } = exposure;

  const hasWamData = wamCoverage != null && wamCoverage > 0.1;
  const hasMaturity = hasWamData && maturityBuckets && maturityBuckets.some((b) => b.pct > 0);
  const hasPik = pikExposure && pikExposure.pctOfDebtFv != null && pikExposure.pctOfDebtFv > 0;
  const hasDefault = creditFlags && creditFlags.coverage != null && creditFlags.coverage > 0.1
    && creditFlags.pctInDefault != null && creditFlags.pctInDefault > 0;
  const hasArrears = creditFlags && creditFlags.coverage != null && creditFlags.coverage > 0.1
    && creditFlags.pctInArrears != null && creditFlags.pctInArrears > 0;
  const hasCreditFlags = hasDefault || hasArrears;
  // Hide WAC/WAS if coverage is too low to be meaningful
  const MIN_COVERAGE = 0.6;
  const showWac = wac != null && (wacCoverage ?? 0) >= MIN_COVERAGE;
  const showWas = was != null && (wacCoverage ?? 0) >= MIN_COVERAGE;
  const hasRow1 = showWac || showWas || wam != null || concentration?.top10Pct != null;
  const hasRow3 = hasPik || hasCreditFlags;

  if (!hasRow1 && !hasMaturity && !hasRow3) return null;

  // Show WAC coverage subtitle if <90% of direct private credit
  const showWacCoverage = wacCoverage != null && wacCoverage < 0.9;

  return (
    <>
      {/* Row 1: Core metrics */}
      {hasRow1 && (
        <div className={embedded ? 'border-b border-surface-muted pb-5 mb-5' : 'bg-white shadow-card p-5 mb-4'}>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
            {showWac && (
              <StatItem
                label="Weighted Avg Coupon"
                value={`${wac!.toFixed(1)}%`}
                subtitle={showWacCoverage ? `${(wacCoverage! * 100).toFixed(0)}% coverage` : undefined}
              />
            )}
            {showWas && <StatItem label="Weighted Avg Spread" value={`${was!.toFixed(0)} bps`} />}
            {wam != null && (
              <StatItem
                label="Weighted Avg Maturity"
                value={formatYears(wam)}
                subtitle={wamCoverage != null ? `${(wamCoverage * 100).toFixed(0)}% coverage` : undefined}
              />
            )}
            {concentration?.top10Pct != null && (
              <StatItem label="Top 10 Positions" value={formatPercent(concentration.top10Pct)} />
            )}
          </div>
        </div>
      )}

      {/* Row 2: Maturity chart */}
      {hasMaturity && maturityBuckets && (
        <div className={hasRow3 ? 'border-b border-surface-muted pb-5 mb-5' : ''}>
          <MaturityChart buckets={maturityBuckets} coverage={wamCoverage ?? 0} embedded={embedded} />
        </div>
      )}

      {/* Row 3: Risk metrics */}
      {hasRow3 && (
        <div className={embedded ? '' : 'bg-white shadow-card p-5'}>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-6">
            {hasPik && pikExposure && (
              <StatItem
                label={pikExposure.label}
                value={formatPercent(pikExposure.pctOfDebtFv)}
              />
            )}
            {hasDefault && creditFlags && (
              <StatItem
                label="In Default"
                value={formatPercent(creditFlags.pctInDefault!)}
                color="text-red-600"
              />
            )}
            {hasArrears && creditFlags && (
              <StatItem
                label="In Arrears"
                value={formatPercent(creditFlags.pctInArrears!)}
                color="text-amber-600"
              />
            )}
          </div>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function FundPage({ params }: { params: { cik: string } }) {
  const fund = getFundDetail(params.cik);
  if (!fund) notFound();

  const latest = fund.series[fund.series.length - 1];
  const exposure = fund.exposure;
  const topHoldings = fund.topHoldings;
  const isBdc = fund.vehicleType === 'bdc';
  const fundNameParts = getFundNameParts(fund.name, fund.ticker);
  const adviserName = formatDisplayName(fund.adviser, { kind: 'manager' });

  // Line chart (adaptive)
  const lineChart = pickLineChart(fund.series, fund.vehicleType);

  // Ensure first datapoint is 100 (rebase)
  let lineData = lineChart?.data ?? [];
  if (lineData.length > 0) {
    const base = lineData[0].level;
    if (base !== 100 && base > 0) {
      lineData = lineData.map((d) => ({
        quarter: d.quarter,
        level: Math.round((d.level / base) * 100 * 100) / 100,
      }));
    }
  }

  // Quarterly returns for combined chart
  const qReturns = getQuarterlyReturns(fund.series);
  const barData = qReturns.map((q) => ({ quarter: q.quarter, return: q.ret }));

  // Distribution history (BDCs only)
  const distData = fund.series
    .filter((s) => s.distribution_per_share != null && (s.distribution_per_share as number) > 0)
    .map((s) => ({ quarter: s.quarter, return: s.distribution_per_share as number }));

  const hasRiskMetrics = latest?.leverage_ratio != null ||
    latest?.asset_coverage_ratio != null ||
    latest?.unfunded_commitments != null ||
    latest?.redemption_pressure != null ||
    latest?.expense_ratio_pct != null;

  // Trailing 1Y return (compound last 4 quarterly returns)
  const returns = qReturns.map((q) => q.ret);
  const last4 = returns.slice(-4);
  const trail1y = last4.length >= 4
    ? last4.reduce((acc, r) => acc * (1 + r), 1) - 1
    : null;

  // ---------------------------------------------------------------------------
  // Hero identity row (PitchBook-style)
  // ---------------------------------------------------------------------------

  // Derive fund strategy from dominant asset class
  function deriveStrategy(exp: FundExposure | null): string {
    if (!exp?.assetClassSplit) return 'Multi-Strategy';
    const ac = exp.assetClassSplit;
    const entries: [string, number][] = [
      ['Private Credit', ac.privateCredit ?? 0],
      ['Private Equity', ac.privateEquity ?? 0],
      ['Real Estate', ac.realEstate ?? 0],
      ['Structured Credit', ac.structuredCredit ?? 0],
      ['Hedge Fund', ac.hedgeFund ?? 0],
      ['Cash', ac.cash ?? 0],
      ['Other', ac.other ?? 0],
    ];
    const sorted = entries.filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
    if (sorted.length === 0) return 'Multi-Strategy';
    const [topLabel, topPct] = sorted[0];
    // If dominant >70%, name it; if two are significant, "Credit & Equity" style
    if (topPct >= 0.7) return topLabel;
    if (sorted.length >= 2 && sorted[1][1] >= 0.2) {
      return `${sorted[0][0]} / ${sorted[1][0]}`;
    }
    return topLabel;
  }

  // Derive liquidity label from vehicle type
  function deriveLiquidity(vt: string): string {
    if (vt === 'bdc') return 'Unlisted';
    if (vt === 'interval_fund') return 'Semi-Liquid';
    if (vt === 'tender_offer_fund') return 'Semi-Liquid';
    return 'Closed-End';
  }

  // Derive exposure style from exposureTypeSplit
  function deriveExposureStyle(exp: FundExposure | null): string | null {
    if (!exp?.exposureTypeSplit) return null;
    const et = exp.exposureTypeSplit;
    const direct = et.direct ?? 0;
    const fund = et.fund ?? 0;
    if (direct >= 0.8) return 'Direct';
    if (fund >= 0.8) return 'Fund-of-Funds';
    if (direct >= 0.4 && fund >= 0.2) return 'Hybrid';
    return 'Direct';
  }

  const strategy = deriveStrategy(exposure);
  const liquidity = deriveLiquidity(fund.vehicleType);
  const exposureStyle = deriveExposureStyle(exposure);

  // Build hero identity items (PitchBook-style large stats with dividers)
  const heroIdentity: { label: string; value: string }[] = [
    { label: 'Strategy', value: strategy },
    { label: 'Liquidity', value: liquidity },
  ];
  if (exposureStyle) {
    heroIdentity.push({ label: 'Exposure', value: exposureStyle });
  }
  if (adviserName) {
    heroIdentity.push({ label: 'Manager', value: adviserName });
  }

  // Hero stats -- adaptive by vehicle type
  const heroStats: { label: string; value: string }[] = [];
  if (latest?.total_assets != null) {
    heroStats.push({ label: 'GAV', value: formatDollar(latest.total_assets) });
  }
  if (latest?.net_assets != null) {
    heroStats.push({ label: 'NAV', value: formatDollar(latest.net_assets) });
  }
  if (latest?.leverage_ratio != null) {
    heroStats.push({ label: 'Leverage', value: formatPercent(latest.leverage_ratio) });
  }
  if (trail1y != null) {
    heroStats.push({
      label: '1Y Return',
      value: `${trail1y >= 0 ? '+' : ''}${(trail1y * 100).toFixed(1)}%`,
    });
  }
  if (isBdc) {
    if (latest?.nav_per_share != null) {
      heroStats.push({ label: 'NAV/Share', value: `$${latest.nav_per_share.toFixed(2)}` });
    }
    if (latest?.distribution_rate != null) {
      heroStats.push({ label: 'Dist. Rate', value: `${latest.distribution_rate.toFixed(1)}%` });
    }
  } else {
    if (latest?.expense_ratio_pct != null) {
      heroStats.push({ label: 'Expense Ratio', value: `${latest.expense_ratio_pct.toFixed(2)}%` });
    }
    if (exposure && exposure.rateTypeSplit.floating != null && (exposure.assetSplit.debt ?? 0) > 0.1) {
      heroStats.push({ label: '% Floating', value: formatPercent(exposure.rateTypeSplit.floating) });
    }
  }
  if (exposure) {
    heroStats.push({ label: 'Positions', value: formatNumber(exposure.positionCount) });
    if (exposure.lienSplit.firstLien != null && (exposure.assetSplit.debt ?? 0) > 0.1
        && (exposure.lienSplit.coverage ?? 0) >= 0.5) {
      heroStats.push({ label: '% First Lien', value: formatPercent(exposure.lienSplit.firstLien) });
    }
  }

  return (
    <div>
      {/* Identity banner */}
      <div className="hero-gradient hero-pattern">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12 md:py-16">
          <div className="flex flex-col items-start gap-3">
            <VehicleTypeBadge vehicleType={fund.vehicleType} size="md" />
            <h1 className="text-display-sm md:text-display-md text-white">
              {fundNameParts.displayName}
            </h1>
            <div className="flex flex-wrap items-center gap-4 text-sm text-white/60">
              {fundNameParts.ticker && <span className="font-medium text-white/80">{fundNameParts.ticker}</span>}
              <span>CIK {fund.cik}</span>
            </div>
          </div>

          {/* PitchBook-style identity row */}
          <div className="mt-8 flex flex-wrap items-start divide-x divide-white/20">
            {heroIdentity.map((item, i) => (
              <div key={item.label} className={`${i === 0 ? 'pr-6' : 'px-6'} pb-2`}>
                <p className="text-[11px] text-white/50 uppercase tracking-wider mb-1">{item.label}</p>
                <p className="text-lg md:text-xl font-semibold text-white leading-tight">{item.value}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
        {/* Hero stats */}
        {heroStats.length > 0 && (
          <section className="mb-14 -mt-8">
            <div className="bg-white shadow-card p-5">
              <div className={`grid grid-cols-2 sm:grid-cols-4 gap-4 ${
                heroStats.length > 4 ? 'lg:grid-cols-8' : ''
              }`}>
                {heroStats.map((s) => (
                  <div key={s.label} className="text-center">
                    <p className="text-[11px] text-muted uppercase tracking-wider mb-1">{s.label}</p>
                    <p className="text-sm font-semibold text-navy tabular-nums">{s.value}</p>
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        {/* Composition / Exposure */}
        {exposure && (
          <section className="mb-14">
            <SectionHeading>Portfolio Composition</SectionHeading>
            <ExposureSection exposure={exposure} />
          </section>
        )}

        {/* Performance */}
        <section className="mb-14">
          <SectionHeading>Performance</SectionHeading>
          <FundPerformanceTable series={fund.series} />

          {lineData.length >= 2 && (
            <div className="mt-6 bg-white p-4 sm:p-6 shadow-card">
              <p className="text-sm font-medium text-navy mb-3">
                {lineChart?.label ?? 'Total Return'}
              </p>
              <TotalReturnChart
                lineData={lineData}
                barData={barData}
                lineLabel={lineChart?.label ?? 'Total Return'}
                showBars={false}
              />
            </div>
          )}

          {distData.length >= 2 && (
            <div className="mt-6 bg-white p-4 sm:p-6 shadow-card">
              <p className="text-sm font-medium text-navy mb-3">Distribution History ($/Share)</p>
              <TotalReturnChart
                lineData={[]}
                barData={distData}
                lineLabel=""
                positiveColor="#2A9D8F"
              />
            </div>
          )}
        </section>

        {(exposure || hasRiskMetrics) && (
          <section className="mb-14 bg-white shadow-card p-5 sm:p-6">
            <div className="grid gap-8 xl:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)] xl:items-start">
              {/* Portfolio Analytics */}
              {exposure && (
                <div>
                  <SectionHeading>Portfolio Analytics</SectionHeading>
                  <PortfolioAnalytics exposure={exposure} embedded />
                </div>
              )}

              {/* Risk & Leverage */}
              {hasRiskMetrics && (
                <div>
                  <SectionHeading>Risk & Leverage</SectionHeading>
                  <div className="grid grid-cols-2 gap-6">
                    {latest?.leverage_ratio != null && (
                      <StatItem label="Leverage Ratio" value={formatPercent(latest.leverage_ratio)} />
                    )}
                    {latest?.asset_coverage_ratio != null && (
                      <StatItem label="Asset Coverage" value={`${latest.asset_coverage_ratio.toFixed(0)}%`} />
                    )}
                    {latest?.unfunded_commitments != null && (
                      <StatItem label="Unfunded Commitments" value={formatDollar(latest.unfunded_commitments)} />
                    )}
                    {latest?.redemption_pressure != null && (
                      <StatItem label="Redemption Pressure" value={`${latest.redemption_pressure.toFixed(1)}%`} />
                    )}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* Top Holdings */}
        {topHoldings && topHoldings.length > 0 && (
          <section className="mb-14">
            <SectionHeading>Top Holdings</SectionHeading>
            <FundTopHoldings holdings={topHoldings} />
          </section>
        )}
      </div>
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-2xl font-semibold text-navy mb-8 flex items-center gap-3">
      <span className="w-1 h-5 bg-teal" />
      {children}
    </h2>
  );
}

function StatItem({
  label,
  value,
  subtitle,
  color,
}: {
  label: string;
  value: string;
  subtitle?: string;
  color?: string;
}) {
  return (
    <div>
      <p className="text-[11px] text-muted uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-sm font-semibold tabular-nums ${color ?? 'text-navy'}`}>{value}</p>
      {subtitle && <p className="text-[10px] text-muted mt-0.5">{subtitle}</p>}
    </div>
  );
}
