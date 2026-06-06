'use client';

import { useCallback } from 'react';
import AnimatedNumber from './AnimatedNumber';
import { formatDollar, formatNumber } from '@/lib/format';
import { useInView } from '@/lib/useInView';

interface HeroStatsProps {
  totalFv: number;
  loanCount: number;
  commonEquityCount: number;
}

export default function HeroStats({ totalFv, loanCount, commonEquityCount }: HeroStatsProps) {
  const fmtDollar = useCallback((n: number) => formatDollar(n), []);
  const fmtNumber = useCallback((n: number) => formatNumber(n), []);
  const [ref, inView] = useInView(0.3);

  return (
    <div ref={ref} className="grid grid-cols-3 gap-4 md:gap-6 max-w-3xl mx-auto text-center">
      <div>
        <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Indexed Fair Value</p>
        <p className="font-bold tabular-nums text-stat-sm text-white">
          <AnimatedNumber value={totalFv} formatter={fmtDollar} inView={inView} />
        </p>
      </div>
      <div>
        <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Private Credit</p>
        <p className="font-bold tabular-nums text-stat-sm text-white">
          <AnimatedNumber value={loanCount} formatter={fmtNumber} inView={inView} />
        </p>
      </div>
      <div>
        <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Private Equity</p>
        <p className="font-bold tabular-nums text-stat-sm text-white">
          <AnimatedNumber value={commonEquityCount} formatter={fmtNumber} inView={inView} />
        </p>
      </div>
    </div>
  );
}
