const ACCENT_HEX = '#c7a14a';
const NAVY_HEX = '#0b1a2c';

export interface ProportionDonutItem {
  label: string;
  pct: number; // percentage points, e.g. 15.3
}

interface ProportionDonutProps {
  items: ProportionDonutItem[];
  centerStat?: { label: string; value: string; note?: string };
}

export default function ProportionDonut({ items, centerStat }: ProportionDonutProps) {
  const total = items.reduce((s, x) => s + x.pct, 0);
  if (total === 0) return <p className="text-sm text-ink3">No data available.</p>;

  const SIZE = 196;
  const THICKNESS = 26;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const r = (SIZE - THICKNESS) / 2;

  let acc = 0;
  const arcs = items.map((item, i) => {
    const startAngle = (acc / total) * Math.PI * 2 - Math.PI / 2;
    acc += item.pct;
    const endAngle = (acc / total) * Math.PI * 2 - Math.PI / 2;
    const large = endAngle - startAngle > Math.PI ? 1 : 0;
    const x1 = cx + r * Math.cos(startAngle);
    const y1 = cy + r * Math.sin(startAngle);
    const x2 = cx + r * Math.cos(endAngle);
    const y2 = cy + r * Math.sin(endAngle);

    // For segments covering ~100%, arc start/end collapse — draw a near-full circle instead
    const span = endAngle - startAngle;
    let d: string;
    if (span >= Math.PI * 2 - 0.001) {
      const mx = cx + r * Math.cos(startAngle + Math.PI);
      const my = cy + r * Math.sin(startAngle + Math.PI);
      d = `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 1 1 ${mx.toFixed(2)} ${my.toFixed(2)} A ${r} ${r} 0 1 1 ${x1.toFixed(2)} ${(y1 + 0.01).toFixed(2)}`;
    } else {
      d = `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
    }

    const baseColor = i % 2 === 0 ? ACCENT_HEX : NAVY_HEX;
    const step = Math.floor(i / 2);
    const opacity = Math.max(1 - step * 0.16, 0.34);

    return { d, color: baseColor, opacity };
  });

  return (
    <div className="grid grid-cols-1 sm:grid-cols-[196px_minmax(0,1fr)] gap-6 items-center">
      {/* Donut */}
      <div className="relative mx-auto sm:mx-0" style={{ width: SIZE, height: SIZE }}>
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} width={SIZE} height={SIZE} className="block">
          <circle cx={cx} cy={cy} r={r} fill="none" stroke="#eef0f4" strokeWidth={THICKNESS} />
          {arcs.map((a, i) => (
            <path
              key={i}
              d={a.d}
              stroke={a.color}
              strokeOpacity={a.opacity}
              strokeWidth={THICKNESS}
              fill="none"
              strokeLinecap="butt"
            />
          ))}
        </svg>
        {centerStat && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-3">
            <div className="text-[10px] uppercase tracking-[0.14em] text-ink3">{centerStat.label}</div>
            <div className="font-mono text-[30px] text-ink tracking-[-0.01em] mt-0.5 font-semibold tabular-nums">
              {centerStat.value}
            </div>
            {centerStat.note && (
              <div className="text-[10px] text-ink3 mt-1 leading-tight">{centerStat.note}</div>
            )}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="grid grid-cols-2 gap-x-[18px] gap-y-1.5">
        {arcs.map((a, i) => (
          <div
            key={i}
            className="flex items-center gap-2 text-xs text-ink2 border-b border-rule2 py-1"
          >
            <span
              className="w-[9px] h-[9px] shrink-0"
              style={{ backgroundColor: a.color, opacity: a.opacity }}
            />
            <span className="flex-1 truncate">{items[i].label}</span>
            <span className="font-mono text-ink font-medium tabular-nums shrink-0">
              {items[i].pct.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
