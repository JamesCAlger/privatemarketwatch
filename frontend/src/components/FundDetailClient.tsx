'use client';

import { useState } from 'react';
import type { FundDetail, FundPeerDistributions, FundAumPeerBandRow } from '@/lib/types';
import FundTabBar from './FundTabBar';
import FundOverviewTab from './FundOverviewTab';
import FundHoldingsTab from './FundHoldingsTab';
import FundPerformanceTab from './FundPerformanceTab';
import FundFilingsTab from './FundFilingsTab';

interface FundDetailClientProps {
  fund: FundDetail;
  peerDistributions: FundPeerDistributions | null;
  aumPeerBand: FundAumPeerBandRow[];
}

export default function FundDetailClient({ fund, peerDistributions, aumPeerBand }: FundDetailClientProps) {
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
      {/* Tab bar */}
      <FundTabBar tabs={tabs} active={activeTab} onChange={setActiveTab} />

      {/* Tab content */}
      <div>
        {activeTab === 'overview' && (
          <FundOverviewTab
            exposure={fund.exposure}
            peerDistributions={peerDistributions}
            cik={fund.cik}
          />
        )}
        {activeTab === 'holdings' && (
          <FundHoldingsTab holdings={fund.topHoldings} />
        )}
        {activeTab === 'performance' && (
          <FundPerformanceTab series={fund.series} vehicleType={fund.vehicleType} aumPeerBand={aumPeerBand} />
        )}
        {activeTab === 'filings' && (
          <FundFilingsTab cik={fund.cik} name={fund.name} />
        )}
      </div>
    </div>
  );
}

