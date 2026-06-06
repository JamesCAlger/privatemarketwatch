import {
  getIndexSummary,
  getIndexReturns,
  getMetadata,
  getVehicleContribution,
  getManagerConcentration,
  getInvesteeConcentration,
  getPositionConcentration,
  getConcentrationCurve,
  combineConcentration,
} from '@/lib/data';
import { INDICES, getIndexByKey } from '@/lib/constants';
import {
  formatDollar,
  formatQuarter,
  formatLevel,
  formatPercent,
  formatNumber,
  returnSign,
  returnColor,
} from '@/lib/format';
import Link from 'next/link';
import IndexCard from '@/components/IndexCard';
import TimeSeriesChart from '@/components/TimeSeriesChart';
import HeroStats from '@/components/HeroStats';
import UniverseStats from '@/components/UniverseStats';
import ConcentrationPieChart, { COLORS_TEAL_RAMP } from '@/components/ManagerPieChart';
import ConcentrationCurve from '@/components/ConcentrationCurve';

export const metadata = {
  title: 'Indices | Metris Lens',
  description: 'Position-level private market index performance, concentration, and universe coverage.',
};

export default function IndicesPage() {
  const summaries = getIndexSummary();
  const returns = getIndexReturns();
  const metadata = getMetadata();
  const vehicles = getVehicleContribution();

  // Combined concentration across visible indices
  const combinedIndices = INDICES.map((i) => i.key);
  const managerData = combineConcentration(getManagerConcentration(), combinedIndices);
  const concentrationCurve = getConcentrationCurve();
  const combinedInvesteeCurve = concentrationCurve['COMBINED']?.investee ?? [];
  const combinedPositionCurve = concentrationCurve['COMBINED']?.position ?? [];

  // Scope all stats to visible indices only (DL + DE)
  const visibleKeys = new Set(INDICES.map((i) => i.key));
  const visibleSummaries = summaries.filter((s) => visibleKeys.has(s.index));
  const totalFv = visibleSummaries.reduce((sum, s) => sum + (s.totalFv ?? 0), 0);
  const totalPositions = visibleSummaries.reduce((sum, s) => sum + (s.constituents ?? 0), 0);
  const totalCompanies = visibleSummaries.reduce((sum, s) => sum + (s.uniqueCompanies ?? 0), 0);
  // Per-index stats
  const dlSummary = summaries.find((s) => s.index === 'DIRECT_LENDING');
  const ceSummary = summaries.find((s) => s.index === 'COMMON_EQUITY');

  // Build chart series from index_returns
  const chartSeries = INDICES.map((idx) => ({
    key: idx.key,
    name: idx.shortName,
    color: idx.color,
    data: (returns[idx.key] ?? []).map((r) => ({
      quarter: r.quarter,
      level: r.levelFv,
    })),
  })).filter((s) => s.data.length > 0);

  return (
    <div>
      {/* Hero -- full-width dark gradient */}
      <div className="hero-gradient-home hero-pattern">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
          <div className="text-center">
            <h1 className="text-display-sm md:text-display-lg text-white mb-4">
              Private Market Indices
            </h1>
            <p className="text-white/60 text-base md:text-lg mb-10">
              Position-level benchmarks for private credit and equity,
              built from the portfolio holdings of unlisted BDCs.
            </p>

            {/* Hero stat callouts */}
            <HeroStats
              totalFv={totalFv}
              loanCount={dlSummary?.constituents ?? 0}
              commonEquityCount={ceSummary?.constituents ?? 0}
            />
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
        {/* Performance */}
        <section className="mb-14">
          {/* Index Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-6">
            {INDICES.map((idx) => {
              const summary = summaries.find((s) => s.index === idx.key);
              return (
                <IndexCard
                  key={idx.key}
                  name={idx.shortName}
                  slug={idx.slug}
                  level={summary?.level ?? null}
                  trailing12m={summary?.trailing12m ?? null}
                  qoqReturn={summary?.qoqReturn ?? null}
                  constituents={summary?.constituents ?? null}
                  color={idx.color}
                  asOfQuarter={metadata.asOfQuarter ?? null}
                  sparkline={summary?.sparkline}
                />
              );
            })}
          </div>

          {/* Chart */}
          <div className="bg-white p-4 sm:p-6 shadow-card">
            <TimeSeriesChart
              series={chartSeries}
              defaultVisible={['DIRECT_LENDING', 'COMMON_EQUITY']}
            />
          </div>
        </section>

        {/* Summary Table */}
        {summaries.length > 0 && (
          <section className="mb-14">
            <SectionHeading>Returns Summary</SectionHeading>
            <div className="bg-white shadow-card overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-navy">
                    <th className="py-3 px-4 text-left text-xs font-medium text-white/70 uppercase tracking-wider">
                      Index
                    </th>
                    <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                      Level
                    </th>
                    <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider w-[10%]">
                      QoQ
                    </th>
                    <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider w-[10%]">
                      12M
                    </th>
                    <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider w-[10%]">
                      YTD
                    </th>
                    <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider whitespace-nowrap w-[10%]">
                      Since Inception
                    </th>
                    <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                      Holdings
                    </th>
                    <th className="py-3 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                      Fair Value
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleSummaries.map((s, i) => {
                    const meta = getIndexByKey(s.index);
                    return (
                      <tr
                        key={s.index}
                        className={`border-b border-surface last:border-0 hover:bg-surface/50 transition-colors ${
                          i % 2 === 1 ? 'bg-surface/30' : ''
                        }`}
                      >
                        <td className="py-3 px-4 font-medium">
                          <span
                            className="inline-block w-2 h-2 rounded-full mr-2"
                            style={{ backgroundColor: meta?.color }}
                          />
                          {meta?.shortName ?? s.index}
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums font-semibold">
                          {formatLevel(s.level)}
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">
                          <ReturnBadge value={s.qoqReturn} />
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">
                          <ReturnBadge value={s.trailing12m} />
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">
                          <ReturnBadge value={s.ytd} />
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">
                          <ReturnBadge value={s.annualized} />
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">
                          {formatNumber(s.constituents)}
                        </td>
                        <td className="py-3 px-4 text-right tabular-nums">
                          {formatDollar(s.totalFv)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {/* Concentration */}
        {(managerData.length > 0 || combinedInvesteeCurve.length > 0 || combinedPositionCurve.length > 0) && (
          <section className="mb-14">
            <SectionHeading>Concentration</SectionHeading>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {managerData.length > 0 && (
                <div className="bg-white p-5 shadow-card">
                  <ConcentrationPieChart data={managerData} title="By Manager" colors={COLORS_TEAL_RAMP} />
                </div>
              )}
              {combinedInvesteeCurve.length > 0 && (
                <div className="bg-white p-5 shadow-card">
                  <ConcentrationCurve data={combinedInvesteeCurve} title="By Company" />
                </div>
              )}
              {combinedPositionCurve.length > 0 && (
                <div className="bg-white p-5 shadow-card">
                  <ConcentrationCurve data={combinedPositionCurve} title="By Holding" />
                </div>
              )}
            </div>
          </section>
        )}

        {/* Universe Coverage */}
        <section>
          <SectionHeading>Universe Coverage</SectionHeading>

          <UniverseStats
            totalFv={totalFv}
            fundCount={metadata.cikCount}
            positionCount={totalPositions}
            issuerCount={totalCompanies}
          />
          <p className="text-xs text-muted mt-3">
            Counts reflect the latest quarter across all unlisted BDCs.
          </p>
        </section>

        {/* Index CTAs */}
        <section className="mt-14 mb-10">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            {INDICES.map((idx) => (
              <Link
                key={idx.key}
                href={`/indices/${idx.slug}`}
                className="group relative overflow-hidden bg-white p-6 transition-all hover:shadow-panel shadow-card flex flex-col"
              >
                <div
                  className="absolute top-0 left-0 h-1 w-full"
                  style={{ backgroundColor: idx.color }}
                />
                <h3 className="text-lg font-semibold mb-1 text-navy">
                  {idx.name}
                </h3>
                <p className="text-sm mb-4 text-muted flex-1">
                  {idx.description}
                </p>
                <span className="inline-flex items-center gap-1 text-base font-medium text-teal group-hover:text-teal-dark transition-colors">
                  View full index
                  <svg className="w-4 h-4 transition-transform group-hover:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                </span>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}



function ReturnBadge({ value }: { value: number | null | undefined }) {
  if (value == null || isNaN(value)) return <span className="text-muted">--</span>;
  const isPositive = value >= 0;
  return (
    <span className={`inline-block px-1.5 py-0.5 text-xs font-medium ${
      isPositive
        ? 'bg-teal/10 text-teal'
        : 'bg-red/10 text-red'
    }`}>
      {returnSign(value)}
    </span>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xl font-semibold text-navy mb-6 flex items-center gap-3">
      <span className="w-1 h-5 bg-teal" />
      {children}
    </h2>
  );
}
