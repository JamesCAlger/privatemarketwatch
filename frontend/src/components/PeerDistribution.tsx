import type { PeerMetric } from '@/lib/types';
import { formatDollar } from '@/lib/format';

interface PeerDistributionProps {
  metric: PeerMetric;
  cik: string;
}

const NAVY = '#0b1a2c';
const ACCENT = '#c7a14a';
const BAR = '#c8cfd8';

function fmt(v: number, unit: string, decimals: number): string {
  switch (unit) {
    case '$':
      return formatDollar(v);
    case 'bps':
      return `${Math.round(v)} bps`;
    case '%':
      return `${v.toFixed(decimals)}%`;
    case 'x':
      return `${v.toFixed(decimals)}x`;
    case 'yr':
      return `${v.toFixed(decimals)} yr`;
    default:
      return v.toFixed(decimals);
  }
}

function ordinal(n: number): string {
  const s = ['th', 'st', 'nd', 'rd'];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

export default function PeerDistribution({ metric, cik }: PeerDistributionProps) {
  const vals = metric.values.map((x) => x.v);
  const fundVal = metric.values.find((x) => x.cik === cik)?.v;
  if (fundVal == null || vals.length < 4) return null;

  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const pad = span * 0.04;
  const lo = min - pad;
  const hi = max + pad;
  const range = hi - lo;

  // Histogram bins
  const BINS = 22;
  const counts = new Array(BINS).fill(0);
  for (const v of vals) {
    let b = Math.floor(((v - lo) / range) * BINS);
    if (b >= BINS) b = BINS - 1;
    if (b < 0) b = 0;
    counts[b] += 1;
  }
  const maxCount = Math.max(...counts, 1);

  const W = 300;
  const H = 44;
  const xFor = (v: number) => ((v - lo) / range) * W;
  const markerX = xFor(fundVal);
  const medianX = xFor(metric.median);

  // Percentile (share of peers at or below this fund)
  const pct = Math.round((vals.filter((v) => v <= fundVal).length / vals.length) * 100);

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="text-[11px] uppercase tracking-[0.12em] text-ink3">{metric.label}</span>
        <span className="font-mono text-[15px] text-ink font-semibold tabular-nums">
          {fmt(fundVal, metric.unit, metric.decimals)}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} className="block" preserveAspectRatio="none">
        {/* histogram */}
        {counts.map((c, i) => {
          const bw = W / BINS;
          const bh = (c / maxCount) * (H - 10);
          return (
            <rect
              key={i}
              x={i * bw + 0.5}
              y={H - bh}
              width={bw - 1}
              height={bh}
              fill={BAR}
            />
          );
        })}
        {/* baseline */}
        <line x1={0} y1={H} x2={W} y2={H} stroke="#dfe3ea" strokeWidth={1} />
        {/* median */}
        <line x1={medianX} y1={2} x2={medianX} y2={H} stroke={NAVY} strokeWidth={1} strokeDasharray="3 3" opacity={0.5} />
        {/* fund marker */}
        <line x1={markerX} y1={0} x2={markerX} y2={H} stroke={ACCENT} strokeWidth={2} />
        <circle cx={markerX} cy={4} r={3.5} fill={ACCENT} />
      </svg>
      <div className="flex items-baseline justify-between mt-1 text-[10px] text-ink3">
        <span className="text-accent font-medium">{ordinal(pct)} percentile</span>
        <span className="tabular-nums">peer median {fmt(metric.median, metric.unit, metric.decimals)}</span>
      </div>
    </div>
  );
}
