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
} from 'recharts';
import { formatQuarter, formatPercent } from '@/lib/format';

interface QuarterlyBarChartProps {
  data: { quarter: string; return: number | null }[];
  positiveColor?: string;
  negativeColor?: string;
}

export default function QuarterlyBarChart({
  data,
  positiveColor = '#2A9D8F',
  negativeColor = '#E63946',
}: QuarterlyBarChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 border border-surface-muted rounded-lg bg-surface text-muted text-sm">
        No quarterly return data available
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={240}>
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
        <Tooltip
          formatter={(value: number) => [formatPercent(value, 2), 'Return']}
          labelFormatter={formatQuarter}
          contentStyle={{ fontSize: 12 }}
        />
        <Bar dataKey="return" radius={[2, 2, 0, 0]}>
          {data.map((d, i) => (
            <Cell
              key={i}
              fill={(d.return ?? 0) >= 0 ? positiveColor : negativeColor}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
