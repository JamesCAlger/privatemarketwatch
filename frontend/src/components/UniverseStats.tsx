'use client';

import { formatDollar, formatNumber } from '@/lib/format';

interface UniverseStatsProps {
  totalFv: number;
  fundCount: number;
  positionCount: number;
  issuerCount: number;
}

export default function UniverseStats({ totalFv, fundCount, positionCount, issuerCount }: UniverseStatsProps) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
      <div>
        <p className="text-xs text-muted uppercase tracking-wider mb-1">Total Fair Value</p>
        <p className="text-xl font-bold text-navy tabular-nums">
          {formatDollar(totalFv)}
        </p>
      </div>
      <div>
        <p className="text-xs text-muted uppercase tracking-wider mb-1">Registered Funds</p>
        <p className="text-xl font-bold text-navy tabular-nums">
          {formatNumber(fundCount)}
        </p>
      </div>
      <div>
        <p className="text-xs text-muted uppercase tracking-wider mb-1">Index Holdings</p>
        <p className="text-xl font-bold text-navy tabular-nums">
          {formatNumber(positionCount)}
        </p>
      </div>
      <div>
        <p className="text-xs text-muted uppercase tracking-wider mb-1">Unique Companies</p>
        <p className="text-xl font-bold text-navy tabular-nums">
          {formatNumber(issuerCount)}
        </p>
      </div>
    </div>
  );
}
