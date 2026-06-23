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
import { useInView } from '@/lib/useInView';

interface MaturityProfileChartProps {
  buckets: { label: string; pct: number | null }[];
}

const NAVY = '#0b1a2c';

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
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{label}</p>
      <div className="text-white">
        <span className="font-medium tabular-nums">{payload[0].value.toFixed(1)}%</span>
        <span className="text-white/60"> of fair value</span>
      </div>
    </div>
  );
}

export default function MaturityProfileChart({ buckets }: MaturityProfileChartProps) {
  const [ref, inView] = useInView(0.15);

  const data = (buckets ?? [])
    .filter((b) => b.pct != null)
    .map((b) => ({ bucket: b.label, pct: (b.pct as number) * 100 }));
  if (data.length === 0) return null;

  return (
    <div ref={ref}>
      <ResponsiveContainer width="100%" height={220}>
        {inView ? (
          <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f4" vertical={false} />
            <XAxis
              dataKey="bucket"
              tick={{ fontSize: 10, fill: '#6b7280' }}
              axisLine={{ stroke: '#dfe3ea' }}
              tickLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              tick={{ fontSize: 10, fill: '#6b7280' }}
              axisLine={false}
              tickLine={false}
              width={36}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(11, 26, 44, 0.04)' }} />
            <Bar dataKey="pct" fill={NAVY} radius={0} animationDuration={900} animationEasing="ease-out" />
          </BarChart>
        ) : (
          <svg width="100%" height={220} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
