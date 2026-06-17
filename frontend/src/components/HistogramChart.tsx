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
  title?: string;
  medianLabel?: string;
}

const NAVY = '#0b1a2c';
const ACCENT = '#c7a14a';
const RULE = '#eef0f4';
const INK3 = '#6b7280';

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
  const total = payload.find((p) => p.dataKey === 'total')?.value ?? 0;
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{label}</p>
      <div className="flex items-center gap-2 text-white">
        <span className="font-medium tabular-nums">{total} funds</span>
      </div>
    </div>
  );
}

/** Parse a bucket label like "8-10%", "20%+", "<0.2x", or "0.2-0.4x" into [lower, upper). */
function bucketBounds(label: string): [number, number] {
  const cleaned = label.replace(/[%x<]/g, '').trim();
  if (label.includes('+')) {
    const lo = parseFloat(cleaned);
    return [Number.isNaN(lo) ? -Infinity : lo, Infinity];
  }
  if (label.trim().startsWith('<')) {
    const hi = parseFloat(cleaned);
    return [-Infinity, Number.isNaN(hi) ? Infinity : hi];
  }
  const parts = cleaned.split('-').map((s) => parseFloat(s));
  if (parts.length === 2 && !Number.isNaN(parts[0]) && !Number.isNaN(parts[1])) {
    return [parts[0], parts[1]];
  }
  const single = parseFloat(cleaned);
  return [single, single];
}

export default function HistogramChart({ data }: HistogramChartProps) {
  const [ref, inView] = useInView(0.15);

  if (!data.buckets || data.buckets.length === 0) {
    return (
      <div className="flex items-center justify-center h-[220px] border border-rule bg-surface text-ink3 text-sm">
        No data available.
      </div>
    );
  }

  // Trim trailing empty buckets so the axis doesn't trail off into dead space.
  let lastNonEmpty = data.buckets.length - 1;
  while (lastNonEmpty > 0 && data.buckets[lastNonEmpty].total === 0) lastNonEmpty--;
  const buckets = data.buckets.slice(0, lastNonEmpty + 1);

  // Locate the bucket whose range contains the median. Percent buckets are on a
  // 0-100 scale, so scale the fractional median up; leverage buckets are raw "x".
  const isPct = buckets[0].bucket.includes('%');
  const medianValue = isPct ? data.median * 100 : data.median;
  const medianText = isPct ? formatPercent(data.median) : `${data.median.toFixed(2)}x`;
  const medianIdx = buckets.findIndex((b) => {
    const [lo, hi] = bucketBounds(b.bucket);
    return medianValue >= lo && medianValue < hi;
  });

  return (
    <div ref={ref}>
      <ResponsiveContainer width="100%" height={220}>
        {inView ? (
          <BarChart data={buckets} margin={{ top: 16, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={RULE} vertical={false} />
            <XAxis
              dataKey="bucket"
              tick={{ fontSize: 9, fill: INK3 }}
              interval={0}
              angle={-30}
              textAnchor="end"
              height={45}
            />
            <YAxis
              tick={{ fontSize: 10, fill: INK3 }}
              allowDecimals={false}
            />
            {medianIdx >= 0 && (
              <ReferenceLine
                x={buckets[medianIdx]?.bucket}
                stroke={ACCENT}
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{ value: `Median ${medianText}`, fill: ACCENT, fontSize: 10, position: 'top' }}
              />
            )}
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ fill: 'rgba(11, 26, 44, 0.04)' }}
            />
            <Bar
              dataKey="total"
              fill={NAVY}
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
