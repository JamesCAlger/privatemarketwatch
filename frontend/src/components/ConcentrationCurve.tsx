'use client';

import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import type { ConcentrationBracket } from '@/lib/types';
import { formatNumber } from '@/lib/format';
import { useInView } from '@/lib/useInView';

interface ConcentrationCurveProps {
  data: ConcentrationBracket[];
  title?: string;
}

// Darker = more concentrated (top brackets), lighter = tail
const BRACKET_COLORS = [
  '#1A5F56', // Top 1%
  '#1F7268', // Top 1-5%
  '#2A9D8F', // Top 5-10%
  '#5BBFB4', // Top 10-20%
  '#99DDD6', // Top 20-50%
  '#D6F5F2', // Top 50-100%
];

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: ConcentrationBracket & { fill: string } }>;
}) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-white shadow-panel px-4 py-3 text-sm border border-surface-muted">
      <p className="font-semibold text-navy mb-1">{d.label}</p>
      <p className="text-muted">
        FV Share:{' '}
        <span className="text-navy font-medium">
          {d.fvPct < 0.001 ? '<0.1%' : `${(d.fvPct * 100).toFixed(1)}%`}
        </span>
      </p>
      <p className="text-muted">
        Count:{' '}
        <span className="text-navy font-medium">
          {formatNumber(d.count)} of {formatNumber(d.totalCount)}
        </span>
      </p>
    </div>
  );
}

export default function ConcentrationCurve({ data, title }: ConcentrationCurveProps) {
  const [ref, inView] = useInView(0.2);

  if (data.length === 0) {
    return <p className="text-sm text-muted">No data available.</p>;
  }

  // Filter out zero-share slices for the pie chart (keeps legend clean)
  const visibleData = data.filter((d) => d.fvPct > 0.0001);

  return (
    <div ref={ref}>
      {title && (
        <p className="text-sm font-medium text-navy mb-2 text-center">{title}</p>
      )}
      <ResponsiveContainer width="100%" height={240}>
        {inView ? (
          <PieChart>
            <Pie
              data={visibleData}
              dataKey="fvPct"
              nameKey="label"
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
              {visibleData.map((d, i) => {
                // Match color by finding original index in full data array
                const origIdx = data.indexOf(d);
                return (
                  <Cell
                    key={i}
                    fill={BRACKET_COLORS[origIdx % BRACKET_COLORS.length]}
                  />
                );
              })}
            </Pie>
            <Tooltip content={<ChartTooltip />} />
          </PieChart>
        ) : (
          <svg width="100%" height={240} />
        )}
      </ResponsiveContainer>
      {/* Legend */}
      <div className="flex flex-wrap justify-center gap-x-3 gap-y-1.5 mt-3 text-[11px]">
        {data.map((d, i) => (
          <span key={d.label} className="flex items-center gap-1">
            <span
              className="inline-block w-2 h-2 flex-shrink-0"
              style={{ backgroundColor: BRACKET_COLORS[i % BRACKET_COLORS.length] }}
            />
            <span className="text-navy">{d.label}</span>
            <span className="text-muted tabular-nums">
              {d.fvPct < 0.001 ? '<0.1%' : `${(d.fvPct * 100).toFixed(1)}%`}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
