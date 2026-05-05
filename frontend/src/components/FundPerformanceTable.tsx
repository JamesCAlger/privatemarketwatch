import type { FundSeriesEntry } from '@/lib/types';

interface FundPerformanceTableProps {
  series: FundSeriesEntry[];
}

/** Extract quarterly returns from series, computing from monthly returns if needed. */
function getQuarterlyReturns(series: FundSeriesEntry[]): { quarter: string; ret: number }[] {
  const result: { quarter: string; ret: number }[] = [];

  for (const s of series) {
    // Prefer direct quarterly_return (stored as percentage points, convert to decimal)
    if (typeof s.quarterly_return === 'number') {
      result.push({ quarter: s.quarter, ret: s.quarterly_return / 100 });
      continue;
    }

    // Fall back: compound the 3 monthly returns (percentage points -> decimal)
    const m1 = s.monthly_return_1;
    const m2 = s.monthly_return_2;
    const m3 = s.monthly_return_3;
    if (typeof m1 === 'number' && typeof m2 === 'number' && typeof m3 === 'number') {
      const qtr = (1 + m1 / 100) * (1 + m2 / 100) * (1 + m3 / 100) - 1;
      result.push({ quarter: s.quarter, ret: qtr });
      continue;
    }

    // Fall back: total_return_pct from companyfacts (BDCs, percentage points)
    if (typeof s.total_return_pct === 'number') {
      result.push({ quarter: s.quarter, ret: s.total_return_pct / 100 });
    }
  }

  return result;
}

/** Extract quarterly gross returns from series. */
function getQuarterlyGrossReturns(series: FundSeriesEntry[]): { quarter: string; ret: number }[] {
  return series
    .filter(s => typeof s.gross_return_pct === 'number')
    .map(s => ({ quarter: s.quarter, ret: s.gross_return_pct! / 100 }));
}

export { getQuarterlyReturns };

/** Compute summary cells (QTD, YTD, 1Y, 3Y ann., SI ann.) from quarterly returns. */
function computeSummaryCells(qReturns: { quarter: string; ret: number }[]): { label: string; value: number | null }[] {
  if (qReturns.length === 0) {
    return [
      { label: 'QTD', value: null },
      { label: 'YTD', value: null },
      { label: '1 Year', value: null },
      { label: '3 Year (Ann.)', value: null },
      { label: 'Since Inception (Ann.)', value: null },
    ];
  }

  const returns = qReturns.map((q) => q.ret);
  const latest = returns[returns.length - 1];
  const compound = (arr: number[]) =>
    arr.reduce((acc, r) => acc * (1 + r), 1) - 1;

  const latestYear = qReturns[qReturns.length - 1].quarter.slice(0, 4);
  const ytdReturns = qReturns
    .filter((q) => q.quarter.startsWith(latestYear))
    .map((q) => q.ret);
  const ytd = ytdReturns.length > 0 ? compound(ytdReturns) : null;

  const last4 = returns.slice(-4);
  const trail1y = last4.length >= 4 ? compound(last4) : null;

  const last12 = returns.slice(-12);
  const trail3y = last12.length >= 12
    ? Math.pow(1 + compound(last12), 1 / 3) - 1
    : null;

  const total = compound(returns);
  const years = returns.length / 4;
  const sinceInception = years >= 1
    ? Math.pow(1 + total, 1 / years) - 1
    : total;

  return [
    { label: 'QTD', value: latest },
    { label: 'YTD', value: ytd },
    { label: '1 Year', value: trail1y },
    { label: '3 Year (Ann.)', value: trail3y },
    { label: 'Since Inception (Ann.)', value: sinceInception },
  ];
}

export default function FundPerformanceTable({ series }: FundPerformanceTableProps) {
  if (series.length === 0) return null;

  const qReturns = getQuarterlyReturns(series);
  if (qReturns.length === 0) return null;

  const netCells = computeSummaryCells(qReturns);

  const grossReturns = getQuarterlyGrossReturns(series);
  const hasGross = grossReturns.length > 0;
  const grossCells = hasGross ? computeSummaryCells(grossReturns) : null;

  const renderCell = (c: { label: string; value: number | null }) => (
    c.value != null ? (
      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
        c.value >= 0 ? 'bg-teal/10 text-teal' : 'bg-red/10 text-red'
      }`}>
        {c.value >= 0 ? '+' : ''}{(c.value * 100).toFixed(1)}%
      </span>
    ) : (
      <span className="text-muted">--</span>
    )
  );

  return (
    <div className="bg-white rounded-lg shadow-card overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-navy">
            {hasGross && (
              <th className="py-3 px-4 text-left text-xs font-medium text-white/70 uppercase tracking-wider w-24"></th>
            )}
            {netCells.map((c) => (
              <th key={c.label} className="py-3 px-4 text-center text-xs font-medium text-white/70 uppercase tracking-wider">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className={hasGross ? 'border-b border-gray-100' : ''}>
            {hasGross && (
              <td className="py-3 px-4 text-xs font-medium text-slate-500">Net</td>
            )}
            {netCells.map((c) => (
              <td key={c.label} className="py-3 px-4 text-center tabular-nums">
                {renderCell(c)}
              </td>
            ))}
          </tr>
          {grossCells && (
            <tr>
              <td className="py-3 px-4 text-xs font-medium text-slate-500">Gross</td>
              {grossCells.map((c) => (
                <td key={c.label} className="py-3 px-4 text-center tabular-nums">
                  {renderCell(c)}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
