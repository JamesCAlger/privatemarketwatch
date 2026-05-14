'use client';

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { formatPercent } from '@/lib/format';
import { useInView } from '@/lib/useInView';
import type { HistogramData } from '@/lib/types';

interface HistogramChartProps {
  data: HistogramData;
  title: string;
  medianLabel?: string;
}

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
  const bdc = payload.find((p) => p.dataKey === 'bdc')?.value ?? 0;
  const nonBdc = payload.find((p) => p.dataKey === 'nonBdc')?.value ?? 0;
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{label}</p>
      <div className="flex items-center gap-2 text-white">
        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: '#2A9D8F' }} />
        <span className="text-white/70">BDC:</span>
        <span className="font-medium tabular-nums">{bdc}</span>
      </div>
      <div className="flex items-center gap-2 text-white">
        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: '#E9C46A' }} />
        <span className="text-white/70">Non-BDC:</span>
        <span className="font-medium tabular-nums">{nonBdc}</span>
      </div>
      <div className="border-t border-white/20 mt-1 pt-1 text-white font-medium">
        Total: {bdc + nonBdc}
      </div>
    </div>
  );
}

export default function HistogramChart({ data, title, medianLabel }: HistogramChartProps) {
  const [ref, inView] = useInView(0.15);

  if (!data.buckets || data.buckets.length === 0) {
    return (
      <div className="flex items-center justify-center h-[220px] border border-surface-muted bg-surface text-muted text-sm">
        No data available.
      </div>
    );
  }

  // Find the bucket index where median falls for the reference line
  const medianBucketIdx = data.buckets.findIndex((b) => {
    // Parse bucket label to find which contains the median
    // Simplified: just place at closest bucket by total
    return b.total > 0;
  });

  return (
    <div ref={ref}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-navy">{title}</h3>
        <span className="text-xs text-muted tabular-nums">
          {medianLabel ?? `Median: ${formatPercent(data.median)}`} | {data.total} funds
        </span>
      </div>

      {/* Legend */}
      <div className="flex gap-3 mb-2">
        <span className="flex items-center gap-1.5 text-[11px]">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#2A9D8F' }} />
          <span className="text-navy">BDC</span>
        </span>
        <span className="flex items-center gap-1.5 text-[11px]">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#E9C46A' }} />
          <span className="text-navy">Non-BDC</span>
        </span>
      </div>

      <ResponsiveContainer width="100%" height={220}>
        {inView ? (
          <BarChart data={data.buckets}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E9ECEF" vertical={false} />
            <XAxis
              dataKey="bucket"
              tick={{ fontSize: 9, fill: '#6C757D' }}
              interval={0}
              angle={-30}
              textAnchor="end"
              height={45}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#6C757D' }}
              allowDecimals={false}
            />
            {medianBucketIdx >= 0 && (
              <ReferenceLine
                x={data.buckets[medianBucketIdx]?.bucket}
                stroke="#0F1B2D"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{ value: 'Median', fill: '#6C757D', fontSize: 10, position: 'top' }}
              />
            )}
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ fill: 'rgba(15, 27, 45, 0.04)' }}
            />
            <Bar
              dataKey="bdc"
              stackId="hist"
              fill="#2A9D8F"
              radius={0}
              animationDuration={800}
            />
            <Bar
              dataKey="nonBdc"
              stackId="hist"
              fill="#E9C46A"
              radius={0}
              animationDuration={800}
            />
          </BarChart>
        ) : (
          <svg width="100%" height={220} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
