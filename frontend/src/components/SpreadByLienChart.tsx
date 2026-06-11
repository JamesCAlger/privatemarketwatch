'use client';

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  LabelList,
} from 'recharts';
import { formatDollar } from '@/lib/format';
import { useInView } from '@/lib/useInView';
import type { SpreadByLienRow } from '@/lib/types';

interface SpreadByLienChartProps {
  data: SpreadByLienRow[];
}

const LIEN_COLORS: Record<string, string> = {
  'First Lien': '#0b1a2c',
  'Second Lien': '#2a4a6b',
  'Unsecured': '#5a7d9a',
  'Unknown': '#8a9bab',
};

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: SpreadByLienRow & { bps: number } }[];
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{row.lien}</p>
      <div className="text-accent font-medium tabular-nums">
        {row.bps} bps
      </div>
      <div className="text-white/50 tabular-nums mt-1">
        {row.positionCount.toLocaleString()} positions &middot; {formatDollar(row.totalFv)} FV
      </div>
      <div className="text-white/40 tabular-nums">
        {(row.pctOfTotal * 100).toFixed(1)}% of total
      </div>
    </div>
  );
}

export default function SpreadByLienChart({ data }: SpreadByLienChartProps) {
  const [ref, inView] = useInView(0.15);

  if (data.length === 0) return null;

  // Filter out Unknown for the chart unless it's a large share
  const filtered = data.filter((d) => d.lien !== 'Unknown' || d.pctOfTotal >= 0.1);

  const chartData = filtered.map((d) => ({
    ...d,
    bps: Math.round(d.was * 100),
  }));

  return (
    <div ref={ref}>
      <ResponsiveContainer width="100%" height={220}>
        {inView ? (
          <BarChart data={chartData} margin={{ top: 20, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f4" vertical={false} />
            <XAxis
              dataKey="lien"
              tick={{ fontSize: 11, fill: '#6b7280' }}
              axisLine={{ stroke: '#dfe3ea' }}
              tickLine={false}
            />
            <YAxis
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
              radius={[2, 2, 0, 0]}
              animationDuration={800}
              animationEasing="ease-out"
            >
              {chartData.map((entry) => (
                <Cell
                  key={entry.lien}
                  fill={LIEN_COLORS[entry.lien] ?? '#8a9bab'}
                />
              ))}
              <LabelList
                dataKey="bps"
                position="top"
                style={{ fontSize: 11, fill: '#0b1a2c', fontWeight: 600, fontFamily: 'var(--font-mono, monospace)' }}
              />
            </Bar>
          </BarChart>
        ) : (
          <svg width="100%" height={220} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
