import { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
  title: 'Methodology',
  description:
    'How the Evergreen Private Markets Index family is constructed from mandatory SEC regulatory filings.',
};

const sections = [
  { id: 'overview', title: 'Overview' },
  { id: 'data-sources', title: 'Data Sources' },
  { id: 'universe', title: 'Universe Construction' },
  { id: 'holdings', title: 'Holdings Extraction' },
  { id: 'classification', title: 'Index Classification' },
  { id: 'matching', title: 'Position Matching' },
  { id: 'returns', title: 'Return Calculation' },
  { id: 'rebalancing', title: 'Rebalancing & Timing' },
  { id: 'limitations', title: 'Limitations' },
];

export default function MethodologyPage() {
  return (
    <div>
      {/* Hero banner */}
      <div className="hero-gradient hero-pattern">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 py-12 md:py-16">
          <h1 className="text-display-sm md:text-display-lg text-white mb-3">Methodology</h1>
          <p className="text-white/60 max-w-2xl text-lg">
            A detailed description of how the Private Markets Index
            family is constructed, from data sourcing through return calculation.
          </p>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10">
        <div className="flex gap-10">
          {/* Sticky TOC */}
          <nav className="hidden lg:block w-52 shrink-0">
            <div className="sticky top-20">
              <p className="text-xs font-medium text-muted uppercase tracking-wider mb-3">
                Contents
              </p>
              <ul className="space-y-0.5 text-sm">
                {sections.map((s, i) => (
                  <li key={s.id}>
                    <a
                      href={`#${s.id}`}
                      className="flex items-center gap-2.5 py-1.5 text-muted hover:text-teal transition-colors"
                    >
                      <span className="w-5 h-5 rounded-full bg-surface-muted text-navy/40 text-xs flex items-center justify-center shrink-0 font-medium">
                        {i + 1}
                      </span>
                      {s.title}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </nav>

          {/* Content */}
          <article className="flex-1 min-w-0 prose-content">
            <Section num={1} id="overview" title="Overview">
              <p>
                The Evergreen Private Markets Index family provides transparent,
                rules-based benchmarks for private credit and equity markets as
                accessed through registered evergreen vehicles. Unlike traditional
                private markets indices that rely on voluntary manager submissions,
                these indices are constructed entirely from mandatory SEC filings,
                ensuring complete and unbiased coverage of the registered vehicle
                universe.
              </p>
              <Callout>
                Each index constituent is an individual position (e.g., a specific
                term loan to a borrower), not an aggregated issuer exposure. This
                mirrors the construction of public credit indices like the
                Morningstar LSTA Leveraged Loan Index.
              </Callout>
              <p>
                Four indices are published, each tracking a distinct segment of
                the private markets:
              </p>
              <ul>
                <li>
                  <strong>Direct Lending Index</strong> -- The largest position-level
                  benchmark for middle-market direct lending
                </li>
                <li>
                  <strong>Direct Equity Index</strong> -- Direct equity
                  co-investments and minority stakes in private companies, held by
                  registered closed-end vehicles
                </li>
                <li>
                  <strong>Private Credit Fund Index</strong> -- Allocations to
                  private credit strategies including CLOs, direct lending funds,
                  and specialty finance platforms
                </li>
                <li>
                  <strong>Private Equity Fund Index</strong> -- Allocations to
                  private equity strategies including buyout, growth equity, and
                  venture capital funds
                </li>
              </ul>
            </Section>

            <Section num={2} id="data-sources" title="Data Sources">
              <p>
                All data is sourced from SEC EDGAR, the public repository of
                regulatory filings. Three filing types provide the raw data:
              </p>
              <h4>BDC XBRL (10-K/10-Q)</h4>
              <p>
                Business Development Companies file annual (10-K) and quarterly
                (10-Q) reports that include a Schedule of Investments in structured
                XBRL format. The SEC began requiring inline XBRL tagging for BDC
                investment schedules starting in 2022-2023. Each position is
                tagged with fair value, cost, interest rate, maturity, and other
                attributes using a typed dimension (investmentIdentifierAxis).
              </p>
              <h4>N-PORT (Quarterly TSV)</h4>
              <p>
                Registered investment companies (including interval funds and
                tender offer funds) file monthly portfolio holdings on Form N-PORT.
                The SEC publishes quarterly bulk data sets containing all
                N-PORT filings in tab-separated format. Each holding includes
                CUSIP, issuer type, asset category, fair value, and additional
                fields for debt securities.
              </p>
              <h4>N-CEN and N-2</h4>
              <p>
                Form N-CEN provides census data for registered investment
                companies, including fund type classification. Form N-2 cover
                pages contain checkboxes identifying whether a fund is a BDC,
                interval fund, or closed-end fund. These are used for universe
                construction, not holdings extraction.
              </p>
            </Section>

            <Section num={3} id="universe" title="Universe Construction">
              <p>
                The investment universe is built using six independent discovery
                methods, then cross-validated against third-party lists:
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
                <li>
                  <strong>N-CEN classification</strong> -- Funds tagged as
                  interval funds or N-2 registrants in N-CEN filings
                </li>
                <li>
                  <strong>N-2 checkbox parsing</strong> -- Automated parsing of
                  N-2 cover page checkboxes to identify interval funds, BDCs, and
                  closed-end funds
                </li>
                <li>
                  <strong>EFTS text search</strong> -- Full-text search of SEC
                  filings for &ldquo;tender offer fund&rdquo; and related terms
                </li>
              </ol>
              <Callout>
                Third-party validation lists include the Interval Fund Tracker,
                Tender Offer Funds database, and Sure Dividend BDC list. Match
                rates consistently exceed 95%.
              </Callout>
            </Section>

            <Section num={4} id="holdings" title="Holdings Extraction">
              <p>
                Holdings are extracted from two sources and unified into a single
                dataset:
              </p>
              <h4>BDC Holdings</h4>
              <p>
                XBRL instance documents are downloaded for each BDC&apos;s 10-K
                and 10-Q filings. The parser extracts facts tagged under the
                investmentIdentifierAxis dimension, mapping XBRL concepts to
                standardized fields (fair_value, cost, interest_rate,
                principal_amount, etc.). A concept mapping table handles
                variations in XBRL taxonomies across filers.
              </p>
              <h4>N-PORT Holdings</h4>
              <p>
                Quarterly TSV data sets are downloaded from the SEC DERA website.
                Holdings are filtered to universe CIKs and mapped to the unified
                schema. Balance and unit fields are converted: PA (par amount)
                maps to principal_amount, NS (number of shares) maps to
                shares_held.
              </p>
              <h4>Unification</h4>
              <p>
                BDC and N-PORT holdings are combined with consistent field names,
                rate harmonization (BDC rates converted from decimal to
                percentage), and cross-source deduplication. When a BDC also
                files N-PORT, the BDC XBRL data is preferred for richer field
                coverage.
              </p>
            </Section>

            <Section num={5} id="classification" title="Index Classification">
              <p>
                Each holding is classified into one of four index categories based
                on asset category and issuer category:
              </p>
              <div className="overflow-x-auto my-4">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr className="bg-navy">
                      <th className="text-left py-2.5 px-4 font-medium text-white/80 text-xs uppercase tracking-wider">Index</th>
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
                      <td className="py-2.5 px-4 font-medium text-navy">Direct Lending</td>
                      <td className="py-2.5 px-4 text-navy/70">LOAN, DEBT</td>
                      <td className="py-2.5 px-4 text-navy/70">CORPORATE</td>
                    </tr>
                    <tr className="border-b border-surface bg-surface/30">
                      <td className="py-2.5 px-4 font-medium text-navy">Direct Equity</td>
                      <td className="py-2.5 px-4 text-navy/70">
                        EQUITY_COMMON, EQUITY_PREFERRED
                      </td>
                      <td className="py-2.5 px-4 text-navy/70">CORPORATE</td>
                    </tr>
                    <tr className="border-b border-surface">
                      <td className="py-2.5 px-4 font-medium text-navy">Private Credit Fund</td>
                      <td className="py-2.5 px-4 text-navy/70">FUND (credit keywords)</td>
                      <td className="py-2.5 px-4 text-navy/70">FUND</td>
                    </tr>
                    <tr className="bg-surface/30">
                      <td className="py-2.5 px-4 font-medium text-navy">Private Equity Fund</td>
                      <td className="py-2.5 px-4 text-navy/70">FUND (equity keywords)</td>
                      <td className="py-2.5 px-4 text-navy/70">FUND</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <p>
                Additional heuristics reduce the unclassified rate: BDC financial
                field fallback (positions with interest rates default to LOAN),
                named co-investment reclassification (fund positions with
                identifiable operating company names reclassified to equity), and
                expanded keyword lists for credit/PE fund detection.
              </p>
            </Section>

            <Section num={6} id="matching" title="Position Matching">
              <p>
                To compute returns, the same position must be linked across
                consecutive quarters. A four-tier matching cascade is used:
              </p>
              <ol>
                <li>
                  <strong>Tier A: Within-filing comparatives</strong> -- BDC XBRL
                  filings contain both current and prior-period facts under the
                  same investmentIdentifierAxis value. These are filer-matched
                  pairs requiring no external matching.
                </li>
                <li>
                  <strong>Tier B1: CUSIP matching</strong> -- N-PORT holdings
                  with CUSIP identifiers are matched across quarters on the same
                  CUSIP within the same CIK.
                </li>
                <li>
                  <strong>Tier B2: Exact name matching</strong> -- Positions are
                  matched by exact issuer_name within the same CIK across
                  adjacent quarters.
                </li>
                <li>
                  <strong>Tier C/D: Normalized and fuzzy matching</strong> --
                  Fallback matching using name normalization and Jaro-Winkler
                  similarity with fair value proximity guards.
                </li>
              </ol>
              <Callout>
                All tiers enforce strict 1:1 matching using row-level
                deduplication with fair value proximity tiebreaking. Cascade
                exclusion prevents the same position from being matched at
                multiple tiers.
              </Callout>
            </Section>

            <Section num={7} id="returns" title="Return Calculation">
              <p>
                Total return for each position is decomposed into three
                components, following the convention of public credit indices:
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
                implied SOFR from peer filers, (3) same-filer median rate. Income
                is accrued proportionally to the holding period.
              </p>
              <h4>Index Aggregation</h4>
              <p>
                Index-level returns are computed as fair-value-weighted averages
                across all constituents. Equal-weighted returns are also published.
                Index levels are chain-linked from a base of 100. A minimum of 10
                constituents per quarter is required for a valid index observation.
              </p>
            </Section>

            <Section num={8} id="rebalancing" title="Rebalancing & Timing">
              <p>
                The indices rebalance quarterly, aligned with SEC filing
                deadlines. BDC 10-K/10-Q filings have a 60-day deadline after
                fiscal period end; N-PORT filings have a 60-day deadline. Data is
                available with a one-quarter lag.
              </p>
              <p>
                New positions entering the index (no prior-period match)
                contribute to AUM statistics but not to return calculations for
                their first quarter. Exiting positions (matched in the prior
                period but absent in the current) are included in returns for
                their final period.
              </p>
            </Section>

            <Section num={9} id="limitations" title="Limitations">
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
                  <strong>Income estimation</strong> -- Coupon income is estimated
                  from filed rate data, not actual cash received. PIK and
                  amendment effects may not be fully captured.
                </li>
                <li>
                  <strong>Incomplete field coverage</strong> -- Portfolio
                  characteristics such as weighted average coupon, spread, and
                  maturity are based on positions where the filer disclosed the
                  relevant data. Not all filers tag all fields, so reported
                  metrics may reflect a subset of the index universe.
                </li>
                <li>
                  <strong>No leverage adjustment</strong> -- Returns reflect
                  gross portfolio performance, not fund-level returns which may
                  include leverage effects.
                </li>
              </ul>
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
    <section id={id} className="mb-10 scroll-mt-20">
      <h2 className="text-xl font-semibold text-navy mb-4 flex items-center gap-3">
        <span className="w-7 h-7 rounded-full bg-teal/10 text-teal text-sm flex items-center justify-center shrink-0 font-bold">
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

function Callout({ children }: { children: React.ReactNode }) {
  return (
    <div className="border-l-3 border-teal bg-teal/5 rounded-r-lg px-4 py-3 my-4 text-sm text-navy/80" style={{ borderLeftWidth: '3px' }}>
      {children}
    </div>
  );
}
