import { Metadata } from 'next';
import Link from 'next/link';
import { getMetadata, getIndexSummary, getVehicleContribution } from '@/lib/data';
import { formatNumber, formatDollar, formatQuarter } from '@/lib/format';

export const metadata: Metadata = {
  title: 'About',
  description:
    'About the Evergreen Private Markets Index family and its construction methodology.',
};

const STEPS = [
  { label: 'Universe identification', detail: '6 independent SEC data sources' },
  { label: 'BDC portfolio extraction', detail: '10-K/10-Q schedules of investments' },
  { label: 'Fund portfolio extraction', detail: 'N-PORT quarterly holdings' },
  { label: 'Holdings unification', detail: 'Classification and deduplication' },
  { label: 'Position matching', detail: 'Across reporting periods' },
  { label: 'Return decomposition', detail: 'Price + income + principal' },
  { label: 'Index aggregation', detail: 'FV-weighted, chain-linked from 100' },
];

export default function AboutPage() {
  const meta = getMetadata();
  const summaries = getIndexSummary();
  const vehicles = getVehicleContribution();

  // Derive private markets stats from actual index data
  const totalFv = summaries.reduce((sum, s) => sum + (s.totalFv ?? 0), 0);
  const allVehicles = new Map<string | number, { vehicleType: string }>();
  for (const key of Object.keys(vehicles)) {
    for (const v of vehicles[key] ?? []) {
      if (!allVehicles.has(v.cik)) allVehicles.set(v.cik, { vehicleType: v.vehicleType });
    }
  }
  const entityCount = allVehicles.size;
  let bdcCount = 0;
  let intervalCount = 0;
  let tenderCount = 0;
  Array.from(allVehicles.values()).forEach((v) => {
    if (v.vehicleType === 'bdc') bdcCount++;
    else if (v.vehicleType === 'interval_fund') intervalCount++;
    else if (v.vehicleType === 'tender_offer_fund') tenderCount++;
  });

  return (
    <div>
      {/* Hero banner */}
      <div className="hero-gradient hero-pattern">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12 md:py-16">
          <h1 className="text-display-sm md:text-display-lg text-white mb-3">About</h1>
          <p className="text-white/60 max-w-2xl text-lg">
            About the Private Markets Index family and how it is constructed.
          </p>
        </div>
      </div>

      <div className="mx-auto max-w-3xl px-4 sm:px-6 py-10">
        {/* Stat callout row */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-10 -mt-2">
          <MiniStat label="Private Markets FV" value={formatDollar(totalFv)} />
          <MiniStat label="BDCs" value={formatNumber(bdcCount)} />
          <MiniStat label="Interval Funds" value={formatNumber(intervalCount)} />
          <MiniStat label="Tender Offer Funds" value={formatNumber(tenderCount)} />
        </div>

        <div className="space-y-8 text-sm text-navy/80 leading-relaxed prose-content">
          <section>
            <h2 className="text-lg font-semibold text-navy mb-3 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              About the Index Family
            </h2>
            <p>
              The Evergreen Private Markets Index family provides transparent,
              position-level benchmarks for the portfolio holdings of
              SEC-registered evergreen vehicles: business development
              companies (BDCs), interval funds, and tender offer funds. These are
              the registered, wealth-accessible vehicles that have opened private
              credit and equity markets to a broader investor base.
            </p>
            <p>
              The index currently tracks{' '}
              <strong>{formatNumber(entityCount)}</strong> reporting
              entities ({formatNumber(bdcCount)} BDCs,{' '}
              {formatNumber(intervalCount)} interval funds,{' '}
              {formatNumber(tenderCount)} tender offer funds)
              representing <strong>{formatDollar(totalFv)}</strong> in
              private markets fair value.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-navy mb-3 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              Why Evergreen Vehicles?
            </h2>
            <Callout>
              Evergreen private market funds have grown from a niche to a core
              allocation for wealth channel investors. Yet performance measurement
              has lagged.
            </Callout>
            <p>
              Existing benchmarks rely on voluntary manager
              surveys or track only a subset of the market.
              By constructing indices from the mandatory portfolio disclosures of
              every registered vehicle, the Evergreen Private Markets Index
              provides complete, unbiased coverage of this rapidly growing market
              segment, at the individual position level, mirroring the
              granularity of public credit benchmarks like the Morningstar LSTA
              Leveraged Loan Index.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-navy mb-3 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              Index Construction
            </h2>
            <p>
              The indices are constructed through a rigorous, rules-based process
              that transforms mandatory SEC filings into position-level
              benchmarks. The methodology is fully systematic with no discretionary
              overrides.
            </p>

            {/* Visual stepper */}
            <div className="mt-5 space-y-0">
              {STEPS.map((step, i) => (
                <div key={i} className="flex gap-4">
                  {/* Vertical connector + dot */}
                  <div className="flex flex-col items-center">
                    <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-xs font-bold ${
                      i === 0 ? 'bg-teal text-white' : 'bg-teal/10 text-teal'
                    }`}>
                      {i + 1}
                    </div>
                    {i < STEPS.length - 1 && (
                      <div className="w-px h-6 bg-surface-muted" />
                    )}
                  </div>
                  <div className="pb-4">
                    <p className="font-medium text-navy text-sm">{step.label}</p>
                    <p className="text-xs text-muted">{step.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-navy mb-3 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              Update Frequency
            </h2>
            <p>
              Indices are updated quarterly following SEC filing deadlines, with
              a one-quarter observation lag. The current dataset covers{' '}
              <strong>2019 Q4 through {formatQuarter(meta.asOfQuarter)}</strong>.
              BDC portfolio coverage begins around 2022 when the SEC phased in
              structured tagging requirements. Fund portfolio data (N-PORT)
              extends back to late 2019.
            </p>
            {meta.dataVintage && (
              <p className="mt-2 text-xs text-muted">
                Last updated: {new Date(meta.dataVintage).toLocaleDateString()}
              </p>
            )}
          </section>

          <section>
            <h2 className="text-lg font-semibold text-navy mb-3 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              Disclaimer
            </h2>
            <p>
              This data is derived from publicly available SEC filings and is
              provided for informational and research purposes only. It does not
              constitute investment advice, a solicitation, or an offer to buy or
              sell any securities. Past performance is not indicative of future
              results.
            </p>
            <p>
              No warranty is made as to the accuracy, completeness, or timeliness
              of the data. The reported fair values reflect fund-level
              mark-to-model estimates, not market transaction prices. Users
              should independently verify any data before making investment
              decisions.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-navy mb-3 flex items-center gap-3">
              <span className="w-1 h-5 bg-teal" />
              Learn More
            </h2>
            <p>
              For detailed information on index construction, see the{' '}
              <Link
                href="/methodology"
                className="text-teal hover:underline font-medium"
              >
                Methodology
              </Link>{' '}
              page.
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white p-4 shadow-card">
      <p className="text-xs text-muted mb-1">{label}</p>
      <p className="text-lg font-bold text-navy tabular-nums">{value}</p>
    </div>
  );
}

function Callout({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-l-3 border-teal bg-teal/5 px-4 py-3 my-4 text-sm text-navy/80" style={{ borderLeftWidth: '3px' }}>
      {children}
    </div>
  );
}
