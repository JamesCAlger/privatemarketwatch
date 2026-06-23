import type { FundExposure, FundPeerDistributions, GicsSectorRow } from '@/lib/types';
import PeerDistribution from './PeerDistribution';
import IndustryVsUniverse from './IndustryVsUniverse';

interface FundPeersTabProps {
  exposure: FundExposure | null;
  peerDistributions?: FundPeerDistributions | null;
  cik?: string;
  universeSectors?: GicsSectorRow[];
}

// Position-level signals first. first-lien % and floating-rate % are excluded:
// ~all BDCs cluster near 100%, so a percentile rank on them misleads.
const PEER_METRIC_ORDER = [
  'spreadBps',
  'top10Pct',
  'creditStressPct',
  'pikPct',
  'wam',
  'distributionRate',
  'leverageRatio',
  'totalAssets',
];

export default function FundPeersTab({ exposure, peerDistributions, cik, universeSectors }: FundPeersTabProps) {
  const peerMetrics = peerDistributions && cik
    ? PEER_METRIC_ORDER
        .map((k) => peerDistributions.metrics[k])
        .filter((m): m is NonNullable<typeof m> =>
          !!m && m.values.some((x) => x.cik === cik))
    : [];

  const hasSectorCompare = !!exposure?.gicsSectors?.length && (universeSectors?.length ?? 0) > 0;

  if (peerMetrics.length === 0 && !hasSectorCompare) {
    return (
      <div className="py-12 text-center text-ink3 text-sm">
        Peer comparison data not available for this fund.
      </div>
    );
  }

  return (
    <div className="space-y-8 py-6">
      {peerMetrics.length > 0 && cik && (
        <div className="bg-white border border-rule p-6">
          <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Peer comparison</h3>
          <p className="text-xs text-ink3 mb-4 mt-1">
            Each metric against the BDC coverage universe. Gold marks this fund; the dashed line is the peer median.
          </p>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-8 gap-y-7">
            {peerMetrics.map((m) => (
              <PeerDistribution key={m.label} metric={m} cik={cik} />
            ))}
          </div>
        </div>
      )}

      {hasSectorCompare && (
        <div className="bg-white border border-rule p-6">
          <h3 className="font-display text-[22px] tracking-[-0.01em] text-ink">Sector exposure vs universe</h3>
          <p className="text-xs text-ink3 mt-1 mb-5">
            GICS sector mix against the BDC coverage universe. Gold = overweight vs the universe.
          </p>
          <IndustryVsUniverse fundSectors={exposure!.gicsSectors!} universe={universeSectors!} />
        </div>
      )}
    </div>
  );
}
