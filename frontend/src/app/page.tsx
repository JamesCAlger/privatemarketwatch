import { getIndexSummary, getIndexReturns, getMetadata, getVehicleContribution } from '@/lib/data';
import { INDICES, getIndexByKey } from '@/lib/constants';
import {
  formatDollar,
  formatQuarter,
  formatLevel,
  formatPercent,
  returnSign,
  returnColor,
  formatNumber,
} from '@/lib/format';
import IndexCard from '@/components/IndexCard';
import TimeSeriesChart from '@/components/TimeSeriesChart';

export default function HomePage() {
  const summaries = getIndexSummary();
  const returns = getIndexReturns();
  const metadata = getMetadata();
  const vehicles = getVehicleContribution();

  // Position and entity counts for the two active indices
  const dlSummary = summaries.find((s) => s.index === 'DIRECT_LENDING');
  const deSummary = summaries.find((s) => s.index === 'DIRECT_EQUITY');
  const dlEntities = (vehicles['DIRECT_LENDING'] ?? []).length;
  const deEntities = (vehicles['DIRECT_EQUITY'] ?? []).length;

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
    <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
      {/* Hero */}
      <div className="mb-14 text-center">
        <h1 className="text-3xl md:text-4xl font-bold text-navy mb-3">
          Private Markets Indices
        </h1>
        <p className="text-muted max-w-2xl mx-auto">
          Independent, rules-based benchmarks tracking how private credit
          loans and equity investments actually perform -- built entirely
          from mandatory SEC filings across {formatNumber(metadata.vehicleCount)} registered
          funds managing {formatDollar(metadata.totalAum)} in assets.
        </p>
      </div>

      {/* Performance */}
      <section className="mb-14">
        <h2 className="text-2xl font-semibold text-navy mb-6">
          Index Performance
        </h2>

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
                color={idx.color}
                asOfQuarter={metadata.asOfQuarter ?? null}
              />
            );
          })}
        </div>

        {/* Chart */}
        <div className="bg-white rounded-lg p-4 sm:p-6 shadow-sm">
          <TimeSeriesChart
            series={chartSeries}
            defaultVisible={['DIRECT_LENDING', 'DIRECT_EQUITY']}
          />
        </div>
      </section>

      {/* Summary Table */}
      {summaries.length > 0 && (
        <section className="mb-14">
          <h2 className="text-2xl font-semibold text-navy mb-6">
            Returns Summary
          </h2>
          <div className="bg-white rounded-lg shadow-sm overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-navy">
                  <th className="py-2.5 px-4 text-left text-xs font-medium text-white/70 uppercase tracking-wider">
                    Index
                  </th>
                  <th className="py-2.5 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                    Level
                  </th>
                  <th className="py-2.5 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                    QoQ
                  </th>
                  <th className="py-2.5 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                    12M
                  </th>
                  <th className="py-2.5 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                    YTD
                  </th>
                  <th className="py-2.5 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                    Since Inception
                  </th>
                  <th className="py-2.5 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                    Companies
                  </th>
                  <th className="py-2.5 px-4 text-right text-xs font-medium text-white/70 uppercase tracking-wider">
                    AUM
                  </th>
                </tr>
              </thead>
              <tbody>
                {summaries.filter((s) => getIndexByKey(s.index)).map((s) => {
                  const meta = getIndexByKey(s.index);
                  return (
                    <tr
                      key={s.index}
                      className="border-b border-surface last:border-0 hover:bg-surface/50 transition-colors"
                    >
                      <td className="py-2.5 px-4 font-medium">
                        <span
                          className="inline-block w-2 h-2 rounded-full mr-2"
                          style={{ backgroundColor: meta?.color }}
                        />
                        {meta?.shortName ?? s.index}
                      </td>
                      <td className="py-2.5 px-4 text-right tabular-nums font-medium">
                        {formatLevel(s.level)}
                      </td>
                      <td className={`py-2.5 px-4 text-right tabular-nums ${returnColor(s.qoqReturn)}`}>
                        {returnSign(s.qoqReturn)}
                      </td>
                      <td className={`py-2.5 px-4 text-right tabular-nums ${returnColor(s.trailing12m)}`}>
                        {returnSign(s.trailing12m)}
                      </td>
                      <td className={`py-2.5 px-4 text-right tabular-nums ${returnColor(s.ytd)}`}>
                        {returnSign(s.ytd)}
                      </td>
                      <td className={`py-2.5 px-4 text-right tabular-nums ${returnColor(s.annualized)}`}>
                        {returnSign(s.annualized)}
                      </td>
                      <td className="py-2.5 px-4 text-right tabular-nums">
                        {formatNumber(s.constituents)}
                      </td>
                      <td className="py-2.5 px-4 text-right tabular-nums">
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

      {/* Universe Coverage */}
      <section>
        <h2 className="text-2xl font-semibold text-navy mb-6">
          Universe Coverage
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
          <StatCard
            label="Total AUM"
            value={formatDollar(metadata.totalAum)}
          />
          <StatCard
            label="Business Development Companies"
            value={formatNumber(metadata.bdcCount)}
          />
          <StatCard
            label="Interval Funds"
            value={formatNumber(metadata.intervalFundCount)}
          />
          <StatCard
            label="Tender Offer Funds"
            value={formatNumber(metadata.tenderOfferCount)}
          />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard
            label="Private Credit Constituent Positions"
            value={formatNumber(dlSummary?.constituents ?? null)}
          />
          <StatCard
            label="Private Credit Entities"
            value={formatNumber(dlEntities)}
          />
          <StatCard
            label="Private Equity Constituent Positions"
            value={formatNumber(deSummary?.constituents ?? null)}
          />
          <StatCard
            label="Private Equity Entities"
            value={formatNumber(deEntities)}
          />
        </div>
        <p className="text-xs text-muted mt-3">
          Covering the complete universe of SEC-registered vehicles providing
          wealth channel access to private credit and equity markets.
        </p>
      </section>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-lg p-4 shadow-sm">
      <p className="text-xs text-muted mb-1">{label}</p>
      <p className="text-xl font-bold text-navy tabular-nums">{value}</p>
    </div>
  );
}
