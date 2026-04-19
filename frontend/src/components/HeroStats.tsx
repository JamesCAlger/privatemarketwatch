'use client';

import { useCallback } from 'react';
import AnimatedNumber from './AnimatedNumber';
import { formatDollar, formatNumber } from '@/lib/format';
import { useInView } from '@/lib/useInView';

interface HeroStatsProps {
  totalFv: number;
  loanCount: number;
  prefEquityCount: number;
  commonEquityCount: number;
}

export default function HeroStats({ totalFv, loanCount, prefEquityCount, commonEquityCount }: HeroStatsProps) {
  const fmtDollar = useCallback((n: number) => formatDollar(n), []);
  const fmtNumber = useCallback((n: number) => formatNumber(n), []);
  const [ref, inView] = useInView(0.3);

  return (
    <div ref={ref} className="grid grid-cols-2 sm:grid-cols-4 gap-4 md:gap-6 max-w-3xl mx-auto text-center">
      <div>
        <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Total Assets</p>
        <p className="font-bold tabular-nums text-stat-sm text-white">
          <AnimatedNumber value={totalFv} formatter={fmtDollar} inView={inView} />
        </p>
      </div>
      <div>
        <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Loans</p>
        <p className="font-bold tabular-nums text-stat-sm text-white">
          <AnimatedNumber value={loanCount} formatter={fmtNumber} inView={inView} />
        </p>
      </div>
      <div>
        <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Pref. Equity</p>
        <p className="font-bold tabular-nums text-stat-sm text-white">
          <AnimatedNumber value={prefEquityCount} formatter={fmtNumber} inView={inView} />
        </p>
      </div>
      <div>
        <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Common Equity</p>
        <p className="font-bold tabular-nums text-stat-sm text-white">
          <AnimatedNumber value={commonEquityCount} formatter={fmtNumber} inView={inView} />
        </p>
      </div>
    </div>
  );
}
