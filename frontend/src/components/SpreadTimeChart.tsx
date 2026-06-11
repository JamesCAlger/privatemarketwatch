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
import { formatDollar, formatQuarter } from '@/lib/format';
import { useInView } from '@/lib/useInView';
import type { SpreadTimeSeriesRow } from '@/lib/types';

interface SpreadTimeChartProps {
  data: SpreadTimeSeriesRow[];
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number; payload: SpreadTimeSeriesRow & { bps: number } }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{formatQuarter(label)}</p>
      <div className="text-accent font-medium tabular-nums">
        {row.bps} bps
      </div>
      <div className="text-white/50 tabular-nums mt-1">
        {formatDollar(row.totalFv)} FV &middot; {row.positionCount.toLocaleString()} positions
      </div>
    </div>
  );
}

export default function SpreadTimeChart({ data }: SpreadTimeChartProps) {
  const [ref, inView] = useInView(0.15);

  if (data.length === 0) return null;

  const chartData = data.map((d) => ({
    ...d,
    bps: Math.round(d.was * 100),
  }));

  const bpsValues = chartData.map((d) => d.bps);
  const minBps = Math.floor(Math.min(...bpsValues) / 50) * 50;
  const maxBps = Math.ceil(Math.max(...bpsValues) / 50) * 50;

  return (
    <div ref={ref}>
      <ResponsiveContainer width="100%" height={240}>
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
              domain={[minBps, maxBps]}
              tickFormatter={(v: number) => `${v}`}
              tick={{ fontSize: 10, fill: '#6b7280' }}
              axisLine={false}
              tickLine={false}
              width={40}
              label={{
                value: 'bps',
                position: 'insideTopLeft',
                offset: -4,
                style: { fontSize: 9, fill: '#6b7280' },
              }}
            />
            <Tooltip
              content={<ChartTooltip />}
              cursor={{ fill: 'rgba(15, 27, 45, 0.04)' }}
            />
            <Bar
              dataKey="bps"
              fill="#0b1a2c"
              radius={[2, 2, 0, 0]}
              animationDuration={1000}
              animationEasing="ease-out"
            />
          </BarChart>
        ) : (
          <svg width="100%" height={240} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
