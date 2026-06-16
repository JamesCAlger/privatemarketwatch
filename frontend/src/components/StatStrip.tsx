'use client';

import { useCallback } from 'react';
import AnimatedNumber from './AnimatedNumber';
import { formatDollar, formatNumber } from '@/lib/format';
import { useInView } from '@/lib/useInView';

interface StatStripProps {
  totalFv: number;
  holdingsCount: number;
  totalFunds: number;
  avgSpread: number | null;
  quarters: number;
}

export default function StatStrip({ totalFv, holdingsCount, totalFunds, avgSpread, quarters }: StatStripProps) {
  const fmtDollar = useCallback((n: number) => formatDollar(n), []);
  const fmtNumber = useCallback((n: number) => formatNumber(n), []);
  const fmtBps = useCallback((n: number) => `${n}bps`, []);
  const fmtQuarters = useCallback((n: number) => String(n), []);
  const [ref, inView] = useInView(0.3);

  // Convert percentage spread (e.g. 4.94) to basis points (494)
  const spreadBps = avgSpread != null ? Math.round(avgSpread * 100) : null;

  return (
    <div ref={ref} className="bg-white border border-rule grid grid-cols-5">
      <div className="border-r border-rule px-5 py-4">
        <div className="text-[10px] uppercase tracking-[0.14em] text-ink3 mb-1.5">
          Fair Value
        </div>
        <div className="font-mono text-[26px] text-ink tracking-[-0.02em] font-semibold tabular-nums">
          <AnimatedNumber value={totalFv} formatter={fmtDollar} inView={inView} />
        </div>
      </div>
      <div className="border-r border-rule px-5 py-4">
        <div className="text-[10px] uppercase tracking-[0.14em] text-ink3 mb-1.5">
          Covered Holdings
        </div>
        <div className="font-mono text-[26px] text-ink tracking-[-0.02em] font-semibold tabular-nums">
          <AnimatedNumber value={holdingsCount} formatter={fmtNumber} inView={inView} />
        </div>
      </div>
      <div className="border-r border-rule px-5 py-4">
        <div className="text-[10px] uppercase tracking-[0.14em] text-ink3 mb-1.5">
          Funds
        </div>
        <div className="font-mono text-[26px] text-ink tracking-[-0.02em] font-semibold tabular-nums">
          <AnimatedNumber value={totalFunds} formatter={fmtNumber} inView={inView} />
        </div>
      </div>
      <div className="border-r border-rule px-5 py-4">
        <div className="text-[10px] uppercase tracking-[0.14em] text-ink3 mb-1.5">
          Avg Spread
        </div>
        <div className="font-mono text-[26px] text-ink tracking-[-0.02em] font-semibold tabular-nums">
          {spreadBps != null ? (
            <AnimatedNumber value={spreadBps} formatter={fmtBps} inView={inView} />
          ) : (
            '--'
          )}
        </div>
      </div>
      <div className="px-5 py-4">
        <div className="text-[10px] uppercase tracking-[0.14em] text-ink3 mb-1.5">
          Quarters
        </div>
        <div className="font-mono text-[26px] text-ink tracking-[-0.02em] font-semibold tabular-nums">
          <AnimatedNumber value={quarters} formatter={fmtQuarters} inView={inView} />
        </div>
      </div>
    </div>
  );
}
