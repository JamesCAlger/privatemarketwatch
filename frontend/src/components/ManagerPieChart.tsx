'use client';

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import type { ConcentrationRow } from '@/lib/types';
import { formatDollar, formatPercent, formatNumber } from '@/lib/format';
import { useInView } from '@/lib/useInView';

interface ConcentrationPieChartProps {
  data: ConcentrationRow[];
  title?: string;
  colors?: string[];
}

const COLORS_DEFAULT = [
  '#1A5F56', '#1F7268', '#24857A', '#2A9D8F', '#3DB0A3',
  '#5BBFB4', '#7ACEC5', '#99DDD6', '#B8ECE7', '#D6F5F2', '#E8FAF8',
];

// Monochromatic teal ramp
export const COLORS_TEAL_RAMP = COLORS_DEFAULT;

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ConcentrationRow }>;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-white rounded-lg shadow-panel px-4 py-3 text-sm border border-surface-muted">
      <p className="font-semibold text-navy mb-1">{d.name}</p>
      <p className="text-muted">
        Fair Value: <span className="text-navy font-medium">{formatDollar(d.totalFv)}</span>
      </p>
      <p className="text-muted">
        Weight: <span className="text-navy font-medium">{formatPercent(d.pctOfIndex)}</span>
      </p>
      <p className="text-muted">
        Holdings: <span className="text-navy font-medium">{formatNumber(d.positionCount)}</span>
      </p>
      {d.fundCount != null && d.fundCount > 1 && (
        <p className="text-muted">
          Funds: <span className="text-navy font-medium">{d.fundCount}</span>
        </p>
      )}
    </div>
  );
}

function ChartLegend({ items }: { items: { name: string; color: string; pct: number }[] }) {
  return (
    <div className="flex flex-wrap justify-center gap-x-3 gap-y-1.5 mt-3 text-[11px]">
      {items.map((entry) => (
        <span key={entry.name} className="flex items-center gap-1">
          <span
            className="inline-block w-2 h-2 rounded-sm flex-shrink-0"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-navy">{entry.name}</span>
          <span className="text-muted tabular-nums">{formatPercent(entry.pct)}</span>
        </span>
      ))}
    </div>
  );
}

export default function ConcentrationPieChart({ data, title, colors }: ConcentrationPieChartProps) {
  const palette = colors ?? COLORS_DEFAULT;
  const [ref, inView] = useInView(0.2);

  if (data.length === 0) {
    return <p className="text-sm text-muted">No data available.</p>;
  }

  const legendItems = data.map((d, i) => ({
    name: d.name,
    color: palette[i % palette.length],
    pct: d.pctOfIndex,
  }));

  return (
    <div ref={ref}>
      {title && (
        <p className="text-sm font-medium text-navy mb-2 text-center">{title}</p>
      )}
      <ResponsiveContainer width="100%" height={240}>
        {inView ? (
          <PieChart>
            <Pie
              data={data}
              dataKey="totalFv"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius="52%"
              outerRadius="88%"
              startAngle={90}
              endAngle={-270}
              paddingAngle={1}
              strokeWidth={0}
              animationDuration={1200}
              animationEasing="ease-out"
            >
              {data.map((_, i) => (
                <Cell key={i} fill={palette[i % palette.length]} />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltip />} />
          </PieChart>
        ) : (
          /* Placeholder preserves height while chart is off-screen */
          <svg width="100%" height={240} />
        )}
      </ResponsiveContainer>
      <ChartLegend items={legendItems} />
    </div>
  );
}
