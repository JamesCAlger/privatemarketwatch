'use client';

import { useState } from 'react';
import type { FundDetail, FundListItem } from '@/lib/types';
import FundTabBar from './FundTabBar';
import FundOverviewTab from './FundOverviewTab';
import FundHoldingsTab from './FundHoldingsTab';
import FundPerformanceTab from './FundPerformanceTab';
import FundFilingsTab from './FundFilingsTab';

export interface PeerRankMetric {
  label: string;
  value: number | null;
  rank: number;
  total: number;
  quartile: 1 | 2 | 3 | 4;
}

export interface PeerRanks {
  metrics: PeerRankMetric[];
}

interface FundDetailClientProps {
  fund: FundDetail;
  peerRanks: PeerRanks;
}

export default function FundDetailClient({ fund, peerRanks }: FundDetailClientProps) {
  const [activeTab, setActiveTab] = useState('overview');

  const holdingsCount = fund.topHoldings?.length ?? 0;

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'holdings', label: 'Holdings', count: holdingsCount > 0 ? holdingsCount : undefined },
    { id: 'performance', label: 'Performance' },
    { id: 'filings', label: 'Filings' },
  ];

  return (
    <div>
      {/* Peer quartile cards */}
      {peerRanks.metrics.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          {peerRanks.metrics.map((m) => (
            <div key={m.label} className="bg-white border border-rule p-4">
              <p className="text-[10px] uppercase tracking-[0.12em] text-ink3 mb-1.5">{m.label}</p>
              <p className="font-mono text-lg text-navy tabular-nums font-semibold">
                {m.value != null ? formatMetric(m.label, m.value) : '--'}
              </p>
              <p className="text-[10px] text-ink3 mt-1">
                Rank {m.rank} of {m.total}
                <span className={`ml-1.5 inline-block px-1.5 py-0.5 text-[9px] font-semibold ${
                  m.quartile === 1 ? 'bg-teal/10 text-teal' :
                  m.quartile === 2 ? 'bg-surface text-ink2' :
                  m.quartile === 3 ? 'bg-amber-50 text-amber-700' :
                  'bg-red/10 text-red'
                }`}>
                  Q{m.quartile}
                </span>
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Tab bar */}
      <FundTabBar tabs={tabs} active={activeTab} onChange={setActiveTab} />

      {/* Tab content */}
      <div>
        {activeTab === 'overview' && (
          <FundOverviewTab exposure={fund.exposure} />
        )}
        {activeTab === 'holdings' && (
          <FundHoldingsTab holdings={fund.topHoldings} />
        )}
        {activeTab === 'performance' && (
          <FundPerformanceTab series={fund.series} vehicleType={fund.vehicleType} />
        )}
        {activeTab === 'filings' && (
          <FundFilingsTab cik={fund.cik} name={fund.name} />
        )}
      </div>
    </div>
  );
}

function formatMetric(label: string, value: number): string {
  if (label.includes('Return') || label.includes('Dist') || label.includes('Distribution')) {
    return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
  }
  if (label.includes('Leverage')) {
    return `${value.toFixed(2)}x`;
  }
  if (label.includes('NAV')) {
    return `$${value.toFixed(2)}`;
  }
  return value.toFixed(2);
}
