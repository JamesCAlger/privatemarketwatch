import { notFound } from 'next/navigation';
import { getFundDetail, getFundDetailCiks, getFundPeerDistributions, getFundAumPeerBand, getGicsSectorBreakdown } from '@/lib/data';
import { formatDollar, formatNumber } from '@/lib/format';
import { formatDisplayName, getFundNameParts } from '@/lib/nameFormat';
import type { FundExposure } from '@/lib/types';
import VehicleTypeBadge from '@/components/VehicleTypeBadge';
import FundDetailClient from '@/components/FundDetailClient';
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
// Page
// ---------------------------------------------------------------------------

export default function FundPage({ params }: { params: { cik: string } }) {
  const fund = getFundDetail(params.cik);
  if (!fund) notFound();

  // Use the most recent *complete* reporting period for the snapshot. A freshly
  // filed period can appear as a partial stub (cover-page share count + income
  // but no balance-sheet instants yet); taking the last series row blindly would
  // blank out NAV/Share and AUM even though the prior quarter is fully reported.
  const completePeriods = fund.series.filter(
    (s) => s.total_assets != null || s.net_assets != null,
  );
  const latest = completePeriods[completePeriods.length - 1]
    ?? fund.series[fund.series.length - 1];
  const isBdc = fund.vehicleType === 'bdc';
  const fundNameParts = getFundNameParts(fund.name, fund.ticker);
  const adviserName = formatDisplayName(fund.adviser, { kind: 'manager' });

  const peerDistributions = getFundPeerDistributions();
  const aumPeerBand = getFundAumPeerBand();
  const universeSectors = getGicsSectorBreakdown();

  // Derive strategy
  const strategy = deriveStrategy(fund.exposure);

  // Hero stat row -- NAV/Share, AUM, Positions, Strategy.
  const heroStats: { label: string; value: string; mono?: boolean }[] = [];
  if (latest?.nav_per_share != null) {
    heroStats.push({ label: 'NAV/Share', value: `$${latest.nav_per_share.toFixed(2)}`, mono: true });
  }
  if (latest?.total_assets != null) {
    heroStats.push({ label: 'AUM', value: formatDollar(latest.total_assets), mono: true });
  }
  if (fund.exposure) {
    heroStats.push({ label: 'Positions', value: formatNumber(fund.exposure.positionCount), mono: true });
  }
  heroStats.push({ label: 'Strategy', value: strategy });

  // Badges
  const badges: { label: string; bg: string; text: string }[] = [
    { label: 'BDC', bg: 'bg-teal/10', text: 'text-teal' },
  ];
  if (isBdc) {
    badges.push(
      fundNameParts.ticker
        ? { label: 'PUBLICLY TRADED', bg: 'bg-white/10', text: 'text-white/85' }
        : { label: 'NON-TRADED', bg: 'bg-navy', text: 'text-white' },
    );
  }

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

          {/* Blurb */}
          {fund.blurb && (
            <p className="text-[15px] leading-relaxed text-white/70 max-w-[760px] mb-6">
              {fund.blurb}
            </p>
          )}

          {/* Key stats (NAV/Share leads) */}
          <div className="flex flex-wrap items-start gap-y-3 divide-x divide-white/20">
            {heroStats.map((s, i) => (
              <div key={s.label} className={i === 0 ? 'pr-6' : 'px-6'}>
                <p className="text-[11px] text-white/50 uppercase tracking-wider mb-1">{s.label}</p>
                <p className={`text-lg font-semibold text-white ${s.mono ? 'font-mono tabular-nums' : ''}`}>
                  {s.value}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Tabbed content */}
      <div className="px-4 md:px-[120px] pt-8">
        <FundDetailClient fund={fund} peerDistributions={peerDistributions} aumPeerBand={aumPeerBand} universeSectors={universeSectors} />
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
