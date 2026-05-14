import { formatPercent, formatDollar } from '@/lib/format';
import type { GicsSectorRow } from '@/lib/types';

interface GicsSectorChartProps {
  data: GicsSectorRow[];
}

export default function GicsSectorChart({ data }: GicsSectorChartProps) {
  if (data.length === 0) {
    return <p className="text-sm text-muted">No sector data available.</p>;
  }

  const maxPct = Math.max(...data.map((d) => d.pctOfTotal));

  return (
    <div className="space-y-2.5">
      {data.map((row) => {
        const isUnclassified = row.sector === 'Unclassified';
        const isOther = row.sector === 'Other';
        const barColor = isUnclassified
          ? '#ADB5BD'
          : isOther
            ? '#6C757D'
            : '#2A9D8F';
        const barOpacity = isUnclassified
          ? 0.5
          : isOther
            ? 0.6
            : 0.7 + 0.3 * (row.pctOfTotal / maxPct);

        return (
          <div key={row.sector}>
            <div className="flex items-center justify-between text-sm mb-0.5">
              <span
                className={`font-medium ${
                  isUnclassified ? 'text-muted italic' : 'text-navy'
                }`}
              >
                {row.sector}
              </span>
              <span className="text-muted tabular-nums text-xs">
                {formatPercent(row.pctOfTotal)} ({formatDollar(row.totalFv)})
                {row.fundCount != null && (
                  <span className="ml-1 text-surface-muted">
                    {row.fundCount} funds
                  </span>
                )}
              </span>
            </div>
            <div className="h-2 bg-surface-muted overflow-hidden">
              <div
                className="h-full transition-all"
                style={{
                  width: `${(row.pctOfTotal / maxPct) * 100}%`,
                  backgroundColor: barColor,
                  opacity: barOpacity,
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
