'use client';

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { formatDollar, formatQuarter } from '@/lib/format';
import { useInView } from '@/lib/useInView';
import type { AumTimeSeriesRow } from '@/lib/types';

interface UniverseGrowthChartProps {
  data: AumTimeSeriesRow[];
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0];
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{formatQuarter(label)}</p>
      <div className="text-white font-medium tabular-nums">
        {formatDollar(row.value)}
      </div>
    </div>
  );
}

export default function UniverseGrowthChart({ data }: UniverseGrowthChartProps) {
  const [ref, inView] = useInView(0.15);

  if (data.length === 0) return null;

  return (
    <div ref={ref}>
      <ResponsiveContainer width="100%" height={240}>
        {inView ? (
          <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="aum-navy-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#0b1a2c" stopOpacity={0.35} />
                <stop offset="100%" stopColor="#0b1a2c" stopOpacity={0.04} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f4" vertical={false} />
            <XAxis
              dataKey="quarter"
              tickFormatter={formatQuarter}
              tick={{ fontSize: 10, fill: '#6b7280' }}
              axisLine={{ stroke: '#dfe3ea' }}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => formatDollar(v)}
              tick={{ fontSize: 10, fill: '#6b7280' }}
              axisLine={false}
              tickLine={false}
              width={52}
            />
            <Tooltip
              content={<ChartTooltip />}
              cursor={{ stroke: '#6b7280', strokeDasharray: '3 3' }}
            />
            <Area
              type="monotone"
              dataKey="total"
              stroke="#0b1a2c"
              strokeWidth={2}
              fill="url(#aum-navy-grad)"
              animationDuration={1200}
              animationEasing="ease-out"
            />
          </AreaChart>
        ) : (
          <svg width="100%" height={240} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
