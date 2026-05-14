'use client';

interface HomepageSparklineProps {
  data: number[];
  color: string;
  width?: number;
  height?: number;
}

export default function HomepageSparkline({
  data,
  color,
  width = 96,
  height = 28,
}: HomepageSparklineProps) {
  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pad = 2;

  const coords = data.map((v, i) => ({
    x: pad + (i / (data.length - 1)) * (width - 2 * pad),
    y: height - pad - ((v - min) / range) * (height - 2 * pad),
  }));

  const points = coords.map((c) => `${c.x},${c.y}`).join(' ');
  const last = coords[coords.length - 1];

  const areaPath =
    `M ${coords[0].x},${coords[0].y} ` +
    coords.slice(1).map((c) => `L ${c.x},${c.y}`).join(' ') +
    ` L ${last.x},${height} L ${coords[0].x},${height} Z`;

  const gid = `hp-spark-${color.replace('#', '')}`;

  return (
    <svg width={width} height={height} className="block">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.25} />
          <stop offset="100%" stopColor={color} stopOpacity={0.03} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gid})`} />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={last.x} cy={last.y} r={2} fill={color} />
    </svg>
  );
}
