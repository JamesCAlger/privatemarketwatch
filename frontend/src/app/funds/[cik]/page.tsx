import { notFound } from 'next/navigation';
import { getFundDetail, getFundDetailCiks } from '@/lib/data';
import { formatDollar, formatPercent, formatNumber, formatYears, formatQuarter } from '@/lib/format';
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
  return {
    title: `${fund.name} | Private Market Watch`,
    description: `Fund one-pager for ${fund.name} (${fund.vehicleType}).`,
  };
}

// ---------------------------------------------------------------------------
// Chart data builders
// ---------------------------------------------------------------------------

/** Build a total return index by chaining monthly returns (base = 100). */
function buildTotalReturnIndex(series: FundSeriesEntry[]): { quarter: string; level: number }[] {
  let level = 100;
  const result: { quarter: string; level: number }[] = [];

  for (const s of series) {
    const months = [s.monthly_return_1, s.monthly_return_2, s.monthly_return_3];
    let anyReturn = false;
    for (const m of months) {
      if (typeof m === 'number') {
        level *= 1 + m / 100; // monthly returns stored as percentage points
        anyReturn = true;
      }
    }
    if (anyReturn) {
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
 * - Interval/tender with monthly returns: total return index (chained monthly)
 * - BDCs with quarterly NAV: NAV/share
 * - Fallback: whichever has more data points
 */
function pickLineChart(series: FundSeriesEntry[], vehicleType: string) {
  const trIndex = buildTotalReturnIndex(series);
  const navIndex = buildNavSeries(series);

  // Count distinct NAV values to detect carried-forward annual snapshots
  const distinctNavs = new Set(navIndex.map((d) => d.level)).size;
  const navIsGenuineQuarterly = distinctNavs >= navIndex.length * 0.5;

  if (vehicleType === 'bdc') {
    if (navIndex.length >= 2) {
      return { data: navIndex, label: 'NAV/Share', key: 'nav' };
    }
    if (trIndex.length >= 2) {
      return { data: trIndex, label: 'Total Return', key: 'tr' };
    }
  } else {
    if (trIndex.length >= 2) {
      return { data: trIndex, label: 'Total Return', key: 'tr' };
    }
    if (navIndex.length >= 2 && navIsGenuineQuarterly) {
      return { data: navIndex, label: 'NAV/Share', key: 'nav' };
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// Maturity bar chart (simple CSS bars)
// ---------------------------------------------------------------------------

function MaturityChart({ buckets, coverage }: {
  buckets: { label: string; pct: number }[];
  coverage: number;
}) {
  const nonZero = buckets.filter((b) => b.pct > 0);
  if (nonZero.length === 0) return null;
  const maxPct = Math.max(...buckets.map((b) => b.pct));

  return (
    <div className="bg-white rounded-lg shadow-card p-5">
      <div className="flex items-baseline justify-between mb-4">
        <p className="text-sm font-medium text-navy">Maturity Profile</p>
        <p className="text-[10px] text-muted">
          {(coverage * 100).toFixed(0)}% of positions have maturity data
        </p>
      </div>
      {/* Bar chart area */}
      <div className="flex gap-2">
        {buckets.map((b) => {
          const barH = maxPct > 0 ? (b.pct / maxPct) * 100 : 0;
          return (
            <div key={b.label} className="flex-1 flex flex-col items-center">
              {/* Label above bar */}
              <span className="text-[10px] text-muted tabular-nums mb-1 h-4">
                {b.pct > 0 ? `${(b.pct * 100).toFixed(0)}%` : ''}
              </span>
              {/* Bar container — fixed height, bars grow upward */}
              <div className="w-full h-28 flex items-end">
                <div
                  className="w-full rounded-t bg-teal/80"
                  style={{
                    height: `${barH}%`,
                    minHeight: b.pct > 0 ? '4px' : '0px',
                  }}
                />
              </div>
              {/* X-axis label */}
              <span className="text-[10px] text-muted mt-1">{b.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// FV Hierarchy bar
// ---------------------------------------------------------------------------

function FvHierarchyBar({ hierarchy }: { hierarchy: NonNullable<FundExposure['fvHierarchy']> }) {
  const levels = [
    { label: 'Level 1', pct: hierarchy.level1 ?? 0, color: '#16A34A' },
    { label: 'Level 2', pct: hierarchy.level2 ?? 0, color: '#2A9D8F' },
    { label: 'Level 3', pct: hierarchy.level3 ?? 0, color: '#E76F51' },
  ];
  const nonZero = levels.filter((l) => l.pct > 0);
  if (nonZero.length === 0) return null;

  return (
    <div>
      <p className="text-[11px] text-muted uppercase tracking-wider mb-2">Fair Value Hierarchy</p>
      <div className="flex rounded-md overflow-hidden h-5 mb-2">
        {levels.map((l) => {
          if (l.pct <= 0) return null;
          return (
            <div
              key={l.label}
              className="flex items-center justify-center text-[10px] text-white font-medium"
              style={{ width: `${l.pct * 100}%`, backgroundColor: l.color }}
              title={`${l.label}: ${(l.pct * 100).toFixed(1)}%`}
            >
              {l.pct >= 0.08 ? `L${l.label.slice(-1)}` : ''}
            </div>
          );
        })}
      </div>
      <div className="flex gap-3 text-[10px]">
        {levels.filter((l) => l.pct > 0).map((l) => (
          <span key={l.label} className="flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-sm" style={{ backgroundColor: l.color }} />
            <span className="text-muted">{l.label}</span>
            <span className="text-navy tabular-nums">{(l.pct * 100).toFixed(1)}%</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Portfolio Analytics section
// ---------------------------------------------------------------------------

function PortfolioAnalytics({ exposure }: { exposure: FundExposure }) {
  const { wac, wacCoverage, was, wam, wamCoverage, maturityBuckets, concentration, pikExposure, fvHierarchy, creditFlags } = exposure;

  const hasWamData = wamCoverage != null && wamCoverage > 0.1;
  const hasMaturity = hasWamData && maturityBuckets && maturityBuckets.some((b) => b.pct > 0);
  const hasPik = pikExposure && pikExposure.pctOfDebtFv != null && pikExposure.pctOfDebtFv > 0;
  const hasFvH = fvHierarchy && fvHierarchy.coverage != null && fvHierarchy.coverage > 0.1;
  const hasCreditFlags = creditFlags && creditFlags.coverage != null && creditFlags.coverage > 0.1;
  // Hide WAC/WAS if coverage is too low to be meaningful
  const MIN_COVERAGE = 0.6;
  const showWac = wac != null && (wacCoverage ?? 0) >= MIN_COVERAGE;
  const showWas = was != null && (wacCoverage ?? 0) >= MIN_COVERAGE;
  const hasRow1 = showWac || showWas || wam != null || concentration?.top10Pct != null;
  const hasRow3 = hasPik || hasFvH || hasCreditFlags;

  if (!hasRow1 && !hasMaturity && !hasRow3) return null;

  // Show WAC coverage subtitle if <90% of direct private credit
  const showWacCoverage = wacCoverage != null && wacCoverage < 0.9;

  return (
    <>
      {/* Row 1: Core metrics */}
      {hasRow1 && (
        <div className="bg-white rounded-lg shadow-card p-5 mb-4">
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
        <div className="mb-4">
          <MaturityChart buckets={maturityBuckets} coverage={wamCoverage ?? 0} />
        </div>
      )}

      {/* Row 3: Risk metrics */}
      {hasRow3 && (
        <div className="bg-white rounded-lg shadow-card p-5">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-6">
            {hasPik && pikExposure && (
              <StatItem
                label={pikExposure.label}
                value={formatPercent(pikExposure.pctOfDebtFv)}
              />
            )}
            {hasCreditFlags && creditFlags && (
              <>
                {creditFlags.pctInDefault != null && creditFlags.pctInDefault > 0 && (
                  <StatItem
                    label="In Default"
                    value={formatPercent(creditFlags.pctInDefault)}
                    color="text-red-600"
                  />
                )}
                {creditFlags.pctInArrears != null && creditFlags.pctInArrears > 0 && (
                  <StatItem
                    label="In Arrears"
                    value={formatPercent(creditFlags.pctInArrears)}
                    color="text-amber-600"
                  />
                )}
              </>
            )}
          </div>
          {hasFvH && fvHierarchy && (
            <div className="mt-5 pt-4 border-t border-surface">
              <FvHierarchyBar hierarchy={fvHierarchy} />
            </div>
          )}
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
    if (vt === 'bdc') return 'Publicly Traded';
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
  if (fund.adviser) {
    heroIdentity.push({ label: 'Manager', value: fund.adviser });
  }

  // Hero stats -- adaptive by vehicle type
  const heroStats: { label: string; value: string }[] = [];
  if (latest?.total_assets != null) {
    heroStats.push({ label: 'AUM', value: formatDollar(latest.total_assets) });
  }
  if (trail1y != null) {
    heroStats.push({
      label: '1Y Return',
      value: `${trail1y >= 0 ? '+' : ''}${(trail1y * 100).toFixed(1)}%`,
    });
  }
  if (latest?.leverage_ratio != null) {
    heroStats.push({ label: 'Leverage', value: formatPercent(latest.leverage_ratio) });
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
      <div className="hero-gradient-home hero-pattern">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12 md:py-16">
          <div className="flex flex-col items-start gap-3">
            <VehicleTypeBadge vehicleType={fund.vehicleType} size="md" />
            <h1 className="text-display-sm md:text-display-md text-white">
              {fund.name}
            </h1>
            <div className="flex flex-wrap items-center gap-4 text-sm text-white/60">
              {fund.ticker && <span className="font-medium text-white/80">{fund.ticker}</span>}
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
          <section className="mb-10 -mt-8">
            <div className="bg-white rounded-lg shadow-card p-5">
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
          <section className="mb-10">
            <SectionHeading>Portfolio Composition</SectionHeading>
            <ExposureSection exposure={exposure} />
          </section>
        )}

        {/* Portfolio Analytics */}
        {exposure && (
          <section className="mb-10">
            <SectionHeading>Portfolio Analytics</SectionHeading>
            <PortfolioAnalytics exposure={exposure} />
          </section>
        )}

        {/* Performance */}
        <section className="mb-10">
          <SectionHeading>Performance</SectionHeading>
          <FundPerformanceTable series={fund.series} />

          {lineData.length >= 2 && (
            <div className="mt-6 bg-white rounded-lg p-4 sm:p-6 shadow-card">
              <p className="text-sm font-medium text-navy mb-3">Total Return</p>
              <TotalReturnChart
                lineData={lineData}
                barData={barData}
                lineLabel={lineChart?.label ?? 'Total Return'}
              />
            </div>
          )}

          {distData.length >= 2 && (
            <div className="mt-6 bg-white rounded-lg p-4 sm:p-6 shadow-card">
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

        {/* Risk & Leverage */}
        {(latest?.leverage_ratio != null ||
          latest?.asset_coverage_ratio != null ||
          latest?.unfunded_commitments != null ||
          latest?.redemption_pressure != null ||
          latest?.expense_ratio_pct != null) && (
          <section className="mb-10">
            <SectionHeading>Risk & Leverage</SectionHeading>
            <div className="bg-white rounded-lg shadow-card p-5">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
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
          </section>
        )}

        {/* Top Holdings */}
        {topHoldings && topHoldings.length > 0 && (
          <section className="mb-10">
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
    <h2 className="text-xl font-semibold text-navy mb-6 flex items-center gap-3">
      <span className="w-1 h-5 bg-teal rounded-full" />
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
