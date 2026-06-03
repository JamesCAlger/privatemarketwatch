'use client';

import { useState } from 'react';
import TimeSeriesChart, { PERIODS, type Period } from './TimeSeriesChart';

const TAB_LABELS: Record<Period, string> = {
  '1y': '1Y',
  '3y': '3Y',
  '5y': '5Y',
  all: 'Since Incep.',
};

interface PerfSectionProps {
  series: {
    key: string;
    name: string;
    color: string;
    data: { quarter: string; level: number | null }[];
  }[];
  title?: string;
  subtitle?: string;
  children?: React.ReactNode;
}

export default function PerfSection({ series, title, subtitle, children }: PerfSectionProps) {
  const [period, setPeriod] = useState<Period>('all');

  return (
    <div className="bg-white border border-rule p-7">
      <div className="grid grid-cols-1 md:grid-cols-[3fr_2fr] gap-9">
        {/* Left: chart */}
        <div>
          <div className="flex flex-wrap items-baseline justify-between gap-4 mb-5">
            <h2 className="font-display text-[28px] tracking-[-0.015em] text-ink">
              {title ?? 'Index performance'}
              {subtitle != null ? (
                <span className="text-ink3 font-normal"> &middot; {subtitle}</span>
              ) : !title ? (
                <span className="text-ink3 font-normal"> &middot; Direct Lending</span>
              ) : null}
            </h2>
            <div className="flex gap-1.5 text-[11px] tracking-[0.06em]">
              {PERIODS.map((p) => (
                <button
                  key={p.key}
                  onClick={() => setPeriod(p.key)}
                  className={`px-3 py-1.5 border transition-colors ${
                    period === p.key
                      ? 'border-ink bg-navy text-white'
                      : 'border-rule text-ink2 hover:bg-rule3'
                  }`}
                >
                  {TAB_LABELS[p.key]}
                </button>
              ))}
            </div>
          </div>
          <TimeSeriesChart
            series={series}
            period={period}
            onPeriodChange={setPeriod}
          />
        </div>
        {/* Right: return summary table */}
        <div className="md:border-l md:border-rule md:pl-7">
          {children}
        </div>
      </div>
    </div>
  );
}
