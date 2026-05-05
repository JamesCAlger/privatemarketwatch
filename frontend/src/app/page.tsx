import { getFundList, getFundSummary, getIndexSummary } from '@/lib/data';
import { INDICES } from '@/lib/constants';
import { formatDollar, formatNumber } from '@/lib/format';
import Link from 'next/link';
import FundTable from '@/components/FundTable';

export default function HomePage() {
  const funds = getFundList();
  const summary = getFundSummary();
  const indexSummaries = getIndexSummary();

  return (
    <div>
      {/* Hero */}
      <div className="hero-gradient-home hero-pattern">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-16 md:py-20">
          <div className="text-center">
            <h1 className="text-display-sm md:text-display-lg text-white mb-4">
              Fund Universe
            </h1>
            <p className="text-white/60 text-base md:text-lg mb-10">
              All SEC-registered vehicles investing in private markets.
              Browse BDCs, interval funds, and tender offer funds with
              financial data extracted directly from regulatory filings.
            </p>

            {/* Hero stats */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 md:gap-6 max-w-3xl mx-auto text-center">
              <div>
                <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Total Funds</p>
                <p className="font-bold tabular-nums text-stat-sm text-white">
                  {formatNumber(summary.totalFunds)}
                </p>
              </div>
              <div>
                <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Total AUM</p>
                <p className="font-bold tabular-nums text-stat-sm text-white">
                  {formatDollar(summary.totalAum)}
                </p>
              </div>
              <div>
                <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Quarters</p>
                <p className="font-bold tabular-nums text-stat-sm text-white">
                  {formatNumber(summary.totalQuarters)}
                </p>
              </div>
              <div>
                <p className="text-white/60 text-xs uppercase tracking-wider mb-1">Vehicle Types</p>
                <p className="font-bold tabular-nums text-stat-sm text-white">3</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
        {/* Fund table */}
        <section className="mb-14">
          <h2 className="text-xl font-semibold text-navy mb-6 flex items-center gap-3">
            <span className="w-1 h-5 bg-teal rounded-full" />
            All Funds
          </h2>
          <FundTable funds={funds} />
        </section>

        {/* Index teaser */}
        {indexSummaries.length > 0 && (
          <section className="mb-10">
            <h2 className="text-xl font-semibold text-navy mb-6 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal rounded-full" />
              Private Market Indices
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
              {INDICES.map((idx) => {
                const s = indexSummaries.find((x) => x.index === idx.key);
                return (
                  <Link
                    key={idx.key}
                    href={`/indices/${idx.slug}`}
                    className="group relative overflow-hidden rounded-lg bg-white p-6 transition-all hover:shadow-panel shadow-card flex flex-col"
                  >
                    <div
                      className="absolute top-0 left-0 h-1 w-full"
                      style={{ backgroundColor: idx.color }}
                    />
                    <h3 className="text-lg font-semibold mb-1 text-navy">
                      {idx.shortName}
                    </h3>
                    <p className="text-sm text-muted mb-3 flex-1">{idx.description}</p>
                    {s && (
                      <p className="text-xs text-muted">
                        Level <span className="font-semibold text-navy">{s.level?.toFixed(1)}</span>
                        {' / '}
                        {formatNumber(s.constituents)} constituents
                      </p>
                    )}
                    <span className="inline-flex items-center gap-1 text-sm font-medium text-teal group-hover:text-teal-dark transition-colors mt-3">
                      View index
                      <svg className="w-4 h-4 transition-transform group-hover:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                      </svg>
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

