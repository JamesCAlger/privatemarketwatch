'use client';

import { useState, useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { formatLevel, formatQuarter } from '@/lib/format';

interface Series {
  key: string;
  name: string;
  color: string;
  data: { quarter: string; level: number | null }[];
}

type Period = '1y' | '3y' | '5y' | 'all';

const PERIODS: { key: Period; label: string; quarters: number | null }[] = [
  { key: '1y', label: '1 YR', quarters: 4 },
  { key: '3y', label: '3 YR', quarters: 12 },
  { key: '5y', label: '5 YR', quarters: 20 },
  { key: 'all', label: 'Since Inception', quarters: null },
];

interface TimeSeriesChartProps {
  series: Series[];
  defaultVisible?: string[];
}

export default function TimeSeriesChart({
  series,
  defaultVisible,
}: TimeSeriesChartProps) {
  const allKeys = series.map((s) => s.key);
  const [visible, setVisible] = useState<Set<string>>(
    new Set(defaultVisible ?? allKeys),
  );
  const [period, setPeriod] = useState<Period>('all');

  const toggleSeries = (key: string) => {
    setVisible((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  // Merge all series into unified data points by quarter
  const allData = useMemo(() => {
    const byQuarter = new Map<string, Record<string, number | null>>();
    for (const s of series) {
      for (const d of s.data) {
        if (!byQuarter.has(d.quarter)) {
          byQuarter.set(d.quarter, {});
        }
        byQuarter.get(d.quarter)![s.key] = d.level;
      }
    }
    return Array.from(byQuarter.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([q, vals]) => ({ quarter: q, ...vals }));
  }, [series]);

  // Filter by selected period
  const chartData = useMemo(() => {
    const p = PERIODS.find((t) => t.key === period);
    if (!p || p.quarters == null || allData.length <= p.quarters) {
      return allData;
    }
    return allData.slice(-p.quarters);
  }, [allData, period]);

  if (allData.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 border border-surface-muted rounded-lg bg-surface text-muted text-sm">
        No data available yet. Run the pipeline with --returns to generate index data.
      </div>
    );
  }

  return (
    <div>
      {/* Period tabs + legend toggles */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              onClick={() => setPeriod(p.key)}
              className={`text-xs px-3 py-1 rounded-md transition-colors ${
                period === p.key
                  ? 'bg-navy text-white font-medium'
                  : 'text-muted hover:text-navy hover:bg-surface'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          {series.map((s) => (
            <button
              key={s.key}
              onClick={() => toggleSeries(s.key)}
              className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border transition-all ${
                visible.has(s.key)
                  ? 'border-current opacity-100'
                  : 'border-surface-muted opacity-40'
              }`}
              style={{ color: visible.has(s.key) ? s.color : undefined }}
            >
              <span
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: s.color }}
              />
              {s.name}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={360}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#E9ECEF" />
          <XAxis
            dataKey="quarter"
            tickFormatter={formatQuarter}
            tick={{ fontSize: 11, fill: '#6C757D' }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 11, fill: '#6C757D' }}
            tickFormatter={(v: number) => formatLevel(v)}
            domain={['auto', 'auto']}
          />
          <Tooltip
            formatter={(value: number, name: string) => [
              formatLevel(value),
              series.find((s) => s.key === name)?.name ?? name,
            ]}
            labelFormatter={formatQuarter}
            contentStyle={{ fontSize: 12 }}
          />
          {series.map(
            (s) =>
              visible.has(s.key) && (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  stroke={s.color}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4 }}
                  connectNulls
                />
              ),
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
