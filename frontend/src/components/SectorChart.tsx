import { formatPercent, formatDollar, formatNumber } from '@/lib/format';
import type { SectorRow } from '@/lib/types';

interface SectorChartProps {
  data: SectorRow[];
  color: string;
}

const CATEGORY_LABELS: Record<string, string> = {
  EQUITY_COMMON: 'Common Equity',
  EQUITY_PREFERRED: 'Preferred Equity',
};

export default function SectorChart({ data, color }: SectorChartProps) {
  if (data.length === 0) {
    return <p className="text-sm text-muted">No sector data available.</p>;
  }

  const maxPct = Math.max(...data.map((d) => d.pctOfIndex));

  return (
    <div className="space-y-3">
      {data.map((row) => (
        <div key={row.assetCategory}>
          <div className="flex items-center justify-between text-sm mb-1">
            <span className="font-medium text-navy">{CATEGORY_LABELS[row.assetCategory] ?? row.assetCategory}</span>
            <span className="text-muted tabular-nums">
              {formatPercent(row.pctOfIndex)} ({formatNumber(row.positionCount)} constituent holdings)
            </span>
          </div>
          <div className="h-2 bg-surface-muted rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${(row.pctOfIndex / maxPct) * 100}%`,
                backgroundColor: color,
                opacity: 0.7 + 0.3 * (row.pctOfIndex / maxPct),
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
