import { formatPercent, formatDollar } from '@/lib/format';
import type { GicsSectorRow } from '@/lib/types';

interface GicsSectorChartProps {
  data: GicsSectorRow[];
}

const SECTOR_COLORS = [
  '#2A9D8F', // teal
  '#264653', // navy
  '#E9C46A', // gold
  '#E76F51', // coral
  '#457B9D', // steel blue
  '#8AB17D', // sage
  '#F4A261', // sandy
  '#6A4C93', // purple
  '#1D3557', // dark navy
  '#A8DADC', // light teal
];
const OTHER_COLOR = '#6C757D';
const UNCLASSIFIED_COLOR = '#ADB5BD';

export default function GicsSectorChart({ data }: GicsSectorChartProps) {
  if (data.length === 0) {
    return <p className="text-sm text-muted">No sector data available.</p>;
  }

  const segments = data.map((row, i) => {
    const isUnclassified = row.sector === 'Unclassified';
    const isOther = row.sector === 'Other';
    const color = isUnclassified
      ? UNCLASSIFIED_COLOR
      : isOther
        ? OTHER_COLOR
        : SECTOR_COLORS[i % SECTOR_COLORS.length];
    return { ...row, color };
  });

  return (
    <div>
      {/* Single stacked horizontal bar */}
      <div className="h-5 flex overflow-hidden bg-surface-muted">
        {segments.map((seg) => (
          <div
            key={seg.sector}
            className="h-full transition-all"
            style={{
              width: `${seg.pctOfTotal * 100}%`,
              backgroundColor: seg.color,
              minWidth: seg.pctOfTotal > 0 ? '2px' : '0',
            }}
            title={`${seg.sector}: ${formatPercent(seg.pctOfTotal)} (${formatDollar(seg.totalFv)})`}
          />
        ))}
      </div>

      {/* Legend */}
      <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1.5">
        {segments.map((seg) => {
          const isUnclassified = seg.sector === 'Unclassified';
          return (
            <div key={seg.sector} className="flex items-center gap-2 text-sm">
              <span
                className="w-2.5 h-2.5 flex-shrink-0"
                style={{ backgroundColor: seg.color }}
              />
              <span
                className={`truncate ${isUnclassified ? 'text-muted italic' : 'text-navy'}`}
              >
                {seg.sector}
              </span>
              <span className="ml-auto text-muted tabular-nums text-xs whitespace-nowrap">
                {formatPercent(seg.pctOfTotal)} ({formatDollar(seg.totalFv)})
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
