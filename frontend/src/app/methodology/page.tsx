import { Metadata } from 'next';
import Link from 'next/link';
import CalloutBox from '@/components/CalloutBox';
import MethodologyTOC from '@/components/MethodologyTOC';

export const metadata: Metadata = {
  title: 'Methodology',
  description:
    'How Metris Lens constructs its index platform and benchmarks from mandatory SEC regulatory filings.',
};

const sections = [
  { id: 'universe', title: 'Universe' },
  { id: 'data-pipeline', title: 'Data Pipeline' },
  { id: 'index-construction', title: 'Index Construction' },
  { id: 'return-calculation', title: 'Return Calculation' },
  { id: 'universe-analytics', title: 'Universe Analytics' },
  { id: 'limitations', title: 'Limitations' },
] as const;

export default function MethodologyPage() {
  return (
    <div>
      {/* Editorial hero */}
      <div className="mx-auto max-w-6xl px-4 sm:px-6 pt-14 pb-10">
        <h1 className="font-display text-[52px] md:text-[68px] leading-[1.05] tracking-[-0.03em] text-ink mb-4">
          Methodology
        </h1>
        <p className="text-[17px] leading-relaxed text-ink2 max-w-[620px] mb-6">
          How the data platform and index family are constructed,
          from universe identification through return calculation and published analytics.
        </p>
        <div className="flex flex-wrap gap-x-8 gap-y-2 text-xs text-ink3">
          <div>
            <span className="text-[10px] uppercase tracking-[0.12em] text-ink3 block">Version</span>
            <span className="text-ink font-medium">1.0</span>
          </div>
          <div>
            <span className="text-[10px] uppercase tracking-[0.12em] text-ink3 block">Last Updated</span>
            <span className="text-ink font-medium">June 2026</span>
          </div>
          <div>
            <span className="text-[10px] uppercase tracking-[0.12em] text-ink3 block">Format</span>
            <span className="text-ink font-medium">Position-level indices</span>
          </div>
        </div>
      </div>

      <div className="border-t border-rule" />

      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
        <div className="flex gap-10">
          {/* Sticky TOC with scroll-spy */}
          <MethodologyTOC sections={sections} />

          {/* Content */}
          <article className="flex-1 min-w-0 prose-content">
            <Section num={1} id="universe" title="Universe">
              <p>
                The index universe covers <strong>unlisted (non-traded) business development
                companies (BDCs)</strong> registered with the SEC. These are closed-end funds
                that have elected BDC status under the Investment Company Act and invest
                primarily in private credit and equity.
              </p>

              <h4>Discovery</h4>
              <p>
                Unlisted BDCs are identified through three independent SEC data sources:
              </p>
              <ol>
                <li>
                  <strong>N-54A/N-54C elections</strong> -- BDCs that have elected
                  or withdrawn BDC status with the SEC
                </li>
                <li>
                  <strong>814- file numbers</strong> -- CIKs with Investment
                  Company Act file numbers in the 814 series
                </li>
                <li>
                  <strong>SEC BDC data set</strong> -- CIKs appearing in the
                  SEC&apos;s structured BDC data sets
                </li>
              </ol>

              <h4>Exclusions</h4>
              <p>
                Listed (publicly traded) BDCs are excluded. The unlisted BDC reference
                list is cross-validated against third-party sources. Consumer and
                marketplace lending vehicles with opaque individual loan IDs are
                excluded from index-level outputs.
              </p>

              <CalloutBox variant="design" title="Design choice">
                Each index constituent is an individual position (e.g., a specific term
                loan), not an aggregated issuer exposure. This mirrors the construction
                of public credit indices like the Morningstar LSTA Leveraged Loan Index.
              </CalloutBox>
            </Section>

            <Section num={2} id="data-pipeline" title="Data Pipeline">
              <p>
                All data is sourced from SEC EDGAR. No voluntary manager surveys, no
                proprietary feeds. This eliminates selection bias and ensures complete
                coverage of the filing universe.
              </p>

              <h4>BDC XBRL (10-K/10-Q)</h4>
              <p>
                Business Development Companies file annual (10-K) and quarterly
                (10-Q) reports that include a Schedule of Investments in structured
                XBRL format. The SEC required inline XBRL tagging for BDC
                investment schedules starting in 2022-2023. Each position is
                tagged with fair value, cost, interest rate, maturity, and other
                attributes using a typed dimension (investmentIdentifierAxis).
              </p>

              <h4>Extraction</h4>
              <p>
                XBRL instance documents are downloaded and parsed. A concept
                mapping layer handles variations in XBRL taxonomies across filers.
                Rate harmonization converts BDC rates from decimal to percentage
                form. Per-CIK wrappers handle filer-specific XBRL variations.
              </p>

              <CalloutBox variant="edge-case" title="Edge case">
                Some filers use non-standard XBRL structures or custom hierarchy
                levels. These are handled by per-CIK configuration rather than
                global rules, preserving extraction accuracy without over-generalizing.
              </CalloutBox>
            </Section>

            <Section num={3} id="index-construction" title="Index Construction">
              <p>
                Two indices are published, each tracking a distinct segment of the
                private markets:
              </p>
              <div className="overflow-x-auto my-4">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr className="bg-navy">
                      <th className="text-left py-2.5 px-4 font-medium text-white/80 text-xs uppercase tracking-wider">
                        Index
                      </th>
                      <th className="text-left py-2.5 px-4 font-medium text-white/80 text-xs uppercase tracking-wider">
                        Asset Category
                      </th>
                      <th className="text-left py-2.5 px-4 font-medium text-white/80 text-xs uppercase tracking-wider">
                        Issuer Category
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-surface">
                      <td className="py-2.5 px-4 font-medium text-navy">Private Credit</td>
                      <td className="py-2.5 px-4 text-navy/70">LOAN, DEBT</td>
                      <td className="py-2.5 px-4 text-navy/70">CORPORATE</td>
                    </tr>
                    <tr className="bg-surface/30">
                      <td className="py-2.5 px-4 font-medium text-navy">Private Equity</td>
                      <td className="py-2.5 px-4 text-navy/70">EQUITY_COMMON</td>
                      <td className="py-2.5 px-4 text-navy/70">CORPORATE</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <h4>Position Matching</h4>
              <p>
                To compute returns, the same position must be linked across
                consecutive quarters. A three-tier matching cascade is used:
              </p>
              <ol>
                <li>
                  <strong>Tier A: Within-filing comparatives</strong> -- BDC XBRL
                  filings contain both current and prior-period facts under the
                  same investmentIdentifierAxis value.
                </li>
                <li>
                  <strong>Tier B: Exact name matching</strong> -- Positions matched
                  by exact issuer_name within the same CIK across adjacent quarters.
                </li>
                <li>
                  <strong>Tier C/D: Normalized and fuzzy matching</strong> --
                  Fallback matching using name normalization and Jaro-Winkler
                  similarity with fair value proximity guards.
                </li>
              </ol>

              <CalloutBox variant="design" title="Design choice">
                All tiers enforce strict 1:1 matching using row-level
                deduplication with fair value proximity tiebreaking. Cascade
                exclusion prevents double-matching.
              </CalloutBox>
            </Section>

            <Section num={4} id="return-calculation" title="Return Calculation">
              <p>
                Total return for each position is decomposed into components,
                following the convention of public credit indices:
              </p>

              <h4>Capital Return (Price)</h4>
              <p>
                Per-unit price return isolates price changes from quantity
                changes. For loans: price = fair_value / principal_amount. For
                equity: price = fair_value / shares_held, with fallback to
                fair_value / cost. This prevents amortizing loans from being
                penalized and new purchases from inflating returns.
              </p>

              <h4>Income Return</h4>
              <p>
                Estimated coupon accrual based on a three-tier rate imputation:
                (1) direct interest_rate from the filing, (2) basis_spread plus
                implied SOFR from peer filers, (3) same-filer median rate.
              </p>

              <h4>Aggregation</h4>
              <p>
                Index-level returns are fair-value-weighted averages across all
                constituents. Equal-weighted returns are also published. Index levels
                are chain-linked from a base of 100. A minimum of 10 constituents per
                quarter is required for a valid observation.
              </p>

              <CalloutBox variant="limitation" title="Limitation">
                Income return is estimated from filed rate data, not actual cash
                received. PIK and amendment effects may not be fully captured.
              </CalloutBox>
            </Section>

            <Section num={5} id="universe-analytics" title="Universe Analytics">
              <p>
                Beyond index returns, the platform publishes fund-level analytics
                and portfolio characteristics:
              </p>
              <ul>
                <li>
                  <strong>Portfolio characteristics</strong> -- Weighted average
                  coupon, spread, and maturity with coverage disclosure
                </li>
                <li>
                  <strong>Structural composition</strong> -- Lien position, rate
                  type, and asset class breakdowns
                </li>
                <li>
                  <strong>Manager concentration</strong> -- AUM share by adviser
                </li>
                <li>
                  <strong>Fund-level performance</strong> -- NAV returns,
                  distribution rates, leverage ratios
                </li>
                <li>
                  <strong>Credit risk indicators</strong> -- PIK exposure,
                  non-accrual rates, default flags where disclosed
                </li>
              </ul>
              <p>
                All analytics are derived from the same mandatory filing data.
                Coverage gaps are disclosed inline (e.g., &quot;86% coverage&quot;
                next to weighted average coupon).
              </p>
            </Section>

            <Section num={6} id="limitations" title="Limitations">
              <ul>
                <li>
                  <strong>Coverage starts ~2022</strong> -- BDC XBRL tagging was
                  phased in by the SEC starting in 2022. Pre-2022 filings are
                  unstructured HTML.
                </li>
                <li>
                  <strong>Quarterly frequency</strong> -- Unlike daily public
                  market indices, these indices update quarterly due to the
                  filing cadence.
                </li>
                <li>
                  <strong>Fair value estimation</strong> -- Reported fair values
                  reflect fund-level mark-to-model estimates, not market
                  transaction prices.
                </li>
                <li>
                  <strong>Survivorship bias</strong> -- Funds that de-register or
                  stop filing exit the index. Historical returns include only
                  active filers.
                </li>
                <li>
                  <strong>Incomplete field coverage</strong> -- Portfolio
                  characteristics are based on positions where the filer disclosed
                  the relevant data. Coverage rates are disclosed alongside
                  each metric.
                </li>
                <li>
                  <strong>No leverage adjustment</strong> -- Returns reflect
                  gross portfolio performance, not fund-level returns which may
                  include leverage effects.
                </li>
              </ul>

              <CalloutBox variant="limitation" title="Important">
                This data is derived from publicly available SEC filings and is
                provided for informational and research purposes only. It does not
                constitute investment advice. Past performance is not indicative of
                future results.
              </CalloutBox>
            </Section>
          </article>
        </div>
      </div>
    </div>
  );
}

function Section({
  num,
  id,
  title,
  children,
}: {
  num: number;
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="mb-12 scroll-mt-20">
      <h2 className="font-display text-[28px] tracking-[-0.015em] text-ink mb-4 flex items-center gap-3">
        <span className="w-8 h-8 rounded-full bg-teal/10 text-teal text-sm flex items-center justify-center shrink-0 font-bold">
          {num}
        </span>
        {title}
      </h2>
      <div className="text-sm text-navy/80 leading-relaxed space-y-3">
        {children}
      </div>
    </section>
  );
}
