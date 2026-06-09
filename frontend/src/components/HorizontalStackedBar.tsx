const PALETTE = [
  '#1A5F56', '#2A9D8F', '#3DB0A3', '#5BBFB4',
  '#7ACEC5', '#99DDD6', '#B8ECE7', '#D6F5F2',
];

interface StackedBarItem {
  label: string;
  pct: number;
}

interface HorizontalStackedBarProps {
  items: StackedBarItem[];
  footnote?: string;
}

export default function HorizontalStackedBar({ items, footnote }: HorizontalStackedBarProps) {
  const filtered = items.filter((d) => d.pct > 0);
  if (filtered.length === 0) return null;

  const total = filtered.reduce((s, d) => s + d.pct, 0);

  return (
    <div>
      {/* Bar */}
      <div className="flex h-7 overflow-hidden">
        {filtered.map((item, i) => {
          const widthPct = (item.pct / total) * 100;
          return (
            <div
              key={item.label}
              className="flex items-center justify-center text-[10px] font-mono text-white tabular-nums"
              style={{
                width: `${widthPct}%`,
                backgroundColor: PALETTE[i % PALETTE.length],
                minWidth: widthPct > 3 ? undefined : '2px',
              }}
            >
              {widthPct > 8 ? `${(item.pct * 100).toFixed(0)}%` : ''}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-[11px]">
        {filtered.map((item, i) => (
          <span key={item.label} className="flex items-center gap-1.5">
            <span
              className="inline-block w-2.5 h-2.5"
              style={{ backgroundColor: PALETTE[i % PALETTE.length] }}
            />
            <span className="text-ink2">{item.label}</span>
            <span className="font-mono text-ink3 tabular-nums">
              {(item.pct * 100).toFixed(1)}%
            </span>
          </span>
        ))}
      </div>

      {footnote && (
        <p className="text-[10px] text-ink3 mt-2">{footnote}</p>
      )}
    </div>
  );
}
