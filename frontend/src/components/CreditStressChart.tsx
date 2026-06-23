'use client';

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

interface CreditStressChartProps {
  data: CreditRiskRow[];
}

// Ink value ramp — single-hue monotonic encoding per the V2 design.
// Darkest = most severe (top of stack), lightest = broadest signal (bottom).
const TIERS = [
  { key: 'deepDistress', label: 'Deep Distress (<80% par)', color: '#0b1a2c' },
  { key: 'nonAccrual', label: 'Non-Accrual', color: '#6b7a8b' },
  { key: 'markedBelowCost', label: 'Marked 10%+ Below Cost', color: '#c0c6ce' },
] as const;

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { dataKey: string; color: string; value: number }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, e) => s + (e.value ?? 0), 0);
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{formatQuarter(label)}</p>
      {[...payload].reverse().map((entry) => {
        const tier = TIERS.find((t) => t.key === entry.dataKey);
        return (
          <div key={entry.dataKey} className="flex items-center gap-2 text-white">
            <span className="w-2 h-2 shrink-0" style={{ backgroundColor: entry.color }} />
            <span className="text-white/70">{tier?.label ?? entry.dataKey}:</span>
            <span className="font-medium tabular-nums">{formatPercent(entry.value)}</span>
          </div>
        );
      })}
      <div className="border-t border-white/20 mt-1 pt-1 text-white font-medium tabular-nums">
        Cumulative: {formatPercent(total)}
      </div>
    </div>
  );
}

export default function CreditStressChart({ data }: CreditStressChartProps) {
  const [ref, inView] = useInView(0.15);

  if (data.length === 0) return null;

  const chartData = data.map((row) => ({
    quarter: row.quarter,
    deepDistress: row.byFv.deepDistress ?? 0,
    nonAccrual: row.byFv.nonAccrual ?? 0,
    markedBelowCost: row.byFv.markedBelowCost ?? 0,
  }));

  return (
    <div ref={ref}>
      <ResponsiveContainer width="100%" height={220}>
        {inView ? (
          <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f4" vertical={false} />
            <XAxis
              dataKey="quarter"
              tickFormatter={formatQuarter}
              tick={{ fontSize: 10, fill: '#6b7280' }}
              axisLine={{ stroke: '#dfe3ea' }}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
              tick={{ fontSize: 10, fill: '#6b7280' }}
              axisLine={false}
              tickLine={false}
              width={36}
            />
            <Tooltip
              content={<ChartTooltip />}
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
          <svg width="100%" height={220} />
        )}
      </ResponsiveContainer>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 mt-3 text-[11px] text-ink2">
        {[...TIERS].reverse().map((t) => (
          <span key={t.key} className="inline-flex items-center gap-1.5">
            <span className="w-[9px] h-[9px] border border-rule" style={{ backgroundColor: t.color }} />
            {t.label}
          </span>
        ))}
      </div>
    </div>
  );
}
