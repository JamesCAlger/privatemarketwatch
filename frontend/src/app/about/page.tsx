import { Metadata } from 'next';
import Link from 'next/link';
import { getMetadata } from '@/lib/data';
import { formatNumber, formatDollar, formatQuarter } from '@/lib/format';

export const metadata: Metadata = {
  title: 'About',
  description:
    'About the Evergreen Private Markets Index family and its construction methodology.',
};

export default function AboutPage() {
  const meta = getMetadata();

  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-8">
      <h1 className="text-3xl font-bold text-navy mb-2">About</h1>
      <p className="text-muted mb-8">
        About the Evergreen Private Markets Index family.
      </p>

      <div className="space-y-8 text-sm text-navy/80 leading-relaxed">
        <section>
          <h2 className="text-lg font-semibold text-navy mb-3">
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
          <p className="mt-3">
            The index universe currently covers{' '}
            <strong>{formatNumber(meta.vehicleCount)}</strong> registered
            vehicles ({formatNumber(meta.bdcCount)} BDCs,{' '}
            {formatNumber(meta.intervalFundCount)} interval funds,{' '}
            {formatNumber(meta.tenderOfferCount)} tender offer funds)
            representing <strong>{formatDollar(meta.totalAum)}</strong> in
            assets under management.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-navy mb-3">
            Why Evergreen Vehicles?
          </h2>
          <p>
            Evergreen private market funds have grown from a niche to a core
            allocation for wealth channel investors. Yet performance measurement
            has lagged. Existing benchmarks rely on voluntary manager
            surveys or track only a subset of the market.
          </p>
          <p className="mt-3">
            By constructing indices from the mandatory portfolio disclosures of
            every registered vehicle, the Evergreen Private Markets Index
            provides complete, unbiased coverage of this rapidly growing market
            segment, at the individual position level, mirroring the
            granularity of public credit benchmarks like the Morningstar LSTA
            Leveraged Loan Index.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-navy mb-3">
            Index Construction
          </h2>
          <p>
            The indices are constructed through a rigorous, rules-based process
            that transforms mandatory SEC filings into position-level
            benchmarks. The methodology is fully systematic with no discretionary
            overrides.
          </p>
          <div className="mt-4 bg-surface rounded-lg p-4 text-xs font-mono text-navy/60">
            <div>1. Universe identification</div>
            <div>2. BDC portfolio extraction (10-K/10-Q schedules of investments)</div>
            <div>3. Fund portfolio extraction (N-PORT quarterly holdings)</div>
            <div>4. Holdings unification and classification</div>
            <div>5. Position matching across reporting periods</div>
            <div>6. Total return decomposition (price + income + principal)</div>
            <div>7. Index aggregation (fair-value weighted, chain-linked)</div>
          </div>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-navy mb-3">
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
          <h2 className="text-lg font-semibold text-navy mb-3">
            Disclaimer
          </h2>
          <p>
            This data is derived from publicly available SEC filings and is
            provided for informational and research purposes only. It does not
            constitute investment advice, a solicitation, or an offer to buy or
            sell any securities. Past performance is not indicative of future
            results.
          </p>
          <p className="mt-3">
            No warranty is made as to the accuracy, completeness, or timeliness
            of the data. The reported fair values reflect fund-level
            mark-to-model estimates, not market transaction prices. Users
            should independently verify any data before making investment
            decisions.
          </p>
        </section>

        <section>
          <h2 className="text-lg font-semibold text-navy mb-3">Learn More</h2>
          <p>
            For detailed information on index construction, see the{' '}
            <Link
              href="/methodology"
              className="text-teal hover:underline"
            >
              Methodology
            </Link>{' '}
            page.
          </p>
        </section>
      </div>
    </div>
  );
}
