import type { FundExposure, FundPeerDistributions, GicsSectorRow } from '@/lib/types';
import { formatPercent, formatYears } from '@/lib/format';
import ExposureSection from './ExposureSection';
import PeerDistribution from './PeerDistribution';
import IndustryVsUniverse from './IndustryVsUniverse';

interface FundOverviewTabProps {
  exposure: FundExposure | null;
  peerDistributions?: FundPeerDistributions | null;
  cik?: string;
  universeSectors?: GicsSectorRow[];
}

// Order the peer-comparison metrics, position-level signals first.
const PEER_METRIC_ORDER = [
  'spreadBps',
  'firstLienPct',
  'floatingPct',
  'top10Pct',
  'creditStressPct',
  'pikPct',
  'wam',
  'distributionRate',
  'leverageRatio',
  'totalAssets',
];

export default function FundOverviewTab({ exposure, peerDistributions, cik, universeSectors }: FundOverviewTabProps) {
  if (!exposure) {
    return (
      <div className="py-12 text-center text-ink3 text-sm">
        Portfolio composition data not available for this fund.
      </div>
    );
  }

  // Peer-comparison metrics this fund actually has a value for.
  const peerMetrics = peerDistributions && cik
    ? PEER_METRIC_ORDER
        .map((k) => peerDistributions.metrics[k])
        .filter((m): m is NonNullable<typeof m> =>
          !!m && m.values.some((x) => x.cik === cik))
    : [];

  const { wac, wacCoverage, was, wam, wamCoverage, concentration, pikExposure, creditFlags } = exposure;

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

  return (
    <div className="space-y-8 py-6">
      {/* How it compares — position-level metrics vs the peer universe */}
      {peerMetrics.length > 0 && cik && (
        <div className="bg-white border border-rule p-6">
          <div className="flex items-baseline justify-between mb-1">
            <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">How it compares</h3>
          </div>
          <p className="text-xs text-ink3 mb-5">
            Each metric against the BDC coverage universe. Gold marks this fund; the dashed line is the peer median.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-10 gap-y-6">
            {peerMetrics.map((m) => (
              <PeerDistribution key={m.label} metric={m} cik={cik} />
            ))}
          </div>
        </div>
      )}

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
              <MetricCard
                label="Wtd. Avg. Spread"
                value={`${was!.toFixed(0)} bps`}
                dark
              />
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
              <MetricCard
                label="Top 10 Concentration"
                value={formatPercent(concentration.top10Pct)}
                dark
              />
            )}
          </div>
        </div>
      )}

      {/* Exposure donuts */}
      <div>
        <ExposureSection exposure={exposure} />
      </div>

      {/* Sector exposure vs universe */}
      {exposure.gicsSectors && exposure.gicsSectors.length > 0 && (universeSectors?.length ?? 0) > 0 && (
        <div className="bg-white border border-rule p-6">
          <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Sector exposure vs universe</h3>
          <p className="text-xs text-ink3 mt-2 mb-5">
            GICS sector mix against the BDC coverage universe. Gold = overweight vs the universe.
          </p>
          <IndustryVsUniverse fundSectors={exposure.gicsSectors} universe={universeSectors!} />
        </div>
      )}

      {/* Credit risk indicators */}
      {hasCreditFlags && (
        <div className="bg-white border border-rule p-5">
          <div className="eyebrow text-ink2 mb-4">Risk & Credit Indicators</div>
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
      {sub && (
        <p className={`text-[10px] mt-1 ${dark ? 'text-white/30' : 'text-ink3'}`}>{sub}</p>
      )}
    </div>
  );
}
