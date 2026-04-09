'use client';

import { useInView } from '@/lib/useInView';

interface SparklineProps {
  data: number[];
  color: string;
  width?: number;
  height?: number;
}

export default function SparklineChart({
  data,
  color,
  width = 120,
  height = 32,
}: SparklineProps) {
  const [ref, inView] = useInView<SVGSVGElement>(0.3);

  if (data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const padding = 2;

  const coords = data.map((v, i) => {
    const x = padding + (i / (data.length - 1)) * (width - 2 * padding);
    const y = height - padding - ((v - min) / range) * (height - 2 * padding);
    return { x, y };
  });

  const points = coords.map((c) => `${c.x},${c.y}`).join(' ');
  const last = coords[coords.length - 1];

  // Build area fill path (line + bottom edge)
  const areaPath = `M ${coords[0].x},${coords[0].y} ` +
    coords.slice(1).map((c) => `L ${c.x},${c.y}`).join(' ') +
    ` L ${last.x},${height} L ${coords[0].x},${height} Z`;

  const gradientId = `spark-grad-${color.replace('#', '')}`;

  // Approximate total polyline length for stroke animation
  let pathLength = 0;
  for (let i = 1; i < coords.length; i++) {
    const dx = coords[i].x - coords[i - 1].x;
    const dy = coords[i].y - coords[i - 1].y;
    pathLength += Math.sqrt(dx * dx + dy * dy);
  }

  return (
    <svg ref={ref} width={width} height={height} className="block">
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.2} />
          <stop offset="100%" stopColor={color} stopOpacity={0.02} />
        </linearGradient>
      </defs>
      <path
        d={areaPath}
        fill={`url(#${gradientId})`}
        opacity={inView ? 1 : 0}
        style={{ transition: 'opacity 0.8s ease-out 0.3s' }}
      />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray={pathLength}
        strokeDashoffset={inView ? 0 : pathLength}
        style={{ transition: 'stroke-dashoffset 1s ease-out' }}
      />
      <circle
        cx={last.x}
        cy={last.y}
        r={2.5}
        fill={color}
        opacity={inView ? 1 : 0}
        style={{ transition: 'opacity 0.3s ease-out 0.9s' }}
      />
    </svg>
  );
}
