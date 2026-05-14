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
  Cell,
} from 'recharts';
import { formatQuarter, formatPercent } from '@/lib/format';
import { useInView } from '@/lib/useInView';

interface QuarterlyBarChartProps {
  data: { quarter: string; return: number | null }[];
  positiveColor?: string;
  negativeColor?: string;
}

// Recharts tooltip props are untyped
function CustomTooltip(props: {
  active?: boolean;
  payload?: { value: number }[];
  label?: string;
}) {
  const { active, payload, label } = props;
  if (!active || !payload || payload.length === 0) return null;
  const value = payload[0]?.value;
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{formatQuarter(label)}</p>
      <p className="text-white font-medium tabular-nums">{formatPercent(value, 2)}</p>
    </div>
  );
}

export default function QuarterlyBarChart({
  data,
  positiveColor = '#2A9D8F',
  negativeColor = '#E63946',
}: QuarterlyBarChartProps) {
  const [ref, inView] = useInView(0.2);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 border border-surface-muted bg-surface text-muted text-sm">
        No quarterly return data available
      </div>
    );
  }

  return (
    <div ref={ref}>
      <ResponsiveContainer width="100%" height={280}>
        {inView ? (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E9ECEF" vertical={false} />
            <XAxis
              dataKey="quarter"
              tickFormatter={formatQuarter}
              tick={{ fontSize: 10, fill: '#6C757D' }}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={(v: number) => formatPercent(v, 1)}
              tick={{ fontSize: 10, fill: '#6C757D' }}
            />
            <ReferenceLine y={0} stroke="#6C757D" strokeWidth={1} />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ fill: 'rgba(15, 27, 45, 0.04)' }}
            />
            <Bar dataKey="return" radius={0} animationDuration={1000} animationEasing="ease-out">
              {data.map((d, i) => (
                <Cell
                  key={i}
                  fill={(d.return ?? 0) >= 0 ? positiveColor : negativeColor}
                />
              ))}
            </Bar>
          </BarChart>
        ) : (
          <svg width="100%" height={280} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
