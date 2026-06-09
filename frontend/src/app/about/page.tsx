import { Metadata } from 'next';
import Link from 'next/link';
import { getMetadata, getIndexSummary, getVehicleContribution } from '@/lib/data';
import { formatNumber, formatDollar, formatQuarter } from '@/lib/format';

export const metadata: Metadata = {
  title: 'About',
  description:
    'About Metris Lens -- the index platform for private credit, with position-level benchmarks for unlisted BDCs.',
};

const PRINCIPLES = [
  {
    title: 'Independent',
    description: 'No voluntary manager surveys. No proprietary feeds. All data comes from mandatory SEC filings, eliminating selection bias.',
  },
  {
    title: 'Rules-based',
    description: 'Fully systematic construction with no discretionary overrides. Every classification, matching, and aggregation step follows published rules.',
  },
  {
    title: 'Transparent',
    description: 'Coverage gaps are disclosed inline. Data quality metrics are published. The methodology is open and documented.',
  },
  {
    title: 'Reproducible',
    description: 'Given the same SEC filings, anyone can reproduce the index. The pipeline is deterministic with published validation.',
  },
];

export default function AboutPage() {
  const meta = getMetadata();
  const summaries = getIndexSummary();
  const vehicles = getVehicleContribution();

  const totalFv = summaries.reduce((sum, s) => sum + (s.totalFv ?? 0), 0);
  const allVehicles = new Map<string | number, { vehicleType: string }>();
  for (const key of Object.keys(vehicles)) {
    for (const v of vehicles[key] ?? []) {
      if (!allVehicles.has(v.cik)) allVehicles.set(v.cik, { vehicleType: v.vehicleType });
    }
  }
  const bdcCount = Array.from(allVehicles.values()).filter((v) => v.vehicleType === 'bdc').length;
  const totalConstituents = summaries.reduce((sum, s) => sum + (s.constituents ?? 0), 0);

  return (
    <div>
      {/* Hero */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 pt-14 pb-10">
        <h1 className="font-display text-[52px] md:text-[68px] leading-[1.05] tracking-[-0.03em] text-ink mb-5">
          Making private markets<br />observable.
        </h1>
        <p className="text-[17px] leading-relaxed text-ink2 max-w-[620px]">
          Metris Lens provides the first position-level benchmarks for unlisted
          BDCs, built entirely from mandatory SEC filings. Independent, rules-based,
          transparent, and reproducible.
        </p>
      </div>

      <div className="border-t border-rule" />

      <div className="mx-auto max-w-3xl px-4 sm:px-6 py-12 space-y-16">

        {/* Manifesto */}
        <section>
          <h2 className="font-display text-[28px] tracking-[-0.015em] text-ink mb-5">
            Why this exists
          </h2>
          <div className="space-y-4 text-[15px] leading-relaxed text-ink2">
            <p>
              Private credit is the fastest-growing asset class in wealth management.
              Unlisted BDCs have grown from a niche product to a core allocation for
              advisors and institutions. Yet performance measurement has lagged far
              behind the assets under management.
            </p>
            <p>
              Existing benchmarks rely on voluntary manager surveys that cover a
              fraction of the market, or track only listed BDCs whose market prices
              reflect trading dynamics rather than portfolio performance. There has
              been no comprehensive, rules-based benchmark for the unlisted BDC
              universe -- until now.
            </p>
            <p>
              By sourcing all data from mandatory portfolio disclosures filed with
              the SEC, Metris Lens provides complete, unbiased coverage of the
              unlisted BDC market. Every position in every fund&apos;s schedule of
              investments becomes a data point. No voluntary submissions, no
              selection bias, no gaps.
            </p>
          </div>
        </section>

        {/* Principles */}
        <section>
          <h2 className="font-display text-[28px] tracking-[-0.015em] text-ink mb-6">
            Principles
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {PRINCIPLES.map((p) => (
              <div key={p.title} className="border border-rule p-5">
                <h3 className="text-sm font-semibold text-navy mb-2">{p.title}</h3>
                <p className="text-xs text-ink2 leading-relaxed">{p.description}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Coverage stats */}
        <section>
          <h2 className="font-display text-[28px] tracking-[-0.015em] text-ink mb-6">
            Coverage
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatBox label="Private Markets FV" value={formatDollar(totalFv)} />
            <StatBox label="Unlisted BDCs" value={formatNumber(bdcCount)} />
            <StatBox label="Indexed Positions" value={formatNumber(totalConstituents)} />
            <StatBox
              label="Data As Of"
              value={meta.asOfQuarter ? formatQuarter(meta.asOfQuarter) : '--'}
            />
          </div>
        </section>

        {/* People placeholder */}
        <section>
          <h2 className="font-display text-[28px] tracking-[-0.015em] text-ink mb-6">
            Team
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="border border-rule p-5 text-center">
                <div className="w-14 h-14 rounded-full bg-surface mx-auto mb-3" />
                <div className="h-3 bg-surface rounded w-20 mx-auto mb-2" />
                <div className="h-2 bg-surface/70 rounded w-16 mx-auto" />
              </div>
            ))}
          </div>
          <p className="text-xs text-ink3 mt-3">
            Team profiles coming soon.
          </p>
        </section>

        {/* Contact */}
        <section>
          <div className="bg-navy p-8">
            <h2 className="font-display text-[24px] text-white mb-4">
              Get in touch
            </h2>
            <p className="text-sm text-white/60 mb-6">
              Interested in the data, methodology, or partnership opportunities?
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <ContactItem label="General Inquiries" value="info@metrislens.com" />
              <ContactItem label="Data & Research" value="research@metrislens.com" />
              <ContactItem label="Partnerships" value="partners@metrislens.com" />
              <ContactItem label="Press" value="press@metrislens.com" />
            </div>
          </div>
        </section>

        {/* Disclaimer */}
        <section>
          <h2 className="font-display text-[28px] tracking-[-0.015em] text-ink mb-4">
            Disclaimer
          </h2>
          <div className="text-sm text-ink2 leading-relaxed space-y-3">
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
              mark-to-model estimates, not market transaction prices.
            </p>
          </div>
        </section>

        {/* Learn more */}
        <section>
          <div className="flex gap-4">
            <Link
              href="/methodology"
              className="inline-block px-5 py-3 bg-navy text-white text-sm font-medium hover:bg-navy/90 transition-colors"
            >
              Read the methodology &rarr;
            </Link>
            <Link
              href="/"
              className="inline-block px-5 py-3 border border-rule text-ink2 text-sm font-medium hover:bg-surface/50 transition-colors"
            >
              Browse the fund universe
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-rule p-4">
      <p className="text-[10px] uppercase tracking-[0.12em] text-ink3 mb-1.5">{label}</p>
      <p className="font-mono text-lg text-navy font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function ContactItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white/[0.06] border border-white/[0.1] p-3">
      <p className="text-[10px] uppercase tracking-[0.12em] text-white/40 mb-1">{label}</p>
      <p className="text-sm text-white/80">{value}</p>
    </div>
  );
}
