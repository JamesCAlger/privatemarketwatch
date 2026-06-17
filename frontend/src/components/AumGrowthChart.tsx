'use client';

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { formatQuarter } from '@/lib/format';
import { useInView } from '@/lib/useInView';
import type { FundSeriesEntry, FundAumPeerBandRow } from '@/lib/types';

interface AumGrowthChartProps {
  series: FundSeriesEntry[];
  band: FundAumPeerBandRow[];
}

const NAVY = '#0b1a2c';
const ACCENT = '#c7a14a';

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { dataKey: string; value: number }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const fund = payload.find((p) => p.dataKey === 'fund')?.value;
  const peer = payload.find((p) => p.dataKey === 'peer')?.value;
  return (
    <div className="bg-navy px-3 py-2 shadow-panel text-xs">
      <p className="text-white/60 mb-1">{formatQuarter(label)}</p>
      {fund != null && (
        <div className="flex items-center gap-2 text-white">
          <span className="w-2 h-2 shrink-0" style={{ backgroundColor: ACCENT }} />
          <span className="text-white/70">This fund:</span>
          <span className="font-medium tabular-nums">{fund.toFixed(0)}</span>
        </div>
      )}
      {peer != null && (
        <div className="flex items-center gap-2 text-white mt-0.5">
          <span className="w-2 h-2 shrink-0" style={{ backgroundColor: '#8a9bab' }} />
          <span className="text-white/70">Peer median:</span>
          <span className="font-medium tabular-nums">{peer.toFixed(0)}</span>
        </div>
      )}
    </div>
  );
}

export default function AumGrowthChart({ series, band }: AumGrowthChartProps) {
  const [ref, inView] = useInView(0.15);

  const fundPts = series
    .filter((s) => s.total_assets != null && (s.total_assets as number) > 0)
    .map((s) => ({ date: s.reportDate, quarter: s.quarter, aum: s.total_assets as number }));
  if (fundPts.length < 2) return null;

  const bandMap = new Map(band.map((b) => [b.date, b.median]));
  const anchorDate = fundPts[0].date;
  const fundBase = fundPts[0].aum;
  const peerBase = bandMap.get(anchorDate) ?? null;

  const data = fundPts.map((p) => {
    const peerAbs = bandMap.get(p.date);
    return {
      quarter: p.quarter,
      fund: Math.round((p.aum / fundBase) * 1000) / 10,
      peer: peerBase != null && peerAbs != null
        ? Math.round((peerAbs / peerBase) * 1000) / 10
        : null,
    };
  });
  const hasPeer = data.some((d) => d.peer != null);

  return (
    <div ref={ref}>
      <div className="flex flex-wrap gap-4 mb-3 text-[11px] text-ink2">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-[9px] h-[9px]" style={{ backgroundColor: ACCENT }} /> This fund
        </span>
        {hasPeer && (
          <span className="inline-flex items-center gap-1.5">
            <span className="w-[14px] h-0 border-t-2 border-dashed" style={{ borderColor: '#8a9bab' }} /> Peer median
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={240}>
        {inView ? (
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f4" vertical={false} />
            <XAxis
              dataKey="quarter"
              tickFormatter={formatQuarter}
              tick={{ fontSize: 10, fill: '#6b7280' }}
              axisLine={{ stroke: '#dfe3ea' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 10, fill: '#6b7280' }}
              axisLine={false}
              tickLine={false}
              width={36}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: '#dfe3ea' }} />
            {hasPeer && (
              <Line
                type="monotone"
                dataKey="peer"
                stroke="#8a9bab"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                connectNulls
                animationDuration={900}
              />
            )}
            <Line
              type="monotone"
              dataKey="fund"
              stroke={ACCENT}
              strokeWidth={2}
              dot={false}
              animationDuration={900}
            />
          </LineChart>
        ) : (
          <svg width="100%" height={240} />
        )}
      </ResponsiveContainer>
    </div>
  );
}
