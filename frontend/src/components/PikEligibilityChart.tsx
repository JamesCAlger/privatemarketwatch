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
import type { PikEligibilityRow } from '@/lib/types';

interface PikEligibilityChartProps {
  data: PikEligibilityRow[];
}

const BAR_COLOR = '#0b1a2c';

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { payload: PikEligibilityRow }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{formatQuarter(label)}</p>
      <div className="flex items-center gap-2 text-white">
        <span className="text-white/70">By count:</span>
        <span className="font-medium tabular-nums">{formatPercent(row.byCount)}</span>
        <span className="text-white/40 tabular-nums">
          ({row.pikCount.toLocaleString()} / {row.totalPositions.toLocaleString()})
        </span>
      </div>
      <div className="flex items-center gap-2 text-white mt-0.5">
        <span className="text-white/70">By fair value:</span>
        <span className="font-medium tabular-nums">{formatPercent(row.byFv)}</span>
      </div>
    </div>
  );
}

export default function PikEligibilityChart({ data }: PikEligibilityChartProps) {
  const [ref, inView] = useInView(0.15);

  if (data.length === 0) return null;

  const chartData = data.map((row) => ({
    quarter: row.quarter,
    byCount: row.byCount ?? 0,
    byFv: row.byFv ?? 0,
    pikCount: row.pikCount,
    totalPositions: row.totalPositions,
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
            <Bar
              dataKey="byCount"
              fill={BAR_COLOR}
              radius={0}
              animationDuration={1000}
              animationEasing="ease-out"
            />
          </BarChart>
        ) : (
          <svg width="100%" height={220} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
