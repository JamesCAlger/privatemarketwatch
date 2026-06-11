import { notFound } from 'next/navigation';
import { getFundDetail, getFundDetailCiks, getFundList } from '@/lib/data';
import { formatDollar, formatPercent, formatNumber } from '@/lib/format';
import { formatDisplayName, getFundNameParts } from '@/lib/nameFormat';
import type { FundExposure, FundListItem } from '@/lib/types';
import VehicleTypeBadge from '@/components/VehicleTypeBadge';
import FundDetailClient, { type PeerRanks } from '@/components/FundDetailClient';
import { getQuarterlyReturns } from '@/components/FundPerformanceTable';
import Breadcrumb from '@/components/Breadcrumb';

export function generateStaticParams() {
  return getFundDetailCiks().map((cik) => ({ cik }));
}

export function generateMetadata({ params }: { params: { cik: string } }) {
  const fund = getFundDetail(params.cik);
  if (!fund) return { title: 'Fund Not Found' };
  const fundName = getFundNameParts(fund.name, fund.ticker).displayName;
  return {
    title: `${fundName} | Metris Lens`,
    description: `Fund detail for ${fundName} (${fund.vehicleType}).`,
  };
}

// ---------------------------------------------------------------------------
// Peer ranking computation
// ---------------------------------------------------------------------------

