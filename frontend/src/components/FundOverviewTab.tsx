import type { FundExposure } from '@/lib/types';
import { formatPercent, formatYears } from '@/lib/format';
import ExposureSection from './ExposureSection';
import MaturityProfileChart from './MaturityProfileChart';

interface FundOverviewTabProps {
  exposure: FundExposure | null;
}

export default function FundOverviewTab({ exposure }: FundOverviewTabProps) {
  if (!exposure) {
    return (
      <div className="py-12 text-center text-ink3 text-sm">
        Portfolio composition data not available for this fund.
      </div>
    );
  }

  const { wac, wacCoverage, was, wam, wamCoverage, concentration, pikExposure, creditFlags, maturityBuckets } = exposure;

  // Hide WAC/WAS if coverage is too low to be meaningful
  const MIN_COVERAGE = 0.6;
  const showWac = wac != null && (wacCoverage ?? 0) >= MIN_COVERAGE;
  const showWas = was != null && (wacCoverage ?? 0) >= MIN_COVERAGE;
  const showWacCoverage = wacCoverage != null && wacCoverage < 0.9;

  const hasCoreMetrics = showWac || showWas || wam != null || concentration?.top10Pct != null;
  const hasPik = pikExposure && pikExposure.pctOfDebtFv != null && pikExposure.pctOfDebtFv > 0;
  const hasDefault = creditFlags && creditFlags.coverage != null && creditFlags.coverage > 0.1
    && creditFlags.pctInDefault != null && creditFlags.pctInDefault > 0;
  const hasArrears = creditFlags && creditFlags.coverage != null && creditFlags.coverage > 0.1
    && creditFlags.pctInArrears != null && creditFlags.pctInArrears > 0;
  const hasCreditFlags = hasDefault || hasArrears || hasPik;
  const hasMaturity = !!maturityBuckets && maturityBuckets.some((b) => b.pct != null && b.pct > 0);

  return (
    <div className="space-y-8 py-6">
      {/* Portfolio Characteristics (dark band) */}
      {hasCoreMetrics && (
        <div className="bg-navy -mx-6 px-6 py-6">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
            {showWac && (
              <MetricCard
                label="Wtd. Avg. Coupon"
                value={`${wac!.toFixed(1)}%`}
                sub={showWacCoverage ? `${(wacCoverage! * 100).toFixed(0)}% coverage` : undefined}
                dark
              />
            )}
            {showWas && (
              <MetricCard label="Wtd. Avg. Spread" value={`${was!.toFixed(0)} bps`} dark />
            )}
            {wam != null && (
              <MetricCard
                label="Wtd. Avg. Maturity"
                value={formatYears(wam)}
                sub={wamCoverage != null ? `${(wamCoverage * 100).toFixed(0)}% coverage` : undefined}
                dark
              />
            )}
            {concentration?.top10Pct != null && (
              <MetricCard label="Top 10 Concentration" value={formatPercent(concentration.top10Pct)} dark />
            )}
          </div>
        </div>
      )}

      {/* Exposure donuts */}
      <div>
        <ExposureSection exposure={exposure} />
      </div>

      {/* Maturity profile */}
      {hasMaturity && (
        <div className="bg-white border border-rule p-6">
          <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Maturity profile</h3>
          <p className="text-xs text-ink3 mt-1 mb-4">
            Share of debt fair value by years to maturity.
          </p>
          <MaturityProfileChart buckets={maturityBuckets!} />
        </div>
      )}

      {/* Credit risk indicators */}
      {hasCreditFlags && (
        <div className="bg-white border border-rule p-5">
          <div className="eyebrow text-ink2 mb-4">Risk &amp; Credit Indicators</div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-6">
            {hasPik && pikExposure && (
              <div>
                <p className="text-[11px] text-ink3 uppercase tracking-wider mb-1">{pikExposure.label}</p>
                <p className="text-sm font-semibold text-navy tabular-nums">{formatPercent(pikExposure.pctOfDebtFv)}</p>
              </div>
            )}
            {hasDefault && creditFlags && (
              <div>
                <p className="text-[11px] text-ink3 uppercase tracking-wider mb-1">In Default</p>
                <p className="text-sm font-semibold text-red tabular-nums">{formatPercent(creditFlags.pctInDefault!)}</p>
              </div>
            )}
            {hasArrears && creditFlags && (
              <div>
                <p className="text-[11px] text-ink3 uppercase tracking-wider mb-1">In Arrears</p>
                <p className="text-sm font-semibold text-amber-600 tabular-nums">{formatPercent(creditFlags.pctInArrears!)}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricCard({
  label,
  value,
  sub,
  dark = false,
}: {
  label: string;
  value: string;
  sub?: string;
  dark?: boolean;
}) {
  return (
    <div>
      <p className={`text-[10px] uppercase tracking-[0.14em] mb-1.5 ${dark ? 'text-white/40' : 'text-ink3'}`}>
        {label}
      </p>
      <p className={`font-mono text-[28px] tabular-nums leading-none ${dark ? 'text-accent' : 'text-navy'}`}>
        {value}
      </p>
      {sub && <p className={`text-[10px] mt-1 ${dark ? 'text-white/30' : 'text-ink3'}`}>{sub}</p>}
    </div>
  );
}
