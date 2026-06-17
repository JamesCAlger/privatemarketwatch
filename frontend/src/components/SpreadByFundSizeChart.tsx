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
import type { SpreadByFundSizeRow } from '@/lib/types';

interface SpreadByFundSizeChartProps {
  data: SpreadByFundSizeRow[];
}

const BUCKET_COLORS = ['#0b1a2c', '#1e3a5f', '#2a4a6b', '#5a7d9a'];

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: { payload: SpreadByFundSizeRow }[];
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{row.bucket}</p>
      <div className="text-accent font-medium tabular-nums">
        {Math.round(row.was * 100)} bps
      </div>
      <div className="text-white/50 tabular-nums mt-1">
        {row.fundCount} funds &middot; {formatDollar(row.totalFv)} FV
      </div>
    </div>
  );
}

export default function SpreadByFundSizeChart({ data }: SpreadByFundSizeChartProps) {
  const [ref, inView] = useInView(0.15);

  if (data.length === 0) return null;

  const chartData = data.map((d) => ({
    ...d,
    bps: Math.round(d.was * 100),
  }));

  const bpsValues = chartData.map((d) => d.bps);
  const minBps = Math.floor((Math.min(...bpsValues) - 20) / 25) * 25;
  const maxBps = Math.ceil((Math.max(...bpsValues) + 20) / 25) * 25;

  return (
    <div ref={ref}>
      <ResponsiveContainer width="100%" height={220}>
        {inView ? (
          <BarChart data={chartData} margin={{ top: 20, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f4" vertical={false} />
            <XAxis
              dataKey="bucket"
              tick={{ fontSize: 11, fill: '#6b7280' }}
              axisLine={{ stroke: '#dfe3ea' }}
              tickLine={false}
            />
            <YAxis
              domain={[minBps, maxBps]}
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
              radius={0}
              animationDuration={800}
              animationEasing="ease-out"
            >
              {chartData.map((entry, i) => (
                <Cell
                  key={entry.bucket}
                  fill={BUCKET_COLORS[i] ?? '#5a7d9a'}
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