function computePeerRanks(cik: string, funds: FundListItem[]): PeerRanks {
  const metrics: PeerRanks['metrics'] = [];

  // Helper to rank current fund in a metric
  function rankIn(
    label: string,
    getValue: (f: FundListItem) => number | null | undefined,
    higherIsBetter: boolean,
  ) {
    const withValues = funds
      .filter((f) => {
        const v = getValue(f);
        return v != null && isFinite(v);
      })
      .map((f) => ({ cik: f.cik, value: getValue(f) as number }));

    if (withValues.length < 5) return; // not enough peers

    // Sort: higher first if higherIsBetter, lower first otherwise
    const sorted = [...withValues].sort((a, b) =>
      higherIsBetter ? b.value - a.value : a.value - b.value,
    );
    const idx = sorted.findIndex((f) => f.cik === cik);
    if (idx < 0) return;

    const rank = idx + 1;
    const total = sorted.length;
    const quartile = Math.min(4, Math.ceil((rank / total) * 4)) as 1 | 2 | 3 | 4;

    metrics.push({
      label,
      value: sorted[idx].value,
      rank,
      total,
      quartile,
    });
  }

  rankIn('Distribution Rate', (f) => f.distributionRate, true);
  rankIn('Leverage Ratio', (f) => f.leverageRatio, false);
  rankIn('1Y Return', (f) => f.quarterlyReturn, true);
  rankIn('NAV/Share', (f) => f.navPerShare, true);

  return { metrics };
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function FundPage({ params }: { params: { cik: string } }) {
  const fund = getFundDetail(params.cik);
  if (!fund) notFound();

  const funds = getFundList();
  const latest = fund.series[fund.series.length - 1];
  const isBdc = fund.vehicleType === 'bdc';
  const fundNameParts = getFundNameParts(fund.name, fund.ticker);
  const adviserName = formatDisplayName(fund.adviser, { kind: 'manager' });

  // Peer ranking
  const peerRanks = computePeerRanks(fund.cik, funds);

  // Quarterly returns for 1Y trailing
  const qReturns = getQuarterlyReturns(fund.series);
  const returns = qReturns.map((q) => q.ret);
  const last4 = returns.slice(-4);
  const trail1y = last4.length >= 4
    ? last4.reduce((acc, r) => acc * (1 + r), 1) - 1
    : null;

  // Derive strategy
  const strategy = deriveStrategy(fund.exposure);
  const liquidity = deriveLiquidity(fund.vehicleType);

  // Snapshot stats for the hero card
  const snapshotStats: { label: string; value: string }[] = [];
  if (latest?.total_assets != null) {
    snapshotStats.push({ label: 'AUM', value: formatDollar(latest.total_assets) });
  }
  if (latest?.nav_per_share != null) {
    snapshotStats.push({ label: 'NAV/Share', value: `$${latest.nav_per_share.toFixed(2)}` });
  }
  if (latest?.distribution_rate != null) {
    snapshotStats.push({ label: 'Dist. Rate', value: `${latest.distribution_rate.toFixed(1)}%` });
  }
  if (latest?.leverage_ratio != null) {
    snapshotStats.push({ label: 'Leverage', value: formatPercent(latest.leverage_ratio) });
  }

  // Badges
  const badges: { label: string; bg: string; text: string }[] = [
    { label: 'BDC', bg: 'bg-teal/10', text: 'text-teal' },
  ];
  if (isBdc) {
    badges.push({ label: 'NON-TRADED', bg: 'bg-navy', text: 'text-white' });
  }
  // Check if this fund is in an index
  badges.push({ label: 'INDEX MEMBER', bg: 'bg-accent/10', text: 'text-accent' });

  return (
    <div>
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: 'Home', href: '/' },
          { label: 'Funds', href: '/' },
          { label: fundNameParts.displayName },
        ]}
      />

      {/* Hero banner */}
      <div className="hero-gradient hero-pattern">
        <div className="px-4 md:px-[120px] py-10 md:py-14">
          {/* Badges */}
          <div className="flex gap-2 mb-4">
            {badges.map((b) => (
              <span
                key={b.label}
                className={`inline-block px-2.5 py-1 text-[11px] font-semibold tracking-[0.06em] ${b.bg} ${b.text}`}
              >
                {b.label}
              </span>
            ))}
          </div>

          {/* Fund name */}
          <h1 className="text-display-sm md:text-display-md text-white mb-2">
            {fundNameParts.displayName}
          </h1>
          <div className="flex flex-wrap items-center gap-4 text-sm text-white/60 mb-6">
            {fundNameParts.ticker && (
              <span className="font-medium text-white/80">{fundNameParts.ticker}</span>
            )}
            <span>CIK {fund.cik}</span>
            {adviserName && <span>{adviserName}</span>}
          </div>

          {/* Identity row */}
          <div className="flex flex-wrap items-start divide-x divide-white/20">
            <div className="pr-6 pb-2">
              <p className="text-[11px] text-white/50 uppercase tracking-wider mb-1">Strategy</p>
              <p className="text-lg font-semibold text-white">{strategy}</p>
            </div>
            <div className="px-6 pb-2">
              <p className="text-[11px] text-white/50 uppercase tracking-wider mb-1">Liquidity</p>
              <p className="text-lg font-semibold text-white">{liquidity}</p>
            </div>
            {trail1y != null && (
              <div className="px-6 pb-2">
                <p className="text-[11px] text-white/50 uppercase tracking-wider mb-1">1Y Return</p>
                <p className="text-lg font-semibold text-white">
                  {trail1y >= 0 ? '+' : ''}{(trail1y * 100).toFixed(1)}%
                </p>
              </div>
            )}
            {fund.exposure && (
              <div className="px-6 pb-2">
                <p className="text-[11px] text-white/50 uppercase tracking-wider mb-1">Positions</p>
                <p className="text-lg font-semibold text-white">{formatNumber(fund.exposure.positionCount)}</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Snapshot stats card (overlapping hero) */}
      <div className="px-4 md:px-[120px] -mt-6">
        {snapshotStats.length > 0 && (
          <div className="bg-white border border-rule p-5 mb-6">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {snapshotStats.map((s) => (
                <div key={s.label} className="text-center">
                  <p className="text-[10px] uppercase tracking-[0.12em] text-ink3 mb-1.5">{s.label}</p>
                  <p className="font-mono text-lg text-navy font-semibold tabular-nums">{s.value}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tabbed content */}
        <FundDetailClient fund={fund} peerRanks={peerRanks} />
      </div>

      {/* Spacer */}
      <div className="h-10" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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
  if (topPct >= 0.7) return topLabel;
  if (sorted.length >= 2 && sorted[1][1] >= 0.2) {
    return `${sorted[0][0]} / ${sorted[1][0]}`;
  }
  return topLabel;
}

function deriveLiquidity(vt: string): string {
  if (vt === 'bdc') return 'Unlisted';
  if (vt === 'interval_fund') return 'Semi-Liquid';
  if (vt === 'tender_offer_fund') return 'Semi-Liquid';
  return 'Closed-End';
}
