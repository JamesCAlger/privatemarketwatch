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

interface StackedAreaChartProps {
  data: AumTimeSeriesRow[];
}

const SERIES = [
  { key: 'bdc', name: 'BDCs', color: '#2A9D8F' },
  { key: 'intervalFund', name: 'Interval Funds', color: '#E76F51' },
  { key: 'tenderOffer', name: 'Tender Offer Funds', color: '#E9C46A' },
] as const;

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { dataKey: string; color: string; value: number }[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const total = payload.reduce((s, e) => s + (e.value ?? 0), 0);
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{formatQuarter(label)}</p>
      {[...payload].reverse().map((entry) => (
        <div key={entry.dataKey} className="flex items-center gap-2 text-white">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-white/70">
            {SERIES.find((s) => s.key === entry.dataKey)?.name ?? entry.dataKey}:
          </span>
          <span className="font-medium tabular-nums">{formatDollar(entry.value)}</span>
        </div>
      ))}
      <div className="border-t border-white/20 mt-1 pt-1 text-white font-medium tabular-nums">
        Total: {formatDollar(total)}
      </div>
    </div>
  );
}

export default function StackedAreaChart({ data }: StackedAreaChartProps) {
  const [ref, inView] = useInView(0.15);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 border border-surface-muted bg-surface text-muted text-sm">
        No AUM data available.
      </div>
    );
  }

  return (
    <div ref={ref}>
      {/* Legend */}
      <div className="flex flex-wrap gap-3 mb-4">
        {SERIES.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5 text-xs">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: s.color }}
            />
            <span className="text-navy">{s.name}</span>
          </span>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={320}>
        {inView ? (
          <AreaChart data={data}>
            <defs>
              {SERIES.map((s) => (
                <linearGradient key={s.key} id={`aum-grad-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={s.color} stopOpacity={0.6} />
                  <stop offset="100%" stopColor={s.color} stopOpacity={0.1} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#E9ECEF" />
            <XAxis
              dataKey="quarter"
              tickFormatter={formatQuarter}
              tick={{ fontSize: 11, fill: '#6C757D' }}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={(v: number) => formatDollar(v)}
              tick={{ fontSize: 11, fill: '#6C757D' }}
            />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ stroke: '#6C757D', strokeDasharray: '3 3' }}
            />
            {SERIES.map((s) => (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                stackId="1"
                stroke={s.color}
                strokeWidth={1.5}
                fill={`url(#aum-grad-${s.key})`}
                animationDuration={1200}
                animationEasing="ease-out"
              />
            ))}
          </AreaChart>
        ) : (
          <svg width="100%" height={320} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
