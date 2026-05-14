'use client';

import type { FundExposure } from '@/lib/types';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';
import { formatPercent } from '@/lib/format';

// Monochromatic teal ramp — matches indices concentration charts
const ASSET_CLASS_COLORS = ['#1A5F56', '#1F7268', '#2A9D8F', '#3DB0A3', '#7ACEC5', '#99DDD6', '#D6F5F2'];
const EXPOSURE_TYPE_COLORS = ['#1A5F56', '#2A9D8F', '#99DDD6'];
const LIEN_COLORS = ['#1A5F56', '#2A9D8F', '#99DDD6'];
const RATE_COLORS = ['#1A5F56', '#5BBFB4'];

interface ExposureSectionProps {
  exposure: FundExposure;
}

function MiniDonut({
  data,
  colors,
  title,
}: {
  data: { name: string; value: number }[];
  colors: string[];
  title: string;
}) {
  // Assign colors before filtering/sorting so each category keeps a stable color.
  // Filter out negligible slices (<0.1%), sort largest-to-smallest, pin "Other" last.
  const MIN_SLICE = 0.001;
  const withColor = data
    .map((d, i) => ({ ...d, color: colors[i % colors.length] }))
    .filter((d) => d.value >= MIN_SLICE);
  const other = withColor.filter((d) => d.name === 'Other');
  const rest = withColor.filter((d) => d.name !== 'Other').sort((a, b) => b.value - a.value);
  const filtered = [...rest, ...other];
  if (filtered.length === 0) return null;

  return (
    <div className="bg-white p-4 shadow-card">
      <p className="text-sm font-medium text-navy mb-2 text-center">{title}</p>
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={filtered}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius="48%"
            outerRadius="82%"
            startAngle={90}
            endAngle={-270}
            paddingAngle={1}
            strokeWidth={0}
          >
            {filtered.map((entry) => (
              <Cell key={entry.name} fill={entry.color} />
            ))}
          </Pie>
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0].payload;
              return (
                <div className="bg-white shadow-panel px-4 py-3 text-sm border border-surface-muted">
                  <p className="font-semibold text-navy">{d.name}</p>
                  <p className="text-muted">{formatPercent(d.value)}</p>
                </div>
              );
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap justify-center gap-x-3 gap-y-1 mt-1 text-[11px]">
        {filtered.map((d) => (
          <span key={d.name} className="flex items-center gap-1">
            <span
              className="inline-block w-2 h-2"
              style={{ backgroundColor: d.color }}
            />
            <span className="text-navy">{d.name}</span>
            <span className="text-muted tabular-nums">{formatPercent(d.value)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export default function ExposureSection({ exposure }: ExposureSectionProps) {
  const { assetClassSplit, exposureTypeSplit, lienSplit, rateTypeSplit, assetSplit } = exposure;

  // Asset Class donut (from 2-axis classification)
  const acSplit = assetClassSplit;
  const assetClassData = acSplit
    ? [
        { name: 'Private Credit', value: acSplit.privateCredit ?? 0 },
        { name: 'Private Equity', value: acSplit.privateEquity ?? 0 },
        { name: 'Real Estate', value: acSplit.realEstate ?? 0 },
        { name: 'Structured Credit', value: acSplit.structuredCredit ?? 0 },
        { name: 'Hedge Fund', value: acSplit.hedgeFund ?? 0 },
        { name: 'Cash', value: acSplit.cash ?? 0 },
        { name: 'Other', value: acSplit.other ?? 0 },
      ]
    : [
        { name: 'Debt', value: assetSplit.debt ?? 0 },
        { name: 'Equity', value: assetSplit.equity ?? 0 },
        { name: 'Funds', value: assetSplit.fund ?? 0 },
        { name: 'Other', value: assetSplit.other ?? 0 },
      ];

  // Exposure Type donut — only show if fund has >5% non-DIRECT exposure
  const etSplit = exposureTypeSplit;
  const directPct = etSplit?.direct ?? 1;
  const showExposureType = etSplit && directPct < 0.95;
  const exposureData = etSplit
    ? [
        { name: 'Direct Investment', value: etSplit.direct ?? 0 },
        { name: 'Fund-of-Funds', value: etSplit.fund ?? 0 },
        { name: 'Liquid / Traded', value: etSplit.liquid ?? 0 },
      ]
    : [];

  const debtPct = assetSplit.debt ?? 0;
  const lienCoverage = lienSplit.coverage ?? 0;
  const showLien = debtPct > 0.1 && lienCoverage >= 0.5;

  const lienData = [
    { name: 'First Lien', value: lienSplit.firstLien ?? 0 },
    { name: 'Second Lien', value: lienSplit.secondLien ?? 0 },
    { name: 'Unsecured', value: lienSplit.unsecured ?? 0 },
  ];

  const rateData = [
    { name: 'Floating', value: rateTypeSplit.floating ?? 0 },
    { name: 'Fixed', value: rateTypeSplit.fixed ?? 0 },
  ];

  // Determine grid columns: 2 on small, up to 4 on large when exposure type shown
  const donutCount = 1 + (showExposureType ? 1 : 0) + (showLien ? 1 : 0) + (debtPct > 0.1 ? 1 : 0);
  const gridCols = donutCount >= 4
    ? 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4'
    : donutCount === 3
      ? 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3'
      : 'grid-cols-1 sm:grid-cols-2';

  return (
    <div className={`grid ${gridCols} gap-5`}>
      <MiniDonut
        data={assetClassData}
        colors={acSplit ? ASSET_CLASS_COLORS : ['#1A5F56', '#2A9D8F', '#5BBFB4', '#99DDD6']}
        title={acSplit ? 'Asset Class' : 'Asset Type'}
      />
      {showExposureType && (
        <MiniDonut data={exposureData} colors={EXPOSURE_TYPE_COLORS} title="Exposure Type" />
      )}
      {showLien && (
        <MiniDonut data={lienData} colors={LIEN_COLORS} title="Lien Position" />
      )}
      {debtPct > 0.1 && (
        <MiniDonut data={rateData} colors={RATE_COLORS} title="Rate Type" />
      )}
    </div>
  );
}
