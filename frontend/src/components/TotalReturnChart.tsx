'use client';

import { useState, useMemo } from 'react';
import {
  ComposedChart,
  Area,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Cell,
} from 'recharts';
import { formatLevel, formatQuarter, formatPercent } from '@/lib/format';
import { useInView } from '@/lib/useInView';

type Period = '1y' | '3y' | '5y' | 'all';

const PERIODS: { key: Period; label: string; quarters: number | null }[] = [
  { key: '1y', label: '1 YR', quarters: 4 },
  { key: '3y', label: '3 YR', quarters: 12 },
  { key: '5y', label: '5 YR', quarters: 20 },
  { key: 'all', label: 'Since Inception', quarters: null },
];

interface TotalReturnChartProps {
  lineData: { quarter: string; level: number }[];
  barData: { quarter: string; return: number | null }[];
  lineLabel: string;
  positiveColor?: string;
  negativeColor?: string;
}

function CustomTooltip(props: {
  active?: boolean;
  payload?: { dataKey: string; value: number; color: string }[];
  label?: string;
  lineLabel: string;
}) {
  const { active, payload, label, lineLabel } = props;
  if (!active || !payload || payload.length === 0) return null;

  const levelEntry = payload.find((p) => p.dataKey === 'level');
  const retEntry = payload.find((p) => p.dataKey === 'return');

  return (
    <div className="bg-navy rounded-lg px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{formatQuarter(label)}</p>
      {levelEntry && (
        <div className="flex items-center gap-2 text-white">
          <span className="w-2 h-2 rounded-full shrink-0 bg-teal" />
          <span className="text-white/70">{lineLabel}:</span>
          <span className="font-medium tabular-nums">{formatLevel(levelEntry.value)}</span>
        </div>
      )}
      {retEntry && (
        <div className="flex items-center gap-2 text-white">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: (retEntry.value ?? 0) >= 0 ? '#2A9D8F' : '#E63946' }} />
          <span className="text-white/70">Quarterly:</span>
          <span className="font-medium tabular-nums">{formatPercent(retEntry.value, 2)}</span>
        </div>
      )}
    </div>
  );
}

export default function TotalReturnChart({
  lineData,
  barData,
  lineLabel,
  positiveColor = '#2A9D8F',
  negativeColor = '#E63946',
}: TotalReturnChartProps) {
  const [period, setPeriod] = useState<Period>('all');
  const [ref, inView] = useInView(0.15);

  const hasLine = lineData.length >= 2;
  const hasBars = barData.length >= 2;

  // Merge line + bar into unified data array
  const allData = useMemo(() => {
    const byQuarter = new Map<string, { level?: number; return?: number | null }>();
    for (const d of lineData) {
      byQuarter.set(d.quarter, { ...byQuarter.get(d.quarter), level: d.level });
    }
    for (const d of barData) {
      byQuarter.set(d.quarter, { ...byQuarter.get(d.quarter), return: d.return });
    }
    return Array.from(byQuarter.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([q, vals]) => ({ quarter: q, ...vals }));
  }, [lineData, barData]);

  // Filter by period
  const chartData = useMemo(() => {
    const p = PERIODS.find((t) => t.key === period);
    if (!p || p.quarters == null || allData.length <= p.quarters) {
      return allData;
    }
    return allData.slice(-p.quarters);
  }, [allData, period]);

  if (allData.length === 0) return null;

  const chartHeight = hasLine && hasBars ? 400 : 280;

  return (
    <div ref={ref}>
      {/* Period tabs */}
      <div className="flex gap-1 mb-4">
        {PERIODS.map((p) => (
          <button
            key={p.key}
            onClick={() => setPeriod(p.key)}
            className={`text-xs px-3 py-1.5 rounded-md transition-colors ${
              period === p.key
                ? 'bg-navy text-white font-medium'
                : 'text-muted hover:text-navy hover:bg-surface'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      <ResponsiveContainer width="100%" height={chartHeight}>
        {inView ? (
          <ComposedChart data={chartData}>
            {hasLine && (
              <defs>
                <linearGradient id="grad-tr" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#2A9D8F" stopOpacity={0.15} />
                  <stop offset="100%" stopColor="#2A9D8F" stopOpacity={0.01} />
                </linearGradient>
              </defs>
            )}
            <CartesianGrid strokeDasharray="3 3" stroke="#E9ECEF" />
            <XAxis
              dataKey="quarter"
              tickFormatter={formatQuarter}
              tick={{ fontSize: 10, fill: '#6C757D' }}
              interval="preserveStartEnd"
            />
            {/* Left axis: index level */}
            {hasLine && (
              <YAxis
                yAxisId="level"
                orientation="left"
                tick={{ fontSize: 10, fill: '#6C757D' }}
                tickFormatter={(v: number) => formatLevel(v)}
                domain={['auto', 'auto']}
              />
            )}
            {/* Right axis: quarterly return % */}
            {hasBars && (
              <YAxis
                yAxisId="return"
                orientation={hasLine ? 'right' : 'left'}
                tick={{ fontSize: 10, fill: '#6C757D' }}
                tickFormatter={(v: number) => formatPercent(v, 1)}
              />
            )}
            {hasLine && (
              <ReferenceLine yAxisId="level" y={100} stroke="#6C757D" strokeDasharray="4 4" strokeOpacity={0.5} />
            )}
            <Tooltip
              content={<CustomTooltip lineLabel={lineLabel} />}
              cursor={{ stroke: '#6C757D', strokeDasharray: '3 3' }}
            />
            {hasBars && (
              <Bar
                yAxisId="return"
                dataKey="return"
                radius={[2, 2, 0, 0]}
                animationDuration={1000}
                animationEasing="ease-out"
                opacity={hasLine ? 0.5 : 1}
              >
                {chartData.map((d, i) => (
                  <Cell
                    key={i}
                    fill={((d as Record<string, unknown>).return as number ?? 0) >= 0 ? positiveColor : negativeColor}
                  />
                ))}
              </Bar>
            )}
            {hasLine && (
              <Area
                yAxisId="level"
                type="monotone"
                dataKey="level"
                stroke="#2A9D8F"
                strokeWidth={2}
                fill="url(#grad-tr)"
                dot={false}
                activeDot={{ r: 4, fill: '#2A9D8F', stroke: '#fff', strokeWidth: 2 }}
                connectNulls
                animationDuration={1500}
                animationEasing="ease-out"
              />
            )}
          </ComposedChart>
        ) : (
          <svg width="100%" height={chartHeight} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
