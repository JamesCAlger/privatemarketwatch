import type { FundSeriesEntry, FundAumPeerBandRow } from '@/lib/types';
import { getQuarterlyReturns } from './FundPerformanceTable';
import { returnColor } from '@/lib/format';
import TotalReturnChart from './TotalReturnChart';
import ReturnSummaryTable from './ReturnSummaryTable';
import AumGrowthChart from './AumGrowthChart';

interface FundPerformanceTabProps {
  series: FundSeriesEntry[];
  vehicleType: string;
  aumPeerBand?: FundAumPeerBandRow[];
}

/** Build a total return index by chaining quarterly or monthly returns. */
function buildTotalReturnIndex(series: FundSeriesEntry[]): { quarter: string; level: number }[] {
  let level = 100;
  const result: { quarter: string; level: number }[] = [];

  for (const s of series) {
    if (typeof s.quarterly_return === 'number') {
      level *= 1 + s.quarterly_return / 100;
      result.push({ quarter: s.quarter, level: Math.round(level * 100) / 100 });
      continue;
    }

    const months = [s.monthly_return_1, s.monthly_return_2, s.monthly_return_3];
    if (months.every((m) => typeof m === 'number')) {
      for (const m of months) {
        level *= 1 + (m as number) / 100;
      }
      result.push({ quarter: s.quarter, level: Math.round(level * 100) / 100 });
    }
  }

  return result;
}

function buildNavSeries(series: FundSeriesEntry[]): { quarter: string; level: number }[] {
  return series
    .filter((s) => s.nav_per_share != null)
    .map((s) => ({ quarter: s.quarter, level: s.nav_per_share as number }));
}

function pickLineChart(series: FundSeriesEntry[], vehicleType: string) {
  const trIndex = buildTotalReturnIndex(series);
  const navIndex = buildNavSeries(series);
  const distinctNavs = new Set(navIndex.map((d) => d.level)).size;
  const navIsGenuineQuarterly = distinctNavs >= navIndex.length * 0.5;

  if (vehicleType === 'bdc') {
    if (trIndex.length >= 2) return { data: trIndex, label: 'Total Return', key: 'tr' };
    if (navIndex.length >= 2) return { data: navIndex, label: 'NAV/Share Index', key: 'nav' };
  } else {
    if (trIndex.length >= 2) return { data: trIndex, label: 'Total Return', key: 'tr' };
    if (navIndex.length >= 2 && navIsGenuineQuarterly) return { data: navIndex, label: 'NAV/Share Index', key: 'nav' };
  }

  return null;
}

export default function FundPerformanceTab({ series, vehicleType, aumPeerBand = [] }: FundPerformanceTabProps) {
  if (series.length === 0) {
    return (
      <div className="py-12 text-center text-ink3 text-sm">
        Performance data not available for this fund.
      </div>
    );
  }

  const qReturns = getQuarterlyReturns(series);
  const lineChart = pickLineChart(series, vehicleType);

  // Rebase to 100
  let lineData = lineChart?.data ?? [];
  if (lineData.length > 0) {
    const base = lineData[0].level;
    if (base !== 100 && base > 0) {
      lineData = lineData.map((d) => ({
        quarter: d.quarter,
        level: Math.round((d.level / base) * 100 * 100) / 100,
      }));
    }
  }

  const barData = qReturns.map((q) => ({ quarter: q.quarter, return: q.ret }));

  // Build return summary rows
  const returns = qReturns.map((q) => q.ret);
  const compound = (arr: number[]) => arr.reduce((acc, r) => acc * (1 + r), 1) - 1;

  const latest = returns.length > 0 ? returns[returns.length - 1] : null;

  const latestQuarter = qReturns.length > 0 ? qReturns[qReturns.length - 1].quarter : null;
  const latestYear = latestQuarter?.slice(0, 4) ?? '';
  const ytdReturns = qReturns.filter((q) => q.quarter.startsWith(latestYear)).map((q) => q.ret);
  const ytd = ytdReturns.length > 0 ? compound(ytdReturns) : null;

  const last4 = returns.slice(-4);
  const trail1y = last4.length >= 4 ? compound(last4) : null;

  const last12 = returns.slice(-12);
  const trail3y = last12.length >= 12 ? Math.pow(1 + compound(last12), 1 / 3) - 1 : null;

  const cumulative = returns.length > 0 ? compound(returns) : null;

  const returnRows = [
    { label: 'QTD', net: latest, gross: null },
    { label: 'YTD', net: ytd, gross: null },
    { label: '1 Year', net: trail1y, gross: null },
    { label: '3 Year (Ann.)', net: trail3y, gross: null },
    { label: 'Cumulative', net: cumulative, gross: null },
  ];

  // Distribution history (BDCs only)
  const distData = series
    .filter((s) => s.distribution_per_share != null && (s.distribution_per_share as number) > 0)
    .map((s) => ({ quarter: s.quarter, return: s.distribution_per_share as number }));

  return (
    <div className="py-6 space-y-8">
      {/* Total return chart */}
      {lineData.length >= 2 && (
        <div className="bg-white border border-rule p-4 sm:p-6">
          <p className="text-sm font-medium text-navy mb-3">
            {lineChart?.label ?? 'Total Return'}
          </p>
          <TotalReturnChart
            lineData={lineData}
            barData={barData}
            lineLabel={lineChart?.label ?? 'Total Return'}
            showBars={false}
          />
        </div>
      )}

      {/* AUM growth vs peers (indexed to 100 at start) */}
      {series.filter((s) => s.total_assets != null).length >= 2 && (
        <div className="bg-white border border-rule p-4 sm:p-6">
          <p className="text-sm font-medium text-navy mb-1">AUM growth</p>
          <p className="text-xs text-ink3 mb-3">
            Indexed to 100 at the start of the fund&apos;s history, against the peer-median fund rebased to the same point.
          </p>
          <AumGrowthChart series={series} band={aumPeerBand} />
        </div>
      )}

      {/* Return summary table */}
      {qReturns.length > 0 && (
        <div className="bg-white border border-rule p-6">
          <ReturnSummaryTable rows={returnRows} showGross={false} />
        </div>
      )}

      {/* Distribution history */}
      {distData.length >= 2 && (
        <div className="bg-white border border-rule p-4 sm:p-6">
          <p className="text-sm font-medium text-navy mb-3">Distribution History ($/Share)</p>
          <TotalReturnChart
            lineData={[]}
            barData={distData}
            lineLabel=""
            positiveColor="#2A9D8F"
          />
        </div>
      )}
    </div>
  );
}
