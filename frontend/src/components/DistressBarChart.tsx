'use client';

import { useState } from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { formatQuarter, formatPercent } from '@/lib/format';
import { useInView } from '@/lib/useInView';
import type { CreditRiskRow } from '@/lib/types';

interface DistressBarChartProps {
  data: CreditRiskRow[];
}

const TIERS = [
  { key: 'deepDistress', label: 'Deep Distress (<80% par)', color: '#9B2226' },
  { key: 'nonAccrual', label: 'Non-Accrual', color: '#CA6702' },
  { key: 'markedBelowCost', label: 'Marked Below Cost (<90% cost)', color: '#EEC643' },
] as const;

type ViewMode = 'count' | 'fv';

function CustomTooltip({
  active,
  payload,
  label,
  viewMode,
}: {
  active?: boolean;
  payload?: { dataKey: string; color: string; value: number }[];
  label?: string;
  viewMode: ViewMode;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const cumulative = payload.reduce((s, e) => s + (e.value ?? 0), 0);
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">
        {formatQuarter(label)} ({viewMode === 'count' ? 'by count' : 'by FV'})
      </p>
      {[...payload].reverse().map((entry) => {
        const tier = TIERS.find((t) => t.key === entry.dataKey);
        return (
          <div key={entry.dataKey} className="flex items-center gap-2 text-white">
            <span
              className="w-2 h-2 shrink-0"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-white/70">{tier?.label ?? entry.dataKey}:</span>
            <span className="font-medium tabular-nums">{formatPercent(entry.value)}</span>
          </div>
        );
      })}
      <div className="border-t border-white/20 mt-1 pt-1 text-white font-medium tabular-nums">
        Cumulative signals: {formatPercent(cumulative)}
      </div>
    </div>
  );
}

export default function DistressBarChart({ data }: DistressBarChartProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('fv');
  const [ref, inView] = useInView(0.15);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 border border-surface-muted bg-surface text-muted text-sm">
        No credit risk data available.
      </div>
    );
  }

  // Signals are independent. The stacked height is cumulative signal incidence,
  // so positions with multiple signals can contribute to multiple segments.
  const chartData = data.map((row) => {
    const source = viewMode === 'count' ? row.byCount : row.byFv;
    return {
      quarter: row.quarter,
      deepDistress: source.deepDistress ?? 0,
      nonAccrual: source.nonAccrual ?? 0,
      markedBelowCost: source.markedBelowCost ?? 0,
    };
  });

  return (
    <div ref={ref}>
      {/* Toggle + legend */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex gap-1">
          <button
            onClick={() => setViewMode('count')}
            className={`text-xs px-3 py-1.5 transition-colors ${
              viewMode === 'count'
                ? 'bg-navy text-white font-medium'
                : 'text-muted hover:text-navy hover:bg-surface'
            }`}
          >
            By Count
          </button>
          <button
            onClick={() => setViewMode('fv')}
            className={`text-xs px-3 py-1.5 transition-colors ${
              viewMode === 'fv'
                ? 'bg-navy text-white font-medium'
                : 'text-muted hover:text-navy hover:bg-surface'
            }`}
          >
            By Fair Value
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {TIERS.map((t) => (
            <span key={t.key} className="flex items-center gap-1.5 text-[11px]">
              <span className="w-2 h-2" style={{ backgroundColor: t.color }} />
              <span className="text-navy">{t.label}</span>
            </span>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={320}>
        {inView ? (
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E9ECEF" vertical={false} />
            <XAxis
              dataKey="quarter"
              tickFormatter={formatQuarter}
              tick={{ fontSize: 10, fill: '#6C757D' }}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={(v: number) => formatPercent(v, 0)}
              tick={{ fontSize: 10, fill: '#6C757D' }}
            />
            <Tooltip
              content={<CustomTooltip viewMode={viewMode} />}
              cursor={{ fill: 'rgba(15, 27, 45, 0.04)' }}
            />
            {TIERS.map((t) => (
              <Bar
                key={t.key}
                dataKey={t.key}
                stackId="stress"
                fill={t.color}
                radius={0}
                animationDuration={1000}
                animationEasing="ease-out"
              />
            ))}
          </BarChart>
        ) : (
          <svg width="100%" height={320} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
